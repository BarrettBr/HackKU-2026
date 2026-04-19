package receiver

import (
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/BarrettBr/HackKU-2026/config"
	"github.com/pion/rtcp"
	"github.com/pion/rtp"
	"github.com/pion/rtp/codecs"
	"github.com/pion/webrtc/v4"
	"github.com/pion/webrtc/v4/pkg/media/samplebuilder"
)

// RTPPacket represents one inbound network packet.
type RTPPacket struct {
	Packet *rtp.Packet
}

type Service struct {
	stopOnce sync.Once
	stopCh   chan struct{}

	trackGeneration atomic.Uint64

	sampleBuilder *samplebuilder.SampleBuilder
	decoder       Decoder
	inboundCh     chan inboundPacket
	codec         string
	pixelFormat   string
	cfgWidth      int
	cfgHeight     int
	decoderWidth  int
	decoderHeight int
	streamWidth   int
	streamHeight  int
	h264PrefixMu  sync.Mutex
	h264Prefix    []byte
	pendingAU     []byte
	pendingHasVCL bool

	sinkMu sync.RWMutex
	sink   FrameSink

	packetCount  atomic.Uint64
	droppedCount atomic.Uint64
	sampleCount  atomic.Uint64
	decodedCount atomic.Uint64
	writtenCount atomic.Uint64
	decodeErrors atomic.Uint64

	debugDump io.WriteCloser
}

type inboundPacket struct {
	packet *rtp.Packet
}

// FrameSink receives decoded frames and forwards them to the next stage
// (e.g. shared memory IPC writer).
type FrameSink interface {
	WriteFrame(frame DecodedFrame) error
}

func New(cfg *config.Receiver) (*Service, error) {
	if cfg == nil {
		return nil, fmt.Errorf("receiver config is nil")
	}

	depacketizer, err := newDepacketizer(cfg.Codec)
	if err != nil {
		return nil, err
	}

	service := &Service{
		stopCh:        make(chan struct{}),
		sampleBuilder: samplebuilder.New(64, depacketizer, 90000),
		inboundCh:     make(chan inboundPacket, 256),
		codec:         strings.ToLower(strings.TrimSpace(cfg.Codec)),
		pixelFormat:   strings.TrimSpace(cfg.PixelFormat),
		cfgWidth:      cfg.Width,
		cfgHeight:     cfg.Height,
	}
	if service.pixelFormat == "" {
		service.pixelFormat = "rgba"
	}
	if os.Getenv("ENGINE_DEBUG_DUMP_H264") == "1" {
		if f, err := os.Create("/tmp/engine-rx.h264"); err == nil {
			service.debugDump = f
		}
	}
	return service, nil
}

func (s *Service) Run() error {
	for {
		pkt, err := s.receivePacket()
		if err != nil {
			if err == io.EOF {
				return nil
			}
			return err
		}

		if pkt.Packet == nil {
			continue
		}

		s.sampleBuilder.Push(pkt.Packet)
		for {
			sample := s.sampleBuilder.Pop()
			if sample == nil {
				break
			}
			s.sampleCount.Add(1)

			frames, err := s.depacketizeSample(sample.Data)
			if err != nil {
				return err
			}
			if len(frames) == 0 {
				continue
			}
			for _, encoded := range frames {
				if err := s.ensureDecoder(encoded); err != nil {
					s.decodeErrors.Add(1)
					continue
				}
				if s.decoder == nil {
					// Need stream parameters (SPS) before decode can start.
					continue
				}

				decoded, err := s.decodeFrame(encoded)
				if err != nil {
					if errors.Is(err, ErrNoFrameReady) {
						continue
					}
					// If ffmpeg decoder enters a bad state on one access unit,
					// recreate it on the next frame instead of stalling forever.
					if s.decoder != nil {
						_ = s.decoder.Close()
						s.decoder = nil
					}
					s.decodeErrors.Add(1)
					// Drop bad samples and keep the receiver alive.
					continue
				}
				s.decodedCount.Add(1)

				if err := s.writeFrame(decoded); err != nil {
					// Sink failures should not tear down the receive loop.
					continue
				}
				s.writtenCount.Add(1)
			}
		}
	}
}

func (s *Service) Stop() error {
	s.stopOnce.Do(func() {
		close(s.stopCh)
	})
	if s.debugDump != nil {
		_ = s.debugDump.Close()
		s.debugDump = nil
	}
	if s.decoder != nil {
		return s.decoder.Close()
	}
	return nil
}

func (s *Service) receivePacket() (RTPPacket, error) {
	select {
	case <-s.stopCh:
		return RTPPacket{}, io.EOF
	case inbound := <-s.inboundCh:
		return RTPPacket{Packet: inbound.packet}, nil
	}
}

