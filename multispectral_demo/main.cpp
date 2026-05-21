/**
 * Multispectral Camera Demo
 * QS SDK - Raspberry Pi 5 (ARM64)
 *
 * Keys:
 *   r - RGB mode
 *   g - Grayscale mode
 *   b - Spectral band mode (custom wavelength)
 *   a - Agriculture band mode (5 fixed bands)
 *   n - NDVI pseudocolor
 *   d - GNDVI pseudocolor
 *   e - NDRE pseudocolor
 *   o - OSAVI pseudocolor
 *   c - LCI pseudocolor
 *   < / > (or , / .) - Previous / Next band
 *   + / - - Increase / decrease exposure
 *   l - Toggle lamp
 *   s - Save current frame + raw .qs file
 *   q / ESC - Quit
 */

#include <iostream>
#include <fstream>
#include <vector>
#include <string>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <atomic>
#include <chrono>
#include <cstring>
#include <cmath>
#include <algorithm>
#include <sstream>
#include <iomanip>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <signal.h>
#include <sys/wait.h>
#include <sys/ioctl.h>
#include <linux/videodev2.h>

extern "C" {
#include "qs_camera.h"
#include "qs_fileio.h"
#include "qs_imgproc.h"
#include "qs_specinv.h"
#include "qs_agriculture.h"
#include "qs_errorcodes.h"
}
#include <dlfcn.h>

/* qs_raw_yuyv_get is in uvc_fix.so (LD_PRELOAD), looked up at runtime */
static int (*fn_raw_yuyv_get)(uint8_t*) = nullptr;
static void init_raw_yuyv() {
    if (!fn_raw_yuyv_get)
        fn_raw_yuyv_get = (int(*)(uint8_t*))dlsym(RTLD_DEFAULT, "qs_raw_yuyv_get");
}

#include <opencv2/opencv.hpp>
#include <X11/Xlib.h>
#include <X11/Xatom.h>

// ─────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────

// Distance from lens center to each LED (cm).
// Adjust this to match your physical hardware.
static const float LED_OFFSET_CM = 1.5f;

static const char* AGR_BAND_NAMES[5] = {
    "Blue  (434-466nm)",
    "Green (544-576nm)",
    "Red   (634-666nm)",
    "RedEdge(714-746nm)",
    "NIR   (814-866nm)"
};

// Band mode: intricacy level (1-1000). Lower = faster, less accurate.
static const int BAND_INTRICACY = 50;

static const int SB_W        = 300;   // kept: drawSidebar still references it (removed in cleanup)
static const int SB_FULL_H   = 1200;  // kept: drawSidebar still references it (removed in cleanup)
static const int DISP_W      = 480;   // portrait logical width (wlr-randr transform=270)
static const int DISP_H      = 800;   // portrait logical height
static const int DISP_PREV_H = 352;   // status bar 32 + image area 288 + label bar 32
static const int GRID_H      = 360;   // button grid (3 rows × 120px)
static const int BOT_H       = 88;    // bottom control bar
static const int GRID_COLS   = 3;
static const int GRID_ROWS   = 3;
static const int CELL_W      = DISP_W / GRID_COLS;  // 160
static const int CELL_H      = GRID_H / GRID_ROWS;  // 120

// Returns {path, exposure_us} for the best available white ref.
// Priority: 5000us > 2500us > 1250us. Bean spec is captured at the same exposure
// (whiteRefExp), so SDK non-linearity cancels in the flat-field ratio.
static std::pair<std::string,int> ffWhiteRef(const std::string& dir) {
    for (int exp : {5000, 2500, 1250}) {
        std::string p = dir + "/white_ref_" + std::to_string(exp) + "us.qs";
        if (access(p.c_str(), F_OK) == 0) return {p, exp};
    }
    return {"", 0};
}
// Cross-exposure scaling of spec_raw.csv is intentionally a no-op:
// SDK qsToQsi is non-linear across exposures (white paper and beans scale differently),
// so any linear correction factor is incorrect. Flat-field is only valid when
// bean and white are captured at the same exposure (ensured by whiteRefExp logic).
static void scaleSpecCsv(const std::string&, int) {}
static const char* roastLabel(int mean) {
    if (mean >= 70) return "Light Roast";
    if (mean >= 50) return "Medium Roast";
    return "Dark Roast";
}
static void writeFFMarker(const std::string& dir, const std::string& whiteRef) {
    std::string marker = dir + "/flatfield_used.txt";
    if (whiteRef.empty()) { remove(marker.c_str()); return; }
    std::ofstream(marker) << whiteRef;
}

// ─────────────────────────────────────────────────────────
// Display Mode
// ─────────────────────────────────────────────────────────

enum class Mode {
    RGB,
    GRAY,
    SPEC_BAND,   // custom wavelength bands
    AGR_BAND,    // 5 fixed agriculture bands
    NDVI,
    GNDVI,
    NDRE,
    OSAVI,
    LCI,
    DEPTH,       // relative depth map from LED on/off difference
    RAW_YUYV,   // debug: direct Y/U/V channel display, bypasses SDK
    RAW_RGB,     // debug: raw YUYV + saved SDK header → qsToRgb (tests calibration path)
    SEGMENT,     // bean segmentation result
    MOLD,        // mold detection overlay
    SPEC_VIZ,    // spectral curves visualization (after U capture)
    AGTRON,          // Agtron roast value overlay
    AGTRON_HISTOGRAM, // Agtron distribution histogram
    AGTRON_PIECHART,  // Agtron donut pie chart
    GRIND,            // grind particle labeled overlay
    GRIND_HISTOGRAM   // grind PSD histogram
};

const char* modeToString(Mode m) {
    switch (m) {
        case Mode::RGB:       return "RGB";
        case Mode::GRAY:      return "Grayscale";
        case Mode::SPEC_BAND: return "Spectral Band";
        case Mode::AGR_BAND:  return "Agriculture Band";
        case Mode::NDVI:      return "NDVI";
        case Mode::GNDVI:     return "GNDVI";
        case Mode::NDRE:      return "NDRE";
        case Mode::OSAVI:     return "OSAVI";
        case Mode::LCI:       return "LCI";
        case Mode::DEPTH:     return "Depth Map";
        case Mode::RAW_YUYV:  return "RAW YUYV (debug)";
        case Mode::RAW_RGB:   return "RAW RGB (raw+header→qsToRgb)";
        case Mode::MOLD:      return "Mold Map";
        case Mode::SPEC_VIZ:  return "Spectral Curves";
        case Mode::AGTRON:           return "Agtron Roast";
        case Mode::AGTRON_HISTOGRAM: return "Agtron Histogram";
        case Mode::AGTRON_PIECHART:  return "Agtron Pie Chart";
        case Mode::GRIND:            return "Grind Size Map";
        case Mode::GRIND_HISTOGRAM:  return "Grind PSD";
        default:              return "Unknown";
    }
}

// ─────────────────────────────────────────────────────────
// Application State
// ─────────────────────────────────────────────────────────

struct AppState {
    // Camera
    QsCameraContext**   cameras      = nullptr;
    int                 cameraCount  = 0;
    QsCameraContext*    camera       = nullptr;

    // SDK Contexts
    uint8_t*            qsbsData     = nullptr;
    size_t              qsbsSize     = 0;
    QsImgprocContext*   imgprocCtx   = nullptr;
    QsSpecinvContext*   specinvCtx   = nullptr;
    QsAgricultureContext* agriCtx    = nullptr;

    // Spectral range (from initQsSpecinv)
    size_t              specBegin    = 0;
    size_t              specEnd      = 0;
    int                 bandStep     = 20; // nm between band starts
    int                 bandWidth    = 20; // nm width per band

    // Generated spectral band list {start_nm, end_nm}
    std::vector<std::pair<int,int>> specBands;

    // Display state
    Mode                mode         = Mode::GRAY;
    int                 bandIndex    = 0;   // index into specBands or agr bands (0-4)

    // Frame data (shared between callback thread and main thread)
    std::mutex              frameMutex;
    std::condition_variable frameCV;
    std::vector<uint8_t>    latestFrame;
    bool                    newFrame     = false;
    std::vector<uint8_t>    sdkHeader;   // first 323 bytes of SDK frame (saved on first callback)

    std::atomic<bool>   running      { true };

    // Camera controls
    int  exposureMin  = 7000;  // below ~6000us camera switches mode and image gets darker
    int  exposureMax  = 0;
    int  exposure     = 0;
    int  gain         = 1;
    int  gainMin      = 1;
    int  gainMax      = 64;
    bool hasLamp      = false;
    bool lampOn       = false;

    // Stats
    int  frameCount   = 0;
    int  saveCounter  = 0;
    std::string statusMsg;
    std::string saveDir;          // Desktop/<timestamp> folder, created at startup

    bool specinvReady = false;
    bool agriReady    = false;

    bool saveRequested = false;   // set by mouse callback, handled in main loop

    // ── Depth capture ─────────────────────────────────────
    std::atomic<bool> blockProc{false};        // pause background proc thread
    std::atomic<bool> depthCapturePending{false};
    std::atomic<bool> depthMapUpdated{false};  // set after runDepthCapture succeeds
    float  depthCalibK    = 0.0f;             // calibration scale factor (0 = uncalibrated)
    float  depthCalibDist = 15.0f;            // known distance used for next calibration (cm)
    cv::Mat lastDepthMap;                     // last computed depth (CV_32F, cm units)

    // Auto Exposure (enabled by default)
    bool aeEnabled = false;

    // ── Bean Segmentation ──────────────────────────────────
    cv::Mat       segBg;              // stored background grayscale (CV_8U)
    bool          segBgCaptured = false;
    std::atomic<bool> segPending{false};   // triggered by button/key
    std::atomic<bool> segRunning{false};   // background thread active
    cv::Mat       segOverlay;         // beans_contour.png loaded after run
    int           segBeanCount = -1;  // -1 = no result yet
    std::mutex    segMutex;

    // ── Seg daemon (keeps FastSAM model loaded) ────────────
    FILE*             segDaemonWr   = nullptr;  // write requests to daemon
    FILE*             segDaemonRd   = nullptr;  // read responses from daemon
    pid_t             segDaemonPid  = -1;
    std::atomic<bool> segDaemonReady{false};

    // ── Mold Detection ─────────────────────────────────────
    std::string qsbsPath;             // stored for spec_fingerprint
    std::string qsdbPath;
    std::atomic<bool> specCapturePending{false};
    bool specCaptured{false};
    std::atomic<bool> specRunning{false};   // spec capture in progress
    std::atomic<bool> moldPending{false};
    std::atomic<bool> moldRunning{false};
    cv::Mat moldOverlay;
    cv::Mat specVizImgs[2];           // [0]=all curves, [1]=mean±σ
    int specVizIdx{0};                // which spectral chart is displayed
    int moldHighCount{-1};
    int moldMedCount{-1};
    std::mutex moldMutex;

    // ── Full Analysis pipeline ──────────────────────────────
    std::atomic<bool> fullAnalysisPending{false};
    std::atomic<bool> fullAnalysisRunning{false};
    std::chrono::steady_clock::time_point fullAnalysisStart;
    std::string fullAnalysisStage;  // shown in progress button

    // ── White Reference (for Agtron calibration) ────────────
    bool whiteRefCaptured{false};   // true = white_spec.csv available (session or global)
    bool whiteRefGlobal{false};     // true = loaded from global (not this session)
    int  whiteRefExp{0};            // actual capture exposure (us); 0 = unknown/global

    // ── Agtron ──────────────────────────────────────────────
    bool agtronReady{false};
    int  agtronMean{-1};    // batch mean Agtron (-1 = not computed)
    cv::Mat agtronOverlay;   // agtron_labeled.png
    cv::Mat agtronHistogram; // agtron_histogram.png
    cv::Mat agtronPiechart;  // agtron_piechart.png
    std::atomic<bool> agtronPending{false};
    std::atomic<bool> agtronRunning{false};
    std::chrono::steady_clock::time_point agtronStart;

    // ── Agtron Fixed ROI ─────────────────────────────────────
    bool agtronRoiMode{false};    // user is adjusting the ROI circle
    bool agtronRoiSaved{false};   // ROI saved and used for fast path
    int  agtronRoiCx{800};        // circle center X in full-image coords (1600x1200)
    int  agtronRoiCy{600};        // circle center Y
    int  agtronRoiR{200};         // circle radius in full-image pixels
    bool agtronRoiDragging{false};

    // ── Grind Size Analysis ──────────────────────────────────
    bool grindReady{false};
    float grindD10{-1.0f};
    float grindD50{-1.0f};
    float grindD90{-1.0f};
    bool grindCalibrated{false};
    cv::Mat grindOverlay;
    cv::Mat grindHistogram;
    std::atomic<bool> grindPending{false};
    std::atomic<bool> grindRunning{false};
    std::chrono::steady_clock::time_point grindStart;
    std::mutex grindMutex;

    // ── Operation progress tracking ─────────────────────────
    std::chrono::steady_clock::time_point segStartTime;
    std::chrono::steady_clock::time_point specStartTime;
    std::chrono::steady_clock::time_point moldStartTime;

    // Debounce: pending camera control changes (applied after 500ms idle)
    bool exposurePending = false;
    bool gainPending     = false;
    std::chrono::steady_clock::time_point exposureChanged;
    std::chrono::steady_clock::time_point gainChanged;

    // After applying exposure, skip display for a settle period
    std::chrono::steady_clock::time_point settleUntil{};

    // Background processing output (written by proc thread, read by main)
    std::mutex  resultMutex;
    cv::Mat     latestResult;
    bool        hasResult = false;

    const char* modeName() const {
        switch (mode) {
        case Mode::RGB:      return "RGB";
        case Mode::GRAY:     return "Grayscale";
        case Mode::SPEC_BAND:return "Spectral";
        case Mode::AGR_BAND: return "Agriculture";
        case Mode::NDVI:     return "NDVI";
        case Mode::GNDVI:    return "GNDVI";
        case Mode::NDRE:     return "NDRE";
        case Mode::OSAVI:    return "OSAVI";
        case Mode::LCI:      return "LCI";
        case Mode::DEPTH:    return "Depth";
        case Mode::SEGMENT:  return "Segment";
        case Mode::MOLD:     return "Mold";
        case Mode::SPEC_VIZ: return "SpecViz";
        case Mode::AGTRON:           return "Agtron";
        case Mode::AGTRON_HISTOGRAM: return "Hist";
        case Mode::AGTRON_PIECHART:  return "Pie";
        case Mode::GRIND:            return "Grind";
        case Mode::GRIND_HISTOGRAM:  return "GrindPSD";
        default:             return "";
        }
    }
};

AppState g_app;

// ─────────────────────────────────────────────────────────
// Sidebar Button System
// ─────────────────────────────────────────────────────────

enum class BtnTag {
    NONE = 0,
    RGB, GRAY,
    SPEC_PREV, SPEC_NEXT,
    AGR0, AGR1, AGR2, AGR3, AGR4,
    NDVI, GNDVI, NDRE, OSAVI, LCI,
    LAMP, AE_TOGGLE, EXP_PLUS, EXP_MINUS, GAIN_PLUS, GAIN_MINUS, SAVE,
    DEPTH_CALIB_10, DEPTH_CALIB_15, DEPTH_CALIB_20, DEPTH_CAPTURE,
    SEG_CAPTURE_BG, WHITE_CAPTURE, FULL_ANALYSIS,
    ANALYSIS_COMPLETE, ANALYSIS_QUICK, ANALYSIS_CANCEL, ANALYSIS_DO_RUN,
    SEG_SEGMENT, SPEC_CAPTURE, MOLD_DETECT,  // kept for keyboard shortcuts
    SEG_VIEW, MOLD_VIEW,
    SPEC_VIZ_0, SPEC_VIZ_1,
    AGTRON_RUN, AGTRON_VIZ, AGTRON_HIST, AGTRON_PIE,
    AGTRON_ROI_SETUP, AGTRON_ROI_SAVE, AGTRON_ROI_LARGER, AGTRON_ROI_SMALLER,
    GRIND_CAPTURE, GRIND_VIZ, GRIND_HIST,
    VEG_TOGGLE,
    UV_SCAN,
    QUIT
};

struct SidebarBtn {
    cv::Rect rect;   // sidebar-local coordinates
    BtnTag   tag;
};

static std::vector<SidebarBtn> g_sidebarBtns;
static int  g_previewW      = 0;    // width of the preview area in the composite image
static int  g_sbScrollY       = 0;    // sidebar vertical scroll offset (pixels into SB_FULL_H)
static bool g_vegExpanded     = false; // Vegetation Index section collapsed/expanded
// Analysis prompt state: 0=normal, 1=asking complete/quick, 2=await_bg_then_run
static int  g_analysisPrompt  = 0;
static bool g_analysisModeQuick = false; // true = skip BG diff
static int  g_touchStartY   = -1;   // y coord when finger/mouse pressed down (-1 = not tracking)
static int  g_touchScrollBase = 0;  // g_sbScrollY value when touch began
static bool g_touchDragged  = false; // true once drag exceeds threshold
static const int DRAG_THRESHOLD = 8; // pixels before tap becomes drag

// ─────────────────────────────────────────────────────────
// Camera Callback
// ─────────────────────────────────────────────────────────

void onCameraFrame(const uint8_t* data, const size_t size, void* ctx) {
    AppState* app = static_cast<AppState*>(ctx);
    std::lock_guard<std::mutex> lock(app->frameMutex);
    static int cbCount = 0;
    if (++cbCount <= 3) {
        // Sample bytes at multiple offsets to detect if image body is zero
        auto sample = [&](size_t off) -> std::string {
            if (off + 3 >= size) return "OOB";
            return std::to_string(data[off])   + "," + std::to_string(data[off+1]) + ","
                 + std::to_string(data[off+2]) + "," + std::to_string(data[off+3]);
        };
        // Count non-zero bytes in a middle slice
        size_t mid = size / 2, nonzero = 0;
        for (size_t i = mid; i < mid + 4096 && i < size; ++i)
            if (data[i]) ++nonzero;
        std::cout << "[CB] frame #" << cbCount << " size=" << size << "\n"
                  << "     @0=" << sample(0) << "  @323=" << sample(323)
                  << "  @mid=" << sample(mid) << "  @end=" << sample(size-4) << "\n"
                  << "     mid-4096 non-zero=" << nonzero << "/4096\n";
    }
    // Save SDK header (first 323 bytes) on first frame for RAW_RGB mode
    if (app->sdkHeader.empty() && size >= 323)
        app->sdkHeader.assign(data, data + 323);

    app->latestFrame.assign(data, data + size);
    app->newFrame = true;
    app->frameCV.notify_one();
}

// ─────────────────────────────────────────────────────────
// Band Generation
// ─────────────────────────────────────────────────────────

void generateSpecBands(AppState& app) {
    app.specBands.clear();
    int end = (int)app.specEnd;
    // Must start at specBegin; valid wavelengths are specBegin + N*bandStep.
    // Do NOT align to bandStep from 0 — e.g. 350 % 20 != 0, so that would
    // shift the first band to 360 which the SDK rejects as misaligned.
    int s = (int)app.specBegin;
    while (s + app.bandWidth <= end) {
        app.specBands.push_back({s, s + app.bandWidth});
        s += app.bandStep;
    }
    std::cout << "[SDK] Generated " << app.specBands.size()
              << " spectral bands (" << app.specBegin
              << "-" << app.specEnd << "nm, step=" << app.bandStep << "nm)\n";
}

// ─────────────────────────────────────────────────────────
// Depth Utilities
// ─────────────────────────────────────────────────────────

// Capture one grayscale frame as CV_32F.
// MUST be called with app.blockProc = true so the proc thread is paused.
static cv::Mat captureOneGray(AppState& app, int timeoutMs = 2000) {
    std::unique_lock<std::mutex> lk(app.frameMutex);
    app.newFrame = false;              // flush any stale frame
    bool got = app.frameCV.wait_for(lk, std::chrono::milliseconds(timeoutMs),
        [&]{ return app.newFrame || !app.running; });
    if (!got || !app.newFrame || !app.running) return {};

    std::vector<uint8_t> frame = app.latestFrame;
    app.newFrame = false;
    lk.unlock();

    uint8_t* grayData = nullptr;
    int w = 0, h = 0;
    auto err = qsToGray(app.imgprocCtx, frame.data(), frame.size(), &grayData, &w, &h);
    if (err != QS_ERR_SUCCESS || !grayData) return {};

    cv::Mat mat(h, w, CV_8UC1, grayData);
    cv::Mat result;
    mat.convertTo(result, CV_32F);
    freeQsData(grayData);
    return result;
}

// Start seg_daemon.py in a child process with bidirectional pipes.
// Reads the "ready" JSON line in a background thread; sets app.segDaemonReady when done.
static bool startSegDaemon(AppState& app) {
    int pipe_in[2], pipe_out[2];
    if (pipe(pipe_in) < 0 || pipe(pipe_out) < 0) return false;
    pid_t pid = fork();
    if (pid < 0) {
        close(pipe_in[0]); close(pipe_in[1]);
        close(pipe_out[0]); close(pipe_out[1]);
        return false;
    }
    if (pid == 0) {
        dup2(pipe_in[0],  STDIN_FILENO);
        dup2(pipe_out[1], STDOUT_FILENO);
        close(pipe_in[0]);  close(pipe_in[1]);
        close(pipe_out[0]); close(pipe_out[1]);
        for (int i = 3; i < 256; i++) close(i);
        execl("/usr/bin/python3", "python3",
              "/home/kyle/KyleClaude/seg_daemon.py", nullptr);
        _exit(127);
    }
    close(pipe_in[0]);
    close(pipe_out[1]);
    app.segDaemonPid = pid;
    app.segDaemonWr  = fdopen(pipe_in[1],  "w");
    app.segDaemonRd  = fdopen(pipe_out[0], "r");
    if (!app.segDaemonWr || !app.segDaemonRd) return false;
    // Read "ready" message in background (model load takes ~8s)
    std::thread([&app](){
        char buf[256] = {};
        if (app.segDaemonRd && fgets(buf, sizeof(buf), app.segDaemonRd))
            if (std::string(buf).find("ready") != std::string::npos)
                app.segDaemonReady = true;
    }).detach();
    return true;
}

// Build the depth lookup table once (illumination model I = d / (d²+a²)^1.5).
// Returns monotonically-decreasing I_lut matched index-for-index with d_lut.
static void buildDepthLUT(std::vector<float>& d_lut, std::vector<float>& I_lut) {
    if (!d_lut.empty()) return;
    float a = LED_OFFSET_CM;
    for (float d = 0.5f; d <= 40.0f; d += 0.005f) {
        d_lut.push_back(d);
        I_lut.push_back(d / std::pow(d * d + a * a, 1.5f));
    }
    // I_lut is decreasing (for d > a/sqrt(2) ≈ 1cm) — suitable for reverse binary search
}

