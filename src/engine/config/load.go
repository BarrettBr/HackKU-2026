package config

import "github.com/pion/webrtc/v4"

type Transmitter struct {
	PixelWidth  int
	PixelHeight int
	FrameRate   int
	Codec string
	FfmpegQuality string
	PixelFormat string
	StreamName  string
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
	return &Config{
		"linux-wayland",
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
			FrameRate:   30,
			FfmpegQuality: "fast",
			StreamName:  "screen-capture",
			PixelFormat: "RGBA",
			Codec: "h264",
		},
		Receiver{
			Codec:       "h264",
			Width:       600,
			Height:      600,
			PixelFormat: "yuv420p",
		},
	}, nil
}