func (s *Service) depacketizeSample(sampleData []byte) ([]EncodedFrame, error) {
	if len(sampleData) == 0 {
		return nil, nil
	}

	payload := sampleData
	if s.codec == "" || s.codec == "h264" {
		payload = normalizeH264Bytestream(payload)
		if w, h, ok := s.detectStreamDimensions(payload); ok {
			s.streamWidth = w
			s.streamHeight = h
		}
		payload = s.ensureH264ParameterSets(payload)
		accessUnits := s.assembleH264AccessUnits(payload)
		if len(accessUnits) == 0 {
			return nil, nil
		}

		frames := make([]EncodedFrame, 0, len(accessUnits))
		for _, au := range accessUnits {
			if len(au) == 0 {
				continue
			}
			if s.debugDump != nil {
				_, _ = s.debugDump.Write(au)
			}
			frames = append(frames, EncodedFrame{Payload: au})
		}
		return frames, nil
	}

	return []EncodedFrame{{Payload: payload}}, nil
}

func (s *Service) decodeFrame(frame EncodedFrame) (DecodedFrame, error) {
	return s.decoder.Decode(frame)
}

func (s *Service) ensureDecoder(frame EncodedFrame) error {
	width, height, ok := s.detectStreamDimensions(frame.Payload)
	if !ok {
		if s.streamWidth > 0 && s.streamHeight > 0 {
			width = s.streamWidth
			height = s.streamHeight
			ok = true
		}
	}
	if !ok {
		if s.decoder != nil {
			return nil
		}
		if s.cfgWidth <= 0 || s.cfgHeight <= 0 {
			return nil
		}
		width = s.cfgWidth
		height = s.cfgHeight
	}

	if width <= 0 || height <= 0 {
		return nil
	}
	if s.decoder != nil && s.decoderWidth == width && s.decoderHeight == height {
		return nil
	}

	if s.decoder != nil {
		_ = s.decoder.Close()
		s.decoder = nil
	}

	decoder, err := newDecoder(decoderConfig{
		Codec:       s.codec,
		Width:       width,
		Height:      height,
		PixelFormat: s.pixelFormat,
	})
	if err != nil {
		return err
	}
	s.decoder = decoder
	s.decoderWidth = width
	s.decoderHeight = height
	return nil
}

func (s *Service) detectStreamDimensions(payload []byte) (int, int, bool) {
	if s.codec != "" && s.codec != "h264" {
		return 0, 0, false
	}
	for _, nal := range splitAnnexBNALs(payload) {
		if len(nal) < 2 {
			continue
		}
		nalType := nal[0] & 0x1F
		if nalType != 7 { // SPS
			continue
		}
		width, height, err := parseH264SPSDimensions(nal)
		if err != nil {
			continue
		}
		if width > 0 && height > 0 {
			return width, height, true
		}
	}
	return 0, 0, false
}

func (s *Service) assembleH264AccessUnits(payload []byte) [][]byte {
	nals := splitAnnexBNALs(payload)
	if len(nals) == 0 {
		return nil
	}

	accessUnits := make([][]byte, 0, 2)
	flush := func() {
		if len(s.pendingAU) == 0 {
			return
		}
		out := make([]byte, len(s.pendingAU))
		copy(out, s.pendingAU)
		s.pendingAU = s.pendingAU[:0]
		s.pendingHasVCL = false
		accessUnits = append(accessUnits, out)
	}
	appendNAL := func(nal []byte) {
		s.pendingAU = append(s.pendingAU, 0x00, 0x00, 0x00, 0x01)
		s.pendingAU = append(s.pendingAU, nal...)
	}

	for _, nal := range nals {
		if len(nal) == 0 {
			continue
		}
		nalType := nal[0] & 0x1F
		isVCL := nalType >= 1 && nalType <= 5
		isDelimiterLike := nalType == 6 || nalType == 7 || nalType == 8 || nalType == 9
		if isDelimiterLike && s.pendingHasVCL {
			flush()
			appendNAL(nal)
			continue
		}
		if isVCL {
			firstMB, ok := parseFirstMBSlice(nal)
			if s.pendingHasVCL && ((ok && firstMB == 0) || !ok) {
				flush()
				appendNAL(nal)
				s.pendingHasVCL = true
				continue
			}
			s.pendingHasVCL = true
		}
		appendNAL(nal)
	}
	// Samples coming from SampleBuilder are typically complete access units.
	// Flush trailing VCL so we don't wait extra cycles for another boundary.
	if s.pendingHasVCL {
		flush()
	}
	return accessUnits
}