// Calibrate the depth scale factor k at a known distance (cm).
// Places white card at knownDistCm, captures on/off pair, computes k.
static void runDepthCalibration(AppState& app, float knownDistCm) {
    bool prevLamp = app.lampOn;
    bool prevAE   = app.aeEnabled;
    app.aeEnabled = false;
    app.blockProc = true;

    const int SETTLE_MS = 500;
    bool off = false, on = true;

    controlQsCamera(app.camera, QS_CAMERA_SET_LAMP, &off);
    app.lampOn = false;
    std::this_thread::sleep_for(std::chrono::milliseconds(SETTLE_MS));
    cv::Mat img_off = captureOneGray(app);

    controlQsCamera(app.camera, QS_CAMERA_SET_LAMP, &on);
    app.lampOn = true;
    std::this_thread::sleep_for(std::chrono::milliseconds(SETTLE_MS));
    cv::Mat img_on = captureOneGray(app);

    // Restore
    app.blockProc = false;
    app.aeEnabled = prevAE;
    controlQsCamera(app.camera, QS_CAMERA_SET_LAMP, &prevLamp);
    app.lampOn = prevLamp;

    if (img_off.empty() || img_on.empty()) {
        app.statusMsg = "Calib FAIL: no frame";
        return;
    }

    cv::Mat diff = img_on - img_off;
    cv::threshold(diff, diff, 0.0, 0.0, cv::THRESH_TOZERO);

    // Use center 50% region for stable mean
    int h = diff.rows, w = diff.cols;
    cv::Scalar meanVal = cv::mean(diff(cv::Rect(w / 4, h / 4, w / 2, h / 2)));
    double I_meas = meanVal[0];

    if (I_meas < 1.0) {
        app.statusMsg = "Calib FAIL: diff < 1 (too dark or too far)";
        return;
    }

    float a = LED_OFFSET_CM;
    float d = knownDistCm;
    float I_model = d / std::pow(d * d + a * a, 1.5f);
    app.depthCalibK = (float)(I_meas / I_model);

    // Save to file alongside the binary
    FILE* f = fopen("depth_calib.txt", "w");
    if (f) {
        fprintf(f, "k=%.6f\n", app.depthCalibK);
        fprintf(f, "# calib_dist=%.1f cm  mean_diff=%.2f  I_model=%.8f\n",
                d, I_meas, I_model);
        fclose(f);
    }

    char buf[128];
    snprintf(buf, sizeof(buf), "Calib OK %.0fcm  k=%.1f", knownDistCm, app.depthCalibK);
    app.statusMsg = buf;
    std::cout << "[CALIB] dist=" << d << "cm  diff=" << I_meas
              << "  I_model=" << I_model << "  k=" << app.depthCalibK << "\n";
}

// Capture LED on/off pair, compute depth map (CV_32F, units = cm).
// Stores result in app.lastDepthMap and switches to DEPTH display mode.
static void runDepthCapture(AppState& app) {
    bool prevLamp = app.lampOn;
    bool prevAE   = app.aeEnabled;
    app.aeEnabled = false;
    app.blockProc = true;

    const int SETTLE_MS = 500;
    bool off = false, on = true;

    controlQsCamera(app.camera, QS_CAMERA_SET_LAMP, &off);
    app.lampOn = false;
    std::this_thread::sleep_for(std::chrono::milliseconds(SETTLE_MS));
    cv::Mat img_off = captureOneGray(app);

    controlQsCamera(app.camera, QS_CAMERA_SET_LAMP, &on);
    app.lampOn = true;
    std::this_thread::sleep_for(std::chrono::milliseconds(SETTLE_MS));
    cv::Mat img_on = captureOneGray(app);

    // Restore
    app.blockProc = false;
    app.aeEnabled = prevAE;
    controlQsCamera(app.camera, QS_CAMERA_SET_LAMP, &prevLamp);
    app.lampOn = prevLamp;

    if (img_off.empty() || img_on.empty()) {
        app.statusMsg = "Depth FAIL: no frame";
        return;
    }

    cv::Mat diff = img_on - img_off;
    cv::threshold(diff, diff, 0.0, 0.0, cv::THRESH_TOZERO);

    int h = diff.rows, w = diff.cols;
    cv::Mat center = diff(cv::Rect(w / 4, h / 4, w / 2, h / 2));
    double maxVal; cv::minMaxLoc(center, nullptr, &maxVal);

    if (maxVal < 2.0) {
        app.statusMsg = "Depth FAIL: LED diff too weak (increase exposure, darken room)";
        return;
    }

    // Build LUT
    static std::vector<float> d_lut, I_lut;
    buildDepthLUT(d_lut, I_lut);

    // Determine scale factor k
    float k;
    if (app.depthCalibK > 0.0f) {
        k = app.depthCalibK;
    } else {
        // Uncalibrated: assume center peak corresponds to 15cm
        float a = LED_OFFSET_CM, d0 = 15.0f;
        float I0 = d0 / std::pow(d0 * d0 + a * a, 1.5f);
        k = (float)(maxVal / I0);
        app.statusMsg = "Depth (uncalibrated, assuming 15cm center)";
    }

    // Per-pixel depth via reverse binary search in I_lut (decreasing)
    cv::Mat depth_map(diff.size(), CV_32F);
    const float* dp  = diff.ptr<float>();
    float*       out = depth_map.ptr<float>();
    int N = (int)I_lut.size();
    for (int i = 0; i < (int)diff.total(); ++i) {
        float I_val = dp[i] / k;
        // Binary search: I_lut is decreasing, find first index where I_lut[idx] <= I_val
        int lo = 0, hi = N - 1;
        while (lo < hi) {
            int mid = (lo + hi) / 2;
            if (I_lut[mid] > I_val) lo = mid + 1;
            else hi = mid;
        }
        out[i] = d_lut[std::clamp(lo, 0, N - 1)];
    }

    app.lastDepthMap = depth_map;
    app.mode = Mode::DEPTH;
    app.depthMapUpdated = true;

    // Save files
    cv::Mat vis;
    cv::normalize(depth_map, vis, 0, 255, cv::NORM_MINMAX, CV_8U);
    cv::Mat color; cv::applyColorMap(vis, color, cv::COLORMAP_JET);
    cv::imwrite("depth_map.png", color);
    // 32-bit EXR for precise cm values (requires OpenCV with EXR support)
    try { cv::imwrite("depth_raw.exr", depth_map); } catch (...) {}

    if (app.depthCalibK > 0.0f)
        app.statusMsg = "Depth OK — saved depth_map.png";

    std::cout << "[DEPTH] max_diff=" << maxVal << "  k=" << k << "\n";
}

// ─────────────────────────────────────────────────────────
// Frame Processing
// ─────────────────────────────────────────────────────────

// Convert double[h][w] data to 8-bit grayscale Mat
cv::Mat doubleToGrayMat(const double* data, int w, int h) {
    cv::Mat src(h, w, CV_64F, const_cast<double*>(data));
    cv::Mat norm, out;
    cv::normalize(src, norm, 0.0, 255.0, cv::NORM_MINMAX, CV_64F);
    norm.convertTo(out, CV_8UC1);
    return out;
}

cv::Mat processFrame(AppState& app, const std::vector<uint8_t>& frame) {
    const uint8_t* data = frame.data();
    const size_t   size = frame.size();

    switch (app.mode) {

    // ── RGB ──────────────────────────────────────────────
    case Mode::RGB: {
        uint8_t* rgbData = nullptr;
        int w = 0, h = 0;
        QsErrorcodes err = qsToRgb(app.imgprocCtx, data, size, &rgbData, &w, &h);
        if (err != QS_ERR_SUCCESS || !rgbData) {
            std::cerr << "[ERR] qsToRgb: " << qsErrorToString(err) << "\n";
            return {};
        }
        cv::Mat mat(h, w, CV_8UC3, rgbData);
        cv::Mat result = mat.clone();
        freeQsData(rgbData);
        // SDK gives RGB, OpenCV expects BGR
        cv::cvtColor(result, result, cv::COLOR_RGB2BGR);
        static int rgbDbg = 0;
        if (++rgbDbg <= 5) {
            cv::Scalar m = cv::mean(result);
            double mn, mx;
            cv::minMaxLoc(result, &mn, &mx);
            std::cout << "[RGB] " << w << "x" << h
                      << " mean=(" << m[0] << "," << m[1] << "," << m[2] << ")"
                      << " min=" << mn << " max=" << mx << "\n";
        }
        return result;
    }

    // ── Grayscale ─────────────────────────────────────────
    case Mode::GRAY: {
        uint8_t* grayData = nullptr;
        int w = 0, h = 0;
        QsErrorcodes err = qsToGray(app.imgprocCtx, data, size, &grayData, &w, &h);
        if (err != QS_ERR_SUCCESS || !grayData) {
            std::cerr << "[ERR] qsToGray: " << qsErrorToString(err) << "\n";
            return {};
        }
        cv::Mat mat(h, w, CV_8UC1, grayData);
        cv::Mat result;
        cv::cvtColor(mat.clone(), result, cv::COLOR_GRAY2BGR);
        freeQsData(grayData);
        return result;
    }

    // ── Spectral Band ─────────────────────────────────────
    case Mode::SPEC_BAND: {
        if (!app.specinvReady || app.specBands.empty()) return {};
        int idx = std::clamp(app.bandIndex, 0, (int)app.specBands.size() - 1);
        auto [bStart, bEnd] = app.specBands[idx];

        int bandRange[1][2] = {{bStart, bEnd}};
        uint8_t* qsiData  = nullptr;
        size_t   qsiSize  = 0;

        QsErrorcodes err = qsToQsi(app.specinvCtx, data, size,
                                   -1,  // auto-detect light source
                                   BAND_INTRICACY,
                                   bandRange, 1,
                                   &qsiData, &qsiSize);
        if (err != QS_ERR_SUCCESS || !qsiData) {
            std::cerr << "[ERR] qsToQsi: " << qsErrorToString(err) << "\n";
            return {};
        }

        double* grayData       = nullptr;
        int     w = 0, h = 0;
        int   (*outRange)[2]   = nullptr;
        int     outBandNum     = 0;

        err = qsiToGray(qsiData, qsiSize, 1.0,
                        &grayData, &w, &h,
                        &outRange, &outBandNum);
        freeQsData(qsiData);

        if (err != QS_ERR_SUCCESS || !grayData) {
            std::cerr << "[ERR] qsiToGray: " << qsErrorToString(err) << "\n";
            if (outRange) freeQsData(outRange);
            return {};
        }

        // grayData layout: [bandNum][h][w] flat doubles
        cv::Mat gray = doubleToGrayMat(grayData, w, h);
        freeQsData(grayData);
        if (outRange) freeQsData(outRange);

        cv::Mat result;
        cv::cvtColor(gray, result, cv::COLOR_GRAY2BGR);
        return result;
    }

    // ── Agriculture Band ──────────────────────────────────
    case Mode::AGR_BAND: {
        if (!app.agriReady) return {};

        uint8_t* qabData  = nullptr;
        size_t   qabSize  = 0;
        QsErrorcodes err  = qsToQab(app.agriCtx, data, size, &qabData, &qabSize);
        if (err != QS_ERR_SUCCESS || !qabData) {
            std::cerr << "[ERR] qsToQab: " << qsErrorToString(err) << "\n";
            return {};
        }

        double* grayData = nullptr;
        int w = 0, h = 0;
        err = qabToGray(qabData, qabSize, 1.0, &grayData, &w, &h);
        freeQsData(qabData);

        if (err != QS_ERR_SUCCESS || !grayData) {
            std::cerr << "[ERR] qabToGray: " << qsErrorToString(err) << "\n";
            return {};
        }

        // grayData layout: [5][h][w] flat doubles
        int idx = std::clamp(app.bandIndex, 0, 4);
        cv::Mat gray = doubleToGrayMat(grayData + (size_t)idx * w * h, w, h);
        freeQsData(grayData);

        cv::Mat result;
        cv::cvtColor(gray, result, cv::COLOR_GRAY2BGR);
        return result;
    }

    // ── Vegetation Indices (NDVI / GNDVI / NDRE / OSAVI / LCI) ──
    case Mode::NDVI:
    case Mode::GNDVI:
    case Mode::NDRE:
    case Mode::OSAVI:
    case Mode::LCI: {
        if (!app.agriReady) return {};

        uint8_t* qabData = nullptr;
        size_t   qabSize = 0;
        QsErrorcodes err = qsToQab(app.agriCtx, data, size, &qabData, &qabSize);
        if (err != QS_ERR_SUCCESS || !qabData) {
            std::cerr << "[ERR] qsToQab: " << qsErrorToString(err) << "\n";
            return {};
        }

        double*  idxData = nullptr;
        uint32_t w = 0, h = 0;

        if (app.mode == Mode::NDVI)
            err = qabToNdvi(qabData, qabSize, &idxData, &w, &h);
        else if (app.mode == Mode::GNDVI)
            err = qabToGndvi(qabData, qabSize, &idxData, &w, &h);
        else if (app.mode == Mode::NDRE)
            err = qabToNdre(qabData, qabSize, &idxData, &w, &h);
        else if (app.mode == Mode::OSAVI)
            err = qabToOsavi(qabData, qabSize, &idxData, &w, &h);
        else
            err = qabToLci(qabData, qabSize, &idxData, &w, &h);

        freeQsData(qabData);

        if (err != QS_ERR_SUCCESS || !idxData) {
            std::cerr << "[ERR] vegetation index: " << qsErrorToString(err) << "\n";
            return {};
        }

        // vegetationIndexToPseudoColor outputs RGB
        std::vector<uint8_t> rgb(w * h * 3);
        err = vegetationIndexToPseudoColor(idxData, w, h, rgb.data());
        freeQsData(idxData);

        if (err != QS_ERR_SUCCESS) {
            std::cerr << "[ERR] pseudocolor: " << qsErrorToString(err) << "\n";
            return {};
        }

        cv::Mat mat((int)h, (int)w, CV_8UC3, rgb.data());
        cv::Mat result = mat.clone();
        cv::cvtColor(result, result, cv::COLOR_RGB2BGR);
        return result;
    }

    // ── Depth Map (display last captured result) ──────────
    case Mode::DEPTH: {
        if (app.lastDepthMap.empty()) return {};
        cv::Mat vis;
        cv::normalize(app.lastDepthMap, vis, 0, 255, cv::NORM_MINMAX, CV_8U);
        cv::Mat color; cv::applyColorMap(vis, color, cv::COLORMAP_JET);
        // Overlay depth range annotation
        double minD, maxD;
        cv::minMaxLoc(app.lastDepthMap, &minD, &maxD);
        char ann[64];
        snprintf(ann, sizeof(ann), "%.1f - %.1f cm", (float)minD, (float)maxD);
        cv::putText(color, ann, {10, 30}, cv::FONT_HERSHEY_SIMPLEX, 0.8,
                    {255, 255, 255}, 2, cv::LINE_AA);
        return color;
    }

    // ── Bean Segmentation result ──────────────────────────
    case Mode::SEGMENT: {
        std::lock_guard<std::mutex> lk(app.segMutex);
        if (app.segOverlay.empty()) return {};
        return app.segOverlay.clone();
    }

    // ── Mold Detection result ─────────────────────────────
    case Mode::MOLD: {
        std::lock_guard<std::mutex> lk(app.moldMutex);
        if (app.moldOverlay.empty()) return {};
        return app.moldOverlay.clone();
    }

    // ── Spectral Curves visualization ─────────────────────
    case Mode::SPEC_VIZ: {
        std::lock_guard<std::mutex> lk(app.moldMutex);
        const auto& img = app.specVizImgs[app.specVizIdx];
        if (img.empty()) return {};
        return img.clone();
    }

    // ── Agtron Roast overlay ───────────────────────────────
    case Mode::AGTRON: {
        std::lock_guard<std::mutex> lk(app.moldMutex);
        if (app.agtronOverlay.empty()) return {};
        return app.agtronOverlay.clone();
    }

    // ── Agtron Histogram ──────────────────────────────────
    case Mode::AGTRON_HISTOGRAM: {
        std::lock_guard<std::mutex> lk(app.moldMutex);
        if (app.agtronHistogram.empty()) return {};
        return app.agtronHistogram.clone();
    }

    // ── Agtron Pie Chart ──────────────────────────────────
    case Mode::AGTRON_PIECHART: {
        std::lock_guard<std::mutex> lk(app.moldMutex);
        if (app.agtronPiechart.empty()) return {};
        return app.agtronPiechart.clone();
    }

    // ── Grind Size Map ────────────────────────────────────
    case Mode::GRIND: {
        std::lock_guard<std::mutex> lk(app.grindMutex);
        if (app.grindOverlay.empty()) return {};
        return app.grindOverlay.clone();
    }

    // ── Grind PSD Histogram ───────────────────────────────
    case Mode::GRIND_HISTOGRAM: {
        std::lock_guard<std::mutex> lk(app.grindMutex);
        if (app.grindHistogram.empty()) return {};
        return app.grindHistogram.clone();
    }

    // ── RAW YUYV debug: direct raw camera signal via uvc_fix intercept ──
    case Mode::RAW_YUYV: {
        // qs_raw_yuyv_get() provides the pre-SDK raw YUYV (1600×1200, 3840000 bytes)
        // intercepted from DQBUF before SDK processing. Y channel contains the
        // actual sensor mosaic signal (mean≈135 in a lit room).
        const int W = 1600, H = 1200;
        static std::vector<uint8_t> rawBuf(W * H * 2);
        init_raw_yuyv();
        if (!fn_raw_yuyv_get || !fn_raw_yuyv_get(rawBuf.data())) {
            // Fallback: not ready yet, show black with message
            cv::Mat black(H, W, CV_8UC3, cv::Scalar(0,0,0));
            cv::putText(black, "RAW: waiting for frame...", {10, 30},
                        cv::FONT_HERSHEY_SIMPLEX, 0.8, {0,255,255}, 2, cv::LINE_AA);
            return black;
        }
        // Extract Y channel (every even byte in YUYV = luminance = actual sensor data)
        // Apply 2×2 binning (INTER_AREA resize) to average out the spectral mosaic
        // fixed-pattern noise — adjacent pixels belong to different spectral filters
        // and have different sensitivities, creating a grid artifact at full res.
        const uint8_t* p = rawBuf.data();

        // Build 16-bit accumulator mat for binning (avoids overflow)
        cv::Mat Ymat16(H, W, CV_16UC1);
        for (int i = 0; i < W * H; i++)
            Ymat16.at<uint16_t>(i / W, i % W) = p[i * 2];

        // 2×2 binning → 800×600
        cv::Mat Ybin;
        cv::resize(Ymat16, Ybin, {W/2, H/2}, 0, 0, cv::INTER_AREA);

        // Also build false-colour from U/V channels (U at YUYV[1], V at YUYV[3])
        // U is at even macropixel offset 1, V at offset 3
        // Each macropixel = [Y0,U,Y1,V] covering 2 horizontal pixels.
        // For display: build a YUV image at half horizontal resolution then convert.
        const int HW = W / 2;  // 800 macropixels per row
        cv::Mat YUVhalf(H, HW, CV_8UC3);
        for (int row = 0; row < H; row++) {
            const uint8_t* src = p + row * W * 2;
            for (int col = 0; col < HW; col++) {
                // macropixel: src[col*4]   = Y0
                //              src[col*4+1] = U
                //              src[col*4+2] = Y1
                //              src[col*4+3] = V
                uint8_t y0 = src[col * 4];
                uint8_t y1 = src[col * 4 + 2];
                uint8_t u  = src[col * 4 + 1];
                uint8_t v  = src[col * 4 + 3];
                YUVhalf.at<cv::Vec3b>(row, col) = {(uint8_t)((y0+y1)/2), u, v};
            }
        }
        cv::Mat BGRhalf;
        cv::cvtColor(YUVhalf, BGRhalf, cv::COLOR_YUV2BGR);

        // Stats
        static int rawCnt = 0;
        if (++rawCnt <= 3 || rawCnt % 60 == 0) {
            double yMn, yMx;
            cv::minMaxLoc(Ybin, &yMn, &yMx);
            cv::Scalar yM = cv::mean(Ybin);
            std::cout << "[RAW_Y] binned min=" << yMn << " max=" << yMx
                      << " mean=" << yM[0] << "\n";
        }

        // Normalize binned Y to 8-bit for display
        cv::Mat Ynorm8;
        Ybin.convertTo(Ynorm8, CV_8UC1);  // already averaged, fits in 8-bit
        cv::normalize(Ynorm8, Ynorm8, 0, 255, cv::NORM_MINMAX, CV_8UC1);

        // Blend grayscale Y (binned) with colour (YUV false-colour) 50/50
        cv::Mat Ygray3;
        cv::cvtColor(Ynorm8, Ygray3, cv::COLOR_GRAY2BGR);
        // Resize colour to match binned size (already HW×H = 800×1200; need 800×600)
        cv::Mat BGRbin;
        cv::resize(BGRhalf, BGRbin, {W/2, H/2}, 0, 0, cv::INTER_AREA);
        cv::Mat result;
        cv::addWeighted(Ygray3, 0.7, BGRbin, 0.3, 0, result);

        double yMn, yMx;
        cv::minMaxLoc(Ynorm8, &yMn, &yMx);
        char ann[128];
        snprintf(ann, sizeof(ann), "RAW YUYV 2x2bin (800x600)  Y[%.0f..%.0f]  mean=%.1f",
                 yMn, yMx, cv::mean(Ynorm8)[0]);
        cv::putText(result, ann, {10, 30},
                    cv::FONT_HERSHEY_SIMPLEX, 0.65, {0,255,255}, 2, cv::LINE_AA);
        return result;
    }

    // ── RAW_RGB: splice raw YUYV into SDK header → qsToRgb ──────────────────
    // The SDK transforms the raw YUYV into its internal format (Y≈0, U≈64).
    // If the preprocessing is broken (firmware mismatch), qsToRgb sees garbage.
    // Here we bypass that: take the real raw YUYV (pre-SDK, mean Y≈135) from
    // uvc_fix, prepend the saved 323-byte SDK header, and pass to qsToRgb.
    // If the calibration file encodes raw→RGB directly, this will produce color.
    case Mode::RAW_RGB: {
        const int W = 1600, H = 1200;
        const size_t PIXEL_SZ = (size_t)W * H * 2;  // 3840000 bytes YUYV
        const size_t HDR_SZ   = 323;
        static std::vector<uint8_t> rawBuf(PIXEL_SZ);
        init_raw_yuyv();
        if (!fn_raw_yuyv_get || !fn_raw_yuyv_get(rawBuf.data())) {
            cv::Mat black(H, W, CV_8UC3, cv::Scalar(0,0,0));
            cv::putText(black, "RAW_RGB: waiting for raw frame...", {10,30},
                        cv::FONT_HERSHEY_SIMPLEX, 0.8, {0,255,255}, 2, cv::LINE_AA);
            return black;
        }
        if (app.sdkHeader.size() < HDR_SZ) {
            cv::Mat black(H, W, CV_8UC3, cv::Scalar(0,0,0));
            cv::putText(black, "RAW_RGB: waiting for SDK header...", {10,30},
                        cv::FONT_HERSHEY_SIMPLEX, 0.8, {0,255,255}, 2, cv::LINE_AA);
            return black;
        }
        // Construct synthetic frame: SDK header + raw YUYV pixel data
        std::vector<uint8_t> synth;
        synth.reserve(HDR_SZ + PIXEL_SZ);
        synth.insert(synth.end(), app.sdkHeader.begin(), app.sdkHeader.end());
        synth.insert(synth.end(), rawBuf.begin(), rawBuf.end());

        uint8_t* rgbData = nullptr;
        int w = 0, h = 0;
        QsErrorcodes err = qsToRgb(app.imgprocCtx, synth.data(), synth.size(), &rgbData, &w, &h);
        static int rawRgbDbg = 0;
        if (err != QS_ERR_SUCCESS || !rgbData) {
            std::cerr << "[RAW_RGB] qsToRgb err=" << qsErrorToString(err) << "\n";
            cv::Mat black(H, W, CV_8UC3, cv::Scalar(0,0,0));
            char msg[128];
            snprintf(msg, sizeof(msg), "RAW_RGB: qsToRgb failed (%s)", qsErrorToString(err));
            cv::putText(black, msg, {10,30}, cv::FONT_HERSHEY_SIMPLEX, 0.7, {0,0,255}, 2, cv::LINE_AA);
            return black;
        }
        cv::Mat mat(h, w, CV_8UC3, rgbData);
        cv::Mat result = mat.clone();
        freeQsData(rgbData);
        cv::cvtColor(result, result, cv::COLOR_RGB2BGR);
        if (++rawRgbDbg <= 3) {
            cv::Scalar m = cv::mean(result);
            double mn, mx;
            cv::minMaxLoc(result, &mn, &mx);
            std::cout << "[RAW_RGB] " << w << "x" << h
                      << " mean=(" << m[0] << "," << m[1] << "," << m[2] << ")"
                      << " min=" << mn << " max=" << mx << "\n";
        }
        char ann[64];
        snprintf(ann, sizeof(ann), "RAW_RGB (raw YUYV + SDK hdr)  %dx%d", w, h);
        cv::putText(result, ann, {10,30}, cv::FONT_HERSHEY_SIMPLEX, 0.65, {0,255,255}, 2, cv::LINE_AA);
        return result;
    }

    default:
        return {};
    }
}

