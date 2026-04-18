package transmitter

import (
	"errors"
	"log"

	"github.com/BarrettBr/HackKU-2026/config"
	"github.com/BarrettBr/HackKU-2026/transmitter/recording"
)

func NewRecording(appCfg *config.Config) (error){
	// Init stage
	switch appCfg.OS{
	case "linux-wayland":
		cfg, err := config.Load()
		if err != nil {
			log.Fatal(err)
			return err
		}

		stream, err := recording.NewStream(cfg)
		if err != nil {
			log.Fatal(err)
			return err
		}
		defer stream.Stop()

		return nil
	case "mac":
		return nil
	default:
		log.Print("OS not supported for screen sharing")
		return errors.New("OS not supported")
	}
}
