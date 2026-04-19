package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"

	"github.com/BarrettBr/HackKU-2026/config"
	"github.com/BarrettBr/HackKU-2026/ipc"
	"github.com/BarrettBr/HackKU-2026/receiver"
	"github.com/BarrettBr/HackKU-2026/registry"
	"github.com/BarrettBr/HackKU-2026/room"
	"github.com/pion/ice/v4"
	"github.com/pion/webrtc/v4"
)

type subscribeRequest struct {
	RoomCode     string `json:"room_code"`
	SignalingURL string `json:"signaling_url"`
}

type subscriptionStatus struct {
	Active       bool   `json:"active"`
	RoomCode     string `json:"room_code,omitempty"`
	SignalingURL string `json:"signaling_url,omitempty"`
	IPCPath      string `json:"ipc_path,omitempty"`
	Width        int    `json:"width,omitempty"`
	Height       int    `json:"height,omitempty"`
	PixelFormat  string `json:"pixel_format,omitempty"`
	LastError    string `json:"last_error,omitempty"`
	Packets      uint64 `json:"packets"`
	Dropped      uint64 `json:"dropped"`
	Samples      uint64 `json:"samples"`
	Decoded      uint64 `json:"decoded"`
	Written      uint64 `json:"written"`
	DecodeErrors uint64 `json:"decode_errors"`
}

type offerRequest struct {
	RoomCode string `json:"room_code"`
	Type     string `json:"type"`
	SDP      string `json:"sdp"`
}

type offerResponse struct {
	Type string `json:"type"`
	SDP  string `json:"sdp"`
}

type watcherController struct {
	cfg     *config.Config
	runtime *registry.Registry

	mu            sync.Mutex
	cancel        context.CancelFunc
	status        subscriptionStatus
	sink          frameSinkCloser
	hostPCs       map[string]*webrtc.PeerConnection
	sessionSeq    atomic.Uint64
	activeSession uint64
}

type frameSinkCloser interface {
	receiver.FrameSink
	io.Closer
}

type negotiatedSink struct {
	path        string
	pixelFormat string
	slotCount   int

	mu          sync.Mutex
	inner       *ipc.RingBufferSink
	width       int
	height      int
	onDimension func(width, height int, pixelFormat string)
}

func newNegotiatedSink(path, pixelFormat string, slotCount int, onDimension func(width, height int, pixelFormat string)) *negotiatedSink {
	return &negotiatedSink{
		path:        path,
		pixelFormat: pixelFormat,
		slotCount:   slotCount,
		onDimension: onDimension,
	}
}

func (s *negotiatedSink) WriteFrame(frame receiver.DecodedFrame) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if len(frame.Data) == 0 {
		return nil
	}
	if s.inner == nil {
		width := frame.Width
		height := frame.Height
		if width <= 0 || height <= 0 {
			return nil
		}
		format := strings.TrimSpace(frame.Format)
		if format == "" {
			format = s.pixelFormat
		}
		inner, err := ipc.NewRingBufferSink(ipc.RingBufferConfig{
			Path:        s.path,
			Width:       width,
			Height:      height,
			PixelFormat: format,
			SlotCount:   s.slotCount,
		})
		if err != nil {
			return err
		}
		s.inner = inner
		s.width = width
		s.height = height
		if s.onDimension != nil {
			s.onDimension(width, height, format)
		}
	}
	return s.inner.WriteFrame(frame)
}

func (s *negotiatedSink) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.inner != nil {
		err := s.inner.Close()
		s.inner = nil
		return err
	}
	return nil
}

func newWatcherController(cfg *config.Config, runtime *registry.Registry) *watcherController {
	return &watcherController{cfg: cfg, runtime: runtime, hostPCs: map[string]*webrtc.PeerConnection{}}
}

