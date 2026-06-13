/**
 * preview_daemon — 持續相機串流，輸出 live preview
 *
 * 功能：
 *   - 開啟相機 async 模式，持續接收 callback
 *   - 每幀：fast raw grayscale → 儲存 /dev/shm/preview.ppm（預覽圖）
 *   - 每幀：儲存原始 .qs 到 /dev/shm/qs_latest.qs（供採集 pipeline 使用）
 *   - 寫入 /dev/shm/preview_status.txt：frame_id, fps, timestamp
 *
 * 與 capture_pipeline.py 協作：
 *   capture_pipeline 可設定 --source shm 來讀 /dev/shm/qs_latest.qs
 *   而非呼叫 capture_one（避免兩個程式搶相機）
 *
 * Build: make preview_daemon
 * Run:   LD_PRELOAD=.../uvc_fix.so ./preview_daemon [qsbs_path] [preview_fps] [exposure_us]
 *        default preview_fps = 13, default exposure_us = 6000 (0 keeps camera default)
 */
#include "fast_gray.h"
#include "qs_camera.h"
#include "qs_fileio.h"
#include "qs_imgproc.h"
#include "qs_agriculture.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <mutex>
#include <condition_variable>
#include <vector>
#include <chrono>
#include <thread>
#include <csignal>
#include <fstream>

static volatile bool g_running = true;
static void onSigint(int) { g_running = false; }

// ── Shared frame buffer ────────────────────────────────────
static std::mutex              g_mu;
static std::condition_variable g_cv;
static std::vector<uint8_t>    g_frame;
static uint64_t                g_frame_id = 0;
static bool                    g_new_frame = false;

static void onCameraFrame(const uint8_t* data, size_t size, void*) {
    std::lock_guard<std::mutex> lk(g_mu);
    g_frame.assign(data, data + size);
    ++g_frame_id;
    g_new_frame = true;
    g_cv.notify_one();
}

static void writeFile(const char* path, const void* data, size_t size) {
    FILE* f = fopen(path, "wb");
    if (f) { fwrite(data, 1, size, f); fclose(f); }
}

static void writeUpscaledGrayPpm(const char* path, const uint8_t* gray,
                                 int grayW, int grayH) {
    constexpr int kPreviewW = 1600;
    constexpr int kPreviewH = 1200;

    static std::vector<uint8_t> rgbBuf;
    rgbBuf.resize(static_cast<size_t>(kPreviewW) * kPreviewH * 3);

    for (int y = 0; y < kPreviewH; ++y) {
        const int srcY = y * grayH / kPreviewH;
        const uint8_t* srcRow = gray + static_cast<size_t>(srcY) * grayW;
        uint8_t* dst = rgbBuf.data() + static_cast<size_t>(y) * kPreviewW * 3;
        for (int x = 0; x < kPreviewW; ++x) {
            const int srcX = x * grayW / kPreviewW;
            const uint8_t g = srcRow[srcX];
            dst[x * 3 + 0] = g;
            dst[x * 3 + 1] = g;
            dst[x * 3 + 2] = g;
        }
    }

    char header[64];
    int hlen = snprintf(header, sizeof(header), "P6\n%d %d\n255\n", kPreviewW, kPreviewH);
    FILE* f = fopen(path, "wb");
    if (f) {
        fwrite(header, 1, hlen, f);
        fwrite(rgbBuf.data(), 1, rgbBuf.size(), f);
        fclose(f);
    }
}

