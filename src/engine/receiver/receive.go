package receiver

import (
	"errors"
	"fmt"
	"io"
	"strings"
	"sync"
	"sync/atomic"

	"github.com/BarrettBr/HackKU-2026/config"
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

	trackAttached atomic.Bool

	sampleBuilder *samplebuilder.SampleBuilder
	decoder       Decoder
	inboundCh     chan inboundPacket
}

type inboundPacket struct {
	packet *rtp.Packet
	err    error
}

func New(cfg *config.Receiver) (*Service, error) {
	if cfg == nil {
		return nil, fmt.Errorf("receiver config is nil")
	}

	depacketizer, err := newDepacketizer(cfg.Codec)
	if err != nil {
		return nil, err
	}

	decoder, err := newDecoder(decoderConfig{
		Codec:       cfg.Codec,
		Width:       cfg.Width,
		Height:      cfg.Height,
		PixelFormat: cfg.PixelFormat,
	})
	if err != nil {
		return nil, err
	}

	return &Service{
		stopCh:        make(chan struct{}),
		sampleBuilder: samplebuilder.New(64, depacketizer, 90000),
		decoder:       decoder,
		inboundCh:     make(chan inboundPacket, 256),
	}, nil
}

func (s *Service) Run() error {
	for {
		pkt, err := s.receivePacket()
		if err != nil {
			if errors.Is(err, io.EOF) || errors.Is(err, webrtc.ErrConnectionClosed) {
				// Stream ended or service is shutting down.
				return nil
			}
			return err
		}

		encoded, ready, err := s.depacketize(pkt)
		if err != nil {
			return err
		}
		if !ready {
			continue
		}

		decoded, err := s.decodeFrame(encoded)
		if err != nil {
			return err
		}

		if err := s.writeFrame(decoded); err != nil {
			return err
		}
	}
}

func (s *Service) Stop() error {
	s.stopOnce.Do(func() {
		close(s.stopCh)
	})
	return s.decoder.Close()
}

func (s *Service) receivePacket() (RTPPacket, error) {
	select {
	case <-s.stopCh:
		return RTPPacket{}, io.EOF
	case inbound := <-s.inboundCh:
		if inbound.err != nil {
			return RTPPacket{}, inbound.err
		}
		return RTPPacket{Packet: inbound.packet}, nil
	}
}

func (s *Service) depacketize(pkt RTPPacket) (EncodedFrame, bool, error) {
	if pkt.Packet == nil {
		return EncodedFrame{}, false, fmt.Errorf("nil RTP packet")
	}

	s.sampleBuilder.Push(pkt.Packet)
	sample := s.sampleBuilder.Pop()
	if sample == nil {
		return EncodedFrame{}, false, nil
	}

	return EncodedFrame{Payload: sample.Data}, true, nil
}

func (s *Service) decodeFrame(frame EncodedFrame) (DecodedFrame, error) {
	return s.decoder.Decode(frame)
}

func (s *Service) writeFrame(frame DecodedFrame) error {
	// TODO: shared memory IPC writer
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

// AttachWatcherTrack binds the receiver to a watcher RTP track.
// Pion handles DTLS/SRTP and this service consumes plain RTP packets.
func (s *Service) AttachWatcherTrack(track *webrtc.TrackRemote) error {
	if track == nil {
		return fmt.Errorf("track is nil")
	}

	if !s.trackAttached.CompareAndSwap(false, true) {
		return fmt.Errorf("watcher track already attached")
	}

	go s.readTrackLoop(track)
	return nil
}

func (s *Service) readTrackLoop(track *webrtc.TrackRemote) {
	for {
		packet, _, err := track.ReadRTP()
		if err != nil {
			select {
			case <-s.stopCh:
				return
			case s.inboundCh <- inboundPacket{err: err}:
			default:
			}
			return
		}

		select {
		case <-s.stopCh:
			return
		case s.inboundCh <- inboundPacket{packet: packet}:
		}
	}
}
