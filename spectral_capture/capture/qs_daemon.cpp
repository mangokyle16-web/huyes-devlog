/**
 * QS Capture Daemon - continuous capture at configurable fps
 *
 * Output protocol (stdout binary), per frame:
 *   [frame_id: uint64 LE]
 *   [timestamp_us: int64 LE]
 *   [data_size: uint64 LE]          -- bytes that follow (= 16 + n_bands*W*H*4)
 *   [n_bands: uint32 LE]            -- always 5
 *   [width: uint32 LE]              -- image width (pixels)
 *   [height: uint32 LE]             -- image height (pixels)
 *   [dtype: uint32 LE]              -- 4 = float32
 *   [band_data: float32 × n_bands × H × W]  -- layout: band-first (band0[H×W], band1[H×W], ...)
 *
 * Band wavelengths: 450 / 560 / 650 / 730 / 840 nm
 * stderr: status messages (does not pollute binary output)
 *
 * Build: make (on Pi5 with QS SDK installed)
 * Run:   ./qs_daemon [qsbs_path] [fps]
 *        ./qs_daemon msi.qsbs 13
 */
#include "qs_camera.h"
#include "qs_fileio.h"
#include "qs_agriculture.h"
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include <chrono>
#include <thread>
#include <csignal>

static volatile bool g_running = true;
static void onSigint(int) { g_running = false; }

static int64_t now_us() {
    using namespace std::chrono;
    return duration_cast<microseconds>(
        steady_clock::now().time_since_epoch()).count();
}

static void write_u64(uint64_t v) { fwrite(&v, 8, 1, stdout); }
static void write_i64(int64_t  v) { fwrite(&v, 8, 1, stdout); }
static void write_u32(uint32_t v) { fwrite(&v, 4, 1, stdout); }

int main(int argc, char* argv[]) {
    const char* qsbs_path  = (argc >= 2) ? argv[1] : "msi.qsbs";
    const int   target_fps = (argc >= 3) ? atoi(argv[2]) : 13;
    if (target_fps <= 0 || target_fps > 120) {
        fprintf(stderr, "[qs_daemon] ERROR: invalid fps %d (must be 1-120)\n", target_fps);
        return 1;
    }
    const int frame_ms = 1000 / target_fps;

    signal(SIGINT,  onSigint);
    signal(SIGTERM, onSigint);

    // Load calibration
    uint8_t* qsbsData = nullptr; size_t qsbsSize = 0;
    if (loadQsbsFile(qsbs_path, &qsbsData, &qsbsSize) != QS_ERR_SUCCESS) {
        fprintf(stderr, "[qs_daemon] ERROR: cannot load %s\n", qsbs_path);
        return 1;
    }
    fprintf(stderr, "[qs_daemon] calibration: %zu bytes\n", qsbsSize);

    QsAgricultureContext* agCtx = nullptr;
    if (initQsAgriculture(&agCtx, qsbsData, qsbsSize) != QS_ERR_SUCCESS) {
        fprintf(stderr, "[qs_daemon] ERROR: initQsAgriculture failed\n");
        return 1;
    }

    QsCameraContext** cameras = nullptr; int camCount = 0;
    if (enumQsCamera(&cameras, &camCount) != QS_ERR_SUCCESS || camCount == 0) {
        fprintf(stderr, "[qs_daemon] ERROR: no QS camera detected\n");
        return 1;
    }
    if (openQsCamera(cameras[0], false) != QS_ERR_SUCCESS) {
        fprintf(stderr, "[qs_daemon] ERROR: openQsCamera failed\n");
        return 1;
    }
    fprintf(stderr, "[qs_daemon] ready @ %d fps\n", target_fps);

    if (!freopen(nullptr, "wb", stdout)) {
        fprintf(stderr, "[qs_daemon] WARNING: could not set binary mode on stdout\n");
    }

    uint64_t frame_id = 0;
    while (g_running) {
        auto t0 = std::chrono::steady_clock::now();

        // Capture
        size_t   qsSize = 0;
        uint8_t* qsData = getQsData(cameras[0], &qsSize);
        if (!qsData) {
            fprintf(stderr, "[qs_daemon] WARN: getQsData null, skipping\n");
            continue;
        }

        // QS → QAB (5-band agriculture image)
        uint8_t* qabData = nullptr; size_t qabSize = 0;
        if (qsToQab(agCtx, qsData, qsSize, &qabData, &qabSize) != QS_ERR_SUCCESS) {
            fprintf(stderr, "[qs_daemon] WARN: qsToQab failed, skipping\n");
            freeQsData(qsData);
            continue;
        }

        // QAB → grayscale bands: double[5][height][width] (SDK-decoded, calibrated)
        double*  grayData = nullptr;
        int      width = 0, height = 0;
        if (qabToGray(qabData, qabSize, 1.0, &grayData, &width, &height) != QS_ERR_SUCCESS) {
            fprintf(stderr, "[qs_daemon] WARN: qabToGray failed, skipping\n");
            free(qabData);
            freeQsData(qsData);
            continue;
        }

        // Convert double[5][H][W] → float32 (half the bandwidth, plenty of precision)
        const uint32_t N_BANDS = 5;
        const size_t   n_vals  = (size_t)N_BANDS * width * height;
        std::vector<float> f32(n_vals);
        for (size_t i = 0; i < n_vals; i++)
            f32[i] = static_cast<float>(grayData[i]);

        // Write frame: standard 24-byte header + 16-byte sub-header + float32 data
        const uint64_t data_size = 16 + n_vals * 4;
        write_u64(frame_id);
        write_i64(now_us());
        write_u64(data_size);
        write_u32(N_BANDS);
        write_u32((uint32_t)width);
        write_u32((uint32_t)height);
        write_u32(4);  // dtype = 4 bytes (float32)
        fwrite(f32.data(), 4, n_vals, stdout);
        fflush(stdout);

        ++frame_id;
        free(grayData);
        free(qabData);
        freeQsData(qsData);

        auto elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - t0).count();
        if (elapsed_ms < frame_ms)
            std::this_thread::sleep_for(std::chrono::milliseconds(frame_ms - elapsed_ms));
    }

    closeQsCamera(cameras[0]);
    releaseQsCamera(cameras, camCount);
    deinitQsAgriculture(agCtx);
    freeQsData(qsbsData);
    fprintf(stderr, "[qs_daemon] stopped after %llu frames\n",
            (unsigned long long)frame_id);
    return 0;
}
