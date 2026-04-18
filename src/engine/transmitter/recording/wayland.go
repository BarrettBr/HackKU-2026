package recording

/*
#cgo pkg-config: libpipewire-0.3
#include <pipewire/pipewire.h>
#include <spa/param/video/format-utils.h>
#include <stdint.h>
#include <stdlib.h>

extern void goOnFrame(uintptr_t h, void *data, int size, int w, int h_px, int fmt);
extern void goOnStreamError(uintptr_t h, char *msg);

struct capture_data {
	uintptr_t             handle;
	struct pw_main_loop  *loop;
	struct pw_context    *ctx;
	struct pw_core       *core;
	struct pw_stream     *stream;
	struct spa_hook       listener;
	struct spa_video_info format;
};

static int map_fmt(uint32_t f) {
	switch (f) {
		case SPA_VIDEO_FORMAT_BGRx: return 1;
		case SPA_VIDEO_FORMAT_RGBA: return 2;
		default:                    return 0;
	}
}

static void on_process(void *userdata) {
	struct capture_data *d = userdata;
	struct pw_buffer *b = pw_stream_dequeue_buffer(d->stream);
	if (!b) return;
	struct spa_buffer *buf = b->buffer;
	if (buf->datas[0].data) {
		goOnFrame(d->handle, buf->datas[0].data,
		          (int)buf->datas[0].chunk->size,
		          (int)d->format.info.raw.size.width,
		          (int)d->format.info.raw.size.height,
		          map_fmt(d->format.info.raw.format));
	}
	pw_stream_queue_buffer(d->stream, b);
}

static void on_param_changed(void *userdata, uint32_t id, const struct spa_pod *param) {
	struct capture_data *d = userdata;
	if (!param || id != SPA_PARAM_Format) return;
	if (spa_format_parse(param, &d->format.media_type, &d->format.media_subtype) < 0) return;
	if (d->format.media_type != SPA_MEDIA_TYPE_video ||
	    d->format.media_subtype != SPA_MEDIA_SUBTYPE_raw) return;
	spa_format_video_raw_parse(param, &d->format.info.raw);
}

static void on_state_changed(void *userdata, enum pw_stream_state old,
                             enum pw_stream_state state, const char *error) {
	struct capture_data *d = userdata;
	if (state == PW_STREAM_STATE_ERROR) {
		goOnStreamError(d->handle, (char *)(error ? error : "pipewire error"));
		pw_main_loop_quit(d->loop);
	} else if (state == PW_STREAM_STATE_UNCONNECTED &&
	           (old == PW_STREAM_STATE_STREAMING || old == PW_STREAM_STATE_PAUSED)) {
		goOnStreamError(d->handle, (char *)"stream disconnected");
		pw_main_loop_quit(d->loop);
	}
}

static const struct pw_stream_events events = {
	PW_VERSION_STREAM_EVENTS,
	.state_changed = on_state_changed,
	.param_changed = on_param_changed,
	.process       = on_process,
};

static int do_connect(struct capture_data *d, uint32_t node, int w, int h, int fps) {
	uint8_t buf[1024];
	struct spa_pod_builder b = SPA_POD_BUILDER_INIT(buf, sizeof(buf));
	const struct spa_pod *params[1];
	params[0] = spa_pod_builder_add_object(&b,
		SPA_TYPE_OBJECT_Format, SPA_PARAM_EnumFormat,
		SPA_FORMAT_mediaType,    SPA_POD_Id(SPA_MEDIA_TYPE_video),
		SPA_FORMAT_mediaSubtype, SPA_POD_Id(SPA_MEDIA_SUBTYPE_raw),
		SPA_FORMAT_VIDEO_format, SPA_POD_CHOICE_ENUM_Id(3,
			SPA_VIDEO_FORMAT_BGRx, SPA_VIDEO_FORMAT_BGRx, SPA_VIDEO_FORMAT_RGBA),
		SPA_FORMAT_VIDEO_size, SPA_POD_CHOICE_RANGE_Rectangle(
			&SPA_RECTANGLE((uint32_t)w, (uint32_t)h),
			&SPA_RECTANGLE(1, 1),
			&SPA_RECTANGLE(8192, 8192)),
		SPA_FORMAT_VIDEO_framerate, SPA_POD_CHOICE_RANGE_Fraction(
			&SPA_FRACTION((uint32_t)fps, 1),
			&SPA_FRACTION(0, 1),
			&SPA_FRACTION(1000, 1)));
	return pw_stream_connect(d->stream, PW_DIRECTION_INPUT, node,
		PW_STREAM_FLAG_AUTOCONNECT | PW_STREAM_FLAG_MAP_BUFFERS | PW_STREAM_FLAG_DONT_RECONNECT,
		params, 1);
}

static struct capture_data *new_capture(uintptr_t handle, int fd, uint32_t node,
                                        const char *name, int w, int h, int fps) {
	struct capture_data *d = calloc(1, sizeof(*d));
	if (!d) return NULL;
	d->handle = handle;

	d->loop = pw_main_loop_new(NULL);
	if (!d->loop) goto err;
	d->ctx = pw_context_new(pw_main_loop_get_loop(d->loop), NULL, 0);
	if (!d->ctx) goto err;
	d->core = pw_context_connect_fd(d->ctx, fd, NULL, 0);
	if (!d->core) goto err;

	struct pw_properties *props = pw_properties_new(
		PW_KEY_MEDIA_TYPE, "Video",
		PW_KEY_MEDIA_CATEGORY, "Capture",
		PW_KEY_MEDIA_ROLE, "Screen", NULL);
	d->stream = pw_stream_new(d->core, name, props);
	if (!d->stream) goto err;

	pw_stream_add_listener(d->stream, &d->listener, &events, d);
	if (do_connect(d, node, w, h, fps) < 0) goto err;
	return d;

err:
	if (d->stream) { spa_hook_remove(&d->listener); pw_stream_destroy(d->stream); }
	if (d->core)   pw_core_disconnect(d->core);
	if (d->ctx)    pw_context_destroy(d->ctx);
	if (d->loop)   pw_main_loop_destroy(d->loop);
	free(d);
	return NULL;
}

static void run_loop(struct capture_data *d)  { pw_main_loop_run(d->loop); }
static void stop_loop(struct capture_data *d) { pw_main_loop_quit(d->loop); }

static void free_capture(struct capture_data *d) {
	if (!d) return;
	if (d->stream) { spa_hook_remove(&d->listener); pw_stream_destroy(d->stream); }
	if (d->core)   pw_core_disconnect(d->core);
	if (d->ctx)    pw_context_destroy(d->ctx);
	if (d->loop)   pw_main_loop_destroy(d->loop);
	free(d);
}
*/
import "C"
import (
	"errors"
	"fmt"
	"runtime/cgo"
	"sync"
	"sync/atomic"
	"unsafe"

	"github.com/godbus/dbus/v5"

	"github.com/BarrettBr/HackKU-2026/config"
)