// ─────────────────────────────────────────────────────────
// Sidebar UI
// ─────────────────────────────────────────────────────────

// Filled rounded rectangle (Apple-style button shape)
static void rrect(cv::Mat& img, cv::Rect r, cv::Scalar color, int radius = 7) {
    if (r.width <= 0 || r.height <= 0) return;
    radius = std::min(radius, std::min(r.width, r.height) / 2);
    if (radius <= 1) { cv::rectangle(img, r, color, -1); return; }
    cv::rectangle(img, {r.x + radius, r.y,          r.width - 2 * radius, r.height         }, color, -1);
    cv::rectangle(img, {r.x,          r.y + radius,  r.width,              r.height - 2*radius}, color, -1);
    auto corner = [&](int cx, int cy, double sa, double ea) {
        cv::ellipse(img, {cx, cy}, {radius, radius}, 0, sa, ea, color, -1, cv::LINE_AA);
    };
    corner(r.x + radius,           r.y + radius,            180, 270);
    corner(r.x + r.width - radius, r.y + radius,            270, 360);
    corner(r.x + radius,           r.y + r.height - radius,  90, 180);
    corner(r.x + r.width - radius, r.y + r.height - radius,   0,  90);
}

// ─────────────────────────────────────────────────────────
// Portrait UI helpers
// ─────────────────────────────────────────────────────────

struct GridBtn {
    const char* icon;
    const char* label;
    BtnTag      tag;
};

static const GridBtn GRID_BTNS[9] = {
    {"CAM", "CAPTURE",   BtnTag::FULL_ANALYSIS},
    {"AGT", "AGTRON",    BtnTag::AGTRON_RUN},
    {"SEG", "SEGMENT",   BtnTag::SEG_SEGMENT},
    {"MLD", "MOLD",      BtnTag::MOLD_DETECT},
    {"SPC", "SPECTRUM",  BtnTag::SPEC_CAPTURE},
    {"UV",  "UV SCAN",   BtnTag::UV_SCAN},
    {"ROI", "ROI",       BtnTag::AGTRON_ROI_SETUP},
    {"WHT", "WHITE REF", BtnTag::WHITE_CAPTURE},
    {"END", "QUIT",      BtnTag::QUIT},
};

static bool isBtnActive(BtnTag tag, const AppState& app) {
    switch (tag) {
    case BtnTag::FULL_ANALYSIS:    return app.fullAnalysisRunning.load();
    case BtnTag::AGTRON_RUN:       return app.agtronReady;
    case BtnTag::SEG_SEGMENT:      return app.mode == Mode::SEGMENT;
    case BtnTag::MOLD_DETECT:      return app.mode == Mode::MOLD;
    case BtnTag::SPEC_CAPTURE:     return app.specCaptured;
    case BtnTag::AGTRON_ROI_SETUP: return app.agtronRoiMode;
    case BtnTag::WHITE_CAPTURE:    return app.whiteRefCaptured;
    default:                       return false;
    }
}

static bool isLiveCamMode(Mode m) {
    switch (m) {
    case Mode::SEGMENT: case Mode::MOLD:    case Mode::SPEC_VIZ:
    case Mode::AGTRON:  case Mode::AGTRON_HISTOGRAM: case Mode::AGTRON_PIECHART:
    case Mode::GRIND:   case Mode::GRIND_HISTOGRAM:
        return false;
    default: return true;
    }
}

static cv::Mat drawPortraitUI(const cv::Mat& camImg, AppState& app) {
    // Palette (BGR order — hex values are RGB)
    const cv::Scalar BG_MAIN{26,  26,  26 };   // #1a1a1a
    const cv::Scalar BG_PREV{46,  30,  30 };   // #1e1e2e
    const cv::Scalar BG_BOT {24,  17,  17 };   // #111118
    const cv::Scalar BTN_OFF{60,  42,  42 };   // #2a2a3c
    const cv::Scalar BTN_ON {92,  58,  58 };   // #3a3a5c
    const cv::Scalar ACCENT {255, 122, 122};   // #7a7aff
    const cv::Scalar BDR_OFF{76,  58,  58 };   // #3a3a4c
    const cv::Scalar TXT1   {232, 232, 232};   // #e8e8e8
    const cv::Scalar TXT2   {154, 138, 138};   // #8a8a9a

    g_sidebarBtns.clear();
    cv::Mat canvas(DISP_H, DISP_W, CV_8UC3, BG_MAIN);

    // ── 1. Status bar (y: 0–32) ─────────────────────────────
    cv::putText(canvas, "LUX VISIONS", {8, 22},
                cv::FONT_HERSHEY_SIMPLEX, 0.45, TXT1, 1, cv::LINE_AA);
    {
        char expStr[24];
        snprintf(expStr, sizeof(expStr), "%dus", app.exposure);
        int base = 0;
        cv::Size ts = cv::getTextSize(expStr, cv::FONT_HERSHEY_SIMPLEX, 0.40, 1, &base);
        cv::putText(canvas, expStr, {DISP_W - ts.width - 8, 22},
                    cv::FONT_HERSHEY_SIMPLEX, 0.40, TXT2, 1, cv::LINE_AA);
    }

    // ── 2. Preview background (y: 32–320) ────────────────────
    cv::rectangle(canvas, cv::Rect{0, 32, DISP_W, 288}, BG_PREV, -1);
    if (!camImg.empty()) {
        const int PREV_SZ = 280;
        const int CX = 240, CY = 192;      // circle center in canvas coords
        const int PX = CX - PREV_SZ / 2;  // 100
        const int PY = CY - PREV_SZ / 2;  // 52

        cv::Mat scaled;
        if (isLiveCamMode(app.mode)) {
            // Square-crop center of camera frame, resize to 280×280
            int side = std::min(camImg.cols, camImg.rows);
            int sx   = (camImg.cols - side) / 2;
            int sy   = (camImg.rows - side) / 2;
            cv::Mat cropped = camImg(cv::Rect(sx, sy, side, side));
            cv::resize(cropped, scaled, cv::Size(PREV_SZ, PREV_SZ), 0, 0, cv::INTER_LINEAR);
        } else {
            // Letterbox analysis result to fit 280×280
            double sw = (double)PREV_SZ / camImg.cols;
            double sh = (double)PREV_SZ / camImg.rows;
            double s  = std::min(sw, sh);
            int nw = (int)(camImg.cols * s);
            int nh = (int)(camImg.rows * s);
            cv::Mat tmp;
            cv::resize(camImg, tmp, cv::Size(nw, nh), 0, 0, cv::INTER_AREA);
            scaled = cv::Mat(PREV_SZ, PREV_SZ, CV_8UC3, BG_PREV);
            tmp.copyTo(scaled(cv::Rect((PREV_SZ - nw) / 2, (PREV_SZ - nh) / 2, nw, nh)));
        }

        // Apply circular mask (radius = PREV_SZ/2 = 140)
        cv::Mat mask(PREV_SZ, PREV_SZ, CV_8UC1, cv::Scalar(0));
        cv::circle(mask, {PREV_SZ / 2, PREV_SZ / 2}, PREV_SZ / 2,
                   cv::Scalar(255), -1, cv::LINE_AA);
        cv::Mat bg(PREV_SZ, PREV_SZ, CV_8UC3, BG_PREV);
        scaled.copyTo(bg, mask);
        bg.copyTo(canvas(cv::Rect(PX, PY, PREV_SZ, PREV_SZ)));

        // Agtron ROI overlay (in preview space)
        if (app.agtronRoiMode || app.agtronRoiSaved) {
            double scx = (double)DISP_W / 1600.0;
            double scy = 288.0 / 1200.0;
            int pcx = (int)(app.agtronRoiCx * scx);
            int pcy = 32 + (int)(app.agtronRoiCy * scy);
            int prx = std::max(1, (int)(app.agtronRoiR * scx));
            int pry = std::max(1, (int)(app.agtronRoiR * scy));
            cv::Scalar col = app.agtronRoiMode
                           ? cv::Scalar(0, 165, 255) : cv::Scalar(0, 220, 60);
            int thick = app.agtronRoiMode ? 3 : 2;
            cv::ellipse(canvas, {pcx, pcy}, {prx, pry},
                        0, 0, 360, col, thick, cv::LINE_AA);
            if (app.agtronRoiMode) {
                cv::line(canvas, {pcx - 8, pcy}, {pcx + 8, pcy}, col, 1, cv::LINE_AA);
                cv::line(canvas, {pcx, pcy - 8}, {pcx, pcy + 8}, col, 1, cv::LINE_AA);
            }
        }
    }

    // ── 3. Label bar (y: 320–352) ────────────────────────────
    cv::rectangle(canvas, cv::Rect{0, 320, DISP_W, 32}, BG_MAIN, -1);
    {
        const char* mn = app.modeName();
        int base = 0;
        cv::Size ts = cv::getTextSize(mn, cv::FONT_HERSHEY_SIMPLEX, 0.42, 1, &base);
        cv::putText(canvas, mn, {(DISP_W - ts.width) / 2, 341},
                    cv::FONT_HERSHEY_SIMPLEX, 0.42, TXT1, 1, cv::LINE_AA);
        if (app.agtronMean >= 0) {
            char ag[12]; snprintf(ag, sizeof(ag), "%d", app.agtronMean);
            cv::Size as = cv::getTextSize(ag, cv::FONT_HERSHEY_SIMPLEX, 0.42, 1, &base);
            cv::putText(canvas, ag, {DISP_W - as.width - 8, 341},
                        cv::FONT_HERSHEY_SIMPLEX, 0.42, ACCENT, 1, cv::LINE_AA);
        }
        if (app.segBeanCount > 0) {
            char bc[20]; snprintf(bc, sizeof(bc), "%d beans", app.segBeanCount);
            cv::putText(canvas, bc, {8, 341},
                        cv::FONT_HERSHEY_SIMPLEX, 0.37, TXT2, 1, cv::LINE_AA);
        }
    }

    // ── 4. Button grid (y: 352–712) ──────────────────────────
    for (int r = 0; r < GRID_ROWS; r++) {
        for (int c = 0; c < GRID_COLS; c++) {
            const GridBtn& gb = GRID_BTNS[r * GRID_COLS + c];
            bool active = isBtnActive(gb.tag, app);
            int bx = c * CELL_W + 4;
            int by = DISP_PREV_H + r * CELL_H + 4;
            int bw = CELL_W - 8;
            int bh = CELL_H - 8;
            cv::Rect br{bx, by, bw, bh};
            rrect(canvas, br, active ? BTN_ON : BTN_OFF, 12);
            cv::rectangle(canvas, br, active ? ACCENT : BDR_OFF, 1, cv::LINE_AA);
            int base = 0;
            cv::Size is = cv::getTextSize(gb.icon, cv::FONT_HERSHEY_DUPLEX, 0.70, 1, &base);
            cv::putText(canvas, gb.icon, {bx + (bw - is.width) / 2, by + 55},
                        cv::FONT_HERSHEY_DUPLEX, 0.70,
                        active ? ACCENT : TXT1, 1, cv::LINE_AA);
            cv::Size ls = cv::getTextSize(gb.label, cv::FONT_HERSHEY_SIMPLEX, 0.33, 1, &base);
            cv::putText(canvas, gb.label, {bx + (bw - ls.width) / 2, by + 82},
                        cv::FONT_HERSHEY_SIMPLEX, 0.33,
                        active ? TXT1 : TXT2, 1, cv::LINE_AA);
            g_sidebarBtns.push_back({br, gb.tag});
        }
    }

    // ── 5. Bottom bar (y: 712–800) ───────────────────────────
    {
        const int BAR_Y = DISP_PREV_H + GRID_H;  // 712
        cv::rectangle(canvas, cv::Rect{0, BAR_Y, DISP_W, BOT_H}, BG_BOT, -1);

        cv::Rect em{8,  BAR_Y + 19, 80, 50};
        rrect(canvas, em, BTN_OFF, 8);
        cv::putText(canvas, "EXP-", {em.x + 10, em.y + 32},
                    cv::FONT_HERSHEY_SIMPLEX, 0.38, TXT1, 1, cv::LINE_AA);
        g_sidebarBtns.push_back({em, BtnTag::EXP_MINUS});

        cv::Rect ep{96, BAR_Y + 19, 80, 50};
        rrect(canvas, ep, BTN_OFF, 8);
        cv::putText(canvas, "EXP+", {ep.x + 10, ep.y + 32},
                    cv::FONT_HERSHEY_SIMPLEX, 0.38, TXT1, 1, cv::LINE_AA);
        g_sidebarBtns.push_back({ep, BtnTag::EXP_PLUS});

        // Status message (up to 2 lines of ~20 chars each)
        if (!app.statusMsg.empty()) {
            std::string s1 = app.statusMsg.substr(0, 20);
            std::string s2 = app.statusMsg.size() > 20
                           ? app.statusMsg.substr(20, 20) : "";
            cv::putText(canvas, s1, {186, BAR_Y + 30},
                        cv::FONT_HERSHEY_SIMPLEX, 0.30, TXT1, 1, cv::LINE_AA);
            if (!s2.empty())
                cv::putText(canvas, s2, {186, BAR_Y + 52},
                            cv::FONT_HERSHEY_SIMPLEX, 0.30, TXT2, 1, cv::LINE_AA);
        }

        // STOP button when any analysis is running
        bool busy = app.fullAnalysisRunning.load() || app.agtronRunning.load() ||
                    app.segRunning.load()           || app.moldRunning.load()   ||
                    app.specRunning.load();
        if (busy) {
            cv::Rect sb{388, BAR_Y + 19, 80, 50};
            rrect(canvas, sb, cv::Scalar(56, 68, 255), 8);  // RED
            cv::putText(canvas, "STOP", {sb.x + 14, sb.y + 32},
                        cv::FONT_HERSHEY_SIMPLEX, 0.40, TXT1, 1, cv::LINE_AA);
        }
    }

    return canvas;
}

