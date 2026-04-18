package registry

import (
	"github.com/BarrettBr/HackKU-2026/config"
	"github.com/BarrettBr/HackKU-2026/receiver"
	"github.com/BarrettBr/HackKU-2026/transmitter"
)

type Registry struct {
	transmitter config.Transmitter
	receiver    config.Receiver
}

func New(cfg *config.Config) *Registry {
	return &Registry{
		transmitter: transmitter.New(),
		receiver:    receiver.New(),
	}
}

func (r Registry) Run() {

}
