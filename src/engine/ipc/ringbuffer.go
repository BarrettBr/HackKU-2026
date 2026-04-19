package ipc

import (
	"encoding/binary"
	"fmt"
	"os"
	"strings"
	"sync"
	"syscall"

	"github.com/BarrettBr/HackKU-2026/receiver"
)

const (
	headerSize     = 64
	slotHeaderSize = 16
	magic          = "MOOVIPC1"
)

type RingBufferConfig struct {
	Path        string
	Width       int
	Height      int
	PixelFormat string
	SlotCount   int
}

type RingBufferSink struct {
	cfg      RingBufferConfig
	file     *os.File
	mapped   []byte
	slotSize int

	mu      sync.Mutex
	counter uint64
}

func NewRingBufferSink(cfg RingBufferConfig) (*RingBufferSink, error) {
	if strings.TrimSpace(cfg.Path) == "" {
		return nil, fmt.Errorf("ipc path is required")
	}
	if cfg.Width <= 0 || cfg.Height <= 0 {
		return nil, fmt.Errorf("invalid frame size")
	}
	if strings.TrimSpace(cfg.PixelFormat) == "" {
		cfg.PixelFormat = "yuv420p"
	}
	if cfg.SlotCount <= 0 {
		cfg.SlotCount = 8
	}

	slotPayloadSize, err := frameSize(cfg.PixelFormat, cfg.Width, cfg.Height)
	if err != nil {
		return nil, err
	}
	total := headerSize + cfg.SlotCount*(slotHeaderSize+slotPayloadSize)

	file, err := os.OpenFile(cfg.Path, os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return nil, err
	}
	if err := file.Truncate(int64(total)); err != nil {
		_ = file.Close()
		return nil, err
	}

	mapped, err := syscall.Mmap(int(file.Fd()), 0, total, syscall.PROT_READ|syscall.PROT_WRITE, syscall.MAP_SHARED)
	if err != nil {
		_ = file.Close()
		return nil, err
	}

	s := &RingBufferSink{
		cfg:      cfg,
		file:     file,
		mapped:   mapped,
		slotSize: slotPayloadSize,
	}
	s.writeHeader()
	return s, nil
}

func (s *RingBufferSink) WriteFrame(frame receiver.DecodedFrame) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if len(frame.Data) == 0 {
		return nil
	}

	slotIndex := int(s.counter % uint64(s.cfg.SlotCount))
	slotOffset := headerSize + slotIndex*(slotHeaderSize+s.slotSize)

	payload := frame.Data
	if len(payload) > s.slotSize {
		payload = payload[:s.slotSize]
	}

	// Copy frame bytes first, then publish size/sequence as the commit marker.
	copy(s.mapped[slotOffset+slotHeaderSize:slotOffset+slotHeaderSize+len(payload)], payload)
	binary.LittleEndian.PutUint32(s.mapped[slotOffset+8:slotOffset+12], uint32(len(payload)))
	binary.LittleEndian.PutUint64(s.mapped[slotOffset:slotOffset+8], s.counter+1)

	s.counter++
	binary.LittleEndian.PutUint64(s.mapped[40:48], uint64(slotIndex))
	binary.LittleEndian.PutUint64(s.mapped[48:56], s.counter)
	return nil
}

func (s *RingBufferSink) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()

	var firstErr error
	if s.mapped != nil {
		if err := syscall.Munmap(s.mapped); err != nil && firstErr == nil {
			firstErr = err
		}
		s.mapped = nil
	}
	if s.file != nil {
		if err := s.file.Close(); err != nil && firstErr == nil {
			firstErr = err
		}
		s.file = nil
	}
	return firstErr
}

func (s *RingBufferSink) writeHeader() {
	h := s.mapped[:headerSize]
	for i := range h {
		h[i] = 0
	}
	copy(h[0:8], []byte(magic))
	binary.LittleEndian.PutUint32(h[8:12], 1)
	binary.LittleEndian.PutUint32(h[12:16], uint32(s.cfg.Width))
	binary.LittleEndian.PutUint32(h[16:20], uint32(s.cfg.Height))
	format := []byte(s.cfg.PixelFormat)
	if len(format) > 16 {
		format = format[:16]
	}
	copy(h[20:36], format)
	binary.LittleEndian.PutUint32(h[36:40], uint32(s.cfg.SlotCount))
	binary.LittleEndian.PutUint64(h[40:48], 0)
	binary.LittleEndian.PutUint64(h[48:56], 0)
	binary.LittleEndian.PutUint32(h[56:60], uint32(s.slotSize))
}

func frameSize(pixelFormat string, width, height int) (int, error) {
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