static cv::Mat drawSidebar(int dispH, AppState& app) {
    const int height = SB_FULL_H;
    g_sidebarBtns.clear();

    // ── Apple Dark Mode Palette (BGR) ─────────────────────
    const cv::Scalar BG    = {26,  26,  26 };   // system background
    const cv::Scalar CARD  = {54,  52,  52 };   // inactive button
    const cv::Scalar BLUE  = {255, 132, 10 };   // #0A84FF  active / accent
    const cv::Scalar GREEN = {89,  199, 52 };   // #34C759  positive
    const cv::Scalar RED   = {56,  68,  255};   // #FF4438  danger
    const cv::Scalar TEAL  = {160, 140, 38 };   // depth accent
    const cv::Scalar WARN  = {10,  149, 255};   // #FF9500  orange warning
    const cv::Scalar TXT1  = {255, 255, 255};   // primary text
    const cv::Scalar TXT2  = {138, 138, 150};   // secondary label
    const cv::Scalar SEP   = {58,  56,  62 };   // separator line

    cv::Mat sb(height, SB_W, CV_8UC3, BG);

    const int BX  = 12;
    const int BW  = SB_W - BX * 2;   // 276 px
    const int BH  = 36;
    const int GAP = 4;
    int y = 10;

    // ── helpers ──────────────────────────────────────────
    auto section = [&](const char* title) {
        y += 10;
        cv::putText(sb, title, {BX, y + 11},
                    cv::FONT_HERSHEY_SIMPLEX, 0.34, TXT2, 1, cv::LINE_AA);
        y += 15;
    };

    auto btn = [&](const char* label, BtnTag tag, bool active,
                   cv::Scalar bgOvr = cv::Scalar(-1,-1,-1,-1)) {
        cv::Rect r{BX, y, BW, BH};
        cv::Scalar bg = (bgOvr[0] >= 0) ? bgOvr : (active ? BLUE : CARD);
        rrect(sb, r, bg);
        int base = 0;
        cv::Size ts = cv::getTextSize(label, cv::FONT_HERSHEY_SIMPLEX, 0.44, 1, &base);
        cv::putText(sb, label,
                    {r.x + (r.width - ts.width) / 2, r.y + (r.height + ts.height) / 2 - 1},
                    cv::FONT_HERSHEY_SIMPLEX, 0.44, TXT1, 1, cv::LINE_AA);
        g_sidebarBtns.push_back({r, tag});
        y += BH + GAP;
    };

    // Indeterminate progress button: bouncing segment + elapsed seconds.
    // Does not pretend to know total duration — just shows "working" honestly.
    auto progBtn = [&](const char* label, BtnTag tag, bool running,
                       std::chrono::steady_clock::time_point startTime,
                       cv::Scalar barColor, bool clickable = true) {
        using namespace std::chrono;
        cv::Rect r{BX, y, BW, BH};
        rrect(sb, r, cv::Scalar(32, 30, 30));
        if (running) {
            auto elapsed = duration_cast<milliseconds>(steady_clock::now() - startTime).count();
            // Bouncing segment: period 1.6s, segment width 28% of bar
            const float PERIOD = 1600.0f;
            const float SEG    = 0.28f;
            float phase = std::fmod((float)elapsed / PERIOD, 2.0f);  // 0→2 ping-pong
            float pos   = (phase < 1.0f) ? phase : (2.0f - phase);  // 0→1→0
            int fillX   = r.x + (int)((BW - (int)(BW * SEG)) * pos);
            int fillW   = (int)(BW * SEG);
            cv::Rect fill{fillX, r.y, fillW, r.height};
            rrect(sb, fill, barColor);
            // Elapsed seconds (right-aligned)
            char secBuf[16];
            snprintf(secBuf, sizeof(secBuf), "%llds", (long long)(elapsed / 1000));
            int base2 = 0;
            cv::Size st = cv::getTextSize(secBuf, cv::FONT_HERSHEY_SIMPLEX, 0.32, 1, &base2);
            cv::putText(sb, secBuf, {r.x + BW - st.width - 6, r.y + BH - 8},
                        cv::FONT_HERSHEY_SIMPLEX, 0.32, cv::Scalar(210, 210, 210), 1, cv::LINE_AA);
        }
        int base = 0;
        cv::Size ts = cv::getTextSize(label, cv::FONT_HERSHEY_SIMPLEX, 0.42, 1, &base);
        cv::putText(sb, label,
                    {r.x + (r.width - ts.width) / 2, r.y + (r.height + ts.height) / 2 - 1},
                    cv::FONT_HERSHEY_SIMPLEX, 0.42, TXT1, 1, cv::LINE_AA);
        if (clickable && !running) g_sidebarBtns.push_back({r, tag});
        y += BH + GAP;
    };

    // ── Logo ─────────────────────────────────────────────
    cv::circle(sb, {BX + 7, y + 19}, 6, BLUE, -1, cv::LINE_AA);
    cv::putText(sb, "LUX",     {BX + 18, y + 24},
                cv::FONT_HERSHEY_DUPLEX, 0.72, TXT1, 1, cv::LINE_AA);
    cv::putText(sb, "VISIONS", {BX + 64, y + 24},
                cv::FONT_HERSHEY_DUPLEX, 0.72, BLUE, 1, cv::LINE_AA);
    y += 34;
    cv::line(sb, {BX, y + 4}, {SB_W - BX, y + 4}, SEP, 1);
    y += 12;

    // ── VIEW ─────────────────────────────────────────────
    section("VIEW");
    btn("RGB",       BtnTag::RGB,  app.mode == Mode::RGB);
    btn("Grayscale", BtnTag::GRAY, app.mode == Mode::GRAY);

    // ── SPECTRAL ─────────────────────────────────────────
    section("SPECTRAL  350-950 nm");
    {
        bool specActive = (app.mode == Mode::SPEC_BAND);
        int idx = std::clamp(app.bandIndex, 0, (int)app.specBands.size() - 1);
        std::string bandLabel = app.specBands.empty() ? "N/A"
            : std::to_string(app.specBands[idx].first) + "-"
            + std::to_string(app.specBands[idx].second) + "nm  "
            + std::to_string(idx + 1) + "/" + std::to_string(app.specBands.size());
        const int AW = 38;
        cv::Scalar bbg = specActive ? BLUE : CARD;

        cv::Rect rP{BX, y, AW, BH};
        rrect(sb, rP, bbg);
        cv::putText(sb, "<", {rP.x + 10, rP.y + BH - 10},
                    cv::FONT_HERSHEY_SIMPLEX, 0.65, TXT1, 1, cv::LINE_AA);
        g_sidebarBtns.push_back({rP, BtnTag::SPEC_PREV});

        cv::Rect rL{BX + AW + 3, y, BW - AW * 2 - 6, BH};
        rrect(sb, rL, bbg);
        {
            int base = 0;
            cv::Size ts = cv::getTextSize(bandLabel.c_str(), cv::FONT_HERSHEY_SIMPLEX, 0.42, 1, &base);
            cv::putText(sb, bandLabel,
                        {rL.x + (rL.width - ts.width) / 2, rL.y + BH - 11},
                        cv::FONT_HERSHEY_SIMPLEX, 0.42, TXT1, 1, cv::LINE_AA);
        }
        g_sidebarBtns.push_back({rL, BtnTag::SPEC_NEXT});

        cv::Rect rN{BX + BW - AW, y, AW, BH};
        rrect(sb, rN, bbg);
        cv::putText(sb, ">", {rN.x + 10, rN.y + BH - 10},
                    cv::FONT_HERSHEY_SIMPLEX, 0.65, TXT1, 1, cv::LINE_AA);
        g_sidebarBtns.push_back({rN, BtnTag::SPEC_NEXT});
        y += BH + GAP;
    }

    // ── AGRICULTURE ──────────────────────────────────────
    section("AGRICULTURE");
    {
        const struct { BtnTag tag; const char* label; } agr[] = {
            {BtnTag::AGR0, "Blue   434-466 nm"},
            {BtnTag::AGR1, "Green  544-576 nm"},
            {BtnTag::AGR2, "Red    634-666 nm"},
            {BtnTag::AGR3, "RedEdge 714-746 nm"},
            {BtnTag::AGR4, "NIR    814-866 nm"},
        };
        for (int i = 0; i < 5; i++)
            btn(agr[i].label, agr[i].tag, app.mode == Mode::AGR_BAND && app.bandIndex == i);
    }

    // ── DEPTH ────────────────────────────────────────────
    section("DEPTH");
    {
        char calibInfo[64];
        snprintf(calibInfo, sizeof(calibInfo),
                 app.depthCalibK > 0 ? "k = %.2f  (calibrated)" : "Not calibrated",
                 app.depthCalibK);
        cv::putText(sb, calibInfo, {BX, y + 13},
                    cv::FONT_HERSHEY_SIMPLEX, 0.34,
                    app.depthCalibK > 0 ? GREEN : TXT2, 1, cv::LINE_AA);
        y += 18;

        const int CW = (BW - 2 * GAP) / 3;
        struct { BtnTag tag; const char* lbl; float dist; } cbtns[] = {
            {BtnTag::DEPTH_CALIB_10, "10 cm", 10.0f},
            {BtnTag::DEPTH_CALIB_15, "15 cm", 15.0f},
            {BtnTag::DEPTH_CALIB_20, "20 cm", 20.0f},
        };
        for (int i = 0; i < 3; i++) {
            cv::Rect r{BX + i * (CW + GAP), y, CW, BH};
            bool active = (app.depthCalibDist == cbtns[i].dist && app.depthCalibK > 0);
            rrect(sb, r, active ? TEAL : CARD);
            int base = 0;
            cv::Size ts = cv::getTextSize(cbtns[i].lbl, cv::FONT_HERSHEY_SIMPLEX, 0.40, 1, &base);
            cv::putText(sb, cbtns[i].lbl,
                        {r.x + (r.width - ts.width) / 2, r.y + BH - 10},
                        cv::FONT_HERSHEY_SIMPLEX, 0.40, TXT1, 1, cv::LINE_AA);
            g_sidebarBtns.push_back({r, cbtns[i].tag});
        }
        y += BH + GAP;
        btn("Depth Capture [Z]", BtnTag::DEPTH_CAPTURE, app.mode == Mode::DEPTH);
    }

    // ── ANALYSIS ─────────────────────────────────────────
    section("ANALYSIS");
    {
        // Model status line
        cv::putText(sb, app.segDaemonReady ? "Model: ready" : "Model: loading...",
                    {BX, y + 13}, cv::FONT_HERSHEY_SIMPLEX, 0.34,
                    app.segDaemonReady ? GREEN : WARN, 1, cv::LINE_AA);
        y += 18;

        bool running = app.fullAnalysisRunning.load();

        if (running) {
            // ── Running: progress button ───────────────────
            progBtn(app.fullAnalysisStage.c_str(), BtnTag::FULL_ANALYSIS,
                    true, app.fullAnalysisStart, cv::Scalar(92, 42, 10), false);

        } else if (g_analysisPrompt == 1) {
            // ── Asking: Complete or Quick? ─────────────────
            cv::putText(sb, "Select analysis mode:",
                        {BX, y + 13}, cv::FONT_HERSHEY_SIMPLEX, 0.36, TXT2, 1, cv::LINE_AA);
            y += 18;
            const int HW = (BW - GAP) / 2;
            cv::Rect rC{BX,          y, HW, BH};
            cv::Rect rQ{BX + HW + GAP, y, HW, BH};
            rrect(sb, rC, cv::Scalar(50, 100, 30));   // green tint = Complete
            rrect(sb, rQ, cv::Scalar(30, 60, 110));   // blue tint = Quick
            auto cLabel = [&](cv::Rect r, const char* t) {
                cv::Size ts = cv::getTextSize(t, cv::FONT_HERSHEY_SIMPLEX, 0.38, 1, nullptr);
                cv::putText(sb, t,
                            {r.x + (r.width - ts.width)/2, r.y + (r.height + ts.height)/2 - 1},
                            cv::FONT_HERSHEY_SIMPLEX, 0.38, TXT1, 1, cv::LINE_AA);
            };
            cLabel(rC, "Complete");
            cLabel(rQ, "Quick");
            g_sidebarBtns.push_back({rC, BtnTag::ANALYSIS_COMPLETE});
            g_sidebarBtns.push_back({rQ, BtnTag::ANALYSIS_QUICK});
            y += BH + GAP;
            // Subtitle
            cv::putText(sb, "Complete: with BG diff",
                        {BX, y + 11}, cv::FONT_HERSHEY_SIMPLEX, 0.30, TXT2, 1, cv::LINE_AA);
            cv::putText(sb, "Quick: skip BG, direct seg",
                        {BX + BW/2, y + 11}, cv::FONT_HERSHEY_SIMPLEX, 0.30, TXT2, 1, cv::LINE_AA);
            y += 14;
            btn("Cancel", BtnTag::ANALYSIS_CANCEL, false, cv::Scalar(50, 44, 44));

        } else if (g_analysisPrompt == 2) {
            // ── Complete mode: capture BG then run ────────
            cv::putText(sb, "Complete mode: capture background",
                        {BX, y + 11}, cv::FONT_HERSHEY_SIMPLEX, 0.30, TXT2, 1, cv::LINE_AA);
            y += 14;
            btn("Capture Background", BtnTag::SEG_CAPTURE_BG,
                app.segBgCaptured, app.segBgCaptured ? cv::Scalar(38, 78, 32) : CARD);
            {
                bool canStart = app.segBgCaptured;
                cv::Rect r{BX, y, BW, BH};
                rrect(sb, r, canStart ? cv::Scalar(92, 42, 10) : cv::Scalar(45, 40, 40));
                cv::Size ts = cv::getTextSize("Start Analysis", cv::FONT_HERSHEY_SIMPLEX, 0.44, 1, nullptr);
                cv::putText(sb, "Start Analysis",
                            {r.x + (r.width - ts.width)/2, r.y + (r.height + ts.height)/2 - 1},
                            cv::FONT_HERSHEY_SIMPLEX, 0.44,
                            canStart ? TXT1 : cv::Scalar(90, 85, 85), 1, cv::LINE_AA);
                if (canStart) g_sidebarBtns.push_back({r, BtnTag::ANALYSIS_DO_RUN});
                y += BH + GAP;
            }
            btn("Cancel", BtnTag::ANALYSIS_CANCEL, false, cv::Scalar(50, 44, 44));

        } else {
            // ── Normal state: Full Analysis button ────────
            if (!app.segDaemonReady) {
                cv::Rect r{BX, y, BW, BH};
                rrect(sb, r, cv::Scalar(42, 42, 42));
                cv::putText(sb, "Waiting for model...",
                            {BX + 8, y + BH - 11}, cv::FONT_HERSHEY_SIMPLEX, 0.38,
                            cv::Scalar(90, 85, 85), 1, cv::LINE_AA);
                y += BH + GAP;
            } else {
                const char* lbl = app.segBeanCount >= 0
                    ? "Re-run Full Analysis [T]" : "Full Analysis [T]";
                progBtn(lbl, BtnTag::FULL_ANALYSIS,
                        false, app.fullAnalysisStart,
                        cv::Scalar(92, 42, 10), true);
            }
        }

        // ── Result summary ─────────────────────────────────
        if (app.segBeanCount >= 0 || app.moldHighCount >= 0) {
            char buf[64]; int col = 0;
            if (app.segBeanCount >= 0)
                col += snprintf(buf + col, sizeof(buf) - col, "Beans:%d", app.segBeanCount);
            if (app.moldHighCount >= 0)
                col += snprintf(buf + col, sizeof(buf) - col,
                                "  H:%d M:%d", app.moldHighCount, app.moldMedCount);
            cv::Scalar sc = (app.moldHighCount > 0) ? RED
                          : (app.moldMedCount  > 0) ? WARN
                          : (app.moldHighCount == 0) ? GREEN : TEAL;
            cv::putText(sb, buf, {BX, y + 13},
                        cv::FONT_HERSHEY_SIMPLEX, 0.38, sc, 1, cv::LINE_AA);
            y += 18;
        }

        // ── Result view tabs ──────────────────────────────
        // Show after any analysis has produced results
        if (app.segBeanCount >= 0) {
            const int TW = (BW - GAP) / 2;
            const int TH = BH - 8;

            bool hasSeg  = !app.segOverlay.empty();
            bool hasMold = !app.moldOverlay.empty();
            bool hasSpec = app.specCaptured && !app.specVizImgs[0].empty();

            auto tabDraw = [&](cv::Rect r, const char* t, bool active, bool avail) {
                cv::Scalar bg = active ? BLUE : (avail ? CARD : cv::Scalar(38,38,40));
                rrect(sb, r, bg);
                cv::Size ts = cv::getTextSize(t, cv::FONT_HERSHEY_SIMPLEX, 0.33, 1, nullptr);
                cv::putText(sb, t,
                            {r.x + (r.width-ts.width)/2, r.y+(r.height+ts.height)/2-1},
                            cv::FONT_HERSHEY_SIMPLEX, 0.33,
                            active ? cv::Scalar(255,255,255) : (avail ? TXT2 : cv::Scalar(68,68,68)),
                            1, cv::LINE_AA);
            };

            // Row 1: Segment | Mold
            cv::Rect rSeg {BX,          y, TW, TH};
            cv::Rect rMold{BX + TW + GAP, y, TW, TH};
            tabDraw(rSeg,  "Segment", app.mode == Mode::SEGMENT, hasSeg);
            tabDraw(rMold, "Mold",    app.mode == Mode::MOLD,    hasMold);
            if (hasSeg)  g_sidebarBtns.push_back({rSeg,  BtnTag::SEG_VIEW});
            if (hasMold) g_sidebarBtns.push_back({rMold, BtnTag::MOLD_VIEW});
            y += TH + GAP;

            // Row 2: All Curves | Mean±σ  (only when spectral data ready)
            if (hasSpec) {
                cv::Rect rC{BX,          y, TW, TH};
                cv::Rect rM{BX + TW + GAP, y, TW, TH};
                bool s0 = (app.mode == Mode::SPEC_VIZ && app.specVizIdx == 0);
                bool s1 = (app.mode == Mode::SPEC_VIZ && app.specVizIdx == 1);
                tabDraw(rC, "All Curves", s0, true);
                tabDraw(rM, "Mean+/-s",   s1, true);
                g_sidebarBtns.push_back({rC, BtnTag::SPEC_VIZ_0});
                g_sidebarBtns.push_back({rM, BtnTag::SPEC_VIZ_1});
                y += TH + GAP;
            }
        }
    }

    // ── AGTRON ───────────────────────────────────────────
    section("AGTRON");
    {
        bool agtRunning = app.agtronRunning.load();
        bool whiteOk    = app.whiteRefCaptured;
        bool busy       = app.fullAnalysisRunning || agtRunning;

        if (!whiteOk) {
            // ── 未校準：只顯示 Capture White Ref ─────────────
            cv::putText(sb, "Calibrate white ref first",
                        {BX, y + 12}, cv::FONT_HERSHEY_SIMPLEX, 0.33, WARN, 1, cv::LINE_AA);
            y += 16;
            cv::Rect r{BX, y, BW, BH};
            rrect(sb, r, busy ? cv::Scalar(40,40,40) : CARD);
            cv::putText(sb, "Capture White Ref",
                        {BX + 8, y + BH/2 + 6}, cv::FONT_HERSHEY_SIMPLEX,
                        0.40, busy ? TXT2 : TXT1, 1, cv::LINE_AA);
            if (!busy) g_sidebarBtns.push_back({r, BtnTag::WHITE_CAPTURE});
            y += BH + GAP;
        } else {
            // ── 已校準：Run Agtron 為主按鈕 ──────────────────
            {
                bool hasData = (access((app.saveDir + "/spec_raw.csv").c_str(), F_OK) == 0);
                const char* lbl = agtRunning      ? "Running Agtron..."
                                : app.agtronReady ? "Re-run Agtron"
                                : hasData         ? "Run Agtron"
                                :                  "Capture & Run Agtron";
                progBtn(lbl, BtnTag::AGTRON_RUN,
                        agtRunning, app.agtronStart,
                        cv::Scalar(40, 60, 100), !agtRunning);
            }

            if (app.agtronMean >= 0) {
                char buf[64];
                snprintf(buf, sizeof(buf), "Mean Agtron: %d  %s",
                         app.agtronMean, roastLabel(app.agtronMean));
                cv::putText(sb, buf, {BX, y + 13},
                            cv::FONT_HERSHEY_SIMPLEX, 0.38, TEAL, 1, cv::LINE_AA);
                y += 18;
                if (app.agtronReady) {
                    // Three side-by-side buttons: "Overlay" | "Hist" | "Pie"
                    int w3 = (BW - 2*GAP) / 3;
                    {
                        cv::Rect r{BX, y, w3, BH - 6};
                        bool active = (app.mode == Mode::AGTRON);
                        rrect(sb, r, active ? BLUE : CARD);
                        cv::putText(sb, "Overlay",
                                    {BX + 2, y + (BH-6)/2 + 6}, cv::FONT_HERSHEY_SIMPLEX,
                                    0.30, active ? TXT1 : TXT2, 1, cv::LINE_AA);
                        g_sidebarBtns.push_back({r, BtnTag::AGTRON_VIZ});
                    }
                    {
                        cv::Rect r{BX + w3 + GAP, y, w3, BH - 6};
                        bool active = (app.mode == Mode::AGTRON_HISTOGRAM);
                        rrect(sb, r, active ? BLUE : CARD);
                        cv::putText(sb, "Hist",
                                    {BX + w3 + GAP + 4, y + (BH-6)/2 + 6}, cv::FONT_HERSHEY_SIMPLEX,
                                    0.38, active ? TXT1 : TXT2, 1, cv::LINE_AA);
                        g_sidebarBtns.push_back({r, BtnTag::AGTRON_HIST});
                    }
                    {
                        cv::Rect r{BX + 2*(w3 + GAP), y, w3, BH - 6};
                        bool active = (app.mode == Mode::AGTRON_PIECHART);
                        rrect(sb, r, active ? BLUE : CARD);
                        cv::putText(sb, "Pie",
                                    {BX + 2*(w3 + GAP) + 5, y + (BH-6)/2 + 6}, cv::FONT_HERSHEY_SIMPLEX,
                                    0.38, active ? TXT1 : TXT2, 1, cv::LINE_AA);
                        g_sidebarBtns.push_back({r, BtnTag::AGTRON_PIE});
                    }
                    y += (BH - 6) + GAP;
                }
            }

            // ── 小型次要按鈕：Re-calibrate ───────────────────
            {
                const char* wlbl = app.whiteRefGlobal ? "White ref: saved" : "White ref: ok";
                cv::putText(sb, wlbl, {BX, y + 11},
                            cv::FONT_HERSHEY_SIMPLEX, 0.30, GREEN, 1, cv::LINE_AA);
                y += 15;
                cv::Rect r{BX, y, BW, BH - 10};
                rrect(sb, r, busy ? cv::Scalar(40,40,40) : CARD);
                cv::putText(sb, "Re-calibrate White Ref",
                            {BX + 6, y + (BH-10)/2 + 5},
                            cv::FONT_HERSHEY_SIMPLEX, 0.30, busy ? TXT2 : TXT1, 1, cv::LINE_AA);
                if (!busy) g_sidebarBtns.push_back({r, BtnTag::WHITE_CAPTURE});
                y += (BH - 10) + GAP;
            }

            // ── ROI Setup ────────────────────────────────────
            if (g_app.agtronRoiMode) {
                int wh = (BW - GAP) / 2;
                {
                    cv::Rect r{BX, y, wh, BH - 6};
                    rrect(sb, r, CARD);
                    cv::putText(sb, "Larger", {BX + 6, y + (BH-6)/2 + 5},
                                cv::FONT_HERSHEY_SIMPLEX, 0.33, TXT1, 1, cv::LINE_AA);
                    g_sidebarBtns.push_back({r, BtnTag::AGTRON_ROI_LARGER});
                }
                {
                    cv::Rect r{BX + wh + GAP, y, wh, BH - 6};
                    rrect(sb, r, CARD);
                    cv::putText(sb, "Smaller", {BX + wh + GAP + 4, y + (BH-6)/2 + 5},
                                cv::FONT_HERSHEY_SIMPLEX, 0.33, TXT1, 1, cv::LINE_AA);
                    g_sidebarBtns.push_back({r, BtnTag::AGTRON_ROI_SMALLER});
                }
                y += (BH - 6) + GAP;
                {
                    cv::Rect r{BX, y, BW, BH - 6};
                    rrect(sb, r, cv::Scalar(40, 100, 30));
                    cv::putText(sb, "Save ROI Position", {BX + 6, y + (BH-6)/2 + 5},
                                cv::FONT_HERSHEY_SIMPLEX, 0.35, TXT1, 1, cv::LINE_AA);
                    g_sidebarBtns.push_back({r, BtnTag::AGTRON_ROI_SAVE});
                }
                y += (BH - 6) + GAP;
            } else {
                cv::Rect r{BX, y, BW, BH - 10};
                rrect(sb, r, g_app.agtronRoiSaved ? cv::Scalar(20, 50, 20) : CARD);
                const char* rlbl = g_app.agtronRoiSaved ? "Fixed ROI: ON (tap to edit)"
                                                         : "Set Fixed ROI";
                cv::Scalar rcol = g_app.agtronRoiSaved ? GREEN : TXT1;
                cv::putText(sb, rlbl, {BX + 4, y + (BH-10)/2 + 5},
                            cv::FONT_HERSHEY_SIMPLEX, 0.28, rcol, 1, cv::LINE_AA);
                g_sidebarBtns.push_back({r, BtnTag::AGTRON_ROI_SETUP});
                y += (BH - 10) + GAP;
            }
        }
    }

    // ── GRIND SIZE ────────────────────────────────────────
    section("GRIND SIZE");
    {
        bool grRunning = app.grindRunning.load();
        bool busy      = grRunning;

        const char* lbl = grRunning        ? "Analyzing..."
                        : app.grindReady   ? "Re-analyze Grind"
                        :                    "Analyze Grind";
        progBtn(lbl, BtnTag::GRIND_CAPTURE, grRunning, app.grindStart,
                cv::Scalar(50, 70, 40), !grRunning);

        if (app.grindD50 >= 0) {
            const char* unit = app.grindCalibrated ? "um" : "px";
            char buf[64];
            snprintf(buf, sizeof(buf), "D50: %.0f %s  (D10=%.0f D90=%.0f)",
                     app.grindD50, unit, app.grindD10, app.grindD90);
            cv::putText(sb, buf, {BX, y + 13},
                        cv::FONT_HERSHEY_SIMPLEX, 0.32, cv::Scalar(80, 220, 80),
                        1, cv::LINE_AA);
            y += 18;
            if (app.grindReady) {
                int hw = (BW - GAP) / 2;
                {
                    cv::Rect r{BX, y, hw, BH - 6};
                    bool active = (app.mode == Mode::GRIND);
                    rrect(sb, r, active ? BLUE : CARD);
                    cv::putText(sb, "Overlay",
                                {BX + 4, y + (BH - 6) / 2 + 6},
                                cv::FONT_HERSHEY_SIMPLEX, 0.38,
                                active ? TXT1 : TXT2, 1, cv::LINE_AA);
                    g_sidebarBtns.push_back({r, BtnTag::GRIND_VIZ});
                }
                {
                    cv::Rect r{BX + hw + GAP, y, hw, BH - 6};
                    bool active = (app.mode == Mode::GRIND_HISTOGRAM);
                    rrect(sb, r, active ? BLUE : CARD);
                    cv::putText(sb, "Hist",
                                {BX + hw + GAP + 4, y + (BH - 6) / 2 + 6},
                                cv::FONT_HERSHEY_SIMPLEX, 0.38,
                                active ? TXT1 : TXT2, 1, cv::LINE_AA);
                    g_sidebarBtns.push_back({r, BtnTag::GRIND_HIST});
                }
                y += (BH - 6) + GAP;
            }
        }
        (void)busy;
    }

    // ── CONTROLS ─────────────────────────────────────────
    section("CONTROLS");
    if (app.hasLamp) {
        std::string lbl = std::string("Lamp  ") + (app.lampOn ? "ON" : "OFF");
        btn(lbl.c_str(), BtnTag::LAMP, app.lampOn);
    }
    {
        bool ae = app.aeEnabled;
        cv::Rect r{BX, y, BW, BH};
        rrect(sb, r, ae ? cv::Scalar(35, 76, 28) : CARD);
        std::string lbl = ae ? "[x]  Auto Exposure" : "[ ]  Auto Exposure";
        int base = 0; cv::Size ts = cv::getTextSize(lbl, cv::FONT_HERSHEY_SIMPLEX, 0.44, 1, &base);
        cv::putText(sb, lbl, {r.x + (r.width - ts.width) / 2, r.y + BH - 11},
                    cv::FONT_HERSHEY_SIMPLEX, 0.44, TXT1, 1, cv::LINE_AA);
        g_sidebarBtns.push_back({r, BtnTag::AE_TOGGLE});
        y += BH + GAP;
    }
    auto ctrlRow = [&](const char* name, int val, int /*minV*/, int /*maxV*/,
                       BtnTag tagMinus, BtnTag tagPlus, bool enabled) {
        cv::Scalar lc  = enabled ? TXT1 : TXT2;
        cv::Scalar bbg = enabled ? CARD : cv::Scalar(38, 36, 36);
        cv::Scalar bfg = enabled ? TXT1 : TXT2;
        char valStr[48];
        snprintf(valStr, sizeof(valStr), "%s: %d", name, val);
        cv::putText(sb, valStr, {BX, y + 13},
                    cv::FONT_HERSHEY_SIMPLEX, 0.38, lc, 1, cv::LINE_AA);
        y += 17;
        int hw = (BW - GAP) / 2;
        cv::Rect rM{BX,           y, hw, BH};
        cv::Rect rP{BX + hw + GAP, y, hw, BH};
        for (auto& [r, tag, lbl] : std::initializer_list<std::tuple<cv::Rect, BtnTag, const char*>>{
                {rM, tagMinus, "-"}, {rP, tagPlus, "+"}}) {
            rrect(sb, r, bbg);
            int base = 0;
            cv::Size ts = cv::getTextSize(lbl, cv::FONT_HERSHEY_SIMPLEX, 0.72, 1, &base);
            cv::putText(sb, lbl, {r.x + (r.width - ts.width) / 2, r.y + BH - 8},
                        cv::FONT_HERSHEY_SIMPLEX, 0.72, bfg, 1, cv::LINE_AA);
            if (enabled) g_sidebarBtns.push_back({r, tag});
        }
        y += BH + GAP + 2;
    };
    ctrlRow("EXP (us)", app.exposure, app.exposureMin, 80000,
            BtnTag::EXP_MINUS, BtnTag::EXP_PLUS, !app.aeEnabled);
    ctrlRow("GAIN",     app.gain,     app.gainMin, app.gainMax,
            BtnTag::GAIN_MINUS, BtnTag::GAIN_PLUS, !app.aeEnabled);
    btn("Save Frame [S]", BtnTag::SAVE, false);

    // ── VEGETATION INDEX (collapsible, at bottom) ─────────
    {
        y += 6;
        // Header row: clickable toggle
        bool vegActive = (app.mode == Mode::NDVI || app.mode == Mode::GNDVI ||
                          app.mode == Mode::NDRE  || app.mode == Mode::OSAVI ||
                          app.mode == Mode::LCI);
        cv::Rect hdr{BX, y, BW, 26};
        rrect(sb, hdr, vegActive ? cv::Scalar(40, 55, 30) : cv::Scalar(40, 40, 44), 5);
        // Arrow indicator
        const char* arrow = g_vegExpanded ? " v" : " >";
        cv::putText(sb, arrow, {BX + 4, y + 18},
                    cv::FONT_HERSHEY_SIMPLEX, 0.38, TXT2, 1, cv::LINE_AA);
        cv::putText(sb, "VEGETATION INDEX",
                    {BX + 20, y + 18},
                    cv::FONT_HERSHEY_SIMPLEX, 0.34, vegActive ? GREEN : TXT2, 1, cv::LINE_AA);
        if (vegActive) {
            // Show active mode name on right
            const char* activeStr = modeToString(app.mode);
            cv::Size ts = cv::getTextSize(activeStr, cv::FONT_HERSHEY_SIMPLEX, 0.32, 1, nullptr);
            cv::putText(sb, activeStr,
                        {hdr.x + hdr.width - ts.width - 6, y + 18},
                        cv::FONT_HERSHEY_SIMPLEX, 0.32, GREEN, 1, cv::LINE_AA);
        }
        g_sidebarBtns.push_back({hdr, BtnTag::VEG_TOGGLE});
        y += 26 + GAP;

        if (g_vegExpanded) {
            btn("NDVI",  BtnTag::NDVI,  app.mode == Mode::NDVI);
            btn("GNDVI", BtnTag::GNDVI, app.mode == Mode::GNDVI);
            btn("NDRE",  BtnTag::NDRE,  app.mode == Mode::NDRE);
            btn("OSAVI", BtnTag::OSAVI, app.mode == Mode::OSAVI);
            btn("LCI",   BtnTag::LCI,   app.mode == Mode::LCI);
        }
    }

    // ── QUIT (in scrollable content, at very bottom) ──────
    {
        y += 6;
        cv::Rect qr{BX, y, BW, BH};
        rrect(sb, qr, RED);
        int base = 0;
        cv::Size ts = cv::getTextSize("QUIT", cv::FONT_HERSHEY_SIMPLEX, 0.44, 1, &base);
        cv::putText(sb, "QUIT",
                    {qr.x + (qr.width - ts.width) / 2, qr.y + (qr.height + ts.height) / 2 - 1},
                    cv::FONT_HERSHEY_SIMPLEX, 0.44, {255, 255, 255}, 1, cv::LINE_AA);
        g_sidebarBtns.push_back({qr, BtnTag::QUIT});
        y += BH + GAP;
    }

    // ── Status at bottom of full mat ─────────────────────
    {
        if (!app.statusMsg.empty())
            cv::putText(sb, app.statusMsg, {BX, height - 52},
                        cv::FONT_HERSHEY_SIMPLEX, 0.33, TEAL, 1, cv::LINE_AA);
        char fStr[32];
        snprintf(fStr, sizeof(fStr), "Frame: %d", app.frameCount);
        cv::putText(sb, fStr, {BX, height - 14},
                    cv::FONT_HERSHEY_SIMPLEX, 0.33, TXT2, 1, cv::LINE_AA);
    }

    // ── Scroll: crop to visible area ─────────────────────
    int maxScroll = std::max(0, height - dispH);
    g_sbScrollY   = std::clamp(g_sbScrollY, 0, maxScroll);
    for (auto& b : g_sidebarBtns) b.rect.y -= g_sbScrollY;
    g_sidebarBtns.erase(
        std::remove_if(g_sidebarBtns.begin(), g_sidebarBtns.end(),
            [&](const SidebarBtn& b) {
                return b.rect.y + b.rect.height <= 0 || b.rect.y >= dispH;
            }),
        g_sidebarBtns.end());

    // Scroll indicator (right edge, 3 px)
    if (maxScroll > 0) {
        int barH = std::max(20, dispH * dispH / height);
        int barY = (dispH - barH) * g_sbScrollY / maxScroll;
        cv::rectangle(sb, {SB_W - 4, g_sbScrollY,        3, dispH}, {38, 36, 38}, -1);
        cv::rectangle(sb, {SB_W - 4, g_sbScrollY + barY, 3, barH }, {90, 88, 100}, -1);
    }

    cv::Mat visible = sb.rowRange(g_sbScrollY, g_sbScrollY + dispH).clone();
    return visible;
}

