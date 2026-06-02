/**
 * capture_one.cpp
 * Headless single-frame capture tool for QS multispectral camera.
 *
 * Usage:
 *   capture_one [qsbs_path] [output.qs] [exposure_us]
 *
 *   exposure_us : desired exposure in microseconds (e.g. 5000, 10000)
 *                 0 or omitted = use camera default (auto-exposure)
 *
 * Capture flow:
 *   Phase 0 – stream-start warmup  : skip PHASE0_FRAMES to confirm streaming
 *   (set exposure here if requested)
 *   Phase 1 – post-exposure settle : skip PHASE1_FRAMES for sensor to adapt
 *   Phase 2 – capture              : save next frame as .qs
 */

#include <iostream>
#include <vector>
#include <string>
#include <mutex>
#include <condition_variable>
#include <atomic>
#include <chrono>
#include <cstring>
#include <cstdlib>
#include <fcntl.h>
#include <unistd.h>
#include <signal.h>
#include <sys/stat.h>

extern "C" {
#include "qs_camera.h"
#include "qs_fileio.h"
#include "qs_errorcodes.h"
}

// ── Capture phase ─────────────────────────────────────────────────────────────
enum Phase { PHASE0_WARMUP, PHASE1_SETTLE, PHASE2_CAPTURE, PHASE_DONE };

static constexpr int PHASE0_FRAMES = 3;  // frames to skip before setting exposure
static constexpr int PHASE1_FRAMES = 6;  // frames to skip after exposure change

// ── Globals ───────────────────────────────────────────────────────────────────
static QsCameraContext**  g_cameras   = nullptr;
static int                g_camCount  = 0;
static QsCameraContext*   g_cam       = nullptr;
static int                g_targetExp = 0;       // 0 = don't change

static std::mutex              g_mutex;
static std::condition_variable g_cv;
static std::vector<uint8_t>    g_frame;
static std::atomic<int>        g_frameCount{0};
static std::atomic<Phase>      g_phase{PHASE0_WARMUP};

// ── Frame callback ────────────────────────────────────────────────────────────
void onFrame(const uint8_t* data, const size_t size, void* /*ctx*/) {
    int n = ++g_frameCount;
    Phase ph = g_phase.load();

    if (ph == PHASE0_WARMUP) {
        std::cerr << "  [phase0] frame " << n << "/" << PHASE0_FRAMES << "\n";
        if (n >= PHASE0_FRAMES) {
            // Set exposure (if requested) then transition to settle phase
            if (g_targetExp > 0) {
                int exp = g_targetExp;
                QsErrorcodes e = controlQsCamera(g_cam, QS_CAMERA_SET_EXPOSURE, &exp);
                if (e == QS_ERR_SUCCESS)
                    std::cerr << "  [exposure] set to " << exp << " us\n";
                else
                    std::cerr << "  [exposure] SET_EXPOSURE failed (err=" << e << "), continuing\n";
            } else {
                std::cerr << "  [exposure] using camera default\n";
            }
            g_frameCount.store(0);
            g_phase.store(PHASE1_SETTLE);
        }
        return;
    }

    if (ph == PHASE1_SETTLE) {
        std::cerr << "  [phase1] settling frame " << n << "/" << PHASE1_FRAMES << "\n";
        if (n >= PHASE1_FRAMES) {
            g_frameCount.store(0);
            g_phase.store(PHASE2_CAPTURE);
        }
        return;
    }

    if (ph == PHASE2_CAPTURE) {
        {
            std::lock_guard<std::mutex> lk(g_mutex);
            g_frame.assign(data, data + size);
            g_phase.store(PHASE_DONE);
        }
        g_cv.notify_all();
    }
}

// ── Cleanup ───────────────────────────────────────────────────────────────────
static void cleanup() {
    if (g_cam)     closeQsCamera(g_cam);
    if (g_cameras) releaseQsCamera(g_cameras, g_camCount);
}
static void sigHandler(int) { cleanup(); _exit(0); }

