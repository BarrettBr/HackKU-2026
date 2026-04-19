package config

import (
	"os"
	"strconv"
	"strings"

	"github.com/pion/webrtc/v4"
)

type Transmitter struct {
	PixelWidth    int
	PixelHeight   int
	FrameRate     int
	Codec         string
	FfmpegQuality string
	PixelFormat   string
	StreamName    string
}

type Receiver struct {
	Codec       string
	Width       int
	Height      int
	PixelFormat string // Raw decoded output format for shared memory
}

type Config struct {
	OS       string
	Rtc_Conf *webrtc.Configuration
	Transmitter
	Receiver
}

func Load() (*Config, error) {
	return loadSettings() // Seperated out for os detection / codec extension later down the line
}

func loadSettings() (*Config, error) {
	cfg := &Config{
		"linux-wayland",
		&webrtc.Configuration{
			ICEServers: []webrtc.ICEServer{
				{
					URLs: []string{"stun:stun.l.google.com:19302"},
				},
			},
		},
		Transmitter{
			PixelWidth:    0,
			PixelHeight:   0,
			FrameRate:     30,
			FfmpegQuality: "fast",
			StreamName:    "screen-capture",
			PixelFormat:   "RGBA",
			Codec:         "h264",
		},
		Receiver{
			Codec:       "h264",
			Width:       0,
			Height:      0,
			PixelFormat: "rgba",
		},
	}

	// Optional runtime overrides for local/dev tuning without code edits.
	cfg.Transmitter.PixelWidth = envInt("ENGINE_TX_WIDTH", cfg.Transmitter.PixelWidth)
	cfg.Transmitter.PixelHeight = envInt("ENGINE_TX_HEIGHT", cfg.Transmitter.PixelHeight)
	cfg.Transmitter.FrameRate = envInt("ENGINE_TX_FPS", cfg.Transmitter.FrameRate)
	if quality := strings.TrimSpace(os.Getenv("ENGINE_TX_QUALITY")); quality != "" {
		cfg.Transmitter.FfmpegQuality = quality
	}

	return cfg, nil
}

func envInt(key string, fallback int) int {
	raw := strings.TrimSpace(os.Getenv(key))
	if raw == "" {
		return fallback
	}
	v, err := strconv.Atoi(raw)
	if err != nil {
		return fallback
	}
	return v
}