// ─────────────────────────────────────────────────────────
// Valid Exposure Values (manufacturer-specified, Linux FW)
// 40000 = LED off, 80000 = LED on (magic values for LED cameras)
// Values below 10000 trigger sub-frame mode → avoid for normal use
// ─────────────────────────────────────────────────────────

static const int VALID_EXP[] = {
    0, 1, 2, 5, 10, 20, 39, 78, 156, 312, 625,
    1250, 2500, 5000, 10000, 20000, 40000, 80000
};
static const int VALID_EXP_N = (int)(sizeof(VALID_EXP) / sizeof(VALID_EXP[0]));
static const int EXP_NORMAL_MAX = 20000;  // AE upper bound (excludes LED magic values)

// Snap value to nearest valid exposure
static int snapExp(int v) {
    int best = VALID_EXP[0], bestDiff = std::abs(v - VALID_EXP[0]);
    for (int i = 1; i < VALID_EXP_N; i++) {
        int d = std::abs(v - VALID_EXP[i]);
        if (d < bestDiff) { bestDiff = d; best = VALID_EXP[i]; }
    }
    return best;
}
// Next valid exposure >= min, clamped to max
static int expNext(int v, int minVal, int maxVal) {
    for (int i = 0; i < VALID_EXP_N; i++)
        if (VALID_EXP[i] > v && VALID_EXP[i] >= minVal && VALID_EXP[i] <= maxVal)
            return VALID_EXP[i];
    return std::min(v, maxVal);
}
// Prev valid exposure <= max, clamped to min
static int expPrev(int v, int minVal, int maxVal) {
    for (int i = VALID_EXP_N - 1; i >= 0; i--)
        if (VALID_EXP[i] < v && VALID_EXP[i] >= minVal && VALID_EXP[i] <= maxVal)
            return VALID_EXP[i];
    return std::max(v, minVal);
}

// ─────────────────────────────────────────────────────────
// Mouse Callback
// ─────────────────────────────────────────────────────────

static void fireSidebarClick(int x, int y);  // forward decl

static void onMouse(int event, int x, int y, int flags, void* /*userdata*/) {
    // Portrait layout: preview y<352, grid y 352–712, bottom bar y>=712
    // Mouse wheel: discard — no scroll panels in portrait mode
    if (event == cv::EVENT_MOUSEWHEEL)
        return;

    if (event == cv::EVENT_LBUTTONDOWN) {
        if (y < DISP_PREV_H && g_app.agtronRoiMode) {
            g_app.agtronRoiDragging = true;
            g_app.agtronRoiCx = std::clamp((int)(x * 1600.0 / DISP_W),        0, 1600);
            g_app.agtronRoiCy = std::clamp((int)((y - 32) * 1200.0 / 288.0),  0, 1200);
            return;
        }
        g_touchStartY  = y;
        g_touchDragged = false;
        return;
    }

    if (event == cv::EVENT_MOUSEMOVE && (flags & cv::EVENT_FLAG_LBUTTON)) {
        if (g_app.agtronRoiDragging) {
            g_app.agtronRoiCx = std::clamp((int)(x * 1600.0 / DISP_W),        0, 1600);
            g_app.agtronRoiCy = std::clamp((int)((y - 32) * 1200.0 / 288.0),  0, 1200);
            return;
        }
        if (g_touchStartY >= 0 && std::abs(y - g_touchStartY) >= DRAG_THRESHOLD)
            g_touchDragged = true;
        return;
    }

    if (event == cv::EVENT_LBUTTONUP) {
        if (g_app.agtronRoiDragging) {
            g_app.agtronRoiDragging = false;
            return;
        }
        bool wasDrag = g_touchDragged;
        g_touchStartY  = -1;
        g_touchDragged = false;
        if (!wasDrag)
            fireSidebarClick(x, y);
        return;
    }
}

static void fireSidebarClick(int x, int y) {
    for (auto& b : g_sidebarBtns) {
        if (!b.rect.contains({x, y})) continue;

        auto setMode = [](Mode m) {
            if (m == Mode::SPEC_BAND && !g_app.specinvReady) {
                g_app.statusMsg = "Spectral inversion not available";
                return;
            }
            if ((m == Mode::AGR_BAND || m == Mode::NDVI || m == Mode::GNDVI ||
                 m == Mode::NDRE    || m == Mode::OSAVI || m == Mode::LCI) && !g_app.agriReady) {
                g_app.statusMsg = "Agriculture module not available";
                return;
            }
            g_app.mode = m;
        };

        switch (b.tag) {
        case BtnTag::RGB:      setMode(Mode::RGB);      break;
        case BtnTag::GRAY:     setMode(Mode::GRAY);     break;
        case BtnTag::SPEC_PREV:
            setMode(Mode::SPEC_BAND);
            if (!g_app.specBands.empty())
                g_app.bandIndex = ((int)g_app.bandIndex - 1 + (int)g_app.specBands.size())
                                  % (int)g_app.specBands.size();
            break;
        case BtnTag::SPEC_NEXT:
            setMode(Mode::SPEC_BAND);
            if (!g_app.specBands.empty())
                g_app.bandIndex = (g_app.bandIndex + 1) % (int)g_app.specBands.size();
            break;
        case BtnTag::AGR0: setMode(Mode::AGR_BAND); g_app.bandIndex = 0; break;
        case BtnTag::AGR1: setMode(Mode::AGR_BAND); g_app.bandIndex = 1; break;
        case BtnTag::AGR2: setMode(Mode::AGR_BAND); g_app.bandIndex = 2; break;
        case BtnTag::AGR3: setMode(Mode::AGR_BAND); g_app.bandIndex = 3; break;
        case BtnTag::AGR4: setMode(Mode::AGR_BAND); g_app.bandIndex = 4; break;
        case BtnTag::NDVI:  setMode(Mode::NDVI);  break;
        case BtnTag::GNDVI: setMode(Mode::GNDVI); break;
        case BtnTag::NDRE:  setMode(Mode::NDRE);  break;
        case BtnTag::OSAVI: setMode(Mode::OSAVI); break;
        case BtnTag::LCI:   setMode(Mode::LCI);   break;
        case BtnTag::LAMP:
            if (g_app.hasLamp) {
                g_app.lampOn = !g_app.lampOn;
                controlQsCamera(g_app.camera, QS_CAMERA_SET_LAMP, &g_app.lampOn);
            }
            break;
        case BtnTag::AE_TOGGLE: {
            g_app.aeEnabled = !g_app.aeEnabled;
            // Software AE: analysis loop runs in main display loop.
            // No V4L2 auto_exposure ioctl — mixing V4L2 camera controls with
            // SDK streaming causes double-free crashes in the SDK thread.
            break;
        }
        case BtnTag::EXP_PLUS: {
            g_app.exposure = expNext(g_app.exposure, 1, EXP_NORMAL_MAX);
            g_app.exposurePending = true;
            g_app.exposureChanged = std::chrono::steady_clock::now();
            break;
        }
        case BtnTag::EXP_MINUS: {
            g_app.exposure = expPrev(g_app.exposure, 1, EXP_NORMAL_MAX);
            g_app.exposurePending = true;
            g_app.exposureChanged = std::chrono::steady_clock::now();
            break;
        }
        case BtnTag::GAIN_PLUS: {
            g_app.gain = std::min(g_app.gain + 1, g_app.gainMax);
            g_app.gainPending = true;
            g_app.gainChanged = std::chrono::steady_clock::now();
            break;
        }
        case BtnTag::GAIN_MINUS: {
            g_app.gain = std::max(g_app.gain - 1, g_app.gainMin);
            g_app.gainPending = true;
            g_app.gainChanged = std::chrono::steady_clock::now();
            break;
        }
        case BtnTag::SAVE:
            g_app.saveRequested = true;
            break;
        case BtnTag::DEPTH_CALIB_10:
            g_app.depthCalibDist = 10.0f;
            runDepthCalibration(g_app, 10.0f);
            break;
        case BtnTag::DEPTH_CALIB_15:
            g_app.depthCalibDist = 15.0f;
            runDepthCalibration(g_app, 15.0f);
            break;
        case BtnTag::DEPTH_CALIB_20:
            g_app.depthCalibDist = 20.0f;
            runDepthCalibration(g_app, 20.0f);
            break;
        case BtnTag::DEPTH_CAPTURE:
            g_app.depthCapturePending = true;
            break;
        case BtnTag::SEG_CAPTURE_BG: {
            cv::Mat f = captureOneGray(g_app);
            if (!f.empty()) {
                f.convertTo(g_app.segBg, CV_8U);
                g_app.segBgCaptured = true;
                cv::imwrite(g_app.saveDir + "/background_1250us.png", g_app.segBg);
                g_app.statusMsg = "Background captured & saved";
            } else {
                g_app.statusMsg = "Background capture failed";
            }
            break;
        }
        case BtnTag::WHITE_CAPTURE:
            if (!g_app.fullAnalysisRunning)
                g_app.whiteRefCaptured = false,  // will re-run
                g_app.statusMsg = "Capturing white reference...",
                std::thread([&](){
                    int oldExp = g_app.exposure;
                    // Auto-exposure: 5000us preferred (SDK non-linearity: 5000us gives
                    // NIR≈0.529 matching Difluid 65; 2500us and lower give ~47% less).
                    // Linux SDK only supports: 312/625/1250/2500/5000/10000 us.
                    // Fall back to lower exposures only if paper saturates.
                    static const int TRY_EXPS[] = {5000, 2500, 1250};
                    int actualExp = 2500;
                    cv::Mat f32;
                    for (int exp : TRY_EXPS) {
                        actualExp = exp;
                        controlQsCamera(g_app.camera, QS_CAMERA_SET_EXPOSURE, &exp);
                        std::this_thread::sleep_for(std::chrono::milliseconds(400));
                        f32 = captureOneGray(g_app, 3000);
                        if (f32.empty()) break;
                        // Check saturation in the white-ref ROI (centre 300×300)
                        cv::Mat roi = f32(cv::Rect(650, 450, 300, 300));
                        double roiMean = cv::mean(roi)[0];
                        std::cout << "[white] exp=" << exp << "us  ROI mean=" << roiMean << "\n";
                        if (roiMean <= 248.0) break;  // accept up to 97% of max
                        g_app.statusMsg = "Saturated at " + std::to_string(exp)
                                        + "us, trying " + std::to_string(exp * 3/4) + "us...";
                    }
                    std::string qsPath = g_app.saveDir + "/white_ref_"
                                       + std::to_string(actualExp) + "us.qs";
                    bool saved = false;
                    if (!f32.empty()) {
                        std::lock_guard<std::mutex> lk(g_app.frameMutex);
                        if (!g_app.latestFrame.empty()) {
                            saveQsFile(qsPath.c_str(), g_app.latestFrame.data(), g_app.latestFrame.size());
                            saved = true;
                        }
                    }
                    controlQsCamera(g_app.camera, QS_CAMERA_SET_EXPOSURE, &oldExp);
                    if (!saved) { g_app.statusMsg = "White ref capture failed"; return; }
                    // Create white-ref ROI json: use fixed agtron ROI if saved, else center 300x300
                    std::string wRois = g_app.saveDir + "/white_rois.json";
                    {
                        std::ofstream ofs(wRois);
                        if (g_app.agtronRoiSaved) {
                            int wx0 = std::max(0, g_app.agtronRoiCx - g_app.agtronRoiR);
                            int wy0 = std::max(0, g_app.agtronRoiCy - g_app.agtronRoiR);
                            int wx1 = std::min(1599, g_app.agtronRoiCx + g_app.agtronRoiR);
                            int wy1 = std::min(1199, g_app.agtronRoiCy + g_app.agtronRoiR);
                            ofs << "[{\"id\":1,\"x0\":" << wx0 << ",\"y0\":" << wy0
                                << ",\"x1\":" << wx1 << ",\"y1\":" << wy1 << "}]\n";
                        } else {
                            ofs << "[{\"id\":1,\"x0\":650,\"y0\":450,\"x1\":950,\"y1\":750}]\n";
                        }
                    }
                    // Run spec_fingerprint → white_spec.csv (no labelmap: use all pixels in box)
                    std::string sfBin = "/home/kyle/KyleClaude/multispectral_demo/build/spec_fingerprint";
                    std::string wCsv  = g_app.saveDir + "/white_spec.csv";
                    std::string cmd   = sfBin + " \"" + g_app.qsbsPath + "\" \""
                        + g_app.qsdbPath + "\" \"" + qsPath + "\" \""
                        + wRois + "\" \"" + wCsv + "\" --agtron-only 2>&1";
                    FILE* pp = popen(cmd.c_str(), "r");
                    if (pp) { char buf[256]; while(fgets(buf, sizeof(buf), pp)) std::cout << buf; pclose(pp); }
                    // No cross-exposure scaling: SDK qsToQsi is non-linear, any linear
                    // correction is incorrect. Bean spec is captured at same exposure
                    // (whiteRefExp), so flat-field ratio is always same-exposure.
                    g_app.whiteRefCaptured = (access(wCsv.c_str(), F_OK) == 0);
                    g_app.whiteRefGlobal   = false;  // just captured fresh
                    g_app.whiteRefExp      = actualExp;
                    if (g_app.whiteRefCaptured) {
                        std::string cpCmd = std::string("cp \"") + wCsv
                            + "\" /home/kyle/KyleClaude/white_spec.csv";
                        system(cpCmd.c_str());
                        // Update cal_white_850/930 in agtron_calibration.json with fresh values
                        double cw850 = -1.0, cw930 = -1.0;
                        {
                            std::ifstream wf(wCsv);
                            std::string hdr, ln;
                            std::getline(wf, hdr);
                            while (std::getline(wf, ln)) {
                                auto c = ln.find(',');
                                if (c == std::string::npos) continue;
                                int wl = std::stoi(ln.substr(0, c));
                                double v = std::stod(ln.substr(c + 1));
                                if (wl == 850) cw850 = v;
                                if (wl == 930) cw930 = v;
                            }
                        }
                        if (cw850 > 0.0 && cw930 > 0.0) {
                            static const char* CAL_JSON = "/home/kyle/KyleClaude/agtron_calibration.json";
                            std::string js;
                            if (FILE* cf = fopen(CAL_JSON, "r"); cf) {
                                char buf[4096];
                                while (fgets(buf, sizeof(buf), cf)) js += buf;
                                fclose(cf);
                            }
                            auto replaceVal = [&](const char* key, double val) {
                                auto p = js.find(key);
                                if (p == std::string::npos) return;
                                p = js.find(':', p) + 1;
                                while (p < js.size() && (js[p]==' '||js[p]=='\t')) p++;
                                auto e = p;
                                while (e < js.size() && (std::isdigit(js[e])||js[e]=='.'||js[e]=='-')) e++;
                                char nb[32]; snprintf(nb, sizeof(nb), "%.4f", val);
                                js.replace(p, e - p, nb);
                            };
                            replaceVal("\"cal_white_850\"", cw850);
                            replaceVal("\"cal_white_930\"", cw930);
                            if (FILE* cf = fopen(CAL_JSON, "w"); cf) {
                                fputs(js.c_str(), cf);
                                fclose(cf);
                                std::cout << "[white] cal_white updated: 850=" << cw850
                                          << " 930=" << cw930 << "\n";
                            }
                        }
                        // Persist exposure so next session can restore whiteRefExp
                        std::ofstream expF("/home/kyle/KyleClaude/white_ref_exp.txt");
                        expF << actualExp << "\n";
                        // Save gray PNG from white paper capture → update global cylinder mask
                        // White paper inside cylinder gives bright circle vs dark exterior:
                        // Otsu threshold cleanly finds the valid FOV circle.
                        if (!f32.empty()) {
                            cv::Mat gray8;
                            f32.convertTo(gray8, CV_8U);
                            std::string cylImg = "/home/kyle/KyleClaude/cylinder_white_ref.png";
                            cv::imwrite(cylImg, gray8);
                            std::string cylCmd = "python3 /home/kyle/KyleClaude/update_cylinder_mask.py \""
                                               + cylImg + "\" 2>&1";
                            FILE* cylP = popen(cylCmd.c_str(), "r");
                            if (cylP) {
                                char buf[256];
                                while (fgets(buf, sizeof(buf), cylP)) std::cout << buf;
                                pclose(cylP);
                            }
                            // Also copy updated mask into this session so it's self-contained
                            static const char* GCYL = "/home/kyle/KyleClaude/cylinder_mask.json";
                            if (access(GCYL, F_OK) == 0) {
                                std::string dst = g_app.saveDir + "/cylinder_mask.json";
                                system((std::string("cp \"") + GCYL + "\" \"" + dst + "\"").c_str());
                            }
                        }
                    }
                    std::string expStr = std::to_string(actualExp) + "us";
                    g_app.statusMsg = g_app.whiteRefCaptured
                        ? "White ref saved @ " + expStr + " (global + session)"
                        : "White ref: spec_fingerprint failed";
                }).detach();
            break;
        case BtnTag::FULL_ANALYSIS:
            if (!g_app.fullAnalysisRunning && g_app.segDaemonReady) {
                g_analysisModeQuick = true;
                g_app.fullAnalysisPending = true;
            }
            break;
        case BtnTag::ANALYSIS_COMPLETE:
            if (g_app.segBgCaptured) {
                g_analysisPrompt = 0;
                g_analysisModeQuick = false;
                g_app.fullAnalysisPending = true;
            } else {
                g_analysisPrompt = 2;  // capture BG first
            }
            break;
        case BtnTag::ANALYSIS_QUICK:
            g_analysisPrompt = 0;
            g_analysisModeQuick = true;
            g_app.fullAnalysisPending = true;
            break;
        case BtnTag::ANALYSIS_CANCEL:
            g_analysisPrompt = 0;
            break;
        case BtnTag::ANALYSIS_DO_RUN:
            if (g_app.segBgCaptured) {
                g_analysisPrompt = 0;
                g_analysisModeQuick = false;
                g_app.fullAnalysisPending = true;
            }
            break;
        case BtnTag::AGTRON_RUN:
            if (!g_app.agtronRunning)
                g_app.agtronPending = true;
            break;
        case BtnTag::AGTRON_VIZ:
            g_app.mode = Mode::AGTRON;
            break;
        case BtnTag::AGTRON_HIST:
            g_app.mode = Mode::AGTRON_HISTOGRAM;
            break;
        case BtnTag::AGTRON_PIE:
            g_app.mode = Mode::AGTRON_PIECHART;
            break;
        case BtnTag::AGTRON_ROI_SETUP:
            g_app.agtronRoiMode = !g_app.agtronRoiMode;
            break;
        case BtnTag::AGTRON_ROI_LARGER:
            g_app.agtronRoiR = std::min(g_app.agtronRoiR + 20, 800);
            break;
        case BtnTag::AGTRON_ROI_SMALLER:
            g_app.agtronRoiR = std::max(g_app.agtronRoiR - 20, 20);
            break;
        case BtnTag::AGTRON_ROI_SAVE: {
            g_app.agtronRoiSaved = true;
            g_app.agtronRoiMode  = false;
            FILE* jf = fopen("/home/kyle/KyleClaude/agtron_roi.json", "w");
            if (jf) {
                fprintf(jf, "{\"cx\":%d,\"cy\":%d,\"r\":%d,\"image_w\":1600,\"image_h\":1200}\n",
                        g_app.agtronRoiCx, g_app.agtronRoiCy, g_app.agtronRoiR);
                fclose(jf);
                g_app.statusMsg = "Agtron ROI saved";
            }
            break;
        }
        case BtnTag::GRIND_CAPTURE:
            if (!g_app.grindRunning)
                g_app.grindPending = true;
            break;
        case BtnTag::GRIND_VIZ:
            g_app.mode = Mode::GRIND;
            break;
        case BtnTag::GRIND_HIST:
            g_app.mode = Mode::GRIND_HISTOGRAM;
            break;
        case BtnTag::UV_SCAN:
            g_app.statusMsg = "UV: run uv_mold_scan.py in terminal";
            break;
        // Legacy keyboard-only buttons (kept for T/U/M shortcuts)
        case BtnTag::SEG_SEGMENT:
            if (!g_app.fullAnalysisRunning && !g_app.segRunning && g_app.segDaemonReady)
                g_app.fullAnalysisPending = true;
            break;
        case BtnTag::SPEC_CAPTURE:
            if (!g_app.specRunning && !g_app.moldRunning)
                g_app.specCapturePending = true;
            break;
        case BtnTag::MOLD_DETECT:
            if (g_app.specCaptured && g_app.segBeanCount > 0 && !g_app.moldRunning && !g_app.specRunning)
                g_app.moldPending = true;
            break;
        case BtnTag::SEG_VIEW:
            g_app.mode = Mode::SEGMENT;
            break;
        case BtnTag::MOLD_VIEW:
            if (!g_app.moldOverlay.empty())
                g_app.mode = Mode::MOLD;
            break;
        case BtnTag::SPEC_VIZ_0:
            g_app.specVizIdx = 0;
            g_app.mode = Mode::SPEC_VIZ;
            break;
        case BtnTag::SPEC_VIZ_1:
            g_app.specVizIdx = 1;
            g_app.mode = Mode::SPEC_VIZ;
            break;
        case BtnTag::QUIT:
            g_app.running = false;
            break;
        default: break;
        }
        break;
    }
}

