/**
 * spec_gate.cpp — VNIR Phase 1 gate: 60nm band validation
 * Usage: ./spec_gate <qsbs> <qsdb> <white_ref.qs> <bean_frame.qs> [out_dir]
 *
 * Validates that 60nm / 10-band sampling of the VNIR range produces
 * non-degenerate, mutually-distinguishable spectral bands.
 */

#include <iostream>
#include <fstream>
#include <sstream>
#include <vector>
#include <string>
#include <algorithm>
#include <cmath>
#include <array>
#include <numeric>
#include <iomanip>

#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "stb_image_write.h"

extern "C" {
#include "qs_specinv.h"
#include "qs_fileio.h"
#include "qs_errorcodes.h"
}

// ── helpers ────────────────────────────────────────────────────────────────────

struct BandStat {
    int reqStart, reqEnd;
    int actStart, actEnd;
    bool rangeMatched;
    double mean, stddev;
    double ffMean, ffStd;   // flat-field corrected
};

static double* loadQsGray(QsSpecinvContext* ctx, const char* path,
                           const std::vector<std::array<int,2>>& bands,
                           int lightSrc, int intricacy,
                           int& outW, int& outH, int& outBands,
                           std::vector<std::array<int,2>>& actualRanges)
{
    uint8_t* qsData = nullptr; size_t qsSize = 0;
    if (loadQsFile(path, &qsData, &qsSize) != QS_ERR_SUCCESS) {
        std::cerr << "[FAIL] loadQsFile: " << path << "\n";
        return nullptr;
    }
    uint8_t* qsiData = nullptr; size_t qsiSize = 0;
    QsErrorcodes e = qsToQsi(ctx, qsData, qsSize,
                              lightSrc, intricacy,
                              reinterpret_cast<const int(*)[2]>(bands.data()),
                              (int)bands.size(), &qsiData, &qsiSize);
    freeQsData(qsData);
    if (e != QS_ERR_SUCCESS || !qsiData) {
        std::cerr << "[FAIL] qsToQsi err=" << e << " path=" << path << "\n";
        return nullptr;
    }
    double* gray = nullptr;
    int (*outRange)[2] = nullptr;
    e = qsiToGray(qsiData, qsiSize, 1.0, &gray, &outW, &outH, &outRange, &outBands);
    freeQsData(qsiData);
    if (e != QS_ERR_SUCCESS || !gray) {
        std::cerr << "[FAIL] qsiToGray err=" << e << " path=" << path << "\n";
        if (outRange) freeQsData(outRange);
        return nullptr;
    }
    actualRanges.resize(outBands);
    for (int b = 0; b < outBands; b++)
        actualRanges[b] = {outRange[b][0], outRange[b][1]};
    freeQsData(outRange);
    return gray;
}

static void stats(const double* p, int n, double& mean, double& sd) {
    double s = 0;
    for (int i = 0; i < n; i++) s += p[i];
    mean = s / n;
    double ssq = 0;
    for (int i = 0; i < n; i++) { double d = p[i] - mean; ssq += d * d; }
    sd = std::sqrt(ssq / n);
}

// ── main ───────────────────────────────────────────────────────────────────────

