package capture

/*
#cgo pkg-config: libpipewire-0.3

#include <pipewire/pipewire.h>
#include <spa/param/video/format-utils.h>
#include <spa/debug/types.h>
#include <spa/param/video/type-info.h>
#include <stdlib.h>
#include <string.h>

// Forward-declare the Go callback so C can call it.
extern void goOnFrame(void *frameData, int size, int width, int height);

struct capture_data {
	struct pw_main_loop  *loop;
	struct pw_context    *ctx;
	struct pw_core       *core;
	struct pw_stream     *stream;
	struct spa_video_info format;
};

static void on_process(void *userdata)
{
	struct capture_data *d = userdata;
	struct pw_buffer    *b;
	struct spa_buffer   *buf;

	b = pw_stream_dequeue_buffer(d->stream);
	if (b == NULL)
		return;

	buf = b->buffer;
	if (buf->datas[0].data != NULL) {
		int size   = (int)buf->datas[0].chunk->size;
		int width  = (int)d->format.info.raw.size.width;
		int height = (int)d->format.info.raw.size.height;
		goOnFrame(buf->datas[0].data, size, width, height);
	}

	pw_stream_queue_buffer(d->stream, b);
}

static void on_param_changed(void *userdata, uint32_t id,
                             const struct spa_pod *param)
{
	struct capture_data *d = userdata;

	if (param == NULL || id != SPA_PARAM_Format)
		return;

	if (spa_format_parse(param,
	                     &d->format.media_type,
	                     &d->format.media_subtype) < 0)
		return;

	if (d->format.media_type    != SPA_MEDIA_TYPE_video ||
	    d->format.media_subtype != SPA_MEDIA_SUBTYPE_raw)
		return;

	spa_format_video_raw_parse(param, &d->format.info.raw);
}

static const struct pw_stream_events stream_events = {
	PW_VERSION_STREAM_EVENTS,
	.param_changed = on_param_changed,
	.process       = on_process,
};

// connect_stream takes explicit width, height, and framerate from config
// rather than accepting whatever PipeWire negotiates.
static int connect_stream(struct capture_data *d, uint32_t node_id,
                          int width, int height, int framerate)
{
	uint8_t                buffer[1024];
	struct spa_pod_builder b      = SPA_POD_BUILDER_INIT(buffer, sizeof(buffer));
	const struct spa_pod  *params[1];

	params[0] = spa_pod_builder_add_object(&b,
		SPA_TYPE_OBJECT_Format, SPA_PARAM_EnumFormat,
		SPA_FORMAT_mediaType,    SPA_POD_Id(SPA_MEDIA_TYPE_video),
		SPA_FORMAT_mediaSubtype, SPA_POD_Id(SPA_MEDIA_SUBTYPE_raw),
		SPA_FORMAT_VIDEO_format, SPA_POD_CHOICE_ENUM_Id(4,
			SPA_VIDEO_FORMAT_BGRx,
			SPA_VIDEO_FORMAT_BGRx,
			SPA_VIDEO_FORMAT_RGBA,
			SPA_VIDEO_FORMAT_RGBx),
		SPA_FORMAT_VIDEO_size, SPA_POD_Rectangle(
			(uint32_t)width, (uint32_t)height),
		SPA_FORMAT_VIDEO_framerate, SPA_POD_Fraction(
			(uint32_t)framerate, 1));

	return pw_stream_connect(
		d->stream,
		PW_DIRECTION_INPUT,
		node_id,
		PW_STREAM_FLAG_AUTOCONNECT | PW_STREAM_FLAG_MAP_BUFFERS,
		params, 1);
}

// new_capture takes stream name, dimensions, and framerate from config.
static struct capture_data *new_capture(int portalFd, uint32_t nodeId,
                                        const char *streamName,
                                        int width, int height, int framerate)
{
	struct capture_data *d = calloc(1, sizeof(*d));
	if (!d) return NULL;

	d->loop = pw_main_loop_new(NULL);
	if (!d->loop) goto err;

	d->ctx = pw_context_new(pw_main_loop_get_loop(d->loop), NULL, 0);
	if (!d->ctx) goto err;

	d->core = pw_context_connect_fd(d->ctx, portalFd, NULL, 0);
	if (!d->core) goto err;

	struct pw_properties *props = pw_properties_new(
		PW_KEY_MEDIA_TYPE,     "Video",
		PW_KEY_MEDIA_CATEGORY, "Capture",
		PW_KEY_MEDIA_ROLE,     "Screen",
		NULL);

	d->stream = pw_stream_new(d->core, streamName, props);
	if (!d->stream) goto err;

	pw_stream_add_listener(d->stream, NULL, &stream_events, d);

	if (connect_stream(d, nodeId, width, height, framerate) < 0) goto err;

	return d;

err:
	free(d);
	return NULL;
}

static void run_loop(struct capture_data *d)
{
	pw_main_loop_run(d->loop);
}

static void stop_loop(struct capture_data *d)
{
	pw_main_loop_quit(d->loop);
}

static void free_capture(struct capture_data *d)
{
	if (!d) return;
	if (d->stream) pw_stream_destroy(d->stream);
	if (d->core)   pw_core_disconnect(d->core);
	if (d->ctx)    pw_context_destroy(d->ctx);
	if (d->loop)   pw_main_loop_destroy(d->loop);
	free(d);
}
*/
import "C"
import (
	"fmt"
	"unsafe"

	"your/module/path/config"
)