type PixelFormat uint8

const (
	FormatUnknown PixelFormat = 0
	FormatBGRx    PixelFormat = 1
	FormatRGBA    PixelFormat = 2
)

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

type stream struct {
	data        *C.struct_capture_data
	frames      chan Frame
	handle      cgo.Handle
	wg          sync.WaitGroup
	once        sync.Once
	conn        *dbus.Conn
	sessionPath dbus.ObjectPath

	mu  sync.Mutex
	err error
}

var pwInit sync.Once

// NewStream opens an xdg-desktop-portal ScreenCast session and starts a
// PipeWire capture. The user will see a portal dialog to pick a monitor.
// Returns a ScreenStream delivering frames on a buffered channel.
func NewStream(cfg *config.Config) (ScreenStream, error) {
	pwInit.Do(func() { C.pw_init(nil, nil) })

	conn, sessionPath, fd, nodeID, err := openPortal()
	if err != nil {
		return nil, err
	}

	s := &stream{conn: conn, sessionPath: sessionPath}
	s.handle = cgo.NewHandle(s)

	cname := C.CString(cfg.StreamName)
	defer C.free(unsafe.Pointer(cname))

	d := C.new_capture(C.uintptr_t(s.handle), C.int(fd), C.uint32_t(nodeID),
		cname, C.int(cfg.PixelWidth), C.int(cfg.PixelHeight), C.int(cfg.FrameRate))
	if d == nil {
		s.handle.Delete()
		closeSession(conn, sessionPath)
		return nil, errors.New("pipewire: init failed")
	}
	s.data = d

	buf := cfg.FrameRate / 2
	if buf < 4 {
		buf = 4
	}
	s.frames = make(chan Frame, buf)

	s.wg.Add(1)
	go func() {
		defer s.wg.Done()
		defer close(s.frames)
		C.run_loop(s.data)
	}()
	return s, nil
}

func (s *stream) Frames() <-chan Frame { return s.frames }

func (s *stream) Err() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.err
}

func (s *stream) Stop() {
	s.once.Do(func() {
		C.stop_loop(s.data)
		s.wg.Wait()
		C.free_capture(s.data)
		s.handle.Delete()
		closeSession(s.conn, s.sessionPath)
	})
}

//export goOnFrame
func goOnFrame(h C.uintptr_t, data unsafe.Pointer, size, w, height, pf C.int) {
	s := cgo.Handle(h).Value().(*stream)
	b := make([]byte, int(size))
	copy(b, unsafe.Slice((*byte)(data), int(size)))
	select {
	case s.frames <- Frame{Data: b, Width: int(w), Height: int(height), Format: PixelFormat(pf)}:
	default:
	}
}

//export goOnStreamError
func goOnStreamError(h C.uintptr_t, msg *C.char) {
	s := cgo.Handle(h).Value().(*stream)
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.err == nil {
		s.err = fmt.Errorf("pipewire: %s", C.GoString(msg))
	}
}

// ---- xdg-desktop-portal ScreenCast ----

