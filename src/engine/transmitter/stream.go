package transmitter

import (
	"errors"
	"log"
	"os"
    "os/signal"
    "syscall"


	"github.com/BarrettBr/HackKU-2026/config"
	"github.com/BarrettBr/HackKU-2026/transmitter/recording"
)

func NewRecording(appCfg *config.Config) (error){
	// Init stage
	if appCfg.OS == "linux-wayland"{
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

		// Ctrl-C = clean shutdown
		sigs := make(chan os.Signal, 1)
		signal.Notify(sigs, syscall.SIGINT, syscall.SIGTERM)
		go func() { <-sigs; stream.Stop() }()

		for f := range stream.Frames() {
			log.Printf("frame %dx%d %s %d bytes", f.Width, f.Height, f.Format, len(f.Data))
			// hand f.Data off to your encoder here
		}

		if err := stream.Err(); err != nil {
			log.Fatal(err)
			return err
		}
		return nil
	} else if appCfg.OS =="mac"{
		return nil
	} else {
		log.Print("OS not supported for screen sharing")
		return errors.New("OS not supported")
	}
}
