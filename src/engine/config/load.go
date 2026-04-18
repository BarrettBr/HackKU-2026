package config

import (
	"log"

	"github.com/pion/webrtc/v4"
)

type Config struct {
	rtc_conf *webrtc.Configuration
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
	}, nil
}