func parseFirstMBSlice(nal []byte) (int, bool) {
	if len(nal) < 2 {
		return 0, false
	}
	// Remove NAL header and emulation-prevention bytes.
	rbsp := make([]byte, 0, len(nal)-1)
	for i := 1; i < len(nal); i++ {
		if i+2 < len(nal) && nal[i] == 0x00 && nal[i+1] == 0x00 && nal[i+2] == 0x03 {
			rbsp = append(rbsp, 0x00, 0x00)
			i += 2
			continue
		}
		rbsp = append(rbsp, nal[i])
	}
	br := newSPSBitReader(rbsp)
	return br.readUE()
}

func (s *Service) writeFrame(frame DecodedFrame) error {
	s.sinkMu.RLock()
	sink := s.sink
	s.sinkMu.RUnlock()
	if sink == nil {
		return nil
	}

	return sink.WriteFrame(frame)
}

// SetFrameSink configures where decoded frames are sent after decode.
func (s *Service) SetFrameSink(sink FrameSink) {
	s.sinkMu.Lock()
	defer s.sinkMu.Unlock()
	s.sink = sink
}

// BindWatcherPeerConnection attaches watcher track handling to a Pion PeerConnection.
// Each new video track replaces the previous one (baton pass).
func (s *Service) BindWatcherPeerConnection(pc *webrtc.PeerConnection) error {
	if pc == nil {
		return fmt.Errorf("peer connection is nil")
	}

	pc.OnTrack(func(track *webrtc.TrackRemote, _ *webrtc.RTPReceiver) {
		if track == nil || track.Kind() != webrtc.RTPCodecTypeVideo {
			return
		}

		go s.requestKeyframes(pc, track)

		// Replace current streamer track when a new one arrives (baton pass).
		_ = s.ReplaceWatcherTrack(track)
	})

	return nil
}

func newDepacketizer(codec string) (rtp.Depacketizer, error) {
	switch strings.ToLower(strings.TrimSpace(codec)) {
	case "", "h264":
		return &codecs.H264Packet{}, nil
	case "vp8":
		return &codecs.VP8Packet{}, nil
	case "vp9":
		return &codecs.VP9Packet{}, nil
	default:
		return nil, fmt.Errorf("unsupported receiver codec: %s", codec)
	}
}

// ReplaceWatcherTrack swaps the active watcher track (baton pass).
func (s *Service) ReplaceWatcherTrack(track *webrtc.TrackRemote) error {
	if track == nil {
		return fmt.Errorf("track is nil")
	}

	generation := s.trackGeneration.Add(1)
	go s.readTrackLoop(track, generation)
	return nil
}

// DetachWatcherTrack invalidates the currently attached track and waits for replacement.
func (s *Service) DetachWatcherTrack() {
	s.trackGeneration.Add(1)
}

func (s *Service) readTrackLoop(track *webrtc.TrackRemote, generation uint64) {
	for {
		packet, _, err := track.ReadRTP()
		if err != nil {
			return
		}
		s.packetCount.Add(1)

		// A newer track replaced this one; stop forwarding from stale track.
		if s.trackGeneration.Load() != generation {
			return
		}

		select {
		case <-s.stopCh:
			return
		case s.inboundCh <- inboundPacket{packet: packet}:
		default:
			s.droppedCount.Add(1)
			// Drop one oldest packet to keep the stream live under backpressure.
			select {
			case <-s.inboundCh:
			default:
			}
			select {
			case s.inboundCh <- inboundPacket{packet: packet}:
			default:
			}
		}
	}
}

func (s *Service) requestKeyframes(pc *webrtc.PeerConnection, track *webrtc.TrackRemote) {
	if pc == nil || track == nil {
		return
	}

	sendPLI := func() {
		_ = pc.WriteRTCP([]rtcp.Packet{
			&rtcp.PictureLossIndication{MediaSSRC: uint32(track.SSRC())},
			&rtcp.FullIntraRequest{MediaSSRC: uint32(track.SSRC())},
		})
	}

	sendPLI()
	// Burst PLIs on startup to get the first decodable keyframe quickly.
	for i := 0; i < 6; i++ {
		select {
		case <-s.stopCh:
			return
		case <-time.After(500 * time.Millisecond):
			sendPLI()
		}
	}

	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-s.stopCh:
			return
		case <-ticker.C:
			sendPLI()
		}
	}
}

type Stats struct {
	Packets      uint64 `json:"packets"`
	Dropped      uint64 `json:"dropped"`
	Samples      uint64 `json:"samples"`
	Decoded      uint64 `json:"decoded"`
	Written      uint64 `json:"written"`
	DecodeErrors uint64 `json:"decode_errors"`
}

