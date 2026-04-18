package transmitter

import (
	"errors"
	"log"

	"github.com/BarrettBr/HackKU-2026/config"
	"github.com/BarrettBr/HackKU-2026/transmitter/recording"
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

func Stream(appCfg *config.Config) (error){
	// Init stage
	var data chan recording.Frame
	if appCfg.OS == "linux-wayland"{
		data, err = recording.NewStream_Wayland()
		return nil
	} else if appCfg.OS =="mac"{
		return nil
	} else {
		log.Print("OS not supported for screen sharing")
		return errors.New("OS not supported")
	}
}
