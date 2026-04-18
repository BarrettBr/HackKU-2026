package config

import (
	"log"

	"github.com/pion/webrtc/v4"
)

type Transmitter struct {
	PixelWidth  int
	PixelHeight int
	FrameRate int
	StreamName string
}

type Receiver struct {
}

type Registrar struct {
}

type Config struct {
	OS       string
	Rtc_Conf *webrtc.Configuration
	Transmitter
	Receiver
	Registrar
}

func Load() (*Config, error) {
	appCfg, err := loadSettings()
	if err != nil {
		log.Fatalf("Error building config: %v", err)
	}

	return appCfg, nil
}

func loadSettings() (*Config, error) {
	return &Config{
		"Wayland",
		&webrtc.Configuration{
			ICEServers: []webrtc.ICEServer{
				{
					URLs: []string{"stun:stun.l.google.com:19302"},
				},
			},
		},
		Transmitter{
			PixelWidth:  600,
			PixelHeight: 600,
			FrameRate: 30,
			StreamName: "screen-capture",
		},
		Receiver{},
		Registrar{},
	}, nil
}
