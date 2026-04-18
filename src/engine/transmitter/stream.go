package transmitter

import (
	"errors"
	"log"

	"github.com/BarrettBr/HackKU-2026/config"
)

type ScreenStream interface {
	Frames() <-chan Frame
	Stop()
}

type Frame struct {
	Width  int
	Height int
	Data   []byte
}

func Stream(appCfg *config.Config) error {
	if appCfg.OS == "linux-wayland" {
		return nil
	} else if appCfg.OS == "mac" {
		return nil
	} else {
		log.Print("OS not supported for screen sharing")
		return errors.New("OS not supported")
	}
}
