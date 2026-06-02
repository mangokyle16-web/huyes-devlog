/*
 * uvc_fix.c - LD_PRELOAD shim for QS SDK / CM020D on Linux 6.6+
 *
 * Root cause 1: Linux 6.6+ exposes the second UVC interface as a
 * "Metadata Capture" device. The SDK expects two Video Capture nodes.
 * Without this shim it rejects the second node and reports errors.
 *
 * Root cause 2: The CM020D gadget firmware performs a one-time USB
 * reset on the very first STREAMON after power-on. Run camera_prime
 * BEFORE this app to absorb that reset safely. After priming, STREAMON
 * works normally and this shim does NOT need to intercept it.
 *
 * Fix summary:
 *   - secondary (Metadata Capture) fd:
 *       Fake QUERYCAP as Video Capture so the SDK accepts it.
 *       Fake all streaming ioctls (REQBUFS/QUERYBUF/QBUF/STREAMON/DQBUF).
 *       mmap() on fake-REQBUFS fds returns anonymous memory.
 *       Vendor/extension ioctls are forwarded to the primary device
 *       so the SDK gets consistent version/capability responses.
 *
 *   - primary (Video Capture) fd:
 *       Everything passes through unmodified.
 */

#define _GNU_SOURCE
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdarg.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <linux/videodev2.h>
#include <linux/uvcvideo.h>
#include <linux/usb/video.h>
#include <errno.h>
#include <dlfcn.h>
#include <pthread.h>

/* ── Raw YUYV frame sharing (for app RAW display mode) ─────────────── */
/* When the SDK does DQBUF on primary, we copy the raw YUYV here.       */
/* The app reads this via qs_raw_yuyv_get() to display the real signal. */
#define RAW_YUYV_SIZE (1600 * 1200 * 2)  /* 3840000 bytes */
static uint8_t  raw_yuyv_buf[RAW_YUYV_SIZE];
static int      raw_yuyv_ready = 0;
static pthread_mutex_t raw_mu = PTHREAD_MUTEX_INITIALIZER;

#define API_PUBLIC __attribute__((visibility("default")))

/* Public API for the app to retrieve the latest raw YUYV frame.
 * Returns 1 if a frame was copied to dst (must be RAW_YUYV_SIZE bytes),
 * returns 0 if no frame available yet. */
API_PUBLIC int qs_raw_yuyv_get(uint8_t *dst) {
    pthread_mutex_lock(&raw_mu);
    int ok = raw_yuyv_ready;
    if (ok) memcpy(dst, raw_yuyv_buf, RAW_YUYV_SIZE);
    pthread_mutex_unlock(&raw_mu);
    return ok;
}

/* ── detected QS Camera device paths ───────────────────────────────── */
static char qs_primary[64]   = "";
static char qs_secondary[64] = "";

/* ── fd tracking ────────────────────────────────────────────────────── */
#define MAX_FDS 64
static int sec_fds[MAX_FDS];
static int sec_fd_n = 0;
/* fds that received a fake REQBUFS → mmap returns anon memory */
static int fake_fds[MAX_FDS];
static int fake_fd_n = 0;

/* Track primary REQBUFS count so STREAMON retry can rebuild buffer queue */
static int pri_reqbufs_count = 20;

static pthread_mutex_t mu = PTHREAD_MUTEX_INITIALIZER;

static void fd_set_add(int *arr, int *n, int fd) {
    pthread_mutex_lock(&mu);
    for (int i = 0; i < *n; i++) if (arr[i] == fd) { pthread_mutex_unlock(&mu); return; }
    if (*n < MAX_FDS) arr[(*n)++] = fd;
    pthread_mutex_unlock(&mu);
}
static void fd_set_del(int *arr, int *n, int fd) {
    pthread_mutex_lock(&mu);
    for (int i = 0; i < *n; i++)
        if (arr[i] == fd) { arr[i] = arr[--(*n)]; break; }
    pthread_mutex_unlock(&mu);
}
static int fd_set_has(int *arr, int *n, int fd) {
    pthread_mutex_lock(&mu);
    for (int i = 0; i < *n; i++) if (arr[i] == fd) { pthread_mutex_unlock(&mu); return 1; }
    pthread_mutex_unlock(&mu);
    return 0;
}

