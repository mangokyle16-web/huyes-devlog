/**
 * qs_to_png.cpp
 * Convert a .qs multispectral file to a grayscale PNG using qsToGray.
 *
 * Usage:
 *   qs_to_png <input.qs> <output.png> [qsbs_path]
 */
#include <iostream>
#include <vector>
#include <string>
#include <cstring>

extern "C" {
#include "qs_imgproc.h"
#include "qs_fileio.h"
#include "qs_errorcodes.h"
}

// OpenCV for PNG save
#include <opencv2/core.hpp>
#include <opencv2/imgcodecs.hpp>

int main(int argc, char** argv) {
    if (argc < 3) {
        std::cerr << "Usage: qs_to_png <input.qs> <output.png> [qsbs_path]\n";
        return 1;
    }
    const char* qsPath   = argv[1];
    const char* outPath  = argv[2];
    const char* qsbsPath = (argc >= 4) ? argv[3]
                           : "/home/kyle/KyleClaude/camera_new.qsbs";

    // ── Load QSBS ────────────────────────────────────────────────────────────
    uint8_t* qsbsData = nullptr; size_t qsbsSize = 0;
    QsErrorcodes err = loadQsbsFile(qsbsPath, &qsbsData, &qsbsSize);
    if (err != QS_ERR_SUCCESS) {
        std::cerr << "[FAIL] loadQsbsFile: " << err << "\n"; return 1;
    }
    std::cout << "[OK] QSBS loaded (" << qsbsSize << " bytes)\n";

    // ── Init imgproc context ─────────────────────────────────────────────────
    QsImgprocContext* ctx = nullptr;
    err = initQsImgproc(&ctx, qsbsData, qsbsSize);
    freeQsData(qsbsData);
    if (err != QS_ERR_SUCCESS) {
        std::cerr << "[FAIL] initQsImgproc: " << err << "\n"; return 1;
    }
    std::cout << "[OK] Imgproc context initialized\n";

    // ── Load QS ──────────────────────────────────────────────────────────────
    uint8_t* qsData = nullptr; size_t qsSize = 0;
    err = loadQsFile(qsPath, &qsData, &qsSize);
    if (err != QS_ERR_SUCCESS) {
        std::cerr << "[FAIL] loadQsFile: " << err << "\n"; return 1;
    }
    std::cout << "[OK] QS file loaded (" << qsSize << " bytes)\n";

    // ── Convert to grayscale ─────────────────────────────────────────────────
    uint8_t* grayData = nullptr;
    int width = 0, height = 0;
    err = qsToGray(ctx, qsData, qsSize, &grayData, &width, &height);
    freeQsData(qsData);
    if (err != QS_ERR_SUCCESS) {
        std::cerr << "[FAIL] qsToGray: " << err << "\n"; return 1;
    }
    std::cout << "[OK] Converted to gray: " << width << "x" << height << "\n";

    // ── Save PNG via OpenCV ──────────────────────────────────────────────────
    cv::Mat gray(height, width, CV_8UC1, grayData);
    bool ok = cv::imwrite(outPath, gray);
    free(grayData);
    deinitQsImgproc(ctx);

    if (!ok) {
        std::cerr << "[FAIL] cv::imwrite failed\n"; return 1;
    }
    std::cout << "[OK] Saved: " << outPath << "\n";
    return 0;
}
