package room

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"testing"
	"time"

	"github.com/BarrettBr/HackKU-2026/config"
	"github.com/BarrettBr/HackKU-2026/receiver"
	"github.com/BarrettBr/HackKU-2026/registry"
	"github.com/pion/webrtc/v4"
)

type loopbackSignaling struct {
	t      *testing.T
	hostPC *webrtc.PeerConnection
}

func (s *loopbackSignaling) ExchangeOffer(_ context.Context, _ string, offer webrtc.SessionDescription) (webrtc.SessionDescription, error) {
	if err := s.hostPC.SetRemoteDescription(offer); err != nil {
		return webrtc.SessionDescription{}, err
	}

	answer, err := s.hostPC.CreateAnswer(nil)
	if err != nil {
		return webrtc.SessionDescription{}, err
	}
	if err := s.hostPC.SetLocalDescription(answer); err != nil {
		return webrtc.SessionDescription{}, err
	}
	<-webrtc.GatheringCompletePromise(s.hostPC)
	if s.hostPC.LocalDescription() == nil {
		s.t.Fatal("host local description is nil")
	}
	return *s.hostPC.LocalDescription(), nil
}

type testFrameSink struct {
	ch chan receiver.DecodedFrame
}

func (s *testFrameSink) WriteFrame(frame receiver.DecodedFrame) error {
	select {
	case s.ch <- frame:
	default:
	}
	return nil
}

func TestFullPipelineSmoke(t *testing.T) {
	if os.Getenv("ENGINE_E2E") != "1" {
		t.Skip("set ENGINE_E2E=1 to run full WebRTC media smoke test")
	}
	if _, err := exec.LookPath("ffmpeg"); err != nil {
		t.Skip("ffmpeg not found in PATH")
	}

	cfg := &config.Config{
		Rtc_Conf: &webrtc.Configuration{},
		Transmitter: config.Transmitter{
			PixelWidth:  320,
			PixelHeight: 180,
			FrameRate:   15,
			Codec:       "h264",
			PixelFormat: "rgba",
		},
		Receiver: config.Receiver{
			Codec:       "h264",
			Width:       320,
			Height:      180,
			PixelFormat: "yuv420p",
		},
	}

	appRegistry, err := registry.New(cfg)
	if err != nil {
		t.Fatalf("create registry: %v", err)
	}
	defer func() { _ = appRegistry.Stop() }()

	sink := &testFrameSink{ch: make(chan receiver.DecodedFrame, 16)}
	if err := appRegistry.SetReceiverFrameSink(sink); err != nil {
		t.Fatalf("set receiver sink: %v", err)
	}

	hostPC, err := webrtc.NewPeerConnection(*cfg.Rtc_Conf)
	if err != nil {
		t.Fatalf("create host peer connection: %v", err)
	}
	defer func() { _ = hostPC.Close() }()

	if err := appRegistry.AttachHostPeerConnection(hostPC); err != nil {
		t.Fatalf("attach host track: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()

	errCh := make(chan error, 1)
	go func() {
		errCh <- JoinWatcher(ctx, cfg, appRegistry, &loopbackSignaling{t: t, hostPC: hostPC}, "ROOM-SMOKE")
	}()

	select {
	case frame := <-sink.ch:
		if len(frame.Data) == 0 {
			t.Fatal("decoded frame is empty")
		}
		cancel()
	case err := <-errCh:
		if err == nil {
			t.Fatal("join watcher exited before any frame was decoded")
		}
		t.Fatalf("join watcher failed before first frame: %v", err)
	case <-ctx.Done():
		t.Fatal("timed out waiting for decoded frame")
	}

	select {
	case err := <-errCh:
		if err != nil && !errors.Is(err, context.Canceled) {
			t.Fatalf("join watcher failed: %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("join watcher did not stop after cancel")
	}
}
