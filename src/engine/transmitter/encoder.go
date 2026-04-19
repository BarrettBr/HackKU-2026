package transmitter

import (
	"bufio"
	"bytes"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"sync"

	"github.com/BarrettBr/HackKU-2026/config"
	"github.com/BarrettBr/HackKU-2026/transmitter/recording"
)

// EncodedFrame is the output of a single Encode call. Data is zero or more
// H.264 access units concatenated (each starting with a 0x00000001 start
// code). Zero-length is normal — ffmpeg buffers input and may not emit
// output for every input frame.
type EncodedFrame struct {
    Data [][]byte  // each entry is one access unit
}

type Encoder interface {
	Encode(frame recording.Frame) (EncodedFrame, error)
	Close() error
}

func NewEncoder(cfg *config.Transmitter) (Encoder, error) {
	if cfg == nil {
		return nil, fmt.Errorf("transmitter config is nil")
	}
	return newFFmpegEncoder(cfg)
}

type ffmpegEncoder struct {
	cfg *config.Transmitter

	pixFmt        string
	width, height int
	frameSize     int
	started       bool

	cmd    *exec.Cmd
	stdin  io.WriteCloser
	stdout io.ReadCloser

	// Access units produced by the reader goroutine. Unbounded buffer via
	// a slice guarded by a mutex so we never drop under burst.
	auMu  sync.Mutex
	auBuf [][]byte
	auErr error

	stopOnce sync.Once
	done     chan struct{}
	wg       sync.WaitGroup
}

func newFFmpegEncoder(cfg *config.Transmitter) (*ffmpegEncoder, error) {
	pixFmt := normalizePixelFormat(cfg.PixelFormat)
	if pixFmt == "" {
		pixFmt = "rgba"
	}
	return &ffmpegEncoder{
		cfg:    cfg,
		pixFmt: pixFmt,
		done:   make(chan struct{}),
	}, nil
}

func (e *ffmpegEncoder) Encode(frame recording.Frame) (EncodedFrame, error) {
	if !e.started {
		e.width = frame.Width
		e.height = frame.Height
		size, err := rawFrameSize(e.pixFmt, e.width, e.height)
		if err != nil {
			return EncodedFrame{}, err
		}
		e.frameSize = size
		if err := e.start(); err != nil {
			return EncodedFrame{}, err
		}
		e.started = true
	}

	if frame.Width != e.width || frame.Height != e.height {
		return EncodedFrame{}, fmt.Errorf(
			"capture size changed %dx%d -> %dx%d", e.width, e.height, frame.Width, frame.Height)
	}

	data := frame.Data
	if len(data) < e.frameSize {
		return EncodedFrame{}, fmt.Errorf("frame smaller than expected: %d < %d", len(data), e.frameSize)
	}
	if len(data) > e.frameSize {
		data = data[:e.frameSize]
	}

	// Synchronous write. If ffmpeg stdin backs up we block here — that's the
	// intended back-pressure. No deadline; swallowing writes produced the
	// "stuck one frame behind forever" failure mode in the previous version.
	if _, err := e.stdin.Write(data); err != nil {
		return EncodedFrame{}, err
	}

	// Drain whatever access units are ready right now. Do not wait.
	return EncodedFrame{Data: e.drainAU()}, nil
}

// drainAU atomically pulls all queued access units out of the reader goroutine
// and concatenates them. Returns nil if none are ready. Reports a reader
// error only once all queued AUs have been drained.
func (e *ffmpegEncoder) drainAU() [][]byte {
    e.auMu.Lock()
    defer e.auMu.Unlock()
    if len(e.auBuf) == 0 {
        return nil
    }
    out := e.auBuf
    e.auBuf = nil
    return out
}

func (e *ffmpegEncoder) pushAU(au []byte) {
	cp := make([]byte, len(au))
	copy(cp, au)
	e.auMu.Lock()
	e.auBuf = append(e.auBuf, cp)
	e.auMu.Unlock()
}

