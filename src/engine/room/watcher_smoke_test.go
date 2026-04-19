package room

import (
	"context"
	"sync"
	"sync/atomic"
	"testing"

	"github.com/BarrettBr/HackKU-2026/config"
	"github.com/pion/webrtc/v4"
)

type smokeRuntime struct {
	mu      sync.Mutex
	boundPC *webrtc.PeerConnection

	bindCalls atomic.Int32
	runCalls  atomic.Int32
	stopCalls atomic.Int32
}

func (r *smokeRuntime) BindWatcherPeerConnection(pc *webrtc.PeerConnection) error {
	r.bindCalls.Add(1)
	r.mu.Lock()
	r.boundPC = pc
	r.mu.Unlock()
	return nil
}

func (r *smokeRuntime) RunReceiver() error {
	r.runCalls.Add(1)
	return nil
}

func (r *smokeRuntime) Stop() error {
	r.stopCalls.Add(1)
	return nil
}

type smokeSignaling struct {
	t   *testing.T
	cfg *webrtc.Configuration

	exchangeCalls atomic.Int32
	roomCode      string
}

func (s *smokeSignaling) ExchangeOffer(_ context.Context, roomCode string, offer webrtc.SessionDescription) (webrtc.SessionDescription, error) {
	s.exchangeCalls.Add(1)
	s.roomCode = roomCode
	if offer.Type != webrtc.SDPTypeOffer {
		s.t.Fatalf("expected local offer, got %s", offer.Type.String())
	}
	return buildAnswer(s.t, s.cfg, offer), nil
}

func buildAnswer(t *testing.T, cfg *webrtc.Configuration, offer webrtc.SessionDescription) webrtc.SessionDescription {
	t.Helper()

	pc, err := webrtc.NewPeerConnection(*cfg)
	if err != nil {
		t.Fatalf("create answerer peer connection: %v", err)
	}
	defer func() { _ = pc.Close() }()

	if err := pc.SetRemoteDescription(offer); err != nil {
		t.Fatalf("set remote offer: %v", err)
	}

	answer, err := pc.CreateAnswer(nil)
	if err != nil {
		t.Fatalf("create answer: %v", err)
	}
	if err := pc.SetLocalDescription(answer); err != nil {
		t.Fatalf("set local answer: %v", err)
	}

	<-webrtc.GatheringCompletePromise(pc)
	if pc.LocalDescription() == nil {
		t.Fatal("answerer local description is nil")
	}

	return *pc.LocalDescription()
}

func TestJoinWatcherSmoke(t *testing.T) {
	cfg := &config.Config{
		Rtc_Conf: &webrtc.Configuration{},
	}

	runtime := &smokeRuntime{}
	signaling := &smokeSignaling{
		t:   t,
		cfg: cfg.Rtc_Conf,
	}

	if err := JoinWatcher(context.Background(), cfg, runtime, signaling, "ROOM-SMOKE"); err != nil {
		t.Fatalf("JoinWatcher returned error: %v", err)
	}

	if got := signaling.exchangeCalls.Load(); got != 1 {
		t.Fatalf("expected signaling exchange once, got %d", got)
	}
	if signaling.roomCode != "ROOM-SMOKE" {
		t.Fatalf("expected room code ROOM-SMOKE, got %q", signaling.roomCode)
	}
	if got := runtime.bindCalls.Load(); got != 1 {
		t.Fatalf("expected runtime bind once, got %d", got)
	}
	if got := runtime.runCalls.Load(); got != 1 {
		t.Fatalf("expected runtime run once, got %d", got)
	}
	if got := runtime.stopCalls.Load(); got != 1 {
		t.Fatalf("expected runtime stop once, got %d", got)
	}

	runtime.mu.Lock()
	defer runtime.mu.Unlock()
	if runtime.boundPC == nil {
		t.Fatal("expected watcher peer connection to be bound")
	}
}
