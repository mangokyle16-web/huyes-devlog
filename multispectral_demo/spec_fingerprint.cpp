/**
 * spec_fingerprint.cpp
 * 用法：
 *   ./spec_fingerprint <qsbs> <qsdb> <qs_file> <rois.json>
 *                      [output.csv] [labelmap.png] [white_ref.qs]
 *
 *   labelmap.png  : 像素值 = 豆子 ID（0 = 背景），由分割腳本產生
 *   white_ref.qs  : 純白紙參考影像，做 flat-field 校正
 */

#include <iostream>
#include <fstream>
#include <vector>
#include <string>
#include <algorithm>
#include <cstdio>
#include <cmath>
#include <array>

#define STB_IMAGE_IMPLEMENTATION
#include "stb_image.h"
#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "stb_image_write.h"

extern "C" {
#include "qs_specinv.h"
#include "qs_fileio.h"
#include "qs_errorcodes.h"
}

// ── JSON parser ───────────────────────────────────────────────────────────────
struct BeanROI { int id, x0, y0, x1, y1; };

static std::vector<BeanROI> parseRois(const char* path) {
    std::ifstream f(path);
    std::string s((std::istreambuf_iterator<char>(f)), {});
    std::vector<BeanROI> rois;
    size_t pos = 0;
    while ((pos = s.find("\"id\"", pos)) != std::string::npos) {
        auto readInt = [&](const char* key, size_t from) -> int {
            size_t k = s.find(key, from);
            if (k == std::string::npos) return 0;
            k = s.find(':', k) + 1;
            while (k < s.size() && (s[k]==' '||s[k]=='\t')) k++;
            return std::stoi(s.substr(k));
        };
        BeanROI r{};
        r.id = readInt("\"id\"",  pos);
        r.x0 = readInt("\"x0\"", pos);
        r.y0 = readInt("\"y0\"", pos);
        r.x1 = readInt("\"x1\"", pos);
        r.y1 = readInt("\"y1\"", pos);
        rois.push_back(r);
        pos += 4;
    }
    return rois;
}

// ── .qs → grayData [band][H][W] ──────────────────────────────────────────────
// lightSrc: fixed light-source index (e.g. 9 = QS_MD_LED). Use -1 for auto.
// All captures (bean + flat-field) must use the same index for ratio to be valid.
static double* loadQsAsGray(QsSpecinvContext* ctx, const char* qsPath,
                             const std::vector<std::array<int,2>>& bandArr,
                             int nBands, int intricacy, int lightSrc,
                             int& outW, int& outH, int& outBandNum)
{
    uint8_t* qsData = nullptr; size_t qsSize = 0;
    if (loadQsFile(qsPath, &qsData, &qsSize) != QS_ERR_SUCCESS) {
        std::cerr << "[FAIL] loadQsFile: " << qsPath << "\n";
        return nullptr;
    }
    uint8_t* qsiData = nullptr; size_t qsiSize = 0;
    QsErrorcodes err = qsToQsi(ctx, qsData, qsSize,
                                lightSrc, intricacy,
                                reinterpret_cast<const int(*)[2]>(bandArr.data()), nBands,
                                &qsiData, &qsiSize);
    freeQsData(qsData);
    if (err != QS_ERR_SUCCESS || !qsiData) {
        std::cerr << "[FAIL] qsToQsi: " << err << "\n";
        return nullptr;
    }
    double* gray = nullptr;
    int (*outRange)[2] = nullptr;
    err = qsiToGray(qsiData, qsiSize, 1.0,
                    &gray, &outW, &outH, &outRange, &outBandNum);
    freeQsData(qsiData);
    if (outRange) freeQsData(outRange);
    if (err != QS_ERR_SUCCESS || !gray) {
        std::cerr << "[FAIL] qsiToGray: " << err << "\n";
        return nullptr;
    }
    return gray;
}