// ─────────────────────────────────────────────────────────
// Keyboard Handler
// ─────────────────────────────────────────────────────────

void handleKey(int key, AppState& app, const std::vector<uint8_t>& currentFrame, const cv::Mat& display) {
    app.statusMsg.clear();

    auto setMode = [&](Mode m) {
        if (m == Mode::SPEC_BAND && !app.specinvReady) {
            app.statusMsg = "Spectral inversion not available (check qsdb path)";
            return;
        }
        if ((m == Mode::AGR_BAND || m == Mode::NDVI || m == Mode::GNDVI ||
             m == Mode::NDRE || m == Mode::OSAVI || m == Mode::LCI) && !app.agriReady) {
            app.statusMsg = "Agriculture module not available";
            return;
        }
        app.mode = m;
        app.bandIndex = 0;
    };

    switch (key) {
    case 'q': case 'Q': case 27:
        app.running = false;
        break;

    case 'r': case 'R': setMode(Mode::RGB);       break;
    case 'g': case 'G': setMode(Mode::GRAY);      break;
    case 'b': case 'B': setMode(Mode::SPEC_BAND); break;
    case 'a': case 'A': setMode(Mode::AGR_BAND);  break;
    case 'n': case 'N': setMode(Mode::NDVI);      break;
    case 'd': case 'D': setMode(Mode::GNDVI);     break;
    case 'e': case 'E': setMode(Mode::NDRE);      break;
    case 'o': case 'O': setMode(Mode::OSAVI);     break;
    case 'c': case 'C': setMode(Mode::LCI);       break;

    case '<': case ',': {
        if (app.mode == Mode::SPEC_BAND && !app.specBands.empty()) {
            app.bandIndex = (app.bandIndex - 1 + app.specBands.size()) % app.specBands.size();
        } else if (app.mode == Mode::AGR_BAND) {
            app.bandIndex = (app.bandIndex - 1 + 5) % 5;
        }
        break;
    }
    case '>': case '.': {
        if (app.mode == Mode::SPEC_BAND && !app.specBands.empty()) {
            app.bandIndex = (app.bandIndex + 1) % app.specBands.size();
        } else if (app.mode == Mode::AGR_BAND) {
            app.bandIndex = (app.bandIndex + 1) % 5;
        }
        break;
    }

    case '+': case '=': {
        app.exposure = expNext(app.exposure, 1, EXP_NORMAL_MAX);
        app.exposurePending = true;
        app.exposureChanged = std::chrono::steady_clock::now();
        break;
    }
    case '-': {
        app.exposure = expPrev(app.exposure, 1, EXP_NORMAL_MAX);
        app.exposurePending = true;
        app.exposureChanged = std::chrono::steady_clock::now();
        break;
    }

    case 'l': case 'L': {
        if (app.hasLamp) {
            app.lampOn = !app.lampOn;
            controlQsCamera(app.camera, QS_CAMERA_SET_LAMP, &app.lampOn);
            app.statusMsg = std::string("Lamp: ") + (app.lampOn ? "ON" : "OFF");
        } else {
            app.statusMsg = "This camera has no lamp";
        }
        break;
    }

    case 's': case 'S':
        app.saveRequested = true;
        break;

    case 't': case 'T':
        if (!app.fullAnalysisRunning && app.segDaemonReady)
            g_analysisPrompt = 1;
        else if (!app.segDaemonReady)
            app.statusMsg = "Model still loading...";
        break;

    case 'z': case 'Z':
        if (!app.hasLamp) {
            app.statusMsg = "No lamp detected";
        } else {
            app.statusMsg = "Depth capture in progress...";
            app.depthCapturePending = true;
        }
        break;

    case 'u': case 'U':
        if (!app.specRunning && !app.moldRunning) {
            app.specCapturePending = true;
            app.statusMsg = "Capturing spectrum (2500us)...";
        }
        break;

    case 'm': case 'M':
        if (app.specCaptured && app.segBeanCount > 0 && !app.moldRunning && !app.specRunning) {
            app.moldPending = true;
            app.statusMsg = "Mold analysis starting...";
        } else if (!app.specCaptured) {
            app.statusMsg = "Capture spectrum first (U)";
        } else if (app.segBeanCount <= 0) {
            app.statusMsg = "Run segmentation first (T)";
        }
        break;

    case 'v': case 'V':
        app.mode = Mode::RAW_YUYV;
        app.statusMsg = "RAW YUYV debug (2x2 binned, Y+colour blend)";
        break;

    case 'x': case 'X':
        app.mode = Mode::RAW_RGB;
        app.statusMsg = "RAW RGB: raw YUYV + SDK header → qsToRgb";
        break;

    default:
        break;
    }
}

// ─────────────────────────────────────────────────────────
// Background Processing Thread
// ─────────────────────────────────────────────────────────
// Runs processFrame independently so the display thread is never blocked.
// Always processes the LATEST available raw frame (stale frames are dropped).

static void procThreadFn() {
    while (g_app.running) {
        // Pause while depth capture is in progress
        if (g_app.blockProc) {
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
            continue;
        }

        std::vector<uint8_t> frame;
        {
            std::unique_lock<std::mutex> lock(g_app.frameMutex);
            g_app.frameCV.wait_for(lock, std::chrono::milliseconds(100),
                [&]{ return (g_app.newFrame && !g_app.blockProc) || !g_app.running; });
            if (!g_app.running) break;
            if (!g_app.newFrame || g_app.blockProc) continue;
            frame = g_app.latestFrame;   // grab latest, drop anything older
            g_app.newFrame = false;
        }

        cv::Mat result = processFrame(g_app, frame);
        if (result.empty()) {
            static int emptyCount = 0;
            if (++emptyCount <= 5)
                std::cout << "[PROC] processFrame returned empty (frame size="
                          << frame.size() << ")\n";
            continue;
        }

        // Ensure BGR for display
        if (result.channels() == 1)
            cv::cvtColor(result, result, cv::COLOR_GRAY2BGR);

        std::lock_guard<std::mutex> lock(g_app.resultMutex);
        g_app.latestResult = std::move(result);
        g_app.hasResult = true;
    }
}

// ─────────────────────────────────────────────────────────
// X11 override_redirect — removes title bar without compositor fullscreen
// ─────────────────────────────────────────────────────────

// Recursively search X11 window tree for a window with the given title.
static Window x11FindByTitle(Display* dpy, Window parent, const char* title) {
    char* name = nullptr;
    if (XFetchName(dpy, parent, &name) && name) {
        bool match = (strcmp(name, title) == 0);
        XFree(name);
        if (match) return parent;
    }
    Window root_ret, parent_ret;
    Window* children = nullptr;
    unsigned int n = 0;
    if (!XQueryTree(dpy, parent, &root_ret, &parent_ret, &children, &n))
        return 0;
    Window found = 0;
    for (unsigned i = 0; i < n && !found; i++)
        found = x11FindByTitle(dpy, children[i], title);
    if (children) XFree(children);
    return found;
}

// Set override_redirect on our OpenCV window: tells the window manager to
// leave it alone (no title bar, no borders). Unmap+remap is needed for the
// attribute to take effect on an already-mapped window.
// Called in a detached thread right after namedWindow().
static void applyOverrideRedirect(const std::string& title, int x, int y, int w, int h) {
    using namespace std::chrono_literals;
    std::this_thread::sleep_for(500ms);   // wait for Qt to map the window

    Display* dpy = XOpenDisplay(nullptr);
    if (!dpy) {
        std::cerr << "[X11] Cannot open display\n";
        return;
    }

    Window win = x11FindByTitle(dpy, DefaultRootWindow(dpy), title.c_str());
    if (!win) {
        std::cerr << "[X11] Window '" << title << "' not found\n";
        XCloseDisplay(dpy);
        return;
    }

    XSetWindowAttributes attr{};
    attr.override_redirect = True;
    XChangeWindowAttributes(dpy, win, CWOverrideRedirect, &attr);

    // Remap for override_redirect to apply; reposition to exact DSI coords
    XUnmapWindow(dpy, win);
    XMoveResizeWindow(dpy, win, x, y, w, h);
    XMapRaised(dpy, win);
    XFlush(dpy);
    XCloseDisplay(dpy);

    std::cout << "[X11] override_redirect set on '" << title
              << "' at (" << x << "," << y << ") " << w << "x" << h << "\n";
}

// ─────────────────────────────────────────────────────────
// Main
// ─────────────────────────────────────────────────────────

// Detect the primary QS Camera V4L2 device path (Video Capture node)
static std::string findQsCameraDevice() {
    for (int n = 0; n < 64; n++) {
        char path[32];
        snprintf(path, sizeof(path), "/dev/video%d", n);
        int fd = ::open(path, O_RDWR | O_NONBLOCK);
        if (fd < 0) continue;
        struct v4l2_capability cap{};
        bool match = false;
        if (::ioctl(fd, VIDIOC_QUERYCAP, &cap) == 0 &&
            (cap.device_caps & V4L2_CAP_VIDEO_CAPTURE) &&
            (strstr((char*)cap.card, "QS Camera") ||
             strstr((char*)cap.card, "Webcam gadget")))
            match = true;
        ::close(fd);
        if (match) return path;
    }
    return "/dev/video0"; // fallback
}
static std::string g_camera_dev;

// Signal handler: graceful shutdown on SIGTERM / SIGINT
static void onSignal(int) { g_app.running = false; }

// Emergency camera release: called by atexit() so the camera is always
// closed even if the process crashes or is killed without cleanup.
static void emergencyRelease() {
    if (g_app.camera) {
        closeQsCamera(g_app.camera);
        g_app.camera = nullptr;
    }
    if (g_app.cameras) {
        releaseQsCamera(g_app.cameras, g_app.cameraCount);
        g_app.cameras = nullptr;
    }
}

