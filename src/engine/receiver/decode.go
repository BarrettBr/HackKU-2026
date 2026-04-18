package receiver

import (
	"fmt"
	"io"
	"os/exec"
	"strings"
	"sync"
)

type EncodedFrame struct {
	Payload []byte
}

type DecodedFrame struct {
	Data   []byte
	Width  int
	Height int
	Format string
}

type decoderConfig struct {
	Codec       string
	Width       int
	Height      int
	PixelFormat string
}

type Decoder interface {
	Decode(frame EncodedFrame) (DecodedFrame, error)
	Close() error
}

func newDecoder(cfg decoderConfig) (Decoder, error) {
	return newFFmpegDecoder(cfg)
}

type ffmpegDecoder struct {
	cfg       decoderConfig
	frameSize int

	cmd    *exec.Cmd
	stdin  io.WriteCloser
	stdout io.ReadCloser

	mu sync.Mutex
}

func newFFmpegDecoder(cfg decoderConfig) (*ffmpegDecoder, error) {
	if cfg.Width <= 0 || cfg.Height <= 0 {
		return nil, fmt.Errorf("ffmpeg decode requires width/height")
	}
	if strings.TrimSpace(cfg.Codec) == "" {
		cfg.Codec = "h264"
	}
	if strings.TrimSpace(cfg.PixelFormat) == "" {
		cfg.PixelFormat = "yuv420p"
	}

	frameSize, err := rawFrameSize(cfg.PixelFormat, cfg.Width, cfg.Height)
	if err != nil {
		return nil, err
	}

	d := &ffmpegDecoder{
		cfg:       cfg,
		frameSize: frameSize,
	}
	if err := d.start(); err != nil {
		return nil, err
	}
	return d, nil
}

func (d *ffmpegDecoder) start() error {
	args := []string{
		"-loglevel", "error",
		"-fflags", "nobuffer",
		"-flags", "low_delay",
		"-f", strings.ToLower(d.cfg.Codec),
		"-i", "pipe:0",
		"-f", "rawvideo",
		"-pix_fmt", d.cfg.PixelFormat,
		"pipe:1",
	}

	d.cmd = exec.Command("ffmpeg", args...)

	stdin, err := d.cmd.StdinPipe()
	if err != nil {
		return err
	}
	stdout, err := d.cmd.StdoutPipe()
	if err != nil {
		return err
	}
	if err := d.cmd.Start(); err != nil {
		return err
	}

	d.stdin = stdin
	d.stdout = stdout
	return nil
}

func (d *ffmpegDecoder) Decode(frame EncodedFrame) (DecodedFrame, error) {
	d.mu.Lock()
	defer d.mu.Unlock()

	if _, err := d.stdin.Write(frame.Payload); err != nil {
		return DecodedFrame{}, err
	}

	buf := make([]byte, d.frameSize)
	if _, err := io.ReadFull(d.stdout, buf); err != nil {
		return DecodedFrame{}, err
	}

	return DecodedFrame{
		Data:   buf,
		Width:  d.cfg.Width,
		Height: d.cfg.Height,
		Format: d.cfg.PixelFormat,
	}, nil
}

func (d *ffmpegDecoder) Close() error {
	d.mu.Lock()
	defer d.mu.Unlock()

	if d.stdin != nil {
		_ = d.stdin.Close()
	}
	if d.cmd != nil && d.cmd.Process != nil {
		_ = d.cmd.Process.Kill()
		_ = d.cmd.Wait()
	}
	return nil
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