func (w *watcherController) subscribe(req subscribeRequest) (subscriptionStatus, error) {
	if strings.TrimSpace(req.RoomCode) == "" {
		return subscriptionStatus{}, fmt.Errorf("room_code is required")
	}
	if strings.TrimSpace(req.SignalingURL) == "" {
		return subscriptionStatus{}, fmt.Errorf("signaling_url is required")
	}

	client, err := room.NewHTTPSignalingClient(req.SignalingURL, nil)
	if err != nil {
		return subscriptionStatus{}, err
	}

	ipcPath := filepath.Join("/tmp", fmt.Sprintf("moovie-%s.ipc", sanitizeRoomCode(req.RoomCode)))
	sink := newNegotiatedSink(ipcPath, w.cfg.Receiver.PixelFormat, 8, func(width, height int, pixelFormat string) {
		w.mu.Lock()
		defer w.mu.Unlock()
		w.status.Width = width
		w.status.Height = height
		w.status.PixelFormat = pixelFormat
	})

	w.mu.Lock()
	if w.cancel != nil {
		w.cancel()
		w.cancel = nil
	}
	w.activeSession = 0
	if w.sink != nil {
		_ = w.sink.Close()
		w.sink = nil
	}
	w.mu.Unlock()

	if err := w.runtime.SetReceiverFrameSink(sink); err != nil {
		return subscriptionStatus{}, err
	}

	w.mu.Lock()
	ctx, cancel := context.WithCancel(context.Background())
	sessionID := w.sessionSeq.Add(1)
	w.cancel = cancel
	w.activeSession = sessionID
	w.sink = sink
	w.status = subscriptionStatus{
		Active:       true,
		RoomCode:     req.RoomCode,
		SignalingURL: req.SignalingURL,
		IPCPath:      ipcPath,
		Width:        0,
		Height:       0,
		PixelFormat:  w.cfg.Receiver.PixelFormat,
	}
	status := w.status
	w.mu.Unlock()

	go w.runWatcherSession(ctx, sessionID, client, req.RoomCode, req.SignalingURL)
	return status, nil
}

func (w *watcherController) runWatcherSession(ctx context.Context, sessionID uint64, client room.SignalingClient, roomCode, signalingURL string) {
	err := room.JoinWatcher(ctx, w.cfg, w.runtime, client, roomCode)

	w.mu.Lock()
	defer w.mu.Unlock()
	if w.activeSession == sessionID {
		w.cancel = nil
		w.activeSession = 0
		w.status.Active = false
	}
	if err != nil && err != context.Canceled {
		w.status.LastError = err.Error()
		log.Printf("watcher session ended with error room=%s signaling=%s err=%v", roomCode, signalingURL, err)
	}
}

func (w *watcherController) unsubscribe() {
	w.mu.Lock()
	defer w.mu.Unlock()

	if w.cancel != nil {
		w.cancel()
		w.cancel = nil
	}
	if w.sink != nil {
		_ = w.sink.Close()
		w.sink = nil
	}
	for roomCode, pc := range w.hostPCs {
		_ = pc.Close()
		delete(w.hostPCs, roomCode)
	}
	_ = w.runtime.SetReceiverFrameSink(nil)
	_ = w.runtime.DetachWatcherTrack()
	w.status.Active = false
}

func (w *watcherController) getStatus() subscriptionStatus {
	w.mu.Lock()
	defer w.mu.Unlock()
	status := w.status
	if stats, err := w.runtime.ReceiverStats(); err == nil {
		status.Packets = stats.Packets
		status.Dropped = stats.Dropped
		status.Samples = stats.Samples
		status.Decoded = stats.Decoded
		status.Written = stats.Written
		status.DecodeErrors = stats.DecodeErrors
	}
	return status
}