int main(int argc, char* argv[]) {
    signal(SIGTERM, onSignal);
    signal(SIGINT,  onSignal);
    atexit(emergencyRelease);  // last-resort cleanup on any exit path
    // Make stdout line-buffered so messages appear even when piped
    setvbuf(stdout, nullptr, _IOLBF, 0);
    std::string qsbsPath;
    std::string qsdbPath;

    if (argc >= 2) {
        qsbsPath = argv[1];
    } else {
        // Default search locations on the USB disk
        for (const auto& c : {
            "/media/kyle/Kyle/camera_new.qsbs",
            "/media/kyle/Kyle/4065-77.qsbs"
        }) {
            if (FILE* f = fopen(c, "rb"); f) {
                fclose(f);
                qsbsPath = c;
                break;
            }
        }
    }

    if (argc >= 3) {
        qsdbPath = argv[2];
    } else {
        qsdbPath = "/media/kyle/Kyle/db_std.qsdb";
    }

    if (qsbsPath.empty()) {
        std::cerr << "Error: No .qsbs calibration file found.\n";
        std::cerr << "Usage: " << argv[0] << " <calibration.qsbs> [db.qsdb]\n";
        return 1;
    }

    g_app.qsbsPath = qsbsPath;
    g_app.qsdbPath = qsdbPath;

    std::cout << "=== Multispectral Camera Demo ===\n";
    std::cout << "Calibration : " << qsbsPath << "\n";
    std::cout << "DB          : " << qsdbPath << "\n\n";

    // ── Load calibration file ─────────────────────────────
    QsErrorcodes err = loadQsbsFile(qsbsPath.c_str(), &g_app.qsbsData, &g_app.qsbsSize);
    if (err != QS_ERR_SUCCESS) {
        std::cerr << "[FAIL] loadQsbsFile: " << qsErrorToString(err) << "\n";
        return 1;
    }
    std::cout << "[OK] Calibration loaded (" << g_app.qsbsSize << " bytes)\n";

    // ── Init image processor ──────────────────────────────
    err = initQsImgproc(&g_app.imgprocCtx, g_app.qsbsData, g_app.qsbsSize);
    if (err != QS_ERR_SUCCESS) {
        std::cerr << "[FAIL] initQsImgproc: " << qsErrorToString(err) << "\n";
        return 1;
    }
    std::cout << "[OK] Image processor ready\n";

    // ── Init spectral inversion ───────────────────────────
    char** lightSrcList = nullptr;
    size_t lightSrcCount = 0;
    err = initQsSpecinv(&g_app.specinvCtx,
                        g_app.qsbsData, g_app.qsbsSize,
                        qsdbPath.c_str(),
                        &g_app.specBegin, &g_app.specEnd,
                        &lightSrcList, &lightSrcCount);
    if (err != QS_ERR_SUCCESS) {
        std::cerr << "[WARN] initQsSpecinv: " << qsErrorToString(err)
                  << " — Spectral Band mode disabled\n";
    } else {
        g_app.specinvReady = true;
        std::cout << "[OK] Spectral inversion ready ("
                  << g_app.specBegin << "-" << g_app.specEnd << "nm)\n";
        std::cout << "     Light sources (" << lightSrcCount << "): ";
        for (size_t i = 0; i < lightSrcCount; ++i)
            std::cout << lightSrcList[i] << " ";
        std::cout << "\n";
        generateSpecBands(g_app);
    }

    // ── Init agriculture module ───────────────────────────
    err = initQsAgriculture(&g_app.agriCtx, g_app.qsbsData, g_app.qsbsSize);
    if (err != QS_ERR_SUCCESS) {
        std::cerr << "[WARN] initQsAgriculture: " << qsErrorToString(err)
                  << " — Agriculture modes disabled\n";
    } else {
        g_app.agriReady = true;
        std::cout << "[OK] Agriculture module ready (NDVI/GNDVI/NDRE/OSAVI/LCI)\n";
    }

    // ── Enumerate cameras ─────────────────────────────────
    err = enumQsCamera(&g_app.cameras, &g_app.cameraCount);
    if (err != QS_ERR_SUCCESS || g_app.cameraCount == 0) {
        std::cerr << "[FAIL] No cameras: " << qsErrorToString(err) << "\n";
        return 1;
    }
    std::cout << "[OK] Found " << g_app.cameraCount << " camera(s)\n";
    g_app.camera = g_app.cameras[0];
    g_camera_dev = findQsCameraDevice();
    std::cout << "[OK] Camera device: " << g_camera_dev << "\n";

    // Camera info
    const char* camName = nullptr;
    controlQsCamera(g_app.camera, QS_CAMERA_GET_NAME, (void*)&camName);
    if (camName) std::cout << "     Name: " << camName << "\n";

    bool hasLamp = false;
    controlQsCamera(g_app.camera, QS_CAMERA_HAS_LAMP, &hasLamp);
    g_app.hasLamp = hasLamp;
    if (hasLamp) std::cout << "     Has lamp: yes\n";

    controlQsCamera(g_app.camera, QS_CAMERA_GET_EXPOSURE_MIN, &g_app.exposureMin);
    g_app.exposureMin = std::max(g_app.exposureMin, 7000);  // CM020D: below ~6000us triggers sub-frame mode → black image
    controlQsCamera(g_app.camera, QS_CAMERA_GET_EXPOSURE_MAX, &g_app.exposureMax);
    controlQsCamera(g_app.camera, QS_CAMERA_GET_EXPOSURE,     &g_app.exposure);
    std::cout << "     Exposure: " << g_app.exposure << " us"
              << " [" << g_app.exposureMin << "-" << g_app.exposureMax << "]\n";
    // Read current gain via V4L2
    {
        int fd = ::open(g_camera_dev.c_str(), O_RDWR);
        if (fd >= 0) {
            struct v4l2_queryctrl qc{};
            qc.id = V4L2_CID_GAIN;
            if (::ioctl(fd, VIDIOC_QUERYCTRL, &qc) == 0) {
                g_app.gainMin = qc.minimum;
                g_app.gainMax = qc.maximum;
            }
            struct v4l2_control c{};
            c.id = V4L2_CID_GAIN;
            if (::ioctl(fd, VIDIOC_G_CTRL, &c) == 0)
                g_app.gain = std::max(c.value, g_app.gainMin);
            ::close(fd);
        }
    }
    std::cout << "     Gain: " << g_app.gain
              << " [" << g_app.gainMin << "-" << g_app.gainMax << "]\n";
    // If SDK reports exposure=0 (auto), read the real value from V4L2
    // so our +/- buttons start from the actual current brightness level.
    if (g_app.exposure == 0) {
        int fd = ::open(g_camera_dev.c_str(), O_RDWR);
        if (fd >= 0) {
            struct v4l2_control c{};
            c.id = V4L2_CID_EXPOSURE_ABSOLUTE;
            if (::ioctl(fd, VIDIOC_G_CTRL, &c) == 0 && c.value > 0)
                g_app.exposure = c.value;
            ::close(fd);
        }
        std::cout << "     Exposure (V4L2 actual): " << g_app.exposure << " us\n";
    }
    // Clamp startup exposure to safe range and force-write to camera.
    // This ensures the camera exits sub-frame mode (triggered if a previous
    // session left exposure < ~6000us) before we start streaming.
    g_app.exposure = snapExp(std::max(std::min(g_app.exposure, 20000), 10000));  // snap to valid value, well above sub-frame threshold (~6000us)
    controlQsCamera(g_app.camera, QS_CAMERA_SET_EXPOSURE, &g_app.exposure);
    // Also reset gain to 1 so a previous session's high-gain state doesn't
    // fool the AE into thinking the scene is darker than it is.
    g_app.gain = 1;
    {
        int fd = ::open(g_camera_dev.c_str(), O_RDWR);
        if (fd >= 0) {
            struct v4l2_control c{}; c.id = V4L2_CID_GAIN; c.value = g_app.gain;
            ::ioctl(fd, VIDIOC_S_CTRL, &c);
            ::close(fd);
        }
    }
    std::cout << "     Startup: exposure clamped to " << g_app.exposure
              << " us, gain reset to 1\n";

    // ── Reset video device (SDK leaves stream running after enumQsCamera) ──
    {
        int fd = ::open(g_camera_dev.c_str(), O_RDWR);
        if (fd >= 0) {
            int type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
            ::ioctl(fd, VIDIOC_STREAMOFF, &type);
            v4l2_requestbuffers rb{};
            rb.type   = V4L2_BUF_TYPE_VIDEO_CAPTURE;
            rb.memory = V4L2_MEMORY_MMAP;
            rb.count  = 0;
            ::ioctl(fd, VIDIOC_REQBUFS, &rb);
            ::close(fd);
        }
    }

    // ── Register callback BEFORE open (openQsCamera async checks camera[8] != NULL) ──
    err = registerQsCameraCallback(g_app.camera, onCameraFrame, &g_app);
    if (err != QS_ERR_SUCCESS) {
        std::cerr << "[FAIL] registerQsCameraCallback: " << qsErrorToString(err) << "\n";
        return 1;
    }
    std::cout << "[OK] Callback registered\n";

    // ── Open camera in async mode ──────────────────────────
    err = openQsCamera(g_app.camera, true /*async*/);
    if (err != QS_ERR_SUCCESS) {
        std::cerr << "[FAIL] openQsCamera: " << qsErrorToString(err) << "\n";
        return 1;
    }
    std::cout << "[OK] Camera opened (async mode)\n\n";

    // ── 建立桌面時間戳資料夾（本 session 所有 S 鍵存檔都放這裡）──
    {
        auto now = std::chrono::system_clock::now();
        std::time_t t = std::chrono::system_clock::to_time_t(now);
        std::tm* tm = std::localtime(&t);
        std::ostringstream oss;
        mkdir("/home/kyle/Desktop/Report", 0755);  // ensure parent exists
        oss << "/home/kyle/Desktop/Report/LuxVisions_"
            << std::put_time(tm, "%Y%m%d_%H%M%S");
        g_app.saveDir = oss.str();
        mkdir(g_app.saveDir.c_str(), 0755);
        std::cout << "[OK] Save folder: " << g_app.saveDir << "\n\n";
    }

    // ── Load global white reference if available ──────────
    {
        static const char* GLOBAL_WHITE = "/home/kyle/KyleClaude/white_spec.csv";
        if (access(GLOBAL_WHITE, F_OK) == 0) {
            std::string dst = g_app.saveDir + "/white_spec.csv";
            std::string cmd = std::string("cp \"") + GLOBAL_WHITE + "\" \"" + dst + "\"";
            system(cmd.c_str());
            g_app.whiteRefCaptured = true;
            g_app.whiteRefGlobal   = true;
            std::ifstream expF("/home/kyle/KyleClaude/white_ref_exp.txt");
            if (expF) { int e = 0; expF >> e; if (e > 0) g_app.whiteRefExp = e; }
            std::cout << "[OK] Global white_spec.csv loaded into session"
                      << (g_app.whiteRefExp > 0 ? " (exp=" + std::to_string(g_app.whiteRefExp) + "us)" : "") << "\n";
            // Copy cylinder mask snapshot so each session is self-contained.
            // agtron_analysis.py will prefer the session-local copy over global.
            static const char* GLOBAL_CYL = "/home/kyle/KyleClaude/cylinder_mask.json";
            if (access(GLOBAL_CYL, F_OK) == 0) {
                std::string cylDst = g_app.saveDir + "/cylinder_mask.json";
                system((std::string("cp \"") + GLOBAL_CYL + "\" \"" + cylDst + "\"").c_str());
                std::cout << "[OK] cylinder_mask.json snapshot copied into session\n";
            }
        }
    }

    // ── Start seg daemon (pre-loads FastSAM model) ────────
    if (!startSegDaemon(g_app))
        std::cerr << "[WARN] Seg daemon start failed; will use direct Python\n";
    else
        std::cout << "[OK] Seg daemon starting (FastSAM model load ~8s in background)\n";

    // ── Load depth calibration if available ──────────────
    if (FILE* cf = fopen("depth_calib.txt", "r"); cf) {
        float k = 0.0f;
        if (fscanf(cf, "k=%f", &k) == 1 && k > 0.0f) {
            g_app.depthCalibK = k;
            std::cout << "[OK] Depth calibration loaded: k=" << k << "\n";
        }
        fclose(cf);
    }

    // ── Load Agtron fixed ROI if available ───────────────
    {
        static const char* AROI_JSON = "/home/kyle/KyleClaude/agtron_roi.json";
        FILE* rf = fopen(AROI_JSON, "r");
        if (rf) {
            char buf[512]; std::string s;
            while (fgets(buf, sizeof(buf), rf)) s += buf;
            fclose(rf);
            auto getInt = [&](const char* key, int def) -> int {
                auto p = s.find(key);
                if (p == std::string::npos) return def;
                p = s.find(':', p) + 1;
                while (p < s.size() && (s[p]==' '||s[p]=='\t')) p++;
                try { return std::stoi(s.substr(p)); } catch (...) { return def; }
            };
            g_app.agtronRoiCx    = getInt("\"cx\"", 800);
            g_app.agtronRoiCy    = getInt("\"cy\"", 600);
            g_app.agtronRoiR     = getInt("\"r\"",  200);
            g_app.agtronRoiSaved = true;
            std::cout << "[OK] agtron_roi.json loaded: cx=" << g_app.agtronRoiCx
                      << " cy=" << g_app.agtronRoiCy << " r=" << g_app.agtronRoiR << "\n";
        }
    }

    std::cout << "Keys: [R]GB [G]ray [B]and [A]gr [N]DVI [D]GNDVI [E]NDRE [O]SAVI [C]LCI\n";
    std::cout << "      < / >  band cycle   + / -  exposure   [L]amp   [S]ave   [Z]depth  [V]raw  [X]rawRGB  [Q]uit\n\n";

    // ── OpenCV window ─────────────────────────────────────
    const std::string WIN = "Giga-Image";
    cv::namedWindow(WIN, cv::WINDOW_NORMAL | cv::WINDOW_GUI_NORMAL);
    cv::moveWindow(WIN, 0, 0);               // 7" DSI display at (0,0)
    cv::resizeWindow(WIN, DISP_W, DISP_H);  // exact 800×480, 1:1 with composite

    // Apply override_redirect in background: removes title bar without
    // triggering Wayland compositor fullscreen/direct-scanout mode switch
    // (which would cause HDMI to flicker and need replug to recover).
    std::thread(applyOverrideRedirect, WIN, 0, 0, DISP_W, DISP_H).detach();

    // Show placeholder immediately
    {
        cv::Mat ph(DISP_H, DISP_W, CV_8UC3, cv::Scalar(28, 28, 28));
        cv::putText(ph, "LUX VISIONS",
                    cv::Point((DISP_W - 140) / 2, DISP_H / 2 - 10),
                    cv::FONT_HERSHEY_DUPLEX, 1.0,
                    cv::Scalar(60, 220, 100), 2, cv::LINE_AA);
        cv::putText(ph, "Waiting for camera...",
                    cv::Point((DISP_W - 200) / 2, DISP_H / 2 + 30),
                    cv::FONT_HERSHEY_SIMPLEX, 0.50,
                    cv::Scalar(160, 160, 160), 1, cv::LINE_AA);
        g_previewW = 0;
        cv::imshow(WIN, ph);
        cv::waitKey(1);  // pump Qt events once so window is actually mapped
    }

    cv::setMouseCallback(WIN, onMouse, nullptr);

    // ── Start background processing thread ────────────────
    std::thread procThread(procThreadFn);

    // Switch to 2500us for preview (startup was clamped to ≥10000 to exit sub-frame mode)
    {
        int exp = 2500;
        controlQsCamera(g_app.camera, QS_CAMERA_SET_EXPOSURE, &exp);
        g_app.exposure = 2500;
    }

    cv::Mat displayImg;   // latest BGR frame ready to show

    while (g_app.running) {
        // Detect window X button
        if (cv::getWindowProperty(WIN, cv::WND_PROP_VISIBLE) < 1.0) {
            g_app.running = false;
            break;
        }

        // Pull latest processed result (non-blocking)
        // Skip during settle period after exposure change (avoids flicker)
        // In DEPTH/SEGMENT/MOLD mode, keep showing the last captured result
        if (g_app.mode == Mode::SEGMENT) {
            std::lock_guard<std::mutex> lk(g_app.segMutex);
            if (!g_app.segOverlay.empty())
                displayImg = g_app.segOverlay;
        } else if (g_app.mode == Mode::MOLD) {
            std::lock_guard<std::mutex> lk(g_app.moldMutex);
            if (!g_app.moldOverlay.empty())
                displayImg = g_app.moldOverlay;
        } else if (g_app.mode == Mode::SPEC_VIZ) {
            std::lock_guard<std::mutex> lk(g_app.moldMutex);
            const auto& vi = g_app.specVizImgs[g_app.specVizIdx];
            if (!vi.empty())
                displayImg = vi;
        } else if (g_app.mode != Mode::DEPTH) {
            using namespace std::chrono;
            bool settling = steady_clock::now() < g_app.settleUntil;
            if (!settling) {
                std::lock_guard<std::mutex> lock(g_app.resultMutex);
                if (g_app.hasResult && !g_app.latestResult.empty()) {
                    displayImg = g_app.latestResult;
                    g_app.frameCount++;
                }
            }
        } else {
            // Depth mode: render only when depth map is newly updated
            if (g_app.depthMapUpdated.exchange(false) && !g_app.lastDepthMap.empty()) {
                displayImg = processFrame(g_app, {});  // uses DEPTH case directly
                g_app.frameCount++;
            }
        }

        // Handle depth capture request
        if (g_app.depthCapturePending.exchange(false)) {
            runDepthCapture(g_app);
        }

        // Handle segment request (launch background thread)
        if (g_app.segPending.exchange(false) && !g_app.segRunning) {
            g_app.segRunning = true;
            g_app.segStartTime = std::chrono::steady_clock::now();
            g_app.statusMsg  = g_app.segDaemonReady ? "Segmenting... (~10s)" : "Segmenting... (~20s)";
            std::thread([&](){
                g_app.blockProc = true;  // pause proc thread → free CPU for FastSAM, avoid notify_one race
                // 1. Capture at current exposure (2500us default) → diff base
                cv::Mat frame32 = captureOneGray(g_app);
                if (frame32.empty()) {
                    g_app.statusMsg = "Segment: capture failed";
                    g_app.blockProc = false;
                    g_app.frameCV.notify_all();
                    g_app.segRunning = false;
                    return;
                }
                cv::Mat gray8;
                frame32.convertTo(gray8, CV_8U);
                cv::imwrite(g_app.saveDir + "/capture_2500us_gray.png", gray8);

                // 2. Compute and save diff if background available
                if (g_app.segBgCaptured && !g_app.segBg.empty()) {
                    cv::Mat diff;
                    cv::absdiff(gray8, g_app.segBg, diff);
                    cv::imwrite(g_app.saveDir + "/diff_1250us.png", diff);
                }

                // 3. Run segmentation (daemon if ready, else direct popen fallback)
                int beanCount = -1;
                if (g_app.segDaemonReady && g_app.segDaemonWr && g_app.segDaemonRd) {
                    char req[512];
                    snprintf(req, sizeof(req),
                             "{\"session_dir\":\"%s\",\"n_beans\":51,\"conf\":0.30,\"imgsz\":256}\n",
                             g_app.saveDir.c_str());
                    fputs(req, g_app.segDaemonWr);
                    fflush(g_app.segDaemonWr);
                    char resp[256] = {};
                    if (fgets(resp, sizeof(resp), g_app.segDaemonRd)) {
                        std::string s(resp);
                        auto pos = s.find("\"bean_count\":");
                        if (pos != std::string::npos)
                            try { beanCount = std::stoi(s.substr(pos + 13)); } catch (...) {}
                    }
                } else {
                    // Fallback: direct popen (model loaded fresh each time)
                    std::string cmd = "python3 /home/kyle/KyleClaude/segment_beans_sam.py \""
                                    + g_app.saveDir + "\" 51 2>&1";
                    FILE* pp = popen(cmd.c_str(), "r");
                    if (pp) {
                        char buf[256];
                        while (fgets(buf, sizeof(buf), pp)) {
                            std::string line(buf);
                            auto pos = line.find("FastSAM \xe5\x88\x86\xe5\x89\xb2 ");
                            if (pos != std::string::npos)
                                try { beanCount = std::stoi(line.substr(pos + 13)); } catch (...) {}
                        }
                        pclose(pp);
                    }
                }

                // 5. Load result image and update state
                cv::Mat result = cv::imread(g_app.saveDir + "/beans_contour.png");
                {
                    std::lock_guard<std::mutex> lk(g_app.segMutex);
                    g_app.segOverlay   = result;
                    g_app.segBeanCount = beanCount;
                }
                if (!result.empty()) {
                    g_app.mode = Mode::SEGMENT;
                    g_app.statusMsg = beanCount >= 0
                        ? "Segmentation done: " + std::to_string(beanCount) + " beans"
                        : "Segmentation done";
                } else {
                    g_app.statusMsg = "Segment: result image not found";
                }
                g_app.blockProc = false;
                g_app.frameCV.notify_all();
                g_app.segRunning = false;
            }).detach();
        }

        // Handle spectral capture (2500us, saves .qs for mold analysis)
        if (g_app.specCapturePending.exchange(false) && !g_app.specRunning && !g_app.moldRunning) {
            g_app.specRunning = true;
            g_app.specStartTime = std::chrono::steady_clock::now();
            g_app.statusMsg = "Capturing spectrum at 2500us...";
            std::thread([&](){
                int oldExp = g_app.exposure;
                int newExp = 2500;
                controlQsCamera(g_app.camera, QS_CAMERA_SET_EXPOSURE, &newExp);
                std::this_thread::sleep_for(std::chrono::milliseconds(400));

                cv::Mat frame32 = captureOneGray(g_app, 3000);
                std::string qsPath = g_app.saveDir + "/capture_spec_2500us.qs";
                bool saved = false;
                if (!frame32.empty()) {
                    std::lock_guard<std::mutex> lk(g_app.frameMutex);
                    if (!g_app.latestFrame.empty()) {
                        saveQsFile(qsPath.c_str(), g_app.latestFrame.data(), g_app.latestFrame.size());
                        cv::Mat gray8; frame32.convertTo(gray8, CV_8U);
                        cv::imwrite(g_app.saveDir + "/capture_spec_2500us_gray.png", gray8);
                        saved = true;
                    }
                }
                // Restore exposure
                controlQsCamera(g_app.camera, QS_CAMERA_SET_EXPOSURE, &oldExp);
                g_app.specCaptured = saved;

                if (saved && g_app.segBeanCount > 0) {
                    // Run spec_fingerprint to generate spec_raw.csv
                    g_app.statusMsg = "Generating spectral fingerprint...";
                    std::string sfBin  = "/home/kyle/KyleClaude/multispectral_demo/build/spec_fingerprint";
                    std::string rois   = g_app.saveDir + "/beans_rois.json";
                    std::string csv    = g_app.saveDir + "/spec_raw.csv";
                    std::string lmap   = g_app.saveDir + "/beans_labelmap.png";
                    auto [white, wexp] = ffWhiteRef(g_app.saveDir);
                    writeFFMarker(g_app.saveDir, white);
                    std::string sfCmd  = sfBin + " \"" + g_app.qsbsPath + "\" \""
                        + g_app.qsdbPath + "\" \"" + qsPath + "\" \""
                        + rois + "\" \"" + csv + "\" \"" + lmap + "\""
                        + (white.empty() ? "" : " \"" + white + "\"") + " 2>&1";
                    FILE* pp = popen(sfCmd.c_str(), "r");
                    if (pp) { char buf[256]; while(fgets(buf, sizeof(buf), pp)) std::cout << buf; pclose(pp); }
                    scaleSpecCsv(csv, wexp);

                    // Generate spectral curves visualization
                    if (access(csv.c_str(), F_OK) == 0) {
                        g_app.statusMsg = "Generating spectral visualization...";
                        std::string vizCmd = "python3 /home/kyle/KyleClaude/spec_viz.py \""
                            + g_app.saveDir + "\" 2>&1";
                        pp = popen(vizCmd.c_str(), "r");
                        if (pp) { char buf[256]; while(fgets(buf, sizeof(buf), pp)) std::cout << buf; pclose(pp); }

                        // Load and display both spectral charts
                        cv::Mat viz0 = cv::imread(g_app.saveDir + "/spec_curves_0.png");
                        cv::Mat viz1 = cv::imread(g_app.saveDir + "/spec_curves_1.png");
                        if (!viz0.empty()) {
                            std::lock_guard<std::mutex> lk(g_app.moldMutex);
                            g_app.specVizImgs[0] = viz0;
                            g_app.specVizImgs[1] = viz1;
                            g_app.specVizIdx = 0;
                            g_app.mode = Mode::SPEC_VIZ;
                            g_app.statusMsg = "Spectrum ready — " + std::to_string(g_app.segBeanCount) + " beans  [M to detect mold]";
                        } else {
                            g_app.statusMsg = "Spectrum captured — viz failed";
                        }
                    } else {
                        g_app.statusMsg = "spec_fingerprint failed (check qsdb path)";
                    }
                } else {
                    g_app.statusMsg = saved ? "Spectrum captured (2500us) — segment beans first for analysis"
                                            : "Spectrum capture failed";
                }
                g_app.specRunning = false;
            }).detach();
        }

        // Handle mold detection (spec_fingerprint → mold_analysis_51.py)
        if (g_app.moldPending.exchange(false) && !g_app.moldRunning
            && g_app.specCaptured && g_app.segBeanCount > 0) {
            g_app.moldRunning = true;
            g_app.moldStartTime = std::chrono::steady_clock::now();
            g_app.statusMsg = "Running mold analysis (~30s)...";
            std::thread([&](){
                std::string sfBin  = "/home/kyle/KyleClaude/multispectral_demo/build/spec_fingerprint";
                std::string qsFile = g_app.saveDir + "/capture_spec_2500us.qs";
                std::string rois   = g_app.saveDir + "/beans_rois.json";
                std::string csv    = g_app.saveDir + "/spec_raw.csv";
                std::string lmap   = g_app.saveDir + "/beans_labelmap.png";

                // 1. spec_fingerprint: .qs → spec_raw.csv
                std::string sfCmd = sfBin + " \"" + g_app.qsbsPath + "\" \""
                    + g_app.qsdbPath + "\" \"" + qsFile + "\" \""
                    + rois + "\" \"" + csv + "\" \"" + lmap + "\" 2>&1";
                std::cout << "[MOLD] " << sfCmd << "\n";
                FILE* pp = popen(sfCmd.c_str(), "r");
                if (pp) { char buf[256]; while(fgets(buf, sizeof(buf), pp)) std::cout << buf; pclose(pp); }

                // 2. mold_analysis_51.py: spec_raw.csv → mold_result/
                std::string moldCmd = "python3 /home/kyle/KyleClaude/mold_analysis_51.py \""
                    + g_app.saveDir + "\" 2>&1";
                int high = 0, med = 0;
                pp = popen(moldCmd.c_str(), "r");
                if (pp) {
                    char buf[256];
                    while (fgets(buf, sizeof(buf), pp)) {
                        std::cout << buf;
                        std::string line(buf);
                        if (line.find("HIGH") != std::string::npos &&
                            line.find("疑似") != std::string::npos) {
                            // Parse count from "⚠ 疑似黴菌豆子（共 X 顆）"
                            auto p = line.find('\xef'); // utf-8 start
                            auto q = line.rfind('\xc3'); // before 顆
                        }
                        // Count HIGH/MED from result lines
                        if (line.find("[HIGH]") != std::string::npos) high++;
                        if (line.find("[MED]")  != std::string::npos) med++;
                    }
                    pclose(pp);
                }

                // 3. Load result image
                cv::Mat result = cv::imread(g_app.saveDir + "/mold_result/mold_labeled.png");
                {
                    std::lock_guard<std::mutex> lk(g_app.moldMutex);
                    g_app.moldOverlay   = result;
                    g_app.moldHighCount = high;
                    g_app.moldMedCount  = med;
                }
                if (!result.empty()) {
                    g_app.mode = Mode::MOLD;
                    g_app.statusMsg = "Mold done — HIGH:" + std::to_string(high)
                                    + " MED:" + std::to_string(med);
                } else {
                    g_app.statusMsg = "Mold: result image not found";
                }
                g_app.moldRunning = false;
            }).detach();
        }

        // ── Full Analysis pipeline: seg + spec + mold ──────────────────────
        if (g_app.fullAnalysisPending.exchange(false) && !g_app.fullAnalysisRunning) {
            g_app.fullAnalysisRunning = true;
            g_app.fullAnalysisStart   = std::chrono::steady_clock::now();
            g_app.fullAnalysisStage   = "Capturing...";
            bool quickMode = g_analysisModeQuick;  // snapshot at thread start
            std::thread([&, quickMode](){
                g_app.blockProc = true;

                // ── Stage 1: 2500us gray (FastSAM input) ──────────────────
                g_app.fullAnalysisStage = "Capturing 2500us...";
                cv::Mat frame32 = captureOneGray(g_app);
                if (frame32.empty()) {
                    g_app.statusMsg = "Full Analysis: 2500us capture failed";
                    g_app.blockProc = false; g_app.frameCV.notify_all();
                    g_app.fullAnalysisRunning = false; return;
                }
                cv::Mat gray8;
                frame32.convertTo(gray8, CV_8U);
                cv::imwrite(g_app.saveDir + "/capture_2500us_gray.png", gray8);
                // Only compute BG diff in Complete mode
                if (!quickMode && g_app.segBgCaptured && !g_app.segBg.empty()) {
                    cv::Mat diff; cv::absdiff(gray8, g_app.segBg, diff);
                    cv::imwrite(g_app.saveDir + "/diff_1250us.png", diff);
                }

                // ── Stage 2: spec .qs — match white ref exposure for valid flat-field ──
                int specExp = (g_app.whiteRefExp > 0) ? g_app.whiteRefExp : 2500;
                g_app.fullAnalysisStage = "Capturing " + std::to_string(specExp) + "us...";
                char specExpBuf[32]; snprintf(specExpBuf, sizeof(specExpBuf), "%dus", specExp);
                std::string qsPath = g_app.saveDir + "/capture_spec_" + specExpBuf + ".qs";
                {
                    int oldExp = g_app.exposure;
                    controlQsCamera(g_app.camera, QS_CAMERA_SET_EXPOSURE, &specExp);
                    std::this_thread::sleep_for(std::chrono::milliseconds(400));
                    cv::Mat f2 = captureOneGray(g_app, 3000);
                    bool saved5k = false;
                    if (!f2.empty()) {
                        std::lock_guard<std::mutex> lk(g_app.frameMutex);
                        if (!g_app.latestFrame.empty()) {
                            saveQsFile(qsPath.c_str(), g_app.latestFrame.data(), g_app.latestFrame.size());
                            cv::Mat g2; f2.convertTo(g2, CV_8U);
                            cv::imwrite(g_app.saveDir + "/capture_spec_" + std::string(specExpBuf) + "_gray.png", g2);
                            saved5k = true;
                        }
                    }
                    controlQsCamera(g_app.camera, QS_CAMERA_SET_EXPOSURE, &oldExp);
                    g_app.specCaptured = saved5k;
                    std::cout << "[spec] captured at " << specExp << "us"
                              << (specExp == g_app.whiteRefExp ? " (matches white ref)" : "") << "\n";
                }

                // ── Stage 3: FastSAM segmentation (~10s) ─────────────────
                g_app.fullAnalysisStage = "Segmenting... (~10s)";
                int beanCount = -1;
                if (g_app.segDaemonReady && g_app.segDaemonWr && g_app.segDaemonRd) {
                    char req[512];
                    snprintf(req, sizeof(req),
                             "{\"session_dir\":\"%s\",\"n_beans\":51,\"conf\":0.30,\"imgsz\":256}\n",
                             g_app.saveDir.c_str());
                    fputs(req, g_app.segDaemonWr); fflush(g_app.segDaemonWr);
                    char resp[256] = {};
                    if (fgets(resp, sizeof(resp), g_app.segDaemonRd)) {
                        std::string s(resp);
                        auto pos = s.find("\"bean_count\":");
                        if (pos != std::string::npos)
                            try { beanCount = std::stoi(s.substr(pos + 13)); } catch (...) {}
                    }
                } else {
                    std::string cmd = "python3 /home/kyle/KyleClaude/segment_beans_sam.py \""
                                    + g_app.saveDir + "\" 51 2>&1";
                    FILE* pp = popen(cmd.c_str(), "r");
                    if (pp) { char buf[256]; while(fgets(buf, sizeof(buf), pp)) std::cout << buf; pclose(pp); }
                }
                {
                    cv::Mat seg = cv::imread(g_app.saveDir + "/beans_contour.png");
                    std::lock_guard<std::mutex> lk(g_app.segMutex);
                    g_app.segOverlay   = seg;
                    g_app.segBeanCount = beanCount;
                }

                // ── Stage 4: spec_fingerprint (needs beans_rois.json) ─────
                if (g_app.specCaptured && beanCount > 0) {
                    g_app.fullAnalysisStage = "Computing spectra...";
                    std::string sfBin = "/home/kyle/KyleClaude/multispectral_demo/build/spec_fingerprint";
                    std::string rois  = g_app.saveDir + "/beans_rois.json";
                    std::string csv   = g_app.saveDir + "/spec_raw.csv";
                    std::string lmap  = g_app.saveDir + "/beans_labelmap.png";
                    auto [white, wexp] = ffWhiteRef(g_app.saveDir);
                    writeFFMarker(g_app.saveDir, white);
                    std::string sfCmd = sfBin + " \"" + g_app.qsbsPath + "\" \""
                        + g_app.qsdbPath + "\" \"" + qsPath + "\" \""
                        + rois + "\" \"" + csv + "\" \"" + lmap + "\""
                        + (white.empty() ? "" : " \"" + white + "\"") + " 2>&1";
                    FILE* pp = popen(sfCmd.c_str(), "r");
                    if (pp) { char buf[256]; while(fgets(buf, sizeof(buf), pp)) std::cout << buf; pclose(pp); }
                    scaleSpecCsv(csv, wexp);

                    if (access(csv.c_str(), F_OK) == 0) {
                        // ── Stage 5: spec_viz + mold (parallel) ───────────
                        g_app.fullAnalysisStage = "Analyzing...";
                        std::string sdir = g_app.saveDir;

                        std::thread tViz([sdir](){
                            std::string cmd = "python3 /home/kyle/KyleClaude/spec_viz.py \""
                                           + sdir + "\" 2>&1";
                            FILE* p = popen(cmd.c_str(), "r");
                            if (p) { char b[256]; while(fgets(b,sizeof(b),p)) std::cout<<b; pclose(p); }
                        });

                        int high = 0, med = 0;
                        std::thread tMold([sdir, &high, &med](){
                            std::string cmd = "python3 /home/kyle/KyleClaude/mold_analysis_51.py \""
                                           + sdir + "\" 2>&1";
                            FILE* p = popen(cmd.c_str(), "r");
                            if (p) {
                                char b[256];
                                while(fgets(b,sizeof(b),p)) {
                                    std::cout << b;
                                    std::string ln(b);
                                    if (ln.find("[HIGH]") != std::string::npos) high++;
                                    if (ln.find("[MED]")  != std::string::npos) med++;
                                }
                                pclose(p);
                            }
                        });

                        tViz.join(); tMold.join();

                        // Load results
                        {
                            std::lock_guard<std::mutex> lk(g_app.moldMutex);
                            cv::Mat v0 = cv::imread(sdir + "/spec_curves_0.png");
                            cv::Mat v1 = cv::imread(sdir + "/spec_curves_1.png");
                            if (!v0.empty()) { g_app.specVizImgs[0]=v0; g_app.specVizImgs[1]=v1; g_app.specVizIdx=0; }
                            g_app.moldOverlay   = cv::imread(sdir + "/mold_result/mold_labeled.png");
                            g_app.moldHighCount = high;
                            g_app.moldMedCount  = med;
                        }

                        g_app.mode = Mode::SEGMENT;
                        g_app.statusMsg = "Done — Beans:" + std::to_string(beanCount)
                            + "  HIGH:" + std::to_string(high)
                            + "  MED:"  + std::to_string(med);
                    } else {
                        g_app.statusMsg = "Segmentation done — spec_fingerprint failed";
                        g_app.mode = Mode::SEGMENT;
                    }
                } else {
                    g_app.mode = Mode::SEGMENT;
                    g_app.statusMsg = "Segmentation done: " + std::to_string(beanCount) + " beans";
                }

                g_app.fullAnalysisStage.clear();
                g_app.blockProc = false;
                g_app.frameCV.notify_all();
                g_app.fullAnalysisRunning = false;
            }).detach();
        }

        // ── Agtron analysis (independent, triggered by AGTRON_RUN) ─────────
        if (g_app.agtronPending.exchange(false) && !g_app.agtronRunning) {
            g_app.agtronRunning = true;
            g_app.agtronStart   = std::chrono::steady_clock::now();
            std::thread([&](){
                std::string sdir    = g_app.saveDir;
                std::string specCsv = sdir + "/spec_raw.csv";
                std::string rois    = sdir + "/beans_rois.json";
                std::string lmap    = sdir + "/beans_labelmap.png";
                std::string qsPath  = sdir + "/capture_spec_2500us.qs";

                // ── Fixed-ROI fast path (no gray capture, no FastSAM) ────────
                if (g_app.agtronRoiSaved) {
                    int specExp = (g_app.whiteRefExp > 0) ? g_app.whiteRefExp : 2500;
                    std::string fastQs = sdir + "/capture_spec_"
                                       + std::to_string(specExp) + "us.qs";
                    std::string rawCsv = sdir + "/agtron_raw_spec.csv";

                    // Snapshot ROI params (immutable during this run)
                    int rcx = g_app.agtronRoiCx, rcy = g_app.agtronRoiCy, rr = g_app.agtronRoiR;

                    // 1. Generate circular labelmap (pixel value = 1) and single-entry rois.json
                    g_app.statusMsg = "Agtron: generating ROI...";
                    {
                        cv::Mat lm(1200, 1600, CV_8UC1, cv::Scalar(0));
                        cv::circle(lm, cv::Point(rcx, rcy), rr, cv::Scalar(1), -1);
                        cv::imwrite(lmap, lm);
                        int x0 = std::max(0, rcx - rr);
                        int y0 = std::max(0, rcy - rr);
                        int x1 = std::min(1599, rcx + rr);
                        int y1 = std::min(1199, rcy + rr);
                        FILE* jf = fopen(rois.c_str(), "w");
                        if (jf) {
                            fprintf(jf, "[{\"id\":1,\"x0\":%d,\"y0\":%d,\"x1\":%d,\"y1\":%d}]\n",
                                    x0, y0, x1, y1);
                            fclose(jf);
                        }
                    }

                    // 2. Capture QS spectrum
                    g_app.statusMsg = "Agtron: capturing spectrum...";
                    int oldExp2 = g_app.exposure;
                    controlQsCamera(g_app.camera, QS_CAMERA_SET_EXPOSURE, &specExp);
                    std::this_thread::sleep_for(std::chrono::milliseconds(400));
                    captureOneGray(g_app, 3000);  // prime
                    {
                        std::lock_guard<std::mutex> lk(g_app.frameMutex);
                        if (!g_app.latestFrame.empty())
                            saveQsFile(fastQs.c_str(),
                                       g_app.latestFrame.data(), g_app.latestFrame.size());
                    }
                    controlQsCamera(g_app.camera, QS_CAMERA_SET_EXPOSURE, &oldExp2);

                    if (access(fastQs.c_str(), F_OK) != 0) {
                        g_app.statusMsg = "Agtron: capture failed";
                        g_app.agtronRunning = false;
                        return;
                    }

                    // 3. spec_fingerprint --agtron-only
                    g_app.statusMsg = "Agtron: computing spectra...";
                    {
                        std::string sfBin = "/home/kyle/KyleClaude/multispectral_demo/build/spec_fingerprint";
                        std::string sfCmd = sfBin + " \"" + g_app.qsbsPath + "\" \""
                            + g_app.qsdbPath + "\" \"" + fastQs + "\" \""
                            + rois + "\" \"" + rawCsv + "\" \"" + lmap + "\" --agtron-only 2>&1";
                        FILE* pp = popen(sfCmd.c_str(), "r");
                        if (pp) { char b[256]; while(fgets(b,sizeof(b),pp)) std::cout<<b; pclose(pp); }
                    }

                    // 4. agtron_analysis.py --fast
                    g_app.statusMsg = "Agtron: computing...";
                    {
                        std::string cmd = "python3 /home/kyle/KyleClaude/agtron_analysis.py \""
                                        + sdir + "\" --fast 2>&1";
                        FILE* p = popen(cmd.c_str(), "r");
                        if (p) { char b[256]; while(fgets(b,sizeof(b),p)) std::cout<<b; pclose(p); }
                    }

                // ── Normal path: seg_daemon → spec_fingerprint → agtron_analysis ──
                } else if (access(specCsv.c_str(), F_OK) != 0 &&
                    access((sdir + "/agtron_raw_spec.csv").c_str(), F_OK) != 0) {

                    int specExp = (g_app.whiteRefExp > 0) ? g_app.whiteRefExp : 2500;
                    std::string fastQs = sdir + "/capture_spec_"
                                       + std::to_string(specExp) + "us.qs";
                    std::string grayPng = sdir + "/capture_2500us_gray.png";
                    std::string rawCsv  = sdir + "/agtron_raw_spec.csv";

                    // 1. Capture 2500us gray (FastSAM input)
                    g_app.statusMsg = "Agtron: capturing gray...";
                    int oldExp = g_app.exposure;
                    int grayExp = 2500;
                    controlQsCamera(g_app.camera, QS_CAMERA_SET_EXPOSURE, &grayExp);
                    std::this_thread::sleep_for(std::chrono::milliseconds(400));
                    {
                        cv::Mat grayF = captureOneGray(g_app, 3000);
                        if (!grayF.empty()) {
                            cv::Mat gray8; grayF.convertTo(gray8, CV_8U);
                            cv::imwrite(grayPng, gray8);
                        }
                    }

                    // 2. FastSAM segmentation
                    g_app.statusMsg = "Agtron: segmenting (~10s)...";
                    int beanCount = -1;
                    if (g_app.segDaemonReady && g_app.segDaemonWr && g_app.segDaemonRd) {
                        char req[512];
                        snprintf(req, sizeof(req),
                                 "{\"session_dir\":\"%s\",\"n_beans\":51,\"conf\":0.30,\"imgsz\":256}\n",
                                 sdir.c_str());
                        fputs(req, g_app.segDaemonWr);
                        fflush(g_app.segDaemonWr);
                        char resp[256] = {};
                        if (fgets(resp, sizeof(resp), g_app.segDaemonRd)) {
                            std::string s(resp);
                            auto pos = s.find("\"bean_count\":");
                            if (pos != std::string::npos)
                                try { beanCount = std::stoi(s.substr(pos + 13)); } catch (...) {}
                        }
                    } else {
                        std::string cmd = "python3 /home/kyle/KyleClaude/segment_beans_sam.py \""
                                        + sdir + "\" 51 2>&1";
                        FILE* pp = popen(cmd.c_str(), "r");
                        if (pp) {
                            char buf[256];
                            while (fgets(buf, sizeof(buf), pp)) {
                                std::cout << buf;
                                std::string ln(buf);
                                auto pos = ln.find("FastSAM \xe5\x88\x86\xe5\x89\xb2 ");
                                if (pos != std::string::npos)
                                    try { beanCount = std::stoi(ln.substr(pos + 13)); } catch (...) {}
                            }
                            pclose(pp);
                        }
                    }
                    std::cout << "[agtron] seg done: " << beanCount << " beans\n";

                    // 3. Capture QS spectrum at whiteRefExp (sequential — must be after gray capture)
                    g_app.statusMsg = "Agtron: capturing spectrum...";
                    controlQsCamera(g_app.camera, QS_CAMERA_SET_EXPOSURE, &specExp);
                    std::this_thread::sleep_for(std::chrono::milliseconds(400));
                    captureOneGray(g_app, 3000);  // prime frame
                    {
                        std::lock_guard<std::mutex> lk(g_app.frameMutex);
                        if (!g_app.latestFrame.empty())
                            saveQsFile(fastQs.c_str(),
                                       g_app.latestFrame.data(), g_app.latestFrame.size());
                    }
                    controlQsCamera(g_app.camera, QS_CAMERA_SET_EXPOSURE, &oldExp);

                    if (access(fastQs.c_str(), F_OK) != 0) {
                        g_app.statusMsg = "Agtron: capture failed";
                        g_app.agtronRunning = false;
                        return;
                    }

                    // 4. spec_fingerprint --agtron-only → agtron_raw_spec.csv (850+930nm only)
                    if (beanCount > 0) {
                        g_app.statusMsg = "Agtron: computing spectra...";
                        std::string sfBin = "/home/kyle/KyleClaude/multispectral_demo/build/spec_fingerprint";
                        std::string sfCmd = sfBin + " \"" + g_app.qsbsPath + "\" \""
                            + g_app.qsdbPath + "\" \"" + fastQs + "\" \""
                            + rois + "\" \"" + rawCsv + "\" \"" + lmap + "\" --agtron-only 2>&1";
                        FILE* pp = popen(sfCmd.c_str(), "r");
                        if (pp) { char b[256]; while(fgets(b,sizeof(b),pp)) std::cout<<b; pclose(pp); }
                    }

                    // 5. agtron_analysis.py --fast (JSON + labeled PNG, skip matplotlib charts)
                    g_app.statusMsg = "Agtron: computing...";
                    {
                        std::string cmd = "python3 /home/kyle/KyleClaude/agtron_analysis.py \""
                                        + sdir + "\" --fast 2>&1";
                        FILE* p = popen(cmd.c_str(), "r");
                        if (p) { char b[256]; while(fgets(b,sizeof(b),p)) std::cout<<b; pclose(p); }
                    }
                } else {

                    // ── Run agtron_analysis.py (full-pipeline path) ───────────
                    g_app.statusMsg = "Agtron: computing...";
                    std::string cmd = "python3 /home/kyle/KyleClaude/agtron_analysis.py \""
                                    + sdir + "\" 2>&1";
                    FILE* p = popen(cmd.c_str(), "r");
                    if (p) { char b[256]; while(fgets(b,sizeof(b),p)) std::cout<<b; pclose(p); }
                }

                // Load labeled PNG + JSON result immediately (charts may not exist yet)
                cv::Mat overlay = cv::imread(sdir + "/agtron_labeled.png");
                int mean = -1;
                {
                    std::string aj = sdir + "/agtron_result.json";
                    FILE* jf = fopen(aj.c_str(), "r");
                    if (jf) {
                        char buf[512]; std::string s;
                        while(fgets(buf, sizeof(buf), jf)) s += buf;
                        fclose(jf);
                        auto pos = s.find("\"mean_agtron\":");
                        if (pos != std::string::npos)
                            try { mean = (int)std::stof(s.substr(pos+14)); } catch(...) {}
                    }
                }
                {
                    std::lock_guard<std::mutex> lk(g_app.moldMutex);
                    g_app.agtronOverlay   = overlay;
                    g_app.agtronHistogram = cv::Mat{};  // charts coming in background
                    g_app.agtronPiechart  = cv::Mat{};
                    g_app.agtronMean      = mean;
                }
                g_app.agtronReady = !overlay.empty();
                g_app.statusMsg   = g_app.agtronReady
                    ? "Agtron done — Mean: " + std::to_string(mean) + "  " + roastLabel(mean)
                    : "Agtron: analysis failed";
                if (g_app.agtronReady)
                    g_app.mode = Mode::AGTRON;
                g_app.agtronRunning = false;

                // Generate histogram + piechart in background (matplotlib is slow)
                if (g_app.agtronReady) {
                    std::thread([sdir, &g_app = g_app](){
                        std::string cmd = "python3 /home/kyle/KyleClaude/agtron_analysis.py \""
                                        + sdir + "\" 2>&1";
                        FILE* p = popen(cmd.c_str(), "r");
                        if (p) { char b[256]; while(fgets(b,sizeof(b),p)) std::cout<<b; pclose(p); }
                        cv::Mat histogram = cv::imread(sdir + "/agtron_histogram.png");
                        cv::Mat piechart  = cv::imread(sdir + "/agtron_piechart.png");
                        if (!histogram.empty() || !piechart.empty()) {
                            std::lock_guard<std::mutex> lk(g_app.moldMutex);
                            if (!histogram.empty()) g_app.agtronHistogram = histogram;
                            if (!piechart.empty())  g_app.agtronPiechart  = piechart;
                        }
                    }).detach();
                }
            }).detach();
        }

        // ── Grind size analysis ───────────────────────────────────────────────
        if (g_app.grindPending.exchange(false) && !g_app.grindRunning) {
            g_app.grindRunning = true;
            g_app.grindStart   = std::chrono::steady_clock::now();
            std::thread([&](){
                std::string sdir = g_app.saveDir;

                // Capture current frame as grayscale PNG
                g_app.statusMsg = "Grind: capturing...";
                g_app.blockProc = true;
                cv::Mat f32 = captureOneGray(g_app, 3000);
                g_app.blockProc = false;
                g_app.frameCV.notify_all();

                if (f32.empty()) {
                    g_app.statusMsg  = "Grind: capture failed";
                    g_app.grindRunning = false;
                    return;
                }
                cv::Mat gray8;
                f32.convertTo(gray8, CV_8U);
                std::string imgPath = sdir + "/grind_capture.png";
                cv::imwrite(imgPath, gray8);

                // Run grind_analysis.py
                g_app.statusMsg = "Grind: analyzing...";
                std::string cmd = "python3 /home/kyle/KyleClaude/grind_analysis.py \""
                                + imgPath + "\" \"" + sdir + "\" 2>&1";
                FILE* p = popen(cmd.c_str(), "r");
                if (p) { char b[256]; while (fgets(b, sizeof(b), p)) std::cout << b; pclose(p); }

                cv::Mat overlay   = cv::imread(sdir + "/grind_labeled.png");
                cv::Mat histogram = cv::imread(sdir + "/grind_histogram.png");
                float d10 = -1.0f, d50 = -1.0f, d90 = -1.0f;
                bool cal = false;
                {
                    FILE* jf = fopen((sdir + "/grind_result.json").c_str(), "r");
                    if (jf) {
                        char buf[512]; std::string s;
                        while (fgets(buf, sizeof(buf), jf)) s += buf;
                        fclose(jf);
                        auto getF = [&](const char* key) -> float {
                            auto pos = s.find(key);
                            if (pos == std::string::npos) return -1.0f;
                            try { return std::stof(s.substr(pos + strlen(key))); }
                            catch (...) { return -1.0f; }
                        };
                        d10 = getF("\"d10\":");
                        d50 = getF("\"d50\":");
                        d90 = getF("\"d90\":");
                        cal = (s.find("\"calibrated\": true") != std::string::npos);
                    }
                }
                {
                    std::lock_guard<std::mutex> lk(g_app.grindMutex);
                    g_app.grindOverlay   = overlay;
                    g_app.grindHistogram = histogram;
                    g_app.grindD10       = d10;
                    g_app.grindD50       = d50;
                    g_app.grindD90       = d90;
                    g_app.grindCalibrated = cal;
                }
                g_app.grindReady = !overlay.empty();
                if (g_app.grindReady) {
                    char buf[128];
                    const char* unit = cal ? "um" : "px";
                    snprintf(buf, sizeof(buf),
                             "Grind done — D50: %.0f %s  (D10=%.0f D90=%.0f)",
                             d50, unit, d10, d90);
                    g_app.statusMsg = buf;
                    g_app.mode = histogram.empty() ? Mode::GRIND : Mode::GRIND_HISTOGRAM;
                } else {
                    g_app.statusMsg = "Grind: analysis failed — check contrast";
                }
                g_app.grindRunning = false;
            }).detach();
        }

        // Handle save (use displayImg as PNG + latest raw .qs)
        if (g_app.saveRequested && !displayImg.empty()) {
            g_app.saveRequested = false;
            // 檔名：capture_001_10000us.png / capture_001_10000us.qs
            char numBuf[8]; snprintf(numBuf, sizeof(numBuf), "%03d", g_app.saveCounter++);
            char expBuf[16]; snprintf(expBuf, sizeof(expBuf), "%dus", g_app.exposure);
            std::string base = g_app.saveDir + "/capture_" + numBuf + "_" + expBuf;
            std::string png = base + ".png";
            cv::imwrite(png, displayImg);
            std::cout << "[SAVE] " << png << "\n";
            {
                std::lock_guard<std::mutex> lock(g_app.frameMutex);
                if (!g_app.latestFrame.empty()) {
                    std::string qs = base + ".qs";
                    saveQsFile(qs.c_str(), g_app.latestFrame.data(), g_app.latestFrame.size());
                    std::cout << "[SAVE] " << qs << "\n";
                }
            }
            g_app.statusMsg = "Saved: capture_" + std::string(numBuf) + " (" + expBuf + ")";
        }

        // Render portrait UI (480×800 single canvas)
        if (!displayImg.empty()) {
            cv::Mat composite = drawPortraitUI(displayImg, g_app);
            cv::imshow(WIN, composite);
        }

        // Software AE: analyse frame brightness every 60 frames (~2s at 30fps).
        // Controls both exposure and gain to avoid saturation:
        //   too bright → reduce exposure first, then gain
        //   too dark   → increase exposure first, then gain
        {
            using namespace std::chrono;
            bool settling = steady_clock::now() < g_app.settleUntil;
            if (g_app.aeEnabled && !displayImg.empty() &&
                g_app.frameCount > 0 && g_app.frameCount % 60 == 0 &&
                !g_app.exposurePending && !g_app.gainPending && !settling) {
                cv::Scalar m = cv::mean(displayImg);
                double brightness = (m[0] + m[1] + m[2]) / 3.0;
                const double LO = 85.0, HI = 165.0;
                auto now2 = steady_clock::now();
                std::cout << "[AE] frame=" << g_app.frameCount
                          << " brightness=" << (int)brightness
                          << " exp=" << g_app.exposure
                          << " gain=" << g_app.gain << "\n";
                if (brightness > HI) {
                    if (g_app.exposure > g_app.exposureMin) {
                        g_app.exposure = expPrev(g_app.exposure, g_app.exposureMin, EXP_NORMAL_MAX);
                        g_app.exposurePending = true;
                        g_app.exposureChanged = now2;
                    } else if (g_app.gain > g_app.gainMin) {
                        g_app.gain -= 1;
                        g_app.gainPending = true;
                        g_app.gainChanged = now2;
                    }
                } else if (brightness < LO) {
                    if (g_app.exposure < EXP_NORMAL_MAX) {
                        g_app.exposure = expNext(g_app.exposure, g_app.exposureMin, EXP_NORMAL_MAX);
                        g_app.exposurePending = true;
                        g_app.exposureChanged = now2;
                    } else if (g_app.gain < g_app.gainMax) {
                        g_app.gain += 1;
                        g_app.gainPending = true;
                        g_app.gainChanged = now2;
                    }
                }
            }
        }

        // Apply debounced camera control changes (100ms after last button press)
        {
            using namespace std::chrono;
            auto now = steady_clock::now();
            constexpr auto DEBOUNCE = milliseconds(100);
            if (g_app.exposurePending &&
                duration_cast<milliseconds>(now - g_app.exposureChanged) >= DEBOUNCE) {
                g_app.exposurePending = false;
                int expVal = g_app.exposure;
                // Apply in background thread to avoid blocking UI
                std::thread([expVal, &app = g_app]() {
                    if (expVal > 0)
                        controlQsCamera(app.camera, QS_CAMERA_SET_EXPOSURE, const_cast<int*>(&expVal));
                }).detach();
                g_app.settleUntil = now + milliseconds(120);
            }
            if (g_app.gainPending &&
                duration_cast<milliseconds>(now - g_app.gainChanged) >= DEBOUNCE) {
                g_app.gainPending = false;
                int gainVal = g_app.gain;
                std::thread([gainVal, dev = g_camera_dev]() {
                    int fd = ::open(dev.c_str(), O_RDWR);
                    if (fd >= 0) {
                        struct v4l2_control c{}; c.id = V4L2_CID_GAIN; c.value = gainVal;
                        ::ioctl(fd, VIDIOC_S_CTRL, &c); ::close(fd);
                    }
                }).detach();
            }
        }

        // Pump Qt events at ~30 fps; keyboard shortcuts still work
        int key = cv::waitKey(33) & 0xFF;
        if (key != 255)
            handleKey(key, g_app, {}, displayImg);
    }

    // ── Cleanup ───────────────────────────────────────────
    g_app.running = false;
    g_app.frameCV.notify_all();   // wake processing thread so it can exit
    procThread.join();

    std::cout << "\nShutting down...\n";

    // Shut down seg daemon
    if (g_app.segDaemonWr) {
        fputs("{\"cmd\":\"exit\"}\n", g_app.segDaemonWr);
        fflush(g_app.segDaemonWr);
        fclose(g_app.segDaemonWr);
        g_app.segDaemonWr = nullptr;
    }
    if (g_app.segDaemonRd) {
        fclose(g_app.segDaemonRd);
        g_app.segDaemonRd = nullptr;
    }
    if (g_app.segDaemonPid > 0) {
        waitpid(g_app.segDaemonPid, nullptr, 0);
        g_app.segDaemonPid = -1;
    }

    closeQsCamera(g_app.camera);
    releaseQsCamera(g_app.cameras, g_app.cameraCount);

    if (g_app.agriCtx)    deinitQsAgriculture(g_app.agriCtx);
    if (g_app.specinvCtx) deinitQsSpecinv(g_app.specinvCtx);
    if (g_app.imgprocCtx) deinitQsImgproc(g_app.imgprocCtx);
    if (g_app.qsbsData)   freeQsData(g_app.qsbsData);

    cv::destroyAllWindows();
    std::cout << "Done. Total frames: " << g_app.frameCount << "\n";
    return 0;
}
