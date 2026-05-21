/*
 * capture_v4l2.c
 * Direct V4L2 single-frame capture — bypasses SDK enumQsCamera.
 * Saves raw frame as .qs (SDK saveQsFile is just fwrite, same format).
 * Usage: ./capture_v4l2 [/dev/videoN] [output.qs]
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <linux/videodev2.h>

#define N_BUFS 4

static int xioctl(int fd, unsigned long req, void *arg) {
    int r;
    do { r = ioctl(fd, req, arg); } while (r == -1 && errno == EINTR);
    return r;
}

int main(int argc, char **argv) {
    const char *dev = "/dev/video1";
    const char *out = "capture_headless.qs";
    int use_grey = 0;  /* --grey: use GREY 544x384@10fps instead of YUYV 1600x1200 */
    /* Parse: ./capture_v4l2 [--grey] [/dev/videoN] [output.qs] */
    int pos = 0;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--grey") == 0) { use_grey = 1; }
        else if (pos == 0) { dev = argv[i]; pos++; }
        else if (pos == 1) { out = argv[i]; pos++; }
    }

    printf("=== V4L2 Headless Capture ===\n");
    printf("Device : %s\n", dev);
    printf("Output : %s\n\n", out);

    /* SDK probe: open + VIDIOC_QUERYCTRL(V4L2_CID_EXPOSURE_ABSOLUTE) + close
     * This "wakes" the camera firmware before the main streaming sequence. */
    {
        int pfd = open(dev, O_RDWR);
        if (pfd >= 0) {
            struct v4l2_queryctrl qc = {};
            qc.id = 0x009a0902; /* V4L2_CID_EXPOSURE_ABSOLUTE */
            xioctl(pfd, VIDIOC_QUERYCTRL, &qc);
            close(pfd);
            printf("Probe  : QUERYCTRL(EXPOSURE_ABSOLUTE) done\n");
        }
    }

    /* Open device (blocking, no O_NONBLOCK — matches SDK open_device behavior) */
    int fd = open(dev, O_RDWR | O_CLOEXEC);
    if (fd < 0) { perror("open"); return 1; }

    /* Query capabilities */
    struct v4l2_capability cap = {};
    if (xioctl(fd, VIDIOC_QUERYCAP, &cap) < 0) { perror("QUERYCAP"); return 1; }
    printf("Card   : %s\n", cap.card);
    printf("Driver : %s\n", cap.driver);

    struct v4l2_format fmt = {};
    fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if (use_grey) {
        /* GREY 544x384@10fps — low bandwidth (261 bytes/microframe → alt 6) */
        fmt.fmt.pix.width       = 544;
        fmt.fmt.pix.height      = 384;
        fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_GREY;
    } else {
        /* YUYV 1600x1200@5fps — full spectral data (2400 bytes/microframe → alt 14) */
        fmt.fmt.pix.width       = 1600;
        fmt.fmt.pix.height      = 1200;
        fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_YUYV;
    }
    fmt.fmt.pix.field = V4L2_FIELD_NONE;
    if (xioctl(fd, VIDIOC_S_FMT, &fmt) < 0) { perror("S_FMT"); return 1; }

    /* Set frame rate */
    {
        struct v4l2_streamparm parm = {};
        parm.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        parm.parm.capture.timeperframe.numerator   = 1;
        parm.parm.capture.timeperframe.denominator = use_grey ? 10 : 5;
        int r = xioctl(fd, VIDIOC_S_PARM, &parm);
        printf("S_PARM : %s  %u/%u s/frame\n",
               r == 0 ? "OK" : "FAIL",
               parm.parm.capture.timeperframe.numerator,
               parm.parm.capture.timeperframe.denominator);
    }
    printf("Format : %dx%d pixfmt=0x%08x bpl=%u sz=%u\n",
           fmt.fmt.pix.width, fmt.fmt.pix.height,
           fmt.fmt.pix.pixelformat,
           fmt.fmt.pix.bytesperline,
           fmt.fmt.pix.sizeimage);

    /* Request MMAP buffers */
    struct v4l2_requestbuffers rb = {};
    rb.type   = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    rb.memory = V4L2_MEMORY_MMAP;
    rb.count  = N_BUFS;
    if (xioctl(fd, VIDIOC_REQBUFS, &rb) < 0) { perror("REQBUFS"); return 1; }
    printf("Buffers: %u allocated\n", rb.count);

    /* Map buffers */
    void  *buf_start[N_BUFS];
    size_t buf_len[N_BUFS];
    for (unsigned i = 0; i < rb.count; i++) {
        struct v4l2_buffer b = {};
        b.type   = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        b.memory = V4L2_MEMORY_MMAP;
        b.index  = i;
        if (xioctl(fd, VIDIOC_QUERYBUF, &b) < 0) { perror("QUERYBUF"); return 1; }
        buf_len[i]   = b.length;
        buf_start[i] = mmap(NULL, b.length, PROT_READ | PROT_WRITE,
                            MAP_SHARED, fd, b.m.offset);
        if (buf_start[i] == MAP_FAILED) { perror("mmap"); return 1; }
    }

    /* Queue all buffers */
    for (unsigned i = 0; i < rb.count; i++) {
        struct v4l2_buffer b = {};
        b.type   = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        b.memory = V4L2_MEMORY_MMAP;
        b.index  = i;
        if (xioctl(fd, VIDIOC_QBUF, &b) < 0) { perror("QBUF"); return 1; }
    }

    /* Start streaming */
    enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if (xioctl(fd, VIDIOC_STREAMON, &type) < 0) { perror("STREAMON"); return 1; }
    printf("[OK] Stream started\n");

    /* Warm up: skip first few frames */
    int warmup = 5;
    printf("Waiting for %d warm-up frames...\n", warmup); fflush(stdout);

    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);

    int captured = 0;
    int skip = warmup;
    struct v4l2_buffer saved_buf = {};

    while (captured < 1) {
        fd_set fds;
        FD_ZERO(&fds);
        FD_SET(fd, &fds);
        struct timeval tv = { .tv_sec = 5, .tv_usec = 0 };
        int r = select(fd + 1, &fds, NULL, NULL, &tv);
        if (r < 0) { perror("select"); return 1; }
        if (r == 0) { fprintf(stderr, "[FAIL] Timeout\n"); return 1; }

        struct v4l2_buffer b = {};
        b.type   = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        b.memory = V4L2_MEMORY_MMAP;
        if (xioctl(fd, VIDIOC_DQBUF, &b) < 0) { perror("DQBUF"); return 1; }

        if (skip > 0) {
            fprintf(stderr, "  [warmup] skipping frame %d/%d (%u bytes)\n",
                    warmup - skip + 1, warmup, b.bytesused);
            skip--;
            if (xioctl(fd, VIDIOC_QBUF, &b) < 0) { perror("QBUF requeue"); return 1; }
        } else {
            /* This is our capture frame */
            clock_gettime(CLOCK_MONOTONIC, &t1);
            saved_buf = b;
            captured = 1;

            double elapsed = (t1.tv_sec - t0.tv_sec) +
                             (t1.tv_nsec - t0.tv_nsec) * 1e-9;

            printf("\n=== CAPTURE REPORT ===\n");
            printf("Frame bytes : %u\n", b.bytesused);
            printf("Image size  : %dx%d\n",
                   fmt.fmt.pix.width, fmt.fmt.pix.height);
            printf("Pixel format: 0x%08x", fmt.fmt.pix.pixelformat);
            /* Print 4CC */
            char fcc[5];
            memcpy(fcc, &fmt.fmt.pix.pixelformat, 4); fcc[4] = 0;
            printf(" ('%s')\n", fcc);
            printf("Time to settled frame: %.3f s\n", elapsed);

            /* Save raw frame */
            FILE *f = fopen(out, "wb");
            if (!f) { perror("fopen output"); return 1; }
            fwrite(buf_start[b.index], 1, b.bytesused, f);
            fclose(f);

            /* File size check */
            struct stat st;
            stat(out, &st);
            printf("File saved  : %s  (%ld bytes", out, (long)st.st_size);
            if (st.st_size >= 1024*1024)
                printf(" / %.1f MB", st.st_size / (1024.0*1024.0));
            else
                printf(" / %.1f KB", st.st_size / 1024.0);
            printf(")\n======================\n");

            /* Requeue (clean shutdown) */
            xioctl(fd, VIDIOC_QBUF, &saved_buf);
        }
    }

    /* Stop stream */
    xioctl(fd, VIDIOC_STREAMOFF, &type);

    /* Unmap */
    for (unsigned i = 0; i < rb.count; i++)
        munmap(buf_start[i], buf_len[i]);

    close(fd);
    return 0;
}
