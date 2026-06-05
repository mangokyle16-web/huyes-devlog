/**
 * QS Capture Daemon - continuous capture via callback API
 *
 * Uses registerQsCameraCallback (not getQsData) — the SDK manages frame buffers.
 * The callback copies each frame; we process the copy. freeQsData is never called
 * on camera-delivered buffers (only on file-loaded data).
 *
 * Output protocol (stdout binary), per frame:
 *   [frame_id: uint64 LE][timestamp_us: int64 LE][data_size: uint64 LE]
 *   [n_bands: uint32 LE][width: uint32 LE][height: uint32 LE][dtype: uint32 LE=4]
 *   [band_data: float32 × 5 × H × W]  -- band-first: NDVI, GNDVI, NDRE, OSAVI, LCI
 *
 * Build: make  (on Pi5 with QS SDK, requires LD_PRELOAD=uvc_fix.so at runtime)
 * Run:   LD_PRELOAD=.../uvc_fix.so ./qs_daemon [qsbs_path] [fps]
 */
#include "qs_camera.h"
#include "qs_fileio.h"
#include "qs_agriculture.h"
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <mutex>
#include <condition_variable>
#include <atomic>
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

// ── Frame buffer (callback → main loop) ────────────────────────────────────
static std::mutex              g_mu;
static std::condition_variable g_cv;
static std::vector<uint8_t>    g_frame_buf;
static bool                    g_frame_ready = false;

// Called from SDK camera thread; copy data immediately and signal main loop
static void onFrame(const uint8_t* data, const size_t size, void* /*ctx*/) {
    {
        std::lock_guard<std::mutex> lk(g_mu);
        g_frame_buf.assign(data, data + size);
        g_frame_ready = true;
    }
    g_cv.notify_one();
}

int main(int argc, char* argv[]) {
    const char* qsbs_path  = (argc >= 2) ? argv[1] : "msi.qsbs";
    const int   target_fps = (argc >= 3) ? atoi(argv[2]) : 13;
    if (target_fps <= 0 || target_fps > 120) {
        fprintf(stderr, "[qs_daemon] ERROR: invalid fps %d\n", target_fps);
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
        fprintf(stderr, "[qs_daemon] ERROR: no camera\n");
        return 1;
    }

    // Register callback BEFORE opening camera
    if (registerQsCameraCallback(cameras[0], onFrame, nullptr) != QS_ERR_SUCCESS) {
        fprintf(stderr, "[qs_daemon] ERROR: registerQsCameraCallback failed\n");
        return 1;
    }

    if (openQsCamera(cameras[0], true /*async — required for callback*/) != QS_ERR_SUCCESS) {
        fprintf(stderr, "[qs_daemon] ERROR: openQsCamera failed\n");
        return 1;
    }
    fprintf(stderr, "[qs_daemon] ready @ %d fps\n", target_fps);

    if (!freopen(nullptr, "wb", stdout)) {
        fprintf(stderr, "[qs_daemon] WARNING: binary mode failed\n");
    }

    uint64_t frame_id  = 0;
    int      skip_warm = 3;  // skip first 3 frames (camera stabilize)

    while (g_running) {
        auto t0 = std::chrono::steady_clock::now();

        // Wait for next frame from callback (timeout = 2× frame budget)
        std::vector<uint8_t> frame_copy;
        {
            std::unique_lock<std::mutex> lk(g_mu);
            if (!g_cv.wait_for(lk, std::chrono::milliseconds(frame_ms * 2),
                               [] { return g_frame_ready || !g_running; })) {
                fprintf(stderr, "[qs_daemon] WARN: frame timeout\n");
                continue;
            }
            if (!g_running) break;
            frame_copy.swap(g_frame_buf);
            g_frame_ready = false;
        }

        // Warmup: discard first few frames
        if (skip_warm > 0) { --skip_warm; continue; }

        // Compute vegetation indices
        uint8_t* qabData = nullptr; size_t qabSize = 0;
        if (qsToQab(agCtx, frame_copy.data(), frame_copy.size(),
                    &qabData, &qabSize) != QS_ERR_SUCCESS) {
            fprintf(stderr, "[qs_daemon] WARN: qsToQab failed\n");
            continue;
        }

        double *ndvi=nullptr,*gndvi=nullptr,*ndre=nullptr,*osavi=nullptr,*lci=nullptr;
        uint32_t W=0,H=0, w2=0,h2=0,w3=0,h3=0,w4=0,h4=0,w5=0,h5=0;
        bool ok = true;
        ok &= (qabToNdvi (qabData,qabSize,&ndvi, &W, &H ) == QS_ERR_SUCCESS);
        ok &= (qabToGndvi(qabData,qabSize,&gndvi,&w2,&h2) == QS_ERR_SUCCESS);
        ok &= (qabToNdre (qabData,qabSize,&ndre, &w3,&h3) == QS_ERR_SUCCESS);
        ok &= (qabToOsavi(qabData,qabSize,&osavi,&w4,&h4) == QS_ERR_SUCCESS);
        ok &= (qabToLci  (qabData,qabSize,&lci,  &w5,&h5) == QS_ERR_SUCCESS);

        if (ok && W > 0 && H > 0) {
            const size_t n_px = (size_t)W * H;
            std::vector<float> f32(5 * n_px);
            const double* bands[5] = {ndvi, gndvi, ndre, osavi, lci};
            for (int b = 0; b < 5; ++b)
                for (size_t i = 0; i < n_px; ++i)
                    f32[b * n_px + i] = static_cast<float>(bands[b][i]);

            const uint64_t data_size = 16 + 5 * n_px * 4;
            write_u64(frame_id);
            write_i64(now_us());
            write_u64(data_size);
            write_u32(5); write_u32(W); write_u32(H); write_u32(4);
            fwrite(f32.data(), 4, 5 * n_px, stdout);
            fflush(stdout);
            ++frame_id;
        } else {
            fprintf(stderr, "[qs_daemon] WARN: index computation failed\n");
        }

        // Free SDK-allocated arrays (allocated with new[])
        delete[] ndvi; delete[] gndvi; delete[] ndre;
        delete[] osavi; delete[] lci;
        delete[] qabData;

        // Frame rate control
        auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - t0).count();
        if (elapsed < frame_ms)
            std::this_thread::sleep_for(std::chrono::milliseconds(frame_ms - elapsed));
    }

    closeQsCamera(cameras[0]);
    releaseQsCamera(cameras, camCount);
    deinitQsAgriculture(agCtx);
    freeQsData(qsbsData);
    fprintf(stderr, "[qs_daemon] stopped after %llu frames\n",
            (unsigned long long)frame_id);
    return 0;
}
