package receiver

import "github.com/BarrettBr/HackKU-2026/config"

type Service struct {
	cfg config.Receiver
}

func New(cfg config.Receiver) (*Service, error) {
	return &Service{cfg: cfg}, nil
}

func (s *Service) Run() error {
	return nil
}

func (s *Service) Stop() error {
	return nil
}