func (e *ffmpegEncoder) start() error {
	fps := e.cfg.FrameRate
	if fps < 1 {
		fps = 30
	}

	encoder := pickH264Encoder()
	preset := firstNonEmpty(e.cfg.FfmpegQuality, "ultrafast")

	args := []string{
		"-hide_banner",
		"-loglevel", "warning",

		"-f", "rawvideo",
		"-pixel_format", e.pixFmt,
		"-video_size", fmt.Sprintf("%dx%d", e.width, e.height),
		"-framerate", fmt.Sprintf("%d", fps),
		"-i", "pipe:0",

		"-an",
		"-bsf:v", "dump_extra",
		"-c:v", encoder,
		"-pix_fmt", "yuv420p",
		"-g", "15",
		"-keyint_min", "15",
	}

	switch encoder {
	case "h264_nvenc":
		// NVENC presets are p1 (fastest) .. p7 (slowest). Map ultrafast->p1.
		nvPreset := "p1"
		if preset != "ultrafast" {
			nvPreset = "p4"
		}
		args = append(args,
			"-preset", nvPreset,
			"-tune", "ll",
			"-rc", "cbr",
			"-zerolatency", "1",
			"-bf", "0",
		)
	case "h264_vaapi", "h264_qsv":
		// Keep minimal; these need more setup (device, hwupload) for real use.
		args = append(args, "-preset", preset)
	default: // libx264
		args = append(args,
			"-preset", preset,
			"-tune", "zerolatency",
			"-sc_threshold", "0",
		)
	}

	args = append(args, "-f", "h264", "pipe:1")

	e.cmd = exec.Command("ffmpeg", args...)
	e.cmd.Stderr = os.Stderr

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

	e.wg.Add(1)
	go e.readAccessUnits()
	return nil
}

// readAccessUnits parses the Annex-B byte stream from ffmpeg's stdout,
// groups NALs into access units on AUD (NAL type 9) boundaries, and pushes
// each complete AU to the shared slice.
func (e *ffmpegEncoder) readAccessUnits() {
	defer e.wg.Done()

	br := bufio.NewReaderSize(e.stdout, 1<<16)
	sc := []byte{0x00, 0x00, 0x00, 0x01}

	var pending bytes.Buffer // unparsed stream bytes
	var au bytes.Buffer      // current access unit being assembled
	tmp := make([]byte, 32*1024)

	for {
		n, readErr := br.Read(tmp)
		if n > 0 {
			pending.Write(tmp[:n])
			e.splitNALs(&pending, &au, sc)
		}
		if readErr != nil {
			if au.Len() > 0 {
				e.pushAU(au.Bytes())
			}
			e.auMu.Lock()
			e.auErr = readErr
			e.auMu.Unlock()
			return
		}
	}
}

// splitNALs walks `pending`, extracts every complete NAL (bounded by two
// start codes), and appends it to `au`. When an AUD (type 9) NAL arrives,
// the prior `au` is flushed and a fresh one begins.
func (e *ffmpegEncoder) splitNALs(pending, au *bytes.Buffer, sc []byte) {
    data := pending.Bytes()
    for {
        i := bytes.Index(data, sc)
        if i < 0 {
            keep := len(data)
            if keep > 3 { keep = 3 }
            pending.Reset()
            pending.Write(data[len(data)-keep:])
            return
        }
        j := bytes.Index(data[i+4:], sc)
        if j < 0 {
            pending.Reset()
            pending.Write(data[i:])
            return
        }
        nal := data[i+4 : i+4+j]
        if len(nal) > 0 {
            // Emit each NAL as its own unit with start code
            out := make([]byte, 0, len(sc)+len(nal))
            out = append(out, sc...)
            out = append(out, nal...)
            e.pushAU(out)
        }
        data = data[i+4+j:]
    }
}

func (e *ffmpegEncoder) Close() error {
	e.stopOnce.Do(func() { close(e.done) })
	if e.stdin != nil {
		_ = e.stdin.Close()
	}
	if e.cmd != nil && e.cmd.Process != nil {
		_ = e.cmd.Process.Kill()
		_ = e.cmd.Wait()
	}
	e.wg.Wait()
	return nil
}

// --- encoder selection ---

func pickH264Encoder() string {
	return "libx264"
}

var (
	ffmpegEncodersOnce sync.Once
	ffmpegEncoders     map[string]bool
)

func ffmpegHasEncoder(name string) bool {
	ffmpegEncodersOnce.Do(func() {
		ffmpegEncoders = map[string]bool{}
		out, err := exec.Command("ffmpeg", "-hide_banner", "-encoders").Output()
		if err != nil {
			return
		}
		for _, line := range strings.Split(string(out), "\n") {
			fields := strings.Fields(line)
			if len(fields) >= 2 {
				ffmpegEncoders[fields[1]] = true
			}
		}
	})
	return ffmpegEncoders[name]
}

// --- format helpers ---

func rawFrameSize(pixelFormat string, width, height int) (int, error) {
	switch strings.ToLower(strings.TrimSpace(pixelFormat)) {
	case "yuv420p", "nv12":
		return (width * height * 3) / 2, nil
	case "rgb24":
		return width * height * 3, nil
	case "rgba", "bgra", "bgr0", "rgb0":
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
	case "nv12":
		return "nv12"
	default:
		return strings.ToLower(strings.TrimSpace(value))
	}
}

func firstNonEmpty(vals ...string) string {
	for _, v := range vals {
		if strings.TrimSpace(v) != "" {
			return v
		}
	}
	return ""
}
