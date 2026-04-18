package config

import (
	"log"
	"github.com/pion/webrtc/v4"
)

type Transmitter struct {
	pixel_height int
	pixel_width int
}

type Receiver struct {
}

type Registrar struct {
}

type Config struct {
	rtc_conf *webrtc.Configuration
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
		&webrtc.Configuration{
			ICEServers: []webrtc.ICEServer{
				{
					URLs: []string{"stun:stun.l.google.com:19302"},
				},
			},
		},
		Transmitter{
			pixel_height: 600,
			pixel_width: 600,
		},
		Receiver{},
		Registrar{},
	}, nil
}
