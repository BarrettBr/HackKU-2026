package transmitter

import (
	"errors"

	"github.com/BarrettBr/HackKU-2026/config"
	"github.com/BarrettBr/HackKU-2026/transmitter/recording"
)

func NewRecording(appCfg *config.Config) error {
	// Init stage
	switch appCfg.OS {
	case "linux-wayland":
		stream, err := recording.NewStream(appCfg)
		if err != nil {
			return err
		}
		defer stream.Stop()

		return nil
	case "mac":
		return nil
	default:
		return errors.New("OS not supported")
	}
}