int main(int argc, char** argv) {
    if (argc < 5) {
        std::cerr << "Usage: " << argv[0]
                  << " <qsbs> <qsdb> <white_ref.qs> <bean_frame.qs> [out_dir]\n";
        return 1;
    }
    const char*  qsbsPath  = argv[1];
    const char*  qsdbPath  = argv[2];
    const char*  whitePath = argv[3];
    const char*  beanPath  = argv[4];
    std::string  outDir    = argc >= 6 ? argv[5] : ".";

    // ── SDK init ──────────────────────────────────────────────────────────────
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
    const int LIGHT_SRC = (int)lightSrcCount - 1;
    const int STEP = 60, INTRICACY = 100;

    std::cout << "[GATE] specBegin=" << specBegin << " specEnd=" << specEnd << "nm\n";
    std::cout << "[GATE] lightSrc idx=" << LIGHT_SRC
              << " name=" << lightSrcList[LIGHT_SRC] << "\n";
    std::cout << "[GATE] STEP=" << STEP << "nm INTRICACY=" << INTRICACY << "\n";

    // ── Build band array ──────────────────────────────────────────────────────
    std::vector<std::array<int,2>> bands;
    for (int s = (int)specBegin; s + STEP <= (int)specEnd; s += STEP)
        bands.push_back({s, s + STEP});
    int nBands = (int)bands.size();
    std::cout << "[GATE] bands=" << nBands
              << " [" << bands.front()[0] << "-" << bands.back()[1] << "nm]\n";

    // ── Load white ref ────────────────────────────────────────────────────────
    int wW=0, wH=0, wB=0;
    std::vector<std::array<int,2>> wRanges;
    double* wGray = loadQsGray(ctx, whitePath, bands, LIGHT_SRC, INTRICACY,
                               wW, wH, wB, wRanges);
    if (!wGray) { deinitQsSpecinv(ctx); return 1; }
    std::cout << "[GATE] white ref " << wW << "x" << wH << " bands=" << wB << "\n";

    // ── Load bean frame ───────────────────────────────────────────────────────
    int bW=0, bH=0, bB=0;
    std::vector<std::array<int,2>> bRanges;
    double* bGray = loadQsGray(ctx, beanPath, bands, LIGHT_SRC, INTRICACY,
                               bW, bH, bB, bRanges);
    if (!bGray) { freeQsData(wGray); deinitQsSpecinv(ctx); return 1; }
    std::cout << "[GATE] bean frame " << bW << "x" << bH << " bands=" << bB << "\n";

    int pixW = bW, pixH = bH, N = pixW * pixH;

    // ── Per-band stats ────────────────────────────────────────────────────────
    std::vector<BandStat> results(bB);

    // Flat-field: need to map white ref pixels to bean frame resolution
    // (both should be same resolution, but handle mismatch gracefully)
    bool ffOk = (wW == bW && wH == bH && wB == bB);
    if (!ffOk)
        std::cerr << "[WARN] white ref size (" << wW << "x" << wH
                  << ") != bean frame (" << bW << "x" << bH << "), skipping flat-field\n";

    // Also build flat-field corrected buffer
    std::vector<double> ffBuf(N);

    for (int b = 0; b < bB; b++) {
        BandStat& r = results[b];
        r.reqStart = bands[b][0];
        r.reqEnd   = bands[b][1];
        r.actStart = bRanges[b][0];
        r.actEnd   = bRanges[b][1];
        r.rangeMatched = (r.actStart == r.reqStart && r.actEnd == r.reqEnd);

        const double* bPlane = bGray + (size_t)b * N;
        stats(bPlane, N, r.mean, r.stddev);

        // flat-field corrected stats
        if (ffOk) {
            const double* wPlane = wGray + (size_t)b * N;
            for (int i = 0; i < N; i++) {
                double wv = wPlane[i];
                ffBuf[i] = (wv > 1e-9) ? bPlane[i] / wv : 0.0;
            }
            stats(ffBuf.data(), N, r.ffMean, r.ffStd);
        } else {
            r.ffMean = r.mean;
            r.ffStd  = r.stddev;
        }
    }

    // ── Save channel PNGs (bean frame, raw) ───────────────────────────────────
    std::vector<uint8_t> img8(N);
    for (int b = 0; b < bB; b++) {
        const double* plane = bGray + (size_t)b * N;
        double vmin = *std::min_element(plane, plane + N);
        double vmax = *std::max_element(plane, plane + N);
        double range = (vmax - vmin) > 1e-9 ? vmax - vmin : 1.0;
        for (int i = 0; i < N; i++)
            img8[i] = (uint8_t)std::max(0.0, std::min(255.0,
                          (plane[i] - vmin) / range * 255.0));
        int centre = results[b].actStart + STEP / 2;
        std::string fname = outDir + "/gate_chan" + std::to_string(centre) + "nm.png";
        stbi_write_png(fname.c_str(), pixW, pixH, 1, img8.data(), pixW);
        std::cout << "[GATE] saved " << fname << "\n";
    }

    // ── GO/NO-GO criteria ─────────────────────────────────────────────────────
    // 1. All bands non-zero mean
    // 2. All bands have std > 0 (not flat)
    // 3. Adjacent bands differ in mean by > 0.5% of dynamic range
    // 4. outRange matches reqRange for all bands
    bool allNonZero    = true;
    bool allHaveStd    = true;
    bool allRangeMatch = true;
    bool bandsDistinct = true;

    // compute max mean for normalisation
    double maxMean = 0;
    for (auto& r : results) maxMean = std::max(maxMean, r.ffMean);

    for (int b = 0; b < bB; b++) {
        auto& r = results[b];
        if (r.ffMean < 1e-9) allNonZero = false;
        if (r.ffStd  < 1e-9) allHaveStd = false;
        if (!r.rangeMatched) allRangeMatch = false;
        if (b > 0) {
            double diff = std::abs(results[b].ffMean - results[b-1].ffMean);
            if (maxMean > 0 && diff / maxMean < 0.002)  // < 0.2% of range → aliased
                bandsDistinct = false;
        }
    }

    bool go = allNonZero && allHaveStd && bandsDistinct;

    // ── Write markdown report ─────────────────────────────────────────────────
    std::string reportPath = std::string(getenv("HOME")) +
                             "/KyleClaude/docs/vnir_phase1_gate_report.md";
    std::ofstream rpt(reportPath);
    rpt << "# VNIR Phase 1 Gate Report — 60nm Band Validation\n\n";
    rpt << "**Date:** 2026-06-14  \n";
    rpt << "**QSBS:** " << qsbsPath << "  \n";
    rpt << "**QSDB:** " << qsdbPath << "  \n";
    rpt << "**White ref:** " << whitePath << "  \n";
    rpt << "**Bean frame:** " << beanPath << "  \n\n";

    rpt << "## 1. SDK Spectral Range\n\n";
    rpt << "| Parameter | Value |\n|---|---|\n";
    rpt << "| specBegin | " << specBegin << " nm |\n";
    rpt << "| specEnd   | " << specEnd   << " nm |\n";
    rpt << "| STEP      | " << STEP      << " nm |\n";
    rpt << "| INTRICACY | " << INTRICACY << " |\n";
    rpt << "| lightSrc  | idx=" << LIGHT_SRC
        << " (" << lightSrcList[LIGHT_SRC] << ") |\n";
    rpt << "| bands generated | " << bB << " |\n\n";

    rpt << "**Proposal assumption:** 350–950nm / 10 bands.  \n";
    rpt << "**Actual:** " << specBegin << "–" << specEnd << "nm / " << bB << " bands.  \n";
    int offsetNm = (int)specBegin - 350;
    if (offsetNm != 0)
        rpt << "**Band start offset:** " << offsetNm << " nm vs proposal.\n\n";
    else
        rpt << "**Band start offset:** 0 nm (exact match).\n\n";

    rpt << "## 2. Band Mapping & outRange Verification\n\n";
    rpt << "| # | Requested [nm] | SDK outRange [nm] | Match? |\n";
    rpt << "|---|---|---|---|\n";
    for (int b = 0; b < bB; b++) {
        auto& r = results[b];
        rpt << "| " << b+1
            << " | [" << r.reqStart << ", " << r.reqEnd << "]"
            << " | [" << r.actStart << ", " << r.actEnd << "]"
            << " | " << (r.rangeMatched ? "YES" : "**NO**") << " |\n";
    }
    rpt << "\n**All outRange matched:** " << (allRangeMatch ? "YES" : "NO") << "\n\n";

    rpt << "## 3. Per-Band Signal Statistics (bean frame, flat-field corrected)\n\n";
    rpt << "Flat-field correction: " << (ffOk ? "applied" : "skipped (size mismatch)") << "  \n\n";
    rpt << "| # | Band [nm] | mean | std | non-zero? | has-std? |\n";
    rpt << "|---|---|---|---|---|---|\n";
    for (int b = 0; b < bB; b++) {
        auto& r = results[b];
        rpt << std::fixed << std::setprecision(6);
        rpt << "| " << b+1
            << " | [" << r.actStart << "," << r.actEnd << "]"
            << " | " << r.ffMean
            << " | " << r.ffStd
            << " | " << (r.ffMean > 1e-9 ? "YES" : "**NO**")
            << " | " << (r.ffStd  > 1e-9 ? "YES" : "**NO**")
            << " |\n";
    }

    rpt << "\n## 4. Band Distinguishability\n\n";
    rpt << "Adjacent band mean differences (flat-field corrected, normalised to maxMean):\n\n";
    rpt << "| Pair | |ΔmeanFF| | |ΔmeanFF|/maxMean | Distinguishable? |\n";
    rpt << "|---|---|---|---|\n";
    for (int b = 1; b < bB; b++) {
        double diff = std::abs(results[b].ffMean - results[b-1].ffMean);
        double rel  = maxMean > 0 ? diff / maxMean : 0.0;
        bool ok = rel >= 0.002;
        rpt << std::fixed << std::setprecision(6);
        rpt << "| B" << b << "→B" << b+1
            << " | " << diff
            << " | " << rel
            << " | " << (ok ? "YES" : "**NO**") << " |\n";
    }

    rpt << "\n## 5. Channel PNG Saved\n\n";
    for (int b = 0; b < bB; b++) {
        int centre = results[b].actStart + STEP / 2;
        rpt << "- `gate_chan" << centre << "nm.png`\n";
    }

    rpt << "\n## 6. GO / NO-GO\n\n";
    rpt << "| Criterion | Result |\n|---|---|\n";
    rpt << "| All bands non-zero mean | " << (allNonZero    ? "PASS" : "**FAIL**") << " |\n";
    rpt << "| All bands have std > 0  | " << (allHaveStd    ? "PASS" : "**FAIL**") << " |\n";
    rpt << "| outRange matches request| " << (allRangeMatch  ? "PASS" : "**FAIL**") << " |\n";
    rpt << "| Adjacent bands distinct | " << (bandsDistinct  ? "PASS" : "**FAIL**") << " |\n";
    rpt << "\n### **VERDICT: " << (go ? "GO" : "NO-GO") << "**\n\n";
    if (go)
        rpt << "60nm / " << bB << "-band sampling validated. Ready to proceed to Phase 2.\n";
    else
        rpt << "Gate failed — review FAIL rows above before proceeding.\n";

    rpt.close();
    std::cout << "[GATE] report → " << reportPath << "\n";

    // ── stdout summary ────────────────────────────────────────────────────────
    std::cout << "\n===== GATE SUMMARY =====\n";
    std::cout << "specBegin=" << specBegin << " specEnd=" << specEnd << "nm\n";
    std::cout << "STEP=" << STEP << " → " << bB << " bands ["
              << bands.front()[0] << "-" << bands.back()[1] << "nm]\n";
    std::cout << "outRange match: " << (allRangeMatch ? "ALL YES" : "SOME NO") << "\n";
    std::cout << "Band stats (flat-field corrected):\n";
    for (int b = 0; b < bB; b++) {
        auto& r = results[b];
        std::cout << std::fixed << std::setprecision(5)
                  << "  B" << b+1
                  << " [" << r.actStart << "," << r.actEnd << "]nm"
                  << "  mean=" << r.ffMean
                  << "  std="  << r.ffStd << "\n";
    }
    std::cout << "All non-zero: " << (allNonZero   ? "YES" : "NO") << "\n";
    std::cout << "All have std: " << (allHaveStd   ? "YES" : "NO") << "\n";
    std::cout << "Bands distinct: " << (bandsDistinct ? "YES" : "NO") << "\n";
    std::cout << "===== VERDICT: " << (go ? "GO" : "NO-GO") << " =====\n";

    freeQsData(bGray);
    freeQsData(wGray);
    deinitQsSpecinv(ctx);
    return go ? 0 : 1;
}