// ── Main ──────────────────────────────────────────────────────────────────────
int main(int argc, char** argv) {
    const char* qsbsPath = "/home/kyle/KyleClaude/camera_new.qsbs";
    const char* outPath  = "capture_headless.qs";

    if (argc >= 2) qsbsPath  = argv[1];
    if (argc >= 3) outPath   = argv[2];
    if (argc >= 4) g_targetExp = std::atoi(argv[3]);

    ::signal(SIGINT,  sigHandler);
    ::signal(SIGTERM, sigHandler);
    std::atexit(cleanup);

    std::cout << "=== QS Headless Capture ===\n";
    std::cout << "Calibration : " << qsbsPath << "\n";
    std::cout << "Output      : " << outPath  << "\n";
    std::cout << "Exposure    : " << (g_targetExp > 0 ? std::to_string(g_targetExp) + " us" : "default") << "\n\n";

    // ── Load calibration ──────────────────────────────────────────────────────
    uint8_t* qsbsData = nullptr;
    size_t   qsbsSize = 0;
    QsErrorcodes err = loadQsbsFile(qsbsPath, &qsbsData, &qsbsSize);
    if (err != QS_ERR_SUCCESS) {
        std::cerr << "[WARN] loadQsbsFile: " << err << " (continuing without calib check)\n";
    } else {
        std::cout << "[OK] Calibration loaded (" << qsbsSize << " bytes)\n";
        freeQsData(qsbsData);
    }

    // ── Enumerate cameras ─────────────────────────────────────────────────────
    err = enumQsCamera(&g_cameras, &g_camCount);
    if (err != QS_ERR_SUCCESS || g_camCount == 0) {
        std::cerr << "[FAIL] No cameras found (err=" << err << ")\n";
        return 1;
    }
    g_cam = g_cameras[0];
    std::cout << "[OK] Found " << g_camCount << " camera(s)\n"; std::cout.flush();

    const char* camName = nullptr;
    controlQsCamera(g_cam, QS_CAMERA_GET_NAME, (void*)&camName);
    if (camName) { std::cout << "     Name: " << camName << "\n"; std::cout.flush(); }

    // ── Register callback BEFORE open ────────────────────────────────────────
    err = registerQsCameraCallback(g_cam, onFrame, nullptr);
    if (err != QS_ERR_SUCCESS) {
        std::cerr << "[FAIL] registerQsCameraCallback: " << err << "\n";
        return 1;
    }
    std::cout << "[OK] Callback registered\n"; std::cout.flush();

    // ── Open camera (async) ───────────────────────────────────────────────────
    auto t_open = std::chrono::steady_clock::now();
    err = openQsCamera(g_cam, true /*async*/);
    if (err != QS_ERR_SUCCESS) {
        std::cerr << "[FAIL] openQsCamera: " << err << "\n";
        return 1;
    }
    std::cout << "[OK] Camera opened (async)\n"; std::cout.flush();

    // ── Wait for capture ──────────────────────────────────────────────────────
    std::cout << "Waiting for settled frame (phase0=" << PHASE0_FRAMES
              << " + phase1=" << PHASE1_FRAMES << " warmup)...\n";
    auto t_start = std::chrono::steady_clock::now();
    {
        std::unique_lock<std::mutex> lk(g_mutex);
        bool ok = g_cv.wait_for(lk, std::chrono::seconds(30),
                                [] { return g_phase.load() == PHASE_DONE; });
        if (!ok || g_frame.empty()) {
            std::cerr << "[FAIL] Timeout waiting for frame\n";
            return 1;
        }
    }
    auto t_end = std::chrono::steady_clock::now();
    double elapsed_ms = std::chrono::duration<double, std::milli>(t_end - t_start).count();
    double open_ms    = std::chrono::duration<double, std::milli>(t_start - t_open).count();

    // ── Verify actual exposure ────────────────────────────────────────────────
    int actualExp = 0;
    controlQsCamera(g_cam, QS_CAMERA_GET_EXPOSURE, &actualExp);
    std::cout << "[OK] Actual exposure: " << actualExp << " us\n";

    // ── Save .qs ──────────────────────────────────────────────────────────────
    {
        std::lock_guard<std::mutex> lk(g_mutex);
        err = saveQsFile(outPath, g_frame.data(), g_frame.size());
        if (err != QS_ERR_SUCCESS) {
            std::cerr << "[FAIL] saveQsFile: " << err << "\n";
            return 1;
        }
    }

    // ── File size ─────────────────────────────────────────────────────────────
    struct stat st{};
    stat(outPath, &st);
    long file_bytes = (long)st.st_size;

    // ── Report ────────────────────────────────────────────────────────────────
    std::cout << "\n=== CAPTURE REPORT ===\n";
    std::cout << "File        : " << outPath << "\n";
    std::cout << "File size   : " << file_bytes << " bytes";
    if (file_bytes >= 1024*1024)
        std::cout << " (" << file_bytes/1024/1024 << "."
                  << (file_bytes % (1024*1024)) * 10 / (1024*1024) << " MB)";
    else
        std::cout << " (" << file_bytes/1024 << " KB)";
    std::cout << "\n";
    std::cout << "Exposure    : " << actualExp << " us\n";
    std::cout << "Time to capture: " << elapsed_ms/1000.0 << " s\n";
    std::cout << "  (camera open → stream ready: ~" << open_ms/1000.0 << " s)\n";
    std::cout << "======================\n";

    return 0;
}