func (s *Service) Stats() Stats {
	return Stats{
		Packets:      s.packetCount.Load(),
		Dropped:      s.droppedCount.Load(),
		Samples:      s.sampleCount.Load(),
		Decoded:      s.decodedCount.Load(),
		Written:      s.writtenCount.Load(),
		DecodeErrors: s.decodeErrors.Load(),
	}
}

func normalizeH264Bytestream(payload []byte) []byte {
	if len(payload) < 4 {
		return payload
	}

	// Already Annex-B.
	if hasAnnexBStartCode(payload) {
		return payload
	}

	// Try AVCC length-prefixed NAL units.
	converted := make([]byte, 0, len(payload)+16)
	offset := 0
	for offset+4 <= len(payload) {
		nalSize := int(binary.BigEndian.Uint32(payload[offset : offset+4]))
		offset += 4
		if nalSize <= 0 || offset+nalSize > len(payload) {
			converted = converted[:0]
			break
		}
		converted = append(converted, 0x00, 0x00, 0x00, 0x01)
		converted = append(converted, payload[offset:offset+nalSize]...)
		offset += nalSize
	}
	if len(converted) > 0 && offset == len(payload) {
		return converted
	}

	// Single NAL fallback.
	single := make([]byte, 4+len(payload))
	copy(single[:4], []byte{0x00, 0x00, 0x00, 0x01})
	copy(single[4:], payload)
	return single
}

func hasAnnexBStartCode(payload []byte) bool {
	if len(payload) < 4 {
		return false
	}
	if payload[0] == 0x00 && payload[1] == 0x00 && payload[2] == 0x00 && payload[3] == 0x01 {
		return true
	}
	if len(payload) >= 3 && payload[0] == 0x00 && payload[1] == 0x00 && payload[2] == 0x01 {
		return true
	}
	return false
}

func (s *Service) ensureH264ParameterSets(accessUnit []byte) []byte {
	nals := splitAnnexBNALs(accessUnit)
	if len(nals) == 0 {
		return accessUnit
	}

	hasSPS := false
	hasPPS := false
	hasIDR := false
	var latestPrefix []byte

	for _, nal := range nals {
		if len(nal) == 0 {
			continue
		}
		nalType := nal[0] & 0x1F
		switch nalType {
		case 7: // SPS
			hasSPS = true
			latestPrefix = append(latestPrefix, 0x00, 0x00, 0x00, 0x01)
			latestPrefix = append(latestPrefix, nal...)
		case 8: // PPS
			hasPPS = true
			latestPrefix = append(latestPrefix, 0x00, 0x00, 0x00, 0x01)
			latestPrefix = append(latestPrefix, nal...)
		case 5: // IDR
			hasIDR = true
		}
	}

	if hasSPS && hasPPS && len(latestPrefix) > 0 {
		s.h264PrefixMu.Lock()
		s.h264Prefix = append(s.h264Prefix[:0], latestPrefix...)
		s.h264PrefixMu.Unlock()
	}

	if !hasIDR || (hasSPS && hasPPS) {
		return accessUnit
	}

	s.h264PrefixMu.Lock()
	defer s.h264PrefixMu.Unlock()
	if len(s.h264Prefix) == 0 {
		return accessUnit
	}

	out := make([]byte, 0, len(s.h264Prefix)+len(accessUnit))
	out = append(out, s.h264Prefix...)
	out = append(out, accessUnit...)
	return out
}

func splitAnnexBNALs(bytestream []byte) [][]byte {
	starts := findAnnexBStartCodes(bytestream)
	if len(starts) == 0 {
		return nil
	}

	nals := make([][]byte, 0, len(starts))
	for i, start := range starts {
		next := len(bytestream)
		if i+1 < len(starts) {
			next = starts[i+1]
		}

		prefixLen := 3
		if start+4 <= len(bytestream) && bytestream[start] == 0x00 && bytestream[start+1] == 0x00 && bytestream[start+2] == 0x00 && bytestream[start+3] == 0x01 {
			prefixLen = 4
		}
		nalStart := start + prefixLen
		if nalStart >= next || nalStart >= len(bytestream) {
			continue
		}
		nals = append(nals, bytestream[nalStart:next])
	}
	return nals
}

func findAnnexBStartCodes(bytestream []byte) []int {
	indexes := make([]int, 0, 8)
	for i := 0; i+3 < len(bytestream); i++ {
		if bytestream[i] == 0x00 && bytestream[i+1] == 0x00 && bytestream[i+2] == 0x01 {
			indexes = append(indexes, i)
			i += 2
			continue
		}
		if i+4 < len(bytestream) && bytestream[i] == 0x00 && bytestream[i+1] == 0x00 && bytestream[i+2] == 0x00 && bytestream[i+3] == 0x01 {
			indexes = append(indexes, i)
			i += 3
		}
	}
	return indexes
}