/* ── debug logging ──────────────────────────────────────────────────── */
static int dbg = -1; /* -1=uninit, 0=off, 1=on */
static void dbg_init(void) {
    if (dbg == -1) dbg = (getenv("UVC_FIX_DEBUG") != NULL) ? 1 : 0;
}
#define DBG(...) do { dbg_init(); if (dbg) fprintf(stderr, "[uvc_fix] " __VA_ARGS__); } while(0)

/* ── real symbols ───────────────────────────────────────────────────── */
static int   (*r_open)  (const char*, int, ...)      = NULL;
static int   (*r_openat)(int, const char*, int, ...) = NULL;
static int   (*r_ioctl) (int, unsigned long, ...)    = NULL;
static int   (*r_close) (int)                        = NULL;
static void* (*r_mmap)  (void*, size_t, int, int, int, off_t) = NULL;

static void init_syms(void) {
    if (!r_open)   r_open   = dlsym(RTLD_NEXT, "open");
    if (!r_openat) r_openat = dlsym(RTLD_NEXT, "openat");
    if (!r_ioctl)  r_ioctl  = dlsym(RTLD_NEXT, "ioctl");
    if (!r_close)  r_close  = dlsym(RTLD_NEXT, "close");
    if (!r_mmap)   r_mmap   = dlsym(RTLD_NEXT, "mmap");
}

/* ── startup: detect QS Camera nodes ───────────────────────────────── */
__attribute__((constructor))
static void detect_qs_cameras(void) {
    init_syms();
    for (int n = 0; n < 64; n++) {
        char path[32];
        snprintf(path, sizeof(path), "/dev/video%d", n);
        int fd = r_open(path, O_RDWR | O_NONBLOCK, 0);
        if (fd < 0) continue;
        struct v4l2_capability cap;
        if (r_ioctl(fd, VIDIOC_QUERYCAP, &cap) == 0 &&
            (strstr((char*)cap.card, "QS Camera") ||
             strstr((char*)cap.card, "Webcam gadget"))) {
            uint32_t dc = cap.device_caps;
            if ((dc & V4L2_CAP_VIDEO_CAPTURE) && !(dc & V4L2_CAP_META_CAPTURE)
                && qs_primary[0] == '\0') {
                strncpy(qs_primary, path, sizeof(qs_primary)-1);
            } else if ((dc & V4L2_CAP_META_CAPTURE)
                       && qs_secondary[0] == '\0') {
                strncpy(qs_secondary, path, sizeof(qs_secondary)-1);
            }
        }
        r_close(fd);
    }
    fprintf(stderr, "[uvc_fix] primary=%s  secondary=%s\n",
            qs_primary[0]   ? qs_primary   : "(not found)",
            qs_secondary[0] ? qs_secondary : "(not found)");
}

/* ── open: track fds opened to qs_secondary ────────────────────────── */
int open(const char *path, int flags, ...) {
    mode_t mode = 0;
    if (flags & O_CREAT) { va_list ap; va_start(ap,flags); mode=va_arg(ap,mode_t); va_end(ap); }
    init_syms(); dbg_init();
    if (dbg && path && strstr(path, "video")) { fprintf(stderr, "[uvc_fix] open %s\n", path); fflush(stderr); }
    int fd = r_open(path, flags, mode);
    if (fd >= 0 && path && qs_secondary[0] && strcmp(path, qs_secondary) == 0)
        fd_set_add(sec_fds, &sec_fd_n, fd);
    return fd;
}
int openat(int dirfd, const char *path, int flags, ...) {
    mode_t mode = 0;
    if (flags & O_CREAT) { va_list ap; va_start(ap,flags); mode=va_arg(ap,mode_t); va_end(ap); }
    init_syms();
    int fd = r_openat(dirfd, path, flags, mode);
    if (fd >= 0 && path && qs_secondary[0] && strcmp(path, qs_secondary) == 0)
        fd_set_add(sec_fds, &sec_fd_n, fd);
    return fd;
}

