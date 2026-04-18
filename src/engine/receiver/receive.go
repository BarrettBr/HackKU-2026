package receiver

import (
	"errors"
	"fmt"
	"io"
	"strings"
	"sync"
	"time"

	"github.com/BarrettBr/HackKU-2026/config"
	"github.com/pion/rtp"
	"github.com/pion/rtp/codecs"
	"github.com/pion/webrtc/v4/pkg/media/samplebuilder"
)

// RTPPacket represents one inbound network packet.
type RTPPacket struct {
	Raw []byte
}

type Service struct {
	stopOnce sync.Once
	stopCh   chan struct{}

	sampleBuilder *samplebuilder.SampleBuilder
	decoder       Decoder
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
	}, nil
}

func (s *Service) Run() error {
	for {
		select {
		case <-s.stopCh:
			return nil
		default:
		}

		pkt, err := s.receivePacket()
		if err != nil {
			// No packet available yet. Keep receiver alive and polling.
			if errors.Is(err, io.EOF) {
				time.Sleep(5 * time.Millisecond)
				continue
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
	// TODO: SRTP/RTP room transport read needs to be added.
	return RTPPacket{}, io.EOF
}

func (s *Service) depacketize(pkt RTPPacket) (EncodedFrame, bool, error) {
	var rtpPacket rtp.Packet
	if err := rtpPacket.Unmarshal(pkt.Raw); err != nil {
		return EncodedFrame{}, false, err
	}

	s.sampleBuilder.Push(&rtpPacket)
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