func (w *watcherController) handleOffer(req offerRequest) (offerResponse, error) {
	if w.cfg == nil || w.cfg.Rtc_Conf == nil {
		return offerResponse{}, fmt.Errorf("rtc config unavailable")
	}
	if strings.TrimSpace(req.RoomCode) == "" {
		return offerResponse{}, fmt.Errorf("room_code is required")
	}
	if strings.TrimSpace(req.SDP) == "" {
		return offerResponse{}, fmt.Errorf("sdp is required")
	}

	offerType := webrtc.NewSDPType(strings.ToLower(strings.TrimSpace(req.Type)))
	if offerType != webrtc.SDPTypeOffer {
		offerType = webrtc.SDPTypeOffer
	}

	var settingEngine webrtc.SettingEngine
	settingEngine.SetICEMulticastDNSMode(ice.MulticastDNSModeDisabled)
	api := webrtc.NewAPI(webrtc.WithSettingEngine(settingEngine))

	pc, err := api.NewPeerConnection(*w.cfg.Rtc_Conf)
	if err != nil {
		return offerResponse{}, err
	}

	if err := w.runtime.AttachHostPeerConnection(pc); err != nil {
		_ = pc.Close()
		return offerResponse{}, err
	}

	if err := pc.SetRemoteDescription(webrtc.SessionDescription{Type: offerType, SDP: req.SDP}); err != nil {
		_ = pc.Close()
		return offerResponse{}, err
	}

	answer, err := pc.CreateAnswer(nil)
	if err != nil {
		_ = pc.Close()
		return offerResponse{}, err
	}
	if err := pc.SetLocalDescription(answer); err != nil {
		_ = pc.Close()
		return offerResponse{}, err
	}

	gatherDone := webrtc.GatheringCompletePromise(pc)
	<-gatherDone
	if pc.LocalDescription() == nil {
		_ = pc.Close()
		return offerResponse{}, fmt.Errorf("local answer unavailable")
	}

	w.mu.Lock()
	if old, ok := w.hostPCs[req.RoomCode]; ok {
		_ = old.Close()
	}
	w.hostPCs[req.RoomCode] = pc
	w.mu.Unlock()
	pc.OnConnectionStateChange(func(state webrtc.PeerConnectionState) {
		log.Printf("host peer connection state=%s room=%s", state.String(), req.RoomCode)
	})

	return offerResponse{Type: pc.LocalDescription().Type.String(), SDP: pc.LocalDescription().SDP}, nil
}

func setupAPIServer(cfg *config.Config, appRegistry *registry.Registry) *http.Server {
	controller := newWatcherController(cfg, appRegistry)
	mux := http.NewServeMux()

	writeJSON := func(rw http.ResponseWriter, code int, payload any) {
		rw.Header().Set("Content-Type", "application/json")
		rw.WriteHeader(code)
		_ = json.NewEncoder(rw).Encode(payload)
	}

	mux.HandleFunc("/healthz", func(rw http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			rw.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		writeJSON(rw, http.StatusOK, map[string]string{"status": "ok"})
	})

	subscribeHandler := func(rw http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			rw.WriteHeader(http.StatusMethodNotAllowed)
			return
		}

		var req subscribeRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeJSON(rw, http.StatusBadRequest, map[string]string{"error": fmt.Sprintf("invalid request: %v", err)})
			return
		}

		status, err := controller.subscribe(req)
		if err != nil {
			writeJSON(rw, http.StatusBadRequest, map[string]string{"error": err.Error()})
			return
		}

		writeJSON(rw, http.StatusAccepted, map[string]any{"status": "subscribed", "subscription": status})
	}
	mux.HandleFunc("/subscribe", subscribeHandler)
	mux.HandleFunc("/api/subscribe", subscribeHandler)

	unsubscribeHandler := func(rw http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			rw.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		controller.unsubscribe()
		writeJSON(rw, http.StatusOK, map[string]string{"status": "unsubscribed"})
	}
	mux.HandleFunc("/unsubscribe", unsubscribeHandler)
	mux.HandleFunc("/api/unsubscribe", unsubscribeHandler)

	subscriptionHandler := func(rw http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			rw.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		writeJSON(rw, http.StatusOK, controller.getStatus())
	}
	mux.HandleFunc("/subscription", subscriptionHandler)
	mux.HandleFunc("/api/subscription", subscriptionHandler)

	offerHandler := func(rw http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			rw.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		var req offerRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeJSON(rw, http.StatusBadRequest, map[string]string{"error": fmt.Sprintf("invalid request: %v", err)})
			return
		}

		answer, err := controller.handleOffer(req)
		if err != nil {
			writeJSON(rw, http.StatusBadRequest, map[string]string{"error": err.Error()})
			return
		}

		writeJSON(rw, http.StatusOK, answer)
	}
	mux.HandleFunc("/offer", offerHandler)
	mux.HandleFunc("/api/offer", offerHandler)

	return &http.Server{Addr: ":8080", Handler: mux}
}

func sanitizeRoomCode(roomCode string) string {
	var b strings.Builder
	for _, r := range roomCode {
		if (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9') || r == '-' || r == '_' {
			b.WriteRune(r)
		} else {
			b.WriteRune('_')
		}
	}
	if b.Len() == 0 {
		return "default"
	}
	return b.String()
}