/* ── close ──────────────────────────────────────────────────────────── */
int close(int fd) {
    init_syms();
    fd_set_del(sec_fds,  &sec_fd_n,  fd);
    fd_set_del(fake_fds, &fake_fd_n, fd);
    return r_close(fd);
}

/* ── ioctl ──────────────────────────────────────────────────────────── */
int ioctl(int fd, unsigned long req, ...) {
    void *arg;
    va_list ap; va_start(ap, req); arg = va_arg(ap, void*); va_end(ap);
    init_syms();
    dbg_init();
    if (dbg) { fprintf(stderr, "[uvc_fix] ioctl fd=%d req=0x%08lx\n", fd, req); fflush(stderr); }

    /* ── Secondary fd: intercept Video Capture ioctls ─────────────── */
    if (fd_set_has(sec_fds, &sec_fd_n, fd)) {
        DBG("SEC ioctl fd=%d req=0x%lx\n", fd, req);

        if (req == VIDIOC_QUERYCAP) {
            /* Pretend to be a Video Capture device so the SDK accepts it */
            struct v4l2_capability *cap = arg;
            memset(cap, 0, sizeof(*cap));
            strncpy((char*)cap->driver, "uvcvideo", sizeof(cap->driver)-1);
            strncpy((char*)cap->card,   "Webcam gadget: QS Camera", sizeof(cap->card)-1);
            strncpy((char*)cap->bus_info, "usb", sizeof(cap->bus_info)-1);
            cap->version      = 0x060600;
            cap->capabilities = V4L2_CAP_VIDEO_CAPTURE | V4L2_CAP_STREAMING
                              | V4L2_CAP_DEVICE_CAPS;
            cap->device_caps  = V4L2_CAP_VIDEO_CAPTURE | V4L2_CAP_STREAMING;
            errno = 0; return 0;
        }

        if (req == VIDIOC_S_FMT || req == VIDIOC_G_FMT) {
            struct v4l2_format *f = arg;
            if (f->type == V4L2_BUF_TYPE_VIDEO_CAPTURE) {
                struct v4l2_pix_format *p = &f->fmt.pix;
                if (p->width == 0)  p->width  = 1600;
                if (p->height == 0) p->height = 1200;
                if (p->pixelformat == 0) p->pixelformat = V4L2_PIX_FMT_YUYV;
                uint32_t bpl;
                switch (p->pixelformat) {
                    case V4L2_PIX_FMT_YUYV:
                    case V4L2_PIX_FMT_UYVY: bpl = p->width * 2; break;
                    case V4L2_PIX_FMT_GREY: bpl = p->width;     break;
                    default:                bpl = p->width * 2; break;
                }
                p->bytesperline = bpl;
                p->sizeimage    = bpl * p->height;
                p->field        = V4L2_FIELD_NONE;
                p->colorspace   = V4L2_COLORSPACE_SRGB;
                errno = 0; return 0;
            }
        }

        if (req == VIDIOC_REQBUFS) {
            struct v4l2_requestbuffers *rb = arg;
            if (rb->type == V4L2_BUF_TYPE_VIDEO_CAPTURE) {
                if (rb->count > 0) fd_set_add(fake_fds, &fake_fd_n, fd);
                else               fd_set_del(fake_fds, &fake_fd_n, fd);
                errno = 0; return 0;
            }
        }

        if (req == VIDIOC_QUERYBUF) {
            struct v4l2_buffer *b = arg;
            if (b->type == V4L2_BUF_TYPE_VIDEO_CAPTURE) {
                uint32_t bufsz = 3840000; /* 1600×1200×2 */
                b->flags    = V4L2_BUF_FLAG_MAPPED | V4L2_BUF_FLAG_QUEUED;
                b->length   = bufsz;
                b->m.offset = (uint32_t)b->index * bufsz;
                errno = 0; return 0;
            }
        }

        if (req == VIDIOC_QBUF || req == VIDIOC_STREAMON || req == VIDIOC_STREAMOFF
            || req == VIDIOC_DQBUF) {
            errno = 0; return 0;
        }

        /* Vendor/extension ioctls: forward to primary so SDK gets consistent responses */
        if (qs_primary[0]) {
            int pfd = r_open(qs_primary, O_RDWR | O_NONBLOCK, 0);
            if (pfd >= 0) {
                int ret = r_ioctl(pfd, req, arg);
                int saved_errno = errno;
                DBG("SEC vendor fwd req=0x%lx → primary ret=%d errno=%d\n", req, ret, saved_errno);
                r_close(pfd);
                errno = saved_errno;
                return ret;
            } else {
                DBG("SEC vendor fwd req=0x%lx → failed to open primary (errno=%d)\n", req, errno);
            }
        }
        /* Fallback: try real call, ignore errors */
        int ret = r_ioctl(fd, req, arg);
        DBG("SEC fallback req=0x%lx ret=%d errno=%d → forcing 0\n", req, ret, errno);
        if (ret == -1) { errno = 0; return 0; }
        return ret;
    }

    /* ── Primary fd (and all others): pass through unmodified ─────── */
    {
        /* Always log S_FMT and G_FMT on primary so we can see what format SDK requests */
        if (req == VIDIOC_S_FMT || req == VIDIOC_G_FMT) {
            struct v4l2_format *f = arg;
            const char *op = (req == VIDIOC_S_FMT) ? "S_FMT" : "G_FMT";
            int ret = r_ioctl(fd, req, arg);
            int saved_errno = errno;
            if (f->type == V4L2_BUF_TYPE_VIDEO_CAPTURE) {
                struct v4l2_pix_format *p = &f->fmt.pix;
                uint32_t px = p->pixelformat;
                fprintf(stderr, "[uvc_fix] PRI %s fd=%d type=%u fmt=%c%c%c%c %ux%u bpl=%u sz=%u ret=%d\n",
                        op, fd, f->type,
                        (char)(px), (char)(px>>8), (char)(px>>16), (char)(px>>24),
                        p->width, p->height, p->bytesperline, p->sizeimage, ret);
                fflush(stderr);
            }
            errno = saved_errno;
            return ret;
        }

        /* Dump UVCIOC_CTRL_QUERY struct contents and returned data */
        if (req == UVCIOC_CTRL_QUERY) {
            struct uvc_xu_control_query *xq = arg;
            int ret = r_ioctl(fd, req, arg);
            int saved_errno = errno;
            if (ret == 0 && xq->data && xq->size > 0) {
                fprintf(stderr, "[uvc_fix] XU_QUERY fd=%d unit=%u sel=%u query=0x%02x size=%u OK data:",
                        fd, xq->unit, xq->selector, xq->query, xq->size);
                for (int i = 0; i < (int)xq->size && i < 64; i++)
                    fprintf(stderr, " %02x", xq->data[i]);
                fprintf(stderr, "\n");
            } else {
                fprintf(stderr, "[uvc_fix] XU_QUERY fd=%d unit=%u sel=%u query=0x%02x size=%u FAIL errno=%d\n",
                        fd, xq->unit, xq->selector, xq->query, xq->size, saved_errno);
            }
            fflush(stderr);
            errno = saved_errno;
            return ret;
        }

        /* DQBUF on primary: copy raw YUYV to shared buffer for app RAW display */
        if (req == VIDIOC_DQBUF) {
            struct v4l2_buffer *b = arg;
            int ret = r_ioctl(fd, req, arg);
            if (ret == 0 && b->type == V4L2_BUF_TYPE_VIDEO_CAPTURE
                         && b->bytesused >= RAW_YUYV_SIZE) {
                void *ptr = r_mmap(NULL, RAW_YUYV_SIZE, PROT_READ,
                                   MAP_SHARED, fd, (off_t)b->m.offset);
                if (ptr != MAP_FAILED) {
                    pthread_mutex_lock(&raw_mu);
                    memcpy(raw_yuyv_buf, ptr, RAW_YUYV_SIZE);
                    raw_yuyv_ready = 1;
                    pthread_mutex_unlock(&raw_mu);
                    munmap(ptr, RAW_YUYV_SIZE);
                }
            }
            return ret;
        }

        /* Track REQBUFS count on primary so STREAMON retry knows buffer count */
        if (req == VIDIOC_REQBUFS) {
            struct v4l2_requestbuffers *rb = arg;
            int ret = r_ioctl(fd, req, arg);
            if (ret == 0 && rb->type == V4L2_BUF_TYPE_VIDEO_CAPTURE && rb->count > 0) {
                pthread_mutex_lock(&mu);
                pri_reqbufs_count = (int)rb->count;
                pthread_mutex_unlock(&mu);
            }
            return ret;
        }

        /* STREAMON on primary: retry if new camera FW returns EPROTO.
         * New camera FW returns EPROTO on first STREAMON (old FW caused USB reset).
         * Recovery: STREAMOFF → REQBUFS(0) free → REQBUFS(N) → QUERYBUF×N →
         *           QBUF×N → retry STREAMON. */
        if (req == VIDIOC_STREAMON) {
            int ret = r_ioctl(fd, req, arg);
            if (ret == 0) return 0;
            if (errno != EPROTO) {
                if (dbg) DBG("PRI fd=%d STREAMON FAILED errno=%d\n", fd, errno);
                return ret;
            }
            DBG("PRI fd=%d STREAMON EPROTO — reinit and retry\n", fd);

            pthread_mutex_lock(&mu);
            int count = pri_reqbufs_count;
            pthread_mutex_unlock(&mu);

            uint32_t type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
            r_ioctl(fd, VIDIOC_STREAMOFF, &type);

            struct v4l2_requestbuffers rb = {};
            rb.type   = V4L2_BUF_TYPE_VIDEO_CAPTURE;
            rb.memory = V4L2_MEMORY_MMAP;
            rb.count  = 0;
            r_ioctl(fd, VIDIOC_REQBUFS, &rb);

            rb.count = (uint32_t)count;
            if (r_ioctl(fd, VIDIOC_REQBUFS, &rb) < 0) {
                DBG("PRI STREAMON retry: REQBUFS failed errno=%d\n", errno);
                errno = EPROTO; return -1;
            }
            uint32_t actual = rb.count;
            for (uint32_t i = 0; i < actual; i++) {
                struct v4l2_buffer buf = {};
                buf.type   = V4L2_BUF_TYPE_VIDEO_CAPTURE;
                buf.memory = V4L2_MEMORY_MMAP;
                buf.index  = i;
                r_ioctl(fd, VIDIOC_QUERYBUF, &buf);
                r_ioctl(fd, VIDIOC_QBUF, &buf);
            }

            ret = r_ioctl(fd, req, arg);
            if (ret == 0) {
                DBG("PRI STREAMON retry succeeded\n");
            } else {
                DBG("PRI STREAMON retry FAILED errno=%d\n", errno);
            }
            return ret;
        }

        int ret = r_ioctl(fd, req, arg);
        if (ret == -1 && dbg)
            DBG("PRI fd=%d req=0x%lx FAILED errno=%d\n", fd, req, errno);
        return ret;
    }
}

/* ── mmap ───────────────────────────────────────────────────────────── */
void *mmap(void *addr, size_t len, int prot, int flags, int fd, off_t off) {
    init_syms();
    if (fd >= 0 && fd_set_has(fake_fds, &fake_fd_n, fd))
        return r_mmap(NULL, len, prot,
                      (flags & ~MAP_SHARED) | MAP_PRIVATE | MAP_ANONYMOUS,
                      -1, 0);
    return r_mmap(addr, len, prot, flags, fd, off);
}
