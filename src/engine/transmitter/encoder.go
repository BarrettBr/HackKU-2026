package transmitter

import (
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"sync"
	"time"

	"github.com/BarrettBr/HackKU-2026/config"
	"github.com/BarrettBr/HackKU-2026/transmitter/recording"
	"github.com/pion/webrtc/v4/pkg/media/h264reader"
)

type EncodedFrame struct {
	Data []byte
}

type Encoder interface {
	Encode(frame recording.Frame) (EncodedFrame, error)
	Close() error
}

func NewEncoder(appCfg *config.Transmitter) (Encoder, error) {
	if appCfg == nil {
		return nil, fmt.Errorf("transmitter config is nil")
	}

	enc, err := newFFmpegEncoder(appCfg)
	return enc, err
}

type ffmpegEncoder struct {
	frameSize int
	inWidth   int
	inHeight  int
	started   bool

	cfg    *config.Transmitter
	cmd    *exec.Cmd
	stdin  io.WriteCloser
	stdinF *os.File
	stdout io.ReadCloser

	accessUnits chan []byte
	readErrCh   chan error

	mu sync.Mutex
}

func newFFmpegEncoder(cfg *config.Transmitter) (*ffmpegEncoder, error) {
	if strings.TrimSpace(cfg.Codec) == "" {
		cfg.Codec = "h264"
	}
	if cfg.PixelFormat == "" {
		cfg.PixelFormat = "rgba"
	}
	cfg.PixelFormat = normalizePixelFormat(cfg.PixelFormat)
	preset := strings.TrimSpace(cfg.FfmpegQuality)
	if preset == "" {
		preset = "ultrafast"
	}

	e := &ffmpegEncoder{
		cfg:         cfg,
		accessUnits: make(chan []byte, 8),
		readErrCh:   make(chan error, 1),
	}
	e.cfg.FfmpegQuality = preset

	return e, nil
}

func (e *ffmpegEncoder) start() error {
	if e.inWidth <= 0 || e.inHeight <= 0 {
		return fmt.Errorf("ffmpeg encode requires positive input dimensions")
	}

	args := []string{
		"-hide_banner",
		"-loglevel", "error",
		"-f", "rawvideo",
		"-pixel_format", e.cfg.PixelFormat,
		"-video_size", fmt.Sprintf("%dx%d", e.inWidth, e.inHeight),
		"-framerate", fmt.Sprintf("%d", maxInt(e.cfg.FrameRate, 1)),
		"-i", "pipe:0",
		"-an",
		"-c:v", pickH264Encoder(),
		"-preset", e.cfg.FfmpegQuality,
		"-tune", "zerolatency",
		"-g", fmt.Sprintf("%d", maxInt(e.cfg.FrameRate, 1)),
		"-keyint_min", fmt.Sprintf("%d", maxInt(e.cfg.FrameRate, 1)),
		"-sc_threshold", "0",
	}
	if e.cfg.PixelWidth > 0 && e.cfg.PixelHeight > 0 {
		args = append(args,
			"-vf", fmt.Sprintf(
				"scale=%d:%d:force_original_aspect_ratio=decrease:flags=bicubic,pad=%d:%d:(ow-iw)/2:(oh-ih)/2",
				e.cfg.PixelWidth,
				e.cfg.PixelHeight,
				e.cfg.PixelWidth,
				e.cfg.PixelHeight,
			),
		)
	}
	args = append(args, "-pix_fmt", "yuv420p", "-f", "h264", "pipe:1")

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
	if file, ok := stdin.(*os.File); ok {
		e.stdinF = file
	}
	e.stdout = stdout
	e.started = true

	go e.readAccessUnits()
	return nil
}