// Frame holds a single captured screen frame.
type Frame struct {
	Data []byte
	Width, Height int
}

// Stream is a running PipeWire screen capture session.
type Stream struct {
	data *C.struct_capture_data
	frames chan Frame
}

// globalFrames bridges the C on_process callback to Go.
// Single-stream assumption — see comment on NewStream.
var globalFrames chan Frame

//export goOnFrame
func goOnFrame(frameData unsafe.Pointer, size C.int, width C.int, height C.int) {
	if globalFrames == nil {
		return
	}
	b := make([]byte, int(size))
	copy(b, unsafe.Slice((*byte)(frameData), int(size)))
	select {
	case globalFrames <- Frame{Data: b, Width: int(width), Height: int(height)}:
	default:
		// consumer is too slow — drop frame rather than block the PipeWire loop
	}
}

// NewStream starts a capture session using values from appCfg.
// portalFd and nodeID come from the xdg-desktop-portal ScreenCast session.
// Single concurrent stream assumed — globalFrames is package-level.
func NewStream(portalFd int, nodeID uint32, appCfg *config.Config) (*Stream, error) {
	C.pw_init(nil, nil)

	streamName := C.CString(appCfg.StreamName)
	defer C.free(unsafe.Pointer(streamName))

	d := C.new_capture(
		C.int(portalFd),
		C.uint32_t(nodeID),
		streamName,
		C.int(appCfg.PixelWidth),
		C.int(appCfg.PixelHeight),
		C.int(appCfg.FrameRate),
	)
	if d == nil {
		return nil, fmt.Errorf("pipewire: failed to initialise capture")
	}

	// Buffer sized to half a second of frames at the configured rate.
	// Absorbs GC pauses without growing unboundedly if the consumer stalls.
	bufSize := appCfg.FrameRate / 2
	if bufSize < 4 {
		bufSize = 4
	}
	ch := make(chan Frame, bufSize)
	globalFrames = ch

	s := &Stream{data: d, frames: ch}

	// Run the PipeWire main loop on its own goroutine.
	// Blocks until Stop() calls pw_main_loop_quit.
	go func() {
		C.run_loop(d)
	}()

	return s, nil
}

// Frames returns the channel on which captured frames are delivered.
func (s *Stream) Frames() <-chan Frame {
	return s.frames
}

// Stop shuts down the capture loop and frees all resources.
func (s *Stream) Stop() {
	C.stop_loop(s.data)
	C.free_capture(s.data)
	s.data = nil
	globalFrames = nil
	close(s.frames)
}
