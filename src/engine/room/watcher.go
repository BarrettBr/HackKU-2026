package room

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/BarrettBr/HackKU-2026/config"
	"github.com/pion/ice/v4"
	"github.com/pion/webrtc/v4"
)

// WatcherRuntime defines what the room join flow needs from the engine runtime.
type WatcherRuntime interface {
	BindWatcherPeerConnection(pc *webrtc.PeerConnection) error
	RunReceiver() error
	Stop() error
}

// SignalingClient exchanges a local offer for a remote answer.
type SignalingClient interface {
	ExchangeOffer(ctx context.Context, roomCode string, offer webrtc.SessionDescription) (webrtc.SessionDescription, error)
}

// JoinWatcher connects to a room as a watcher and starts the receive/decode pipeline.
// It intentionally stops before shared-memory write implementation.
func JoinWatcher(ctx context.Context, cfg *config.Config, runtime WatcherRuntime, signaling SignalingClient, roomCode string) error {
	if cfg == nil {
		return fmt.Errorf("config is nil")
	}
	if runtime == nil {
		return fmt.Errorf("runtime is nil")
	}
	if signaling == nil {
		return fmt.Errorf("signaling client is nil")
	}
	if strings.TrimSpace(roomCode) == "" {
		return fmt.Errorf("room code is required")
	}
	if cfg.Rtc_Conf == nil {
		return fmt.Errorf("rtc config is nil")
	}

	var settingEngine webrtc.SettingEngine
	settingEngine.SetICEMulticastDNSMode(ice.MulticastDNSModeDisabled)
	api := webrtc.NewAPI(webrtc.WithSettingEngine(settingEngine))

	pc, err := api.NewPeerConnection(*cfg.Rtc_Conf)
	if err != nil {
		return fmt.Errorf("create peer connection: %w", err)
	}
	defer func() {
		_ = pc.Close()
	}()

	if err := runtime.BindWatcherPeerConnection(pc); err != nil {
		return fmt.Errorf("bind watcher peer connection: %w", err)
	}

	_, err = pc.AddTransceiverFromKind(
		webrtc.RTPCodecTypeVideo,
		webrtc.RTPTransceiverInit{Direction: webrtc.RTPTransceiverDirectionRecvonly},
	)
	if err != nil {
		return fmt.Errorf("add video recvonly transceiver: %w", err)
	}

	offer, err := pc.CreateOffer(nil)
	if err != nil {
		return fmt.Errorf("create offer: %w", err)
	}
	if err := pc.SetLocalDescription(offer); err != nil {
		return fmt.Errorf("set local description: %w", err)
	}

	gatherComplete := webrtc.GatheringCompletePromise(pc)
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-gatherComplete:
	case <-time.After(400 * time.Millisecond):
	}

	if pc.LocalDescription() == nil {
		return fmt.Errorf("local description unavailable after ICE gathering")
	}

	answer, err := signaling.ExchangeOffer(ctx, roomCode, *pc.LocalDescription())
	if err != nil {
		return fmt.Errorf("exchange offer: %w", err)
	}
	if err := pc.SetRemoteDescription(answer); err != nil {
		return fmt.Errorf("set remote description: %w", err)
	}

	receiverErrCh := make(chan error, 1)
	go func() {
		receiverErrCh <- runtime.RunReceiver()
	}()

	pcStateErrCh := make(chan error, 1)
	pc.OnConnectionStateChange(func(state webrtc.PeerConnectionState) {
		log.Printf("watcher peer connection state=%s room=%s", state.String(), roomCode)
		switch state {
		case webrtc.PeerConnectionStateFailed:
			select {
			case pcStateErrCh <- fmt.Errorf("peer connection failed"):
			default:
			}
		case webrtc.PeerConnectionStateClosed:
			select {
			case pcStateErrCh <- fmt.Errorf("peer connection closed"):
			default:
			}
		}
	})

	select {
	case <-ctx.Done():
		_ = runtime.Stop()
		return ctx.Err()
	case err := <-pcStateErrCh:
		_ = runtime.Stop()
		if err != nil {
			return err
		}
		return nil
	case err := <-receiverErrCh:
		_ = runtime.Stop()
		if err != nil {
			return err
		}
		return nil
	}
}

type HTTPSignalingClient struct {
	OfferURL   string
	HTTPClient *http.Client
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

func NewHTTPSignalingClient(offerURL string, httpClient *http.Client) (*HTTPSignalingClient, error) {
	if strings.TrimSpace(offerURL) == "" {
		return nil, fmt.Errorf("offer url is required")
	}
	if httpClient == nil {
		httpClient = http.DefaultClient
	}

	return &HTTPSignalingClient{OfferURL: offerURL, HTTPClient: httpClient}, nil
}

func (c *HTTPSignalingClient) ExchangeOffer(ctx context.Context, roomCode string, offer webrtc.SessionDescription) (webrtc.SessionDescription, error) {
	reqBody := offerRequest{
		RoomCode: roomCode,
		Type:     offer.Type.String(),
		SDP:      offer.SDP,
	}

	payload, err := json.Marshal(reqBody)
	if err != nil {
		return webrtc.SessionDescription{}, err
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.OfferURL, bytes.NewReader(payload))
	if err != nil {
		return webrtc.SessionDescription{}, err
	}
	req.Header.Set("Content-Type", "application/json")

	res, err := c.HTTPClient.Do(req)
	if err != nil {
		return webrtc.SessionDescription{}, err
	}
	defer res.Body.Close()

	if res.StatusCode < 200 || res.StatusCode >= 300 {
		return webrtc.SessionDescription{}, fmt.Errorf("signaling returned status %d", res.StatusCode)
	}

	var parsed offerResponse
	if err := json.NewDecoder(res.Body).Decode(&parsed); err != nil {
		return webrtc.SessionDescription{}, err
	}

	answerType := webrtc.NewSDPType(parsed.Type)
	if answerType != webrtc.SDPTypeAnswer {
		answerType = webrtc.SDPTypeAnswer
	}

	return webrtc.SessionDescription{Type: answerType, SDP: parsed.SDP}, nil
}
