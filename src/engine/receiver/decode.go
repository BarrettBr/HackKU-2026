package receiver

import (
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"sync"
	"time"
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

var ErrNoFrameReady = errors.New("decoder frame not ready")

func newDecoder(cfg decoderConfig) (Decoder, error) {
	return newFFmpegDecoder(cfg)
}

type ffmpegDecoder struct {
	cfg       decoderConfig
	frameSize int

	cmd        *exec.Cmd
	stdin      io.WriteCloser
	stdout     io.ReadCloser
	stdoutFile *os.File
	rawBuffer  []byte

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
	}
	if strings.EqualFold(d.cfg.Codec, "h264") || strings.TrimSpace(d.cfg.Codec) == "" {
		// Force FFmpeg's native decoder to avoid libopenh264 decode failures on
		// some distro builds.
		args = append(args, "-c:v", "h264")
	}
	args = append(args,
		"-f", strings.ToLower(d.cfg.Codec),
		"-i", "pipe:0",
		"-vf", fmt.Sprintf("crop=%d:%d:0:0", d.cfg.Width, d.cfg.Height),
		"-f", "rawvideo",
		"-pix_fmt", d.cfg.PixelFormat,
		"pipe:1",
	)

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
	if file, ok := stdout.(*os.File); ok {
		d.stdoutFile = file
	}
	return nil
}

func (d *ffmpegDecoder) Decode(frame EncodedFrame) (DecodedFrame, error) {
	d.mu.Lock()
	defer d.mu.Unlock()

	if _, err := d.stdin.Write(frame.Payload); err != nil {
		return DecodedFrame{}, err
	}

	tmp := make([]byte, 128*1024)
	for len(d.rawBuffer) < d.frameSize {
		if d.stdoutFile != nil {
			_ = d.stdoutFile.SetReadDeadline(time.Now().Add(75 * time.Millisecond))
		}
		n, err := d.stdout.Read(tmp)
		if d.stdoutFile != nil {
			_ = d.stdoutFile.SetReadDeadline(time.Time{})
		}
		if n > 0 {
			d.rawBuffer = append(d.rawBuffer, tmp[:n]...)
		}
		if err != nil {
			var pathErr *os.PathError
			if errors.As(err, &pathErr) && errors.Is(pathErr.Err, os.ErrDeadlineExceeded) {
				return DecodedFrame{}, ErrNoFrameReady
			}
			if errors.Is(err, os.ErrDeadlineExceeded) {
				return DecodedFrame{}, ErrNoFrameReady
			}
			if err == io.EOF {
				return DecodedFrame{}, ErrNoFrameReady
			}
			return DecodedFrame{}, err
		}
		if n == 0 {
			return DecodedFrame{}, ErrNoFrameReady
		}
	}

	buf := make([]byte, d.frameSize)
	copy(buf, d.rawBuffer[:d.frameSize])
	d.rawBuffer = d.rawBuffer[d.frameSize:]

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
