/*
 * camera_prime.c  —  One-shot camera initialization tool
 *
 * The CM020D gadget firmware resets itself on the FIRST STREAMON of each
 * new USB device instance (power-on or USB reset = new instance).
 * Each reset causes a kernel oops, D-state child, USB disconnect/reconnect.
 *
 * Key insight: every reconnect puts firmware back in initial state, so
 * looping and doing STREAMON again just creates another reset — infinite loop.
 * We do exactly ONE round: absorb the first reset, wait for reconnect, exit.
 * The SDK then does STREAMON on the reconnected device.
 *
 * Algorithm:
 *   1. Find the primary QS video node.
 *   2. Fork a child that calls STREAMON (child enters D-state after oops).
 *   3. Wait up to 8s for disconnect.
 *      - If no disconnect after 8s: no reset occurred → camera was already
 *        stable (e.g. USB power survived host reboot). Kill the child to
 *        prevent it from leaving the device in a partial streaming state,
 *        then exit 0.
 *      - If disconnect: wait for reconnect, then exit 0 immediately.
 *
 * NOTE: the child does explicit STREAMOFF+REQBUFS(0) cleanup before exiting
 * so that if STREAMON returns normally (no reset), the camera is left in a
 * clean state for the SDK.
 */

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <signal.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <linux/videodev2.h>
#include <errno.h>
#include <stdint.h>

/* Find the primary QS camera video node (Video Capture, not Metadata). */
static int find_qs_primary(char *out, size_t outsz) {
    for (int n = 0; n < 64; n++) {
        char path[32];
        snprintf(path, sizeof(path), "/dev/video%d", n);
        int fd = open(path, O_RDWR | O_NONBLOCK);
        if (fd < 0) continue;
        struct v4l2_capability cap;
        int ok = (ioctl(fd, VIDIOC_QUERYCAP, &cap) == 0 &&
                  (strstr((char*)cap.card, "QS Camera") ||
                   strstr((char*)cap.card, "Webcam gadget")) &&
                  (cap.device_caps & V4L2_CAP_VIDEO_CAPTURE) &&
                  !(cap.device_caps & V4L2_CAP_META_CAPTURE));
        close(fd);
        if (ok) { snprintf(out, outsz, "%s", path); return 0; }
    }
    return -1;
}

/* Child: opens the primary device and calls STREAMON.
 * Mirrors the SDK's init sequence: vendor ioctl → S_FMT → REQBUFS(20) →
 * QUERYBUF×N → QBUF×N → STREAMON.
 * Will be stuck in D-state after a kernel oops. That's OK. */
static void child_streamon(const char *dev) {
    int fd = open(dev, O_RDWR);
    if (fd < 0) { perror("open"); _exit(1); }

    /* Vendor init ioctl — mirrors what SDK does before STREAMON.
     * May tell firmware to skip the next-STREAMON reset. */
    uint8_t vendor_buf[16] = {0};
    ioctl(fd, 0xc0107521, vendor_buf);  /* ignore return value */

    struct v4l2_format fmt = {};
    fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    ioctl(fd, VIDIOC_G_FMT, &fmt);
    ioctl(fd, VIDIOC_S_FMT, &fmt);

    struct v4l2_requestbuffers rb = {};
    rb.type   = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    rb.memory = V4L2_MEMORY_MMAP;
    rb.count  = 20;  /* match SDK */
    if (ioctl(fd, VIDIOC_REQBUFS, &rb) < 0) { perror("REQBUFS"); _exit(1); }

    /* QUERYBUF + mmap + QBUF for all allocated buffers */
    uint32_t cnt = rb.count < 20 ? rb.count : 20;
    for (uint32_t i = 0; i < cnt; i++) {
        struct v4l2_buffer buf = {};
        buf.type   = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        buf.memory = V4L2_MEMORY_MMAP;
        buf.index  = i;
        if (ioctl(fd, VIDIOC_QUERYBUF, &buf) == 0)
            mmap(NULL, buf.length, PROT_READ|PROT_WRITE, MAP_SHARED, fd, buf.m.offset);
        ioctl(fd, VIDIOC_QBUF, &buf);
    }

    /* STREAMON — may trigger firmware reset → kernel oops → D-state.
     * If STREAMON returns normally (no reset occurred), do explicit cleanup
     * so the camera is left in a clean state for the SDK. */
    uint32_t type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    ioctl(fd, VIDIOC_STREAMON, &type);

    /* Reached here → STREAMON returned (no reset). Clean up explicitly. */
    ioctl(fd, VIDIOC_STREAMOFF, &type);
    struct v4l2_requestbuffers rb2 = {};
    rb2.type   = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    rb2.memory = V4L2_MEMORY_MMAP;
    rb2.count  = 0;
    ioctl(fd, VIDIOC_REQBUFS, &rb2);
    close(fd);
    _exit(0);
}

/* Maximum priming rounds. Different camera firmware generations may need
 * multiple rounds: each reconnect creates a new USB device instance that
 * also requires a STREAMON to absorb its own first-reset. We loop until
 * STREAMON is stable (no disconnect) or we hit the limit. */
#define MAX_ROUNDS 5

int main(void) {
    char dev[64];

    printf("[prime] Searching for QS camera...\n");
    fflush(stdout);

    if (find_qs_primary(dev, sizeof(dev)) < 0) {
        fprintf(stderr, "[prime] No QS camera found — skipping prime\n");
        return 0;
    }
    printf("[prime] Found: %s\n", dev);
    fflush(stdout);

    for (int round = 1; round <= MAX_ROUNDS; round++) {
        printf("[prime] Priming %s (round %d/%d)...\n", dev, round, MAX_ROUNDS);
        fflush(stdout);

        pid_t pid = fork();
        if (pid < 0) { perror("fork"); return 1; }
        if (pid == 0) {
            child_streamon(dev);
            _exit(0);
        }

        /* Wait up to 8s for camera to disconnect */
        int disconnected = 0;
        for (int i = 0; i < 8; i++) {
            sleep(1);
            int fd = open(dev, O_RDONLY | O_NONBLOCK);
            if (fd < 0) {
                printf("[prime] Disconnect detected at %ds.\n", i+1);
                fflush(stdout);
                disconnected = 1;
                break;
            }
            close(fd);
            printf("[prime]   still connected (%ds)...\n", i+1);
            fflush(stdout);
        }

        if (!disconnected) {
            /* STREAMON was stable — camera is ready for the SDK. */
            kill(pid, SIGKILL);
            waitpid(pid, NULL, 0);
            printf("[prime] Round %d: stable. Prime complete.\n", round);
            fflush(stdout);
            return 0;
        }

        /* Reset occurred — wait for camera to reconnect, then do next round. */
        printf("[prime] Round %d: reset detected. Waiting for reconnect...\n", round);
        fflush(stdout);
        char newdev[64];
        int reconnected = 0;
        for (int i = 0; i < 30; i++) {
            sleep(1);
            printf("[prime]   waiting reconnect... (%ds)\n", i+1);
            fflush(stdout);
            if (find_qs_primary(newdev, sizeof(newdev)) == 0) {
                printf("[prime] Reconnected as %s.\n", newdev);
                fflush(stdout);
                sleep(1); /* let node settle */
                strncpy(dev, newdev, sizeof(dev));
                reconnected = 1;
                break;
            }
        }

        if (!reconnected) {
            fprintf(stderr, "[prime] Timeout: camera did not reconnect after round %d\n", round);
            return 1;
        }
        /* Continue to next round with updated dev */
    }

    fprintf(stderr, "[prime] Reached max rounds (%d) without stability — giving up\n", MAX_ROUNDS);
    return 1;
}
