package registry

import (
	"fmt"
	"io"

	"github.com/BarrettBr/HackKU-2026/config"
	"github.com/BarrettBr/HackKU-2026/receiver"
	"github.com/BarrettBr/HackKU-2026/transmitter"
	"github.com/pion/webrtc/v4"
)

type Runnable interface {
	Run() error
	Stop() error
}

type Registry struct {
	transmitter Runnable
	receiver    Runnable
}

type watcherBinder interface {
	BindWatcherPeerConnection(pc *webrtc.PeerConnection) error
}

type trackDetacher interface {
	DetachWatcherTrack()
}

type frameSinkSetter interface {
	SetFrameSink(sink receiver.FrameSink)
}

type receiverStatsProvider interface {
	Stats() receiver.Stats
}

type hostTrackProvider interface {
	LocalTrack() (*webrtc.TrackLocalStaticSample, error)
}

func New(cfg *config.Config) (*Registry, error) {
	if cfg == nil {
		return nil, fmt.Errorf("config is nil")
	}

	tx, err := transmitter.New(cfg)
	if err != nil {
		return nil, fmt.Errorf("create transmitter: %w", err)
	}

	rx, err := receiver.New(&cfg.Receiver)
	if err != nil {
		return nil, fmt.Errorf("create receiver: %w", err)
	}

	return &Registry{
		transmitter: tx,
		receiver:    rx,
	}, nil
}

func (r *Registry) Run() error {
	if err := r.transmitter.Run(); err != nil {
		return fmt.Errorf("run transmitter: %w", err)
	}

	if err := r.receiver.Run(); err != nil {
		return fmt.Errorf("run receiver: %w", err)
	}

	return nil
}

func (r *Registry) RunReceiver() error {
	if err := r.receiver.Run(); err != nil {
		return fmt.Errorf("run receiver: %w", err)
	}

	return nil
}

func (r *Registry) Stop() error {
	if err := r.transmitter.Stop(); err != nil {
		return fmt.Errorf("stop transmitter: %w", err)
	}

	if err := r.receiver.Stop(); err != nil {
		return fmt.Errorf("stop receiver: %w", err)
	}

	return nil
}

func (r *Registry) BindWatcherPeerConnection(pc *webrtc.PeerConnection) error {
	binder, ok := r.receiver.(watcherBinder)
	if !ok {
		return fmt.Errorf("receiver does not support watcher peer connection binding")
	}

	return binder.BindWatcherPeerConnection(pc)
}

func (r *Registry) DetachWatcherTrack() error {
	detacher, ok := r.receiver.(trackDetacher)
	if !ok {
		return fmt.Errorf("receiver does not support watcher track detach")
	}

	detacher.DetachWatcherTrack()
	return nil
}

func (r *Registry) SetReceiverFrameSink(sink receiver.FrameSink) error {
	setter, ok := r.receiver.(frameSinkSetter)
	if !ok {
		return fmt.Errorf("receiver does not support frame sink wiring")
	}

	setter.SetFrameSink(sink)
	return nil
}

func (r *Registry) AttachHostPeerConnection(pc *webrtc.PeerConnection) error {
	if pc == nil {
		return fmt.Errorf("peer connection is nil")
	}

	provider, ok := r.transmitter.(hostTrackProvider)
	if !ok {
		return fmt.Errorf("transmitter does not support host track binding")
	}

	track, err := provider.LocalTrack()
	if err != nil {
		return fmt.Errorf("get host video track: %w", err)
	}

	sender, err := pc.AddTrack(track)
	if err != nil {
		return fmt.Errorf("add host video track: %w", err)
	}

	go func() {
		rtcpBuf := make([]byte, 1500)
		for {
			if _, _, err := sender.Read(rtcpBuf); err != nil {
				if err == io.EOF {
					return
				}
				return
			}
		}
	}()

	return nil
}

func (r *Registry) ReceiverStats() (receiver.Stats, error) {
	provider, ok := r.receiver.(receiverStatsProvider)
	if !ok {
		return receiver.Stats{}, fmt.Errorf("receiver does not expose stats")
	}
	return provider.Stats(), nil
}
