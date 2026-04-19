package recording

type PixelFormat uint8

type Frame struct {
	Data          []byte
	Width, Height int
	Format        PixelFormat
}

type ScreenStream interface {
	Frames() <-chan Frame
	Err() error
	Stop()
}
