/**
 * QS Capture Daemon - continuous capture at configurable fps
 * Output protocol (stdout binary):
 *   Per frame = [frame_id: uint64 LE][timestamp_us: int64 LE][qab_size: uint64 LE][qab_data: bytes]
 * stderr: status messages (does not pollute binary output)
 *
 * Build: make (in this directory, on Pi5 with QS SDK installed)
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

int main(int argc, char* argv[]) {
    const char* qsbs_path = (argc >= 2) ? argv[1] : "msi.qsbs";
    const int   target_fps = (argc >= 3) ? atoi(argv[2]) : 13;
    if (target_fps <= 0 || target_fps > 120) {
        fprintf(stderr, "[qs_daemon] ERROR: invalid fps %d (must be 1-120)\n", target_fps);
        return 1;
    }
    const int   frame_ms   = 1000 / target_fps;

    signal(SIGINT,  onSigint);
    signal(SIGTERM, onSigint);

    // Load calibration
    uint8_t* qsbsData = nullptr; size_t qsbsSize = 0;
    if (loadQsbsFile(qsbs_path, &qsbsData, &qsbsSize) != QS_ERR_SUCCESS) {
        fprintf(stderr, "[qs_daemon] ERROR: cannot load %s\n", qsbs_path);
        return 1;
    }
    fprintf(stderr, "[qs_daemon] calibration: %zu bytes\n", qsbsSize);

    // Init agriculture context (used for qsToQab)
    QsAgricultureContext* agCtx = nullptr;
    if (initQsAgriculture(&agCtx, qsbsData, qsbsSize) != QS_ERR_SUCCESS) {
        fprintf(stderr, "[qs_daemon] ERROR: initQsAgriculture failed\n");
        return 1;
    }

    // Detect camera
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

    // Set stdout to binary mode
    if (!freopen(nullptr, "wb", stdout)) {
        fprintf(stderr, "[qs_daemon] WARNING: could not set binary mode on stdout\n");
    }

    uint64_t frame_id = 0;
    while (g_running) {
        auto t0 = std::chrono::steady_clock::now();

        // Capture raw QS frame
        size_t   qsSize = 0;
        uint8_t* qsData = getQsData(cameras[0], &qsSize);
        if (!qsData) {
            fprintf(stderr, "[qs_daemon] WARN: getQsData null, skipping\n");
            continue;
        }

        // Convert to 5-band QAB
        uint8_t* qabData = nullptr; size_t qabSize = 0;
        if (qsToQab(agCtx, qsData, qsSize, &qabData, &qabSize) != QS_ERR_SUCCESS) {
            fprintf(stderr, "[qs_daemon] WARN: qsToQab failed, skipping\n");
            freeQsData(qsData);
            continue;
        }

        // Write binary frame: header + data
        write_u64(frame_id);
        write_i64(now_us());
        write_u64((uint64_t)qabSize);
        fwrite(qabData, 1, qabSize, stdout);
        fflush(stdout);

        ++frame_id;
        freeQsData(qsData);
        delete[] qabData;  // qsToQab allocates with new[] (matches main.cpp pattern)

        // Frame rate control
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
