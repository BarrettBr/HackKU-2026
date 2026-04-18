package transmitter

import "github.com/BarrettBr/HackKU-2026/config"

type Service struct {
	cfg config.Transmitter
}

func New(cfg config.Transmitter) (*Service, error) {
	return &Service{cfg: cfg}, nil
}

func (s *Service) Run() error {
	return nil
}

func (s *Service) Stop() error {
	return nil
}