func (e *ffmpegEncoder) Encode(frame recording.Frame) (EncodedFrame, error) {
	e.mu.Lock()
	if !e.started {
		e.inWidth = frame.Width
		e.inHeight = frame.Height

		frameSize, err := rawFrameSize(e.cfg.PixelFormat, e.inWidth, e.inHeight)
		if err != nil {
			e.mu.Unlock()
			return EncodedFrame{}, err
		}
		e.frameSize = frameSize

		if err := e.start(); err != nil {
			e.mu.Unlock()
			return EncodedFrame{}, err
		}
	}
	if frame.Width != e.inWidth || frame.Height != e.inHeight {
		e.mu.Unlock()
		return EncodedFrame{}, fmt.Errorf("capture size changed from %dx%d to %dx%d", e.inWidth, e.inHeight, frame.Width, frame.Height)
	}
	if len(frame.Data) < e.frameSize {
		e.mu.Unlock()
		return EncodedFrame{}, errors.New("capture frame smaller than configured raw frame size")
	}
	payload := frame.Data
	if len(payload) > e.frameSize {
		payload = payload[:e.frameSize]
	}

	if e.stdinF != nil {
		_ = e.stdinF.SetWriteDeadline(time.Now().Add(40 * time.Millisecond))
	}
	_, err := e.stdin.Write(payload)
	if e.stdinF != nil {
		_ = e.stdinF.SetWriteDeadline(time.Time{})
	}
	if err != nil {
		var pathErr *os.PathError
		if errors.As(err, &pathErr) && errors.Is(pathErr.Err, os.ErrDeadlineExceeded) {
			e.mu.Unlock()
			return EncodedFrame{}, nil
		}
		if errors.Is(err, os.ErrDeadlineExceeded) {
			e.mu.Unlock()
			return EncodedFrame{}, nil
		}
		e.mu.Unlock()
		return EncodedFrame{}, err
	}
	e.mu.Unlock()

	select {
	case au := <-e.accessUnits:
		return EncodedFrame{Data: au}, nil
	case err := <-e.readErrCh:
		if err == nil {
			err = io.EOF
		}
		return EncodedFrame{}, err
	case <-time.After(50 * time.Millisecond):
		// Encoder may need more input before producing the next access unit.
		// Keep capture loop moving instead of stalling.
		return EncodedFrame{}, nil
	}
}

func (e *ffmpegEncoder) Close() error {
	e.mu.Lock()
	defer e.mu.Unlock()

	if e.stdin != nil {
		_ = e.stdin.Close()
		e.stdin = nil
	}
	if e.stdout != nil {
		_ = e.stdout.Close()
		e.stdout = nil
	}
	if e.cmd != nil && e.cmd.Process != nil {
		_ = e.cmd.Process.Kill()
		_ = e.cmd.Wait()
	}
	return nil
}

func (e *ffmpegEncoder) readAccessUnits() {
	reader, err := h264reader.NewReader(e.stdout)
	if err != nil {
		select {
		case e.readErrCh <- err:
		default:
		}
		return
	}

	writeAU := func(au []byte) {
		if len(au) == 0 {
			return
		}
		out := make([]byte, len(au))
		copy(out, au)
		select {
		case e.accessUnits <- out:
		default:
		}
	}
	for {
		nal, err := reader.NextNAL()
		if err != nil {
			if err == io.EOF {
			}
			select {
			case e.readErrCh <- err:
			default:
			}
			return
		}
		if nal == nil || len(nal.Data) == 0 {
			continue
		}
		out := make([]byte, 4+len(nal.Data))
		copy(out[:4], []byte{0x00, 0x00, 0x00, 0x01})
		copy(out[4:], nal.Data)
		writeAU(out)
	}
}

func rawFrameSize(pixelFormat string, width, height int) (int, error) {
	switch strings.ToLower(strings.TrimSpace(pixelFormat)) {
	case "yuv420p":
		return (width * height * 3) / 2, nil
	case "rgb24":
		return width * height * 3, nil
	case "rgba":
		return width * height * 4, nil
	case "bgr0":
		return width * height * 4, nil
	default:
		return 0, fmt.Errorf("unsupported pixel format: %s", pixelFormat)
	}
}

func normalizePixelFormat(value string) string {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case "rgba":
		return "rgba"
	case "bgrx", "bgr0":
		return "bgr0"
	case "rgb24":
		return "rgb24"
	case "yuv420p":
		return "yuv420p"
	default:
		return strings.ToLower(strings.TrimSpace(value))
	}
}

func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}
