package receiver

import (
	"errors"
	"fmt"
	"io"
	"os"
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

// ErrNoFrameReady is returned when a Decode call successfully wrote input to
// ffmpeg but no complete frame is ready to emit yet. This is normal and
// expected — decoders buffer input and emit when they have a decoded picture.
var ErrNoFrameReady = errors.New("decoder frame not ready")

func newDecoder(cfg decoderConfig) (Decoder, error) {
	return newFFmpegDecoder(cfg)
}

type ffmpegDecoder struct {
	cfg       decoderConfig
	frameSize int

	cmd    *exec.Cmd
	stdin  io.WriteCloser
	stdout io.ReadCloser

	// Decoded frames queued by the reader goroutine. Each entry is one full
	// raw frame of size `frameSize` bytes.
	frameMu  sync.Mutex
	frameBuf [][]byte
	readErr  error

	stopOnce sync.Once
	done     chan struct{}
	wg       sync.WaitGroup
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
		done:      make(chan struct{}),
	}
	if err := d.start(); err != nil {
		return nil, err
	}
	return d, nil
}

func (d *ffmpegDecoder) start() error {
	args := []string{
		"-hide_banner",
		"-loglevel", "warning",
	}
	if strings.EqualFold(d.cfg.Codec, "h264") {
		// Pin the native decoder — some distro builds default to libopenh264
		// which fails on streams with certain NAL orderings.
		args = append(args, "-c:v", "h264")
	}
	args = append(args,
		"-f", strings.ToLower(d.cfg.Codec),
		"-i", "pipe:0",
		"-f", "rawvideo",
		"-pix_fmt", d.cfg.PixelFormat,
		"pipe:1",
	)

	d.cmd = exec.Command("ffmpeg", args...)
	d.cmd.Stderr = os.Stderr

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

	d.wg.Add(1)
	go d.readFrames()
	return nil
}

// readFrames pulls raw frames out of ffmpeg stdout. ffmpeg emits exactly
// `frameSize` bytes per decoded frame in rawvideo mode, so framing is just
// "read full chunks of that size."
func (d *ffmpegDecoder) readFrames() {
	defer d.wg.Done()

	for {
		buf := make([]byte, d.frameSize)
		if _, err := io.ReadFull(d.stdout, buf); err != nil {
			d.frameMu.Lock()
			d.readErr = err
			d.frameMu.Unlock()
			return
		}
		d.frameMu.Lock()
		d.frameBuf = append(d.frameBuf, buf)
		d.frameMu.Unlock()
	}
}

func (d *ffmpegDecoder) Decode(frame EncodedFrame) (DecodedFrame, error) {
	// Write the encoded frame to ffmpeg stdin. No locking needed here — the
	// reader goroutine only touches stdout, not stdin, and Decode is expected
	// to be called from a single goroutine at a time.
	if len(frame.Payload) > 0 {
		if _, err := d.stdin.Write(frame.Payload); err != nil {
			return DecodedFrame{}, err
		}
	}

	// Return whatever's been decoded so far, if anything.
	d.frameMu.Lock()
	defer d.frameMu.Unlock()

	if len(d.frameBuf) == 0 {
		if d.readErr != nil && d.readErr != io.EOF {
			return DecodedFrame{}, d.readErr
		}
		return DecodedFrame{}, ErrNoFrameReady
	}

	// Pop the oldest queued frame. If the decoder has fallen behind and has
	// multiple frames queued, the caller can keep calling Decode with an
	// empty payload to drain the queue.
	out := d.frameBuf[0]
	d.frameBuf = d.frameBuf[1:]

	return DecodedFrame{
		Data:   out,
		Width:  d.cfg.Width,
		Height: d.cfg.Height,
		Format: d.cfg.PixelFormat,
	}, nil
}

func (d *ffmpegDecoder) Close() error {
	d.stopOnce.Do(func() { close(d.done) })
	if d.stdin != nil {
		_ = d.stdin.Close()
	}
	if d.cmd != nil && d.cmd.Process != nil {
		_ = d.cmd.Process.Kill()
		_ = d.cmd.Wait()
	}
	d.wg.Wait()
	return nil
}

func rawFrameSize(pixelFormat string, width, height int) (int, error) {
	switch strings.ToLower(strings.TrimSpace(pixelFormat)) {
	case "yuv420p", "nv12":
		return (width * height * 3) / 2, nil
	case "rgb24":
		return width * height * 3, nil
	case "rgba", "bgra":
		return width * height * 4, nil
	default:
		return 0, fmt.Errorf("unsupported pixel format: %s", pixelFormat)
	}
}