int main(int argc, char** argv) {
    if (argc < 5) {
        std::cerr << "Usage: " << argv[0]
                  << " <qsbs> <qsdb> <qs_file> <rois.json>"
                     " [output.csv] [labelmap.png] [white_ref.qs]\n";
        return 1;
    }
    const char* qsbsPath     = argv[1];
    const char* qsdbPath     = argv[2];
    const char* qsPath       = argv[3];
    const char* roisPath     = argv[4];

    // Parse optional flags and positional args (argv[5+])
    bool agtronOnly = false;
    std::vector<const char*> posArgs;
    for (int i = 5; i < argc; i++) {
        if (std::string(argv[i]) == "--agtron-only") agtronOnly = true;
        else posArgs.push_back(argv[i]);
    }
    const char* csvPath      = posArgs.size() >= 1 ? posArgs[0] : "spec_fingerprint.csv";
    const char* labelmapPath = posArgs.size() >= 2 ? posArgs[1] : nullptr;
    const char* whiteRefPath = posArgs.size() >= 3 ? posArgs[2] : nullptr;

    // ── 校準 + 初始化 ─────────────────────────────────────────────────────────
    uint8_t* qsbsData = nullptr; size_t qsbsSize = 0;
    if (loadQsbsFile(qsbsPath, &qsbsData, &qsbsSize) != QS_ERR_SUCCESS) {
        std::cerr << "[FAIL] loadQsbsFile\n"; return 1;
    }
    QsSpecinvContext* ctx = nullptr;
    size_t specBegin = 0, specEnd = 0;
    char** lightSrcList = nullptr; size_t lightSrcCount = 0;
    QsErrorcodes err = initQsSpecinv(&ctx, qsbsData, qsbsSize, qsdbPath,
                                     &specBegin, &specEnd,
                                     &lightSrcList, &lightSrcCount);
    freeQsData(qsbsData);
    if (err != QS_ERR_SUCCESS) {
        std::cerr << "[FAIL] initQsSpecinv: " << err << "\n"; return 1;
    }
    std::cout << "[OK] specinv " << specBegin << "-" << specEnd << "nm\n";

    // ── 波段列表 ──────────────────────────────────────────────────────────────
    // STEP: 波段寬度與步距 (nm)，SDK 最小 = 20nm，必須不重疊
    // INTRICACY: 光譜反演精細度，越高越準確 (建議 50-200)
    const int STEP = 20, INTRICACY = 100;
    // Fixed light source: QS_MD_LED is the last entry in the SDK list.
    // Using -1 (auto) causes different models for bright white vs dark beans,
    // which breaks flat-field division. Derive index from lightSrcCount - 1.
    const int LIGHT_SRC = (int)lightSrcCount - 1;
    std::cout << "[OK] light source fixed: index=" << LIGHT_SRC << " (" << lightSrcList[LIGHT_SRC] << ")\n";

    // Always compute all bands — SDK Fabry-Perot reconstruction needs full spectral
    // context for accurate 850/930nm values. --agtron-only only skips PNG saves.
    std::vector<std::array<int,2>> bandArr;
    for (int s = (int)specBegin; s + STEP <= (int)specEnd; s += STEP)
        bandArr.push_back({s, s + STEP});
    int nBands = (int)bandArr.size();
    if (agtronOnly)
        std::cout << "[OK] agtron-only mode: " << nBands << " bands (no PNG saves)\n";
    else
        std::cout << "[OK] " << nBands << " bands\n";

    // ── 樣本影像 ──────────────────────────────────────────────────────────────
    int imgW = 0, imgH = 0, outBandNum = 0;
    double* grayData = loadQsAsGray(ctx, qsPath, bandArr, nBands, INTRICACY, LIGHT_SRC,
                                    imgW, imgH, outBandNum);
    if (!grayData) return 1;
    std::cout << "[OK] sample " << imgW << "x" << imgH << " bands=" << outBandNum << "\n";

    // ── 白紙參考（flat-field）────────────────────────────────────────────────
    double* whiteData = nullptr;
    if (whiteRefPath) {
        int wW = 0, wH = 0, wB = 0;
        whiteData = loadQsAsGray(ctx, whiteRefPath, bandArr, nBands, INTRICACY, LIGHT_SRC,
                                 wW, wH, wB);
        if (whiteData && (wW != imgW || wH != imgH || wB != outBandNum)) {
            std::cerr << "[WARN] white ref size mismatch, skipping flat-field\n";
            freeQsData(whiteData); whiteData = nullptr;
        } else if (whiteData) {
            std::cout << "[OK] flat-field enabled\n";
        }
    }

    // ── Label map PNG ─────────────────────────────────────────────────────────
    // 像素值 = 豆子 ID（uint8），0 = 背景
    std::vector<uint8_t> labelMap;
    int lmW = 0, lmH = 0;
    if (labelmapPath) {
        int mw, mh, mc;
        uint8_t* raw = stbi_load(labelmapPath, &mw, &mh, &mc, 1);
        if (!raw) {
            std::cerr << "[WARN] cannot load labelmap: " << labelmapPath << "\n";
        } else {
            lmW = mw; lmH = mh;
            labelMap.assign(raw, raw + (size_t)mw * mh);
            stbi_image_free(raw);
            std::cout << "[OK] labelmap " << lmW << "x" << lmH << "\n";
        }
    }

    // ── ROI ───────────────────────────────────────────────────────────────────
    auto rois = parseRois(roisPath);
    std::cout << "[OK] " << rois.size() << " beans\n";

    // 座標縮放：ROI 座標以 1600×1200 為基準，QSI 可能不同
    double scaleX = (double)imgW / 1600.0;
    double scaleY = (double)imgH / 1200.0;
    // labelmap → QSI 縮放
    double lmScaleX = lmW > 0 ? (double)imgW / lmW : 1.0;
    double lmScaleY = lmH > 0 ? (double)imgH / lmH : 1.0;

    // ── 逐波段、逐豆子統計 ────────────────────────────────────────────────────
    std::vector<std::vector<double>> curves(rois.size(),
                                            std::vector<double>(outBandNum, 0.0));

    for (int b = 0; b < outBandNum; b++) {
        const double* plane      = grayData  + (size_t)b * imgW * imgH;
        const double* whitePlane = whiteData ? whiteData + (size_t)b * imgW * imgH : nullptr;

        for (size_t ri = 0; ri < rois.size(); ri++) {
            const BeanROI& r = rois[ri];
            int rx0 = std::max(0,      (int)(r.x0 * scaleX));
            int ry0 = std::max(0,      (int)(r.y0 * scaleY));
            int rx1 = std::min(imgW-1, (int)(r.x1 * scaleX));
            int ry1 = std::min(imgH-1, (int)(r.y1 * scaleY));

            double sum = 0.0; int cnt = 0;
            for (int y = ry0; y <= ry1; y++) {
                for (int x = rx0; x <= rx1; x++) {
                    // label map 精確遮罩：只取屬於本豆子的像素
                    if (!labelMap.empty()) {
                        int lx = std::min((int)(x / lmScaleX), lmW - 1);
                        int ly = std::min((int)(y / lmScaleY), lmH - 1);
                        if (labelMap[ly * lmW + lx] != (uint8_t)r.id) continue;
                    }
                    double val = plane[y * imgW + x];
                    if (whitePlane) {
                        double wval = whitePlane[y * imgW + x];
                        if (wval < 1e-6) continue;
                        val /= wval;
                    }
                    sum += val;
                    cnt++;
                }
            }
            curves[ri][b] = cnt > 0 ? sum / cnt : 0.0;
            if (b == 0 && cnt == 0)
                std::cerr << "[WARN] bean_" << r.id << " has 0 valid pixels\n";
        }
    }

    // ── CSV ───────────────────────────────────────────────────────────────────
    std::ofstream csv(csvPath);
    csv << "wavelength_nm";
    for (auto& r : rois) csv << ",bean_" << r.id;
    csv << "\n";
    for (int b = 0; b < outBandNum; b++) {
        csv << bandArr[b][0];  // actual band start wavelength (correct in both full and agtron-only mode)
        for (size_t ri = 0; ri < rois.size(); ri++)
            csv << "," << curves[ri][b];
        csv << "\n";
    }
    csv.close();

    // ── Save channel images as PNG (skipped in --agtron-only mode) ─────────────
    if (!agtronOnly) {
        std::string base = csvPath;
        auto dot = base.rfind('.');
        if (dot != std::string::npos) base = base.substr(0, dot);

        std::vector<uint8_t> img8(imgW * imgH);
        for (int b = 0; b < outBandNum; b++) {
            int centre = (int)bandArr[b][0] + STEP / 2;
            const double* plane = grayData + (size_t)b * imgW * imgH;
            double vmin = plane[0], vmax = plane[0];
            for (int i = 1; i < imgW * imgH; i++) {
                if (plane[i] < vmin) vmin = plane[i];
                if (plane[i] > vmax) vmax = plane[i];
            }
            double range = (vmax - vmin) > 1e-9 ? vmax - vmin : 1.0;
            for (int i = 0; i < imgW * imgH; i++)
                img8[i] = (uint8_t)std::max(0.0, std::min(255.0,
                              (plane[i] - vmin) / range * 255.0));
            std::string out = base + "_chan" + std::to_string(centre) + "nm.png";
            stbi_write_png(out.c_str(), imgW, imgH, 1, img8.data(), imgW);
            std::cout << "[OK] channel " << centre << "nm → " << out << "\n";
        }
    }

    freeQsData(grayData);
    if (whiteData) freeQsData(whiteData);
    deinitQsSpecinv(ctx);

    std::cout << "[OK] " << csvPath
              << (whiteData ? " (flat-field)" : "")
              << (!labelMap.empty() ? " (contour mask)" : "") << "\n";
    return 0;
}