const (
	portalDest = "org.freedesktop.portal.Desktop"
	portalPath = "/org/freedesktop/portal/desktop"
	portalIf   = "org.freedesktop.portal.ScreenCast"

	sourceMonitor = uint32(1)
	cursorEmbed   = uint32(2)
)

var tokenCounter atomic.Uint64

func newToken() string {
	return fmt.Sprintf("pw_tok_%d", tokenCounter.Add(1))
}

// openPortal runs the ScreenCast handshake and returns a PipeWire remote fd
// and the source node ID.
func openPortal() (*dbus.Conn, dbus.ObjectPath, int, uint32, error) {
	conn, err := dbus.SessionBus()
	if err != nil {
		return nil, "", 0, 0, fmt.Errorf("dbus: %w", err)
	}

	signals := make(chan *dbus.Signal, 16)
	conn.Signal(signals)
	defer conn.RemoveSignal(signals)
	matchOpts := []dbus.MatchOption{
		dbus.WithMatchInterface("org.freedesktop.portal.Request"),
		dbus.WithMatchMember("Response"),
	}
	if err := conn.AddMatchSignal(matchOpts...); err != nil {
		return nil, "", 0, 0, fmt.Errorf("add match: %w", err)
	}
	defer conn.RemoveMatchSignal(matchOpts...)

	portal := conn.Object(portalDest, portalPath)

	await := func(path dbus.ObjectPath) (map[string]dbus.Variant, error) {
		for sig := range signals {
			if sig.Path != path || len(sig.Body) < 2 {
				continue
			}
			code, _ := sig.Body[0].(uint32)
			if code != 0 {
				return nil, fmt.Errorf("portal request denied or cancelled (code %d)", code)
			}
			res, _ := sig.Body[1].(map[string]dbus.Variant)
			return res, nil
		}
		return nil, errors.New("dbus signal channel closed")
	}

	// CreateSession
	var reqPath dbus.ObjectPath
	err = portal.Call(portalIf+".CreateSession", 0, map[string]dbus.Variant{
		"handle_token":         dbus.MakeVariant(newToken()),
		"session_handle_token": dbus.MakeVariant(newToken()),
	}).Store(&reqPath)
	if err != nil {
		return nil, "", 0, 0, fmt.Errorf("CreateSession: %w", err)
	}
	res, err := await(reqPath)
	if err != nil {
		return nil, "", 0, 0, err
	}
	sessionHandle, ok := res["session_handle"].Value().(string)
	if !ok {
		return nil, "", 0, 0, errors.New("no session_handle")
	}
	sessionPath := dbus.ObjectPath(sessionHandle)

	// SelectSources
	err = portal.Call(portalIf+".SelectSources", 0, sessionPath, map[string]dbus.Variant{
		"handle_token": dbus.MakeVariant(newToken()),
		"types":        dbus.MakeVariant(sourceMonitor),
		"multiple":     dbus.MakeVariant(false),
		"cursor_mode":  dbus.MakeVariant(cursorEmbed),
	}).Store(&reqPath)
	if err != nil {
		closeSession(conn, sessionPath)
		return nil, "", 0, 0, fmt.Errorf("SelectSources: %w", err)
	}
	if _, err := await(reqPath); err != nil {
		closeSession(conn, sessionPath)
		return nil, "", 0, 0, err
	}

	// Start
	err = portal.Call(portalIf+".Start", 0, sessionPath, "", map[string]dbus.Variant{
		"handle_token": dbus.MakeVariant(newToken()),
	}).Store(&reqPath)
	if err != nil {
		closeSession(conn, sessionPath)
		return nil, "", 0, 0, fmt.Errorf("Start: %w", err)
	}
	res, err = await(reqPath)
	if err != nil {
		closeSession(conn, sessionPath)
		return nil, "", 0, 0, err
	}
	streamsV, ok := res["streams"]
	if !ok {
		closeSession(conn, sessionPath)
		return nil, "", 0, 0, errors.New("no streams in Start response")
	}
	// streams signature: a(ua{sv})
	streams, ok := streamsV.Value().([][]interface{})
	if !ok || len(streams) == 0 {
		closeSession(conn, sessionPath)
		return nil, "", 0, 0, errors.New("streams empty or wrong type")
	}
	nodeID, ok := streams[0][0].(uint32)
	if !ok {
		closeSession(conn, sessionPath)
		return nil, "", 0, 0, errors.New("stream node id wrong type")
	}

	// OpenPipeWireRemote — returns a UnixFD
	var fd dbus.UnixFD
	err = portal.Call(portalIf+".OpenPipeWireRemote", 0,
		sessionPath, map[string]dbus.Variant{}).Store(&fd)
	if err != nil {
		closeSession(conn, sessionPath)
		return nil, "", 0, 0, fmt.Errorf("OpenPipeWireRemote: %w", err)
	}
	return conn, sessionPath, int(fd), nodeID, nil
}

func closeSession(conn *dbus.Conn, path dbus.ObjectPath) {
	if conn == nil || path == "" {
		return
	}
	_ = conn.Object(portalDest, path).Call(
		"org.freedesktop.portal.Session.Close", 0).Err
}
