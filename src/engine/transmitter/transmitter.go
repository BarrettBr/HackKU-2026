package transmitter

import (
	"fmt"
	"io"
	"log"
	"os"
	"os/exec"
	"sync"
	"time"

	"github.com/BarrettBr/HackKU-2026/config"
	"github.com/BarrettBr/HackKU-2026/transmitter/recording"
	"github.com/pion/webrtc/v4"
	"github.com/pion/webrtc/v4/pkg/media"
	"github.com/pion/webrtc/v4/pkg/media/h264reader"
)

type Service struct {
	cfg   *config.Config
	track *webrtc.TrackLocalStaticSample

	encoder Encoder

	runOnce  sync.Once
	stopOnce sync.Once
	stopCh   chan struct{}
	wg       sync.WaitGroup
}

func New(cfg *config.Config) (*Service, error) {
	if cfg == nil {
		return nil, fmt.Errorf("transmitter config is nil")
	}

	track, err := webrtc.NewTrackLocalStaticSample(
		webrtc.RTPCodecCapability{
			MimeType:  webrtc.MimeTypeH264,
			ClockRate: 90000,
		},
		"video",
		"moovie-host",
	)
	if err != nil {
		return nil, fmt.Errorf("create host video track: %w", err)
	}

	return &Service{
		cfg:    cfg,
		track:  track,
		stopCh: make(chan struct{}),
	}, nil
}

func (s *Service) Run() error {
	s.runOnce.Do(func() {
		enc, err := NewEncoder(&s.cfg.Transmitter)
		if err == nil {
			s.encoder = enc
		}

		s.wg.Add(1)
		go s.runCaptureLoop()
	})
	return nil
}

func (s *Service) Stop() error {
	s.stopOnce.Do(func() {
		close(s.stopCh)
	})
	s.wg.Wait()
	if s.encoder != nil {
		_ = s.encoder.Close()
	}
	return nil
}

func (s *Service) LocalTrack() (*webrtc.TrackLocalStaticSample, error) {
	if err := s.Run(); err != nil {
		return nil, err
	}
	return s.track, nil
}

func (s *Service) runSyntheticH264Loop() {
	width := s.cfg.Transmitter.PixelWidth
	height := s.cfg.Transmitter.PixelHeight
	frameRate := s.cfg.Transmitter.FrameRate
	if width <= 0 {
		width = 640
	}
	if height <= 0 {
		height = 360
	}
	if frameRate <= 0 {
		frameRate = 30
	}

	args := []string{
		"-hide_banner",
		"-loglevel", "error",
		"-re",
		"-f", "lavfi",
		"-i", fmt.Sprintf("testsrc=size=%dx%d:rate=%d", width, height, frameRate),
		"-an",
		"-c:v", pickH264Encoder(),
		"-pix_fmt", "yuv420p",
		"-f", "h264",
		"pipe:1",
	}

	cmd := exec.Command("ffmpeg", args...)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return
	}
	if err := cmd.Start(); err != nil {
		return
	}
	defer func() {
		_ = cmd.Process.Kill()
		_ = cmd.Wait()
	}()

	reader, err := h264reader.NewReader(stdout)
	if err != nil {
		return
	}

	frameDuration := time.Second / time.Duration(frameRate)
	writeSample := func(nal []byte) {
		if len(nal) == 0 {
			return
		}
		payload := make([]byte, 4+len(nal))
		copy(payload[:4], []byte{0x00, 0x00, 0x00, 0x01})
		copy(payload[4:], nal)
		_ = s.track.WriteSample(media.Sample{
			Data:     payload,
			Duration: frameDuration,
		})
	}
	for {
		select {
		case <-s.stopCh:
			return
		default:
		}

		nal, err := reader.NextNAL()
		if err != nil {
			if err == io.EOF {
				return
			}
			return
		}
		if nal == nil || len(nal.Data) == 0 {
			continue
		}

		writeSample(nal.Data)
	}
}

func (s *Service) runCaptureLoop() {
	defer s.wg.Done()

	// Primary runtime path: real screen capture via portal/PipeWire.
	if s.cfg.OS == "linux-wayland" {
		if stream, err := recording.NewStream(s.cfg); err == nil {
			defer stream.Stop()
			if s.streamFrames(stream) {
				return
			}
			log.Printf("capture stream ended without usable frames")
		} else {
			log.Printf("capture init failed: %v", err)
		}
	}

	// Synthetic fallback is opt-in only so runtime doesn't silently show test video.
	if os.Getenv("ENGINE_ALLOW_SYNTHETIC_FALLBACK") == "1" {
		log.Printf("using synthetic video fallback")
		s.runSyntheticH264Loop()
	}
}

func (s *Service) streamFrames(stream recording.ScreenStream) bool {
	if s.encoder == nil {
		return false
	}

	frameRate := s.cfg.Transmitter.FrameRate
	if frameRate <= 0 {
		frameRate = 30
	}
	frameDuration := time.Second / time.Duration(frameRate)
	frames := 0

	for {
		select {
		case <-s.stopCh:
			return frames > 0
		case frame, ok := <-stream.Frames():
			if !ok {
				return frames > 0
			}
			frames++
			if frames == 1 {
				log.Printf(
					"capture first frame format=%d size=%dx%d cfg=%dx%d",
					frame.Format,
					frame.Width,
					frame.Height,
					s.cfg.Transmitter.PixelWidth,
					s.cfg.Transmitter.PixelHeight,
				)
			}
			encoded, err := s.encoder.Encode(frame)
			if err != nil {
				continue
			}
			if len(encoded.Data) == 0 {
				continue
			}

			_ = s.track.WriteSample(media.Sample{
				Data:     encoded.Data,
				Duration: frameDuration,
			})
		}
	}
}
