package registry

import (
	"fmt"

	"github.com/BarrettBr/HackKU-2026/config"
	"github.com/BarrettBr/HackKU-2026/receiver"
	"github.com/BarrettBr/HackKU-2026/transmitter"
)

type Runnable interface {
	Run() error
	Stop() error
}

type Registry struct {
	transmitter Runnable
	receiver    Runnable
}

func New(cfg *config.Config) (*Registry, error) {
	if cfg == nil {
		return nil, fmt.Errorf("config is nil")
	}

	tx, err := transmitter.New(cfg.Transmitter)
	if err != nil {
		return nil, fmt.Errorf("create transmitter: %w", err)
	}

	rx, err := receiver.New(cfg.Receiver)
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

func (r *Registry) Stop() error {
	if err := r.transmitter.Stop(); err != nil {
		return fmt.Errorf("stop transmitter: %w", err)
	}

	if err := r.receiver.Stop(); err != nil {
		return fmt.Errorf("stop receiver: %w", err)
	}

	return nil
}
