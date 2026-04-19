package transmitter

import (
	"errors"
	"fmt"
	"io"
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

	encoderName := pickH264Encoder()
	fps := maxInt(e.cfg.FrameRate, 1)

	args := []string{
		"-hide_banner",
		"-loglevel", "error",
		"-f", "rawvideo",
		"-pixel_format", e.cfg.PixelFormat,
		"-video_size", fmt.Sprintf("%dx%d", e.inWidth, e.inHeight),
		"-framerate", fmt.Sprintf("%d", fps),
		"-i", "pipe:0",
		"-an",
		"-c:v", encoderName,
		"-preset", e.cfg.FfmpegQuality,
		"-tune", "zerolatency",
		"-g", fmt.Sprintf("%d", fps),
		"-keyint_min", fmt.Sprintf("%d", fps),
		"-sc_threshold", "0",
		"-force_key_frames", "expr:gte(t,n_forced*1)",
	}
	if encoderName == "libx264" {
		// Ensure clear frame boundaries (AUD) and parameter-set repeats at keyframes.
		args = append(args, "-x264-params", fmt.Sprintf("aud=1:repeat-headers=1:keyint=%d:min-keyint=%d:scenecut=0", fps, fps))
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
	// Normalize AU boundaries for downstream depacketize/decode stability.
	args = append(args, "-bsf:v", "h264_metadata=aud=insert")
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

	_, err := e.stdin.Write(payload)
	if err != nil {
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
			// Drop one oldest complete AU instead of dropping random NAL units.
			select {
			case <-e.accessUnits:
			default:
			}
			select {
			case e.accessUnits <- out:
			default:
			}
		}
	}

	flush := func(pending *[]byte) {
		if len(*pending) == 0 {
			return
		}
		writeAU(*pending)
		*pending = (*pending)[:0]
	}

	var pending []byte
	pendingHasVCL := false
	appendNAL := func(nal []byte) {
		pending = append(pending, 0x00, 0x00, 0x00, 0x01)
		pending = append(pending, nal...)
	}

	for {
		nal, err := reader.NextNAL()
		if err != nil {
			flush(&pending)
			if err == io.EOF {
				err = nil
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

		nalType := nal.Data[0] & 0x1F
		isVCL := nalType >= 1 && nalType <= 5
		isDelimiterLike := nalType == 6 || nalType == 7 || nalType == 8 || nalType == 9
		if isDelimiterLike && pendingHasVCL {
			flush(&pending)
			pendingHasVCL = false
		}

		if isVCL {
			firstMB, ok := parseFirstMBSliceFromNAL(nal.Data)
			if pendingHasVCL && ((ok && firstMB == 0) || !ok) {
				flush(&pending)
				pendingHasVCL = false
			}
			pendingHasVCL = true
		}

		appendNAL(nal.Data)
	}
}

func parseFirstMBSliceFromNAL(nal []byte) (int, bool) {
	if len(nal) < 2 {
		return 0, false
	}

	// Remove NAL header and emulation-prevention bytes.
	rbsp := make([]byte, 0, len(nal)-1)
	for i := 1; i < len(nal); i++ {
		if i+2 < len(nal) && nal[i] == 0x00 && nal[i+1] == 0x00 && nal[i+2] == 0x03 {
			rbsp = append(rbsp, 0x00, 0x00)
			i += 2
			continue
		}
		rbsp = append(rbsp, nal[i])
	}

	return readUE(rbsp)
}

func readUE(rbsp []byte) (int, bool) {
	bitPos := 0
	readBit := func() (int, bool) {
		if bitPos >= len(rbsp)*8 {
			return 0, false
		}
		byteIndex := bitPos / 8
		bitIndex := 7 - (bitPos % 8)
		v := int((rbsp[byteIndex] >> bitIndex) & 0x01)
		bitPos++
		return v, true
	}

	zeros := 0
	for {
		bit, ok := readBit()
		if !ok {
			return 0, false
		}
		if bit == 1 {
			break
		}
		zeros++
		if zeros > 31 {
			return 0, false
		}
	}

	codeNum := 1
	for i := 0; i < zeros; i++ {
		bit, ok := readBit()
		if !ok {
			return 0, false
		}
		codeNum = (codeNum << 1) | bit
	}
	return codeNum - 1, true
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