int main(int argc, char* argv[]) {
    const char* qsbs_path   = (argc >= 2) ? argv[1] : "msi.qsbs";
    const int   preview_fps = (argc >= 3) ? atoi(argv[2]) : 13;
    const int   target_exposure_us = (argc >= 4) ? atoi(argv[3]) : 6000;
    const int   preview_ms  = 1000 / (preview_fps > 0 ? preview_fps : 13);

    signal(SIGINT,  onSigint);
    signal(SIGTERM, onSigint);

    // Load calibration
    uint8_t* qsbsData = nullptr; size_t qsbsSize = 0;
    if (loadQsbsFile(qsbs_path, &qsbsData, &qsbsSize) != QS_ERR_SUCCESS) {
        fprintf(stderr, "[preview_daemon] ERROR: cannot load %s\n", qsbs_path);
        return 1;
    }
    fprintf(stderr, "[preview_daemon] calibration: %zu bytes\n", qsbsSize);

    // Keep the SDK imgproc context initialized for the existing camera stack.
    QsImgprocContext* imgCtx = nullptr;
    if (initQsImgproc(&imgCtx, qsbsData, qsbsSize) != QS_ERR_SUCCESS) {
        fprintf(stderr, "[preview_daemon] ERROR: initQsImgproc failed\n");
        return 1;
    }

    // Find and open camera (async + callback)
    QsCameraContext** cameras = nullptr; int camCount = 0;
    if (enumQsCamera(&cameras, &camCount) != QS_ERR_SUCCESS || camCount == 0) {
        fprintf(stderr, "[preview_daemon] ERROR: no camera\n");
        return 1;
    }
    if (registerQsCameraCallback(cameras[0], onCameraFrame, nullptr) != QS_ERR_SUCCESS) {
        fprintf(stderr, "[preview_daemon] ERROR: registerQsCameraCallback failed\n");
        return 1;
    }
    if (openQsCamera(cameras[0], true) != QS_ERR_SUCCESS) {
        fprintf(stderr, "[preview_daemon] ERROR: openQsCamera failed\n");
        return 1;
    }
    if (target_exposure_us > 0) {
        int exp_min = 0;
        int exp_max = 0;
        int exp = target_exposure_us;
        int actual_exp = 0;
        controlQsCamera(cameras[0], QS_CAMERA_GET_EXPOSURE_MIN, &exp_min);
        controlQsCamera(cameras[0], QS_CAMERA_GET_EXPOSURE_MAX, &exp_max);
        QsErrorcodes exp_err = controlQsCamera(cameras[0], QS_CAMERA_SET_EXPOSURE, &exp);
        if (exp_err == QS_ERR_SUCCESS) {
            controlQsCamera(cameras[0], QS_CAMERA_GET_EXPOSURE, &actual_exp);
            fprintf(stderr,
                    "[preview_daemon] exposure set target=%d us actual=%d us range=[%d,%d]\n",
                    target_exposure_us, actual_exp, exp_min, exp_max);
        } else {
            fprintf(stderr,
                    "[preview_daemon] WARNING: QS_CAMERA_SET_EXPOSURE %d us failed err=%d range=[%d,%d]\n",
                    target_exposure_us, exp_err, exp_min, exp_max);
        }
    } else {
        fprintf(stderr, "[preview_daemon] exposure unchanged (camera default)\n");
    }
    fprintf(stderr, "[preview_daemon] ready, preview @ %d fps\n", preview_fps);

    uint64_t last_processed = 0;
    auto t_last = std::chrono::steady_clock::now();
    double fps_display = 0.0;
    int warmup = 3;

    while (g_running) {
        // Wait for a new frame
        std::vector<uint8_t> frame_copy;
        uint64_t fid;
        {
            std::unique_lock<std::mutex> lk(g_mu);
            g_cv.wait_for(lk, std::chrono::milliseconds(preview_ms * 3),
                          [] { return g_new_frame || !g_running; });
            if (!g_running) break;
            if (!g_new_frame) continue;
            frame_copy.swap(g_frame);
            fid = g_frame_id;
            g_new_frame = false;
        }

        // Warmup: skip first frames
        if (warmup > 0) { --warmup; continue; }

        // Rate limit: only process at preview_fps
        auto now = std::chrono::steady_clock::now();
        int elapsed = (int)std::chrono::duration_cast<std::chrono::milliseconds>(now - t_last).count();
        if (elapsed < preview_ms && fid != last_processed + 1) continue;

        // FPS estimate
        double dt = elapsed / 1000.0;
        fps_display = (dt > 0) ? (1.0 / dt) : 0;
        t_last = now;
        last_processed = fid;

        // Save raw .qs for capture pipeline + write frame ID so pipeline knows it's new
        writeFile("/dev/shm/qs_latest.qs",
                  frame_copy.data(), frame_copy.size());
        {
            char id_buf[32];
            snprintf(id_buf, sizeof(id_buf), "%llu\n", (unsigned long long)fid);
            writeFile("/dev/shm/qs_frame_id.txt", id_buf, strlen(id_buf));
        }

        // Convert raw QS to fast grayscale, then upscale to preserve the
        // 1600x1200 preview/detector coordinate system.
        uint8_t* grayData = nullptr;
        int W = 0, H = 0;
        if (fastGrayFromRaw(frame_copy.data(), frame_copy.size(), &grayData, &W, &H) &&
            grayData) {
            writeUpscaledGrayPpm("/dev/shm/preview.ppm", grayData, W, H);
            free(grayData);
        }

        // Write status for display overlay
        {
            char status[256];
            time_t now_t = time(nullptr);
            struct tm* tm_info = localtime(&now_t);
            char tmbuf[32];
            strftime(tmbuf, sizeof(tmbuf), "%H:%M:%S", tm_info);
            snprintf(status, sizeof(status),
                     "{\"frame_id\":%llu,\"fps\":%.1f,\"time\":\"%s\"}",
                     (unsigned long long)fid, fps_display, tmbuf);
            writeFile("/dev/shm/preview_status.json", status, strlen(status));
        }

        fprintf(stderr, "[preview_daemon] frame=%llu fps=%.1f\n",
                (unsigned long long)fid, fps_display);
    }

    closeQsCamera(cameras[0]);
    releaseQsCamera(cameras, camCount);
    deinitQsImgproc(imgCtx);
    freeQsData(qsbsData);
    fprintf(stderr, "[preview_daemon] stopped\n");
    return 0;
}
