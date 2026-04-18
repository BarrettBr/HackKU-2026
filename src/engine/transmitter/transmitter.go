package transmitter

import (
	"fmt"

	"github.com/BarrettBr/HackKU-2026/config"
)

type Service struct {
	cfg *config.Config
}

func New(cfg *config.Config) (*Service, error) {
	if cfg == nil {
		return nil, fmt.Errorf("transmitter config is nil")
	}

	return &Service{cfg: cfg}, nil
}

func (s *Service) Run() error {
	return NewRecording(s.cfg)
}

func (s *Service) Stop() error {
	return nil
}
