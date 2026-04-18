package recording 

/*
#cgo pkg-config: libpipewire-0.3

#include <pipewire/pipewire.h>
#include <spa/param/video/format-utils.h>
#include <spa/debug/types.h>
#include <spa/param/video/type-info.h>
#include <stdlib.h>

// Forward-declare the Go callback so C can call it.
extern void goOnFrame(void *frameData, int size, int width, int height);

// pw_stream_events cannot be constructed in Go (flexible array member
// constraints), so we build it on the C side and expose a single setup
// function that wires everything together.

struct capture_data {
	struct pw_main_loop *loop;
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

// connect_stream wires up a pw_stream to the PipeWire fd and node_id
// that the xdg-desktop-portal handed us. Returns 0 on success.
static int connect_stream(struct capture_data *d, int fd, uint32_t node_id)
{
	uint8_t             buffer[1024];
	struct spa_pod_builder b  = SPA_POD_BUILDER_INIT(buffer, sizeof(buffer));
	const struct spa_pod  *params[1];

	// Advertise the pixel formats we can accept. BGRx is what most
	// Wayland compositors emit; RGBA / RGBx are common fallbacks.
	params[0] = spa_pod_builder_add_object(&b,
		SPA_TYPE_OBJECT_Format, SPA_PARAM_EnumFormat,
		SPA_FORMAT_mediaType,    SPA_POD_Id(SPA_MEDIA_TYPE_video),
		SPA_FORMAT_mediaSubtype, SPA_POD_Id(SPA_MEDIA_SUBTYPE_raw),
		SPA_FORMAT_VIDEO_format, SPA_POD_CHOICE_ENUM_Id(4,
			SPA_VIDEO_FORMAT_BGRx,
			SPA_VIDEO_FORMAT_BGRx,
			SPA_VIDEO_FORMAT_RGBA,
			SPA_VIDEO_FORMAT_RGBx));

	return pw_stream_connect(
		d->stream,
		PW_DIRECTION_INPUT,
		node_id,
		PW_STREAM_FLAG_AUTOCONNECT | PW_STREAM_FLAG_MAP_BUFFERS,
		params, 1);
}

// new_capture allocates and initialises a capture_data. The caller owns it
// and must free it with free_capture().
static struct capture_data *new_capture(int portalFd, uint32_t nodeId)
{
	struct capture_data *d = calloc(1, sizeof(*d));
	if (!d) return NULL;

	d->loop = pw_main_loop_new(NULL);
	if (!d->loop) goto err;

	d->ctx = pw_context_new(pw_main_loop_get_loop(d->loop), NULL, 0);
	if (!d->ctx) goto err;

	// Connect via the restricted fd the portal gave us — this is the key
	// difference from the tutorial's pw_stream_new_simple path.
	d->core = pw_context_connect_fd(d->ctx, portalFd, NULL, 0);
	if (!d->core) goto err;

	struct pw_properties *props = pw_properties_new(
		PW_KEY_MEDIA_TYPE,     "Video",
		PW_KEY_MEDIA_CATEGORY, "Capture",
		PW_KEY_MEDIA_ROLE,     "Screen",
		NULL);

	d->stream = pw_stream_new(d->core, "screen-capture", props);
	if (!d->stream) goto err;

	pw_stream_add_listener(d->stream, NULL, &stream_events, d);

	if (connect_stream(d, portalFd, nodeId) < 0) goto err;

	return d;

err:
	// partial cleanup — in production you'd be more careful here
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
)

// Frame holds a single decoded screen capture frame.
type Frame struct {
	Data          []byte
	Width, Height int
}

// Stream is a running PipeWire screen capture session.
type Stream struct {
	data   *C.struct_capture_data
	frames chan Frame
}

// frames is the global channel that the C on_process callback writes into.
// A registry keyed by pointer would be cleaner if you ever run multiple
// streams concurrently — fine as a single-stream starting point.
var globalFrames chan Frame

//export goOnFrame
func goOnFrame(frameData unsafe.Pointer, size C.int, width C.int, height C.int) {
	if globalFrames == nil {
		return
	}
	// Copy the frame out of the C buffer before we return — PipeWire
	// reclaims the buffer memory as soon as on_process returns.
	b := make([]byte, int(size))
	copy(b, unsafe.Slice((*byte)(frameData), int(size)))
	select {
	case globalFrames <- Frame{Data: b, Width: int(width), Height: int(height)}:
	default:
		// consumer is too slow — drop frame rather than block the PipeWire loop
	}
}

// NewStream starts capturing from the PipeWire node the portal handed us.
// portalFd and nodeID come from the xdg-desktop-portal ScreenCast session.
func NewStream_Wayland(portalFd int, nodeID uint32) (*Stream, error) {
	C.pw_init(nil, nil)

	d := C.new_capture(C.int(portalFd), C.uint32_t(nodeID))
	if d == nil {
		return nil, fmt.Errorf("pipewire: failed to initialise capture")
	}

	ch := make(chan Frame, 4) // small buffer — display loop drains this
	globalFrames = ch

	s := &Stream{data: d, frames: ch}

	// Run the PipeWire main loop on its own goroutine.
	// It blocks until Stop() calls pw_main_loop_quit.
	go func() {
		C.run_loop(d)
	}()

	return s, nil
}

// Frames returns the channel on which captured frames are delivered.
// Read from this in your display loop.
func (s *Stream) Frames_Wayland() <-chan Frame {
	return s.frames
}

// Stop shuts down the capture loop and frees all resources.
func (s *Stream) Stop_Wayland() {
	C.stop_loop(s.data)
	C.free_capture(s.data)
	s.data = nil
	globalFrames = nil
	close(s.frames)
}
