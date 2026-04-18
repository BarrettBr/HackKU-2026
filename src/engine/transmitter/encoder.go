package transmitter

import (
	"fmt"
	"io"
	"os/exec"
	"strings"
	"sync"

	"github.com/BarrettBr/HackKU-2026/config"
	"github.com/BarrettBr/HackKU-2026/transmitter/recording"
)

type EncodedFrame struct {
	Data []byte
	Width int
	Height int
	Format string
}

type Encoder interface {
	Encode(frame recording.Frame) (EncodedFrame, error)
	Close() error
}

func NewEncoder(appCfg *config.Transmitter) (*Encoder, error) {
	if appCfg == nil {
		return nil, fmt.Errorf("receiver config is nil")
	}

	enc, error := newFFmpegEncoder(appCfg)
	return enc, error
}

type ffmpegEncoder struct {
	frameSize int

	cfg    *config.Transmitter
	cmd    *exec.Cmd
	stdin  io.WriteCloser
	stdout io.ReadCloser

	mu sync.Mutex
}

func newFFmpegEncoder(cfg *config.Transmitter) (*ffmpegEncoder, error) {
	if cfg.PixelWidth <= 0 || cfg.PixelHeight <= 0 {
		return nil, fmt.Errorf("ffmpeg decode requires width/height")
	}
	if strings.TrimSpace(cfg.Codec) == "" {
		cfg.Codec = "h264"
	}
	// Default to what is currently working 
	if(cfg.PixelFormat == ""){
		cfg.PixelFormat = "RGBA"
	}
	frameSize, err := rawFrameSize(cfg.PixelFormat, cfg.PixelWidth, cfg.PixelHeight)
	if err != nil {
		return nil, err
	}
	e := &ffmpegEncoder{
		cfg: cfg,
		frameSize: frameSize,
	}

	if err := e.start(); err != nil {
		return nil, err
	}
	return e, nil
}

func (e *ffmpegEncoder) start() error {
	args := []string{
		"-loglevel", "error",
		"-fflags", "nobuffer",
		"-flags", "low_delay",
		"-c:v", "libx264",   // force h.264 encoding for now
		"-preset", e.cfg.FfmpegQuality,  // Knob we can tune based on preset
		// See https://trac.ffmpeg.org/wiki/Encode/H.264
		"-i", "pipe:0",    // The input area
		"-f", "rawvideo",
		"-pix_fmt", e.cfg.PixelFormat,  // currently this will stay as RGBA
		"pipe:1",
	}

	e.cmd = exec.Command("ffmpeg", args...)

	stdin, err := e.cmd.StdinPipe()
	if err != nil {
		return err
	}
	stdout, err := e.cmd.StdoutPipe()
	if err != nil {
		return err
	}
	if err := e.cmd.Start(); err != nil {
		return err
	}

	e.stdin = stdin
	e.stdout = stdout
	return nil
}

func (e *ffmpegEncoder) Decode(frame recording.Frame) (EncodedFrame, error) {
	e.mu.Lock()
	defer e.mu.Unlock()

	if _, err := e.stdin.Write(frame.Data); err != nil {
		fmt.Printf("Error writing frame data")
		return EncodedFrame{}, err
	}

	buf := make([]byte, e.frameSize)
	if _, err := io.ReadFull(e.stdout, buf); err != nil {
		return EncodedFrame{}, err
	}

	return EncodedFrame{
		Data:   buf,
		Width:  e.cfg.PixelWidth,
		Height: e.cfg.PixelHeight,
		Format: e.cfg.PixelFormat,
	}, nil
}

func rawFrameSize(pixelFormat string, width, height int) (int, error) {
	switch strings.ToLower(strings.TrimSpace(pixelFormat)) {
	case "yuv420p":
		return (width * height * 3) / 2, nil
	case "rgb24":
		return width * height * 3, nil
	case "rgba":
		return width * height * 4, nil
	default:
		return 0, fmt.Errorf("unsupported pixel format: %s", pixelFormat)
	}
}

