/**
 * qs_to_bands: Convert one .qs frame into the Phase 1 VNIR 10-band cube.
 *
 * Usage:
 *   qs_to_bands <qsbs> <qsdb> <qs_file> [output.bin] [intricacy] [light_source]
 *
 * Output format:
 *   [n_bands:uint32 LE][width:uint32 LE][height:uint32 LE][dtype:uint32 LE=4]
 *   [band_data: float32 x n_bands x height x width]
 *
 * Band order:
 *   B1 350-410 nm, B2 410-470 nm, B3 470-530 nm, B4 530-590 nm,
 *   B5 590-650 nm, B6 650-710 nm, B7 710-770 nm, B8 770-830 nm,
 *   B9 830-890 nm, B10 890-950 nm.
 */
extern "C" {
#include "qs_fileio.h"
#include "qs_specinv.h"
}

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

namespace {

constexpr int kBandNum = 10;
constexpr int kBandRanges[kBandNum][2] = {
    {350, 410},
    {410, 470},
    {470, 530},
    {530, 590},
    {590, 650},
    {650, 710},
    {710, 770},
    {770, 830},
    {830, 890},
    {890, 950},
};

void writeU32(FILE* fp, uint32_t v) {
    fwrite(&v, sizeof(v), 1, fp);
}

bool writeCube(const char* path, const float* data, int width, int height) {
    FILE* fp = std::strcmp(path, "-") == 0 ? stdout : std::fopen(path, "wb");
    if (!fp) {
        std::fprintf(stderr, "[qs_to_bands] ERROR: cannot open output %s\n", path);
        return false;
    }
    writeU32(fp, static_cast<uint32_t>(kBandNum));
    writeU32(fp, static_cast<uint32_t>(width));
    writeU32(fp, static_cast<uint32_t>(height));
    writeU32(fp, 4);
    const size_t n = static_cast<size_t>(kBandNum) * width * height;
    const bool ok = std::fwrite(data, sizeof(float), n, fp) == n;
    if (std::strcmp(path, "-") != 0) {
        std::fclose(fp);
    } else {
        std::fflush(fp);
    }
    if (!ok) {
        std::fprintf(stderr, "[qs_to_bands] ERROR: short write to %s\n", path);
    }
    return ok;
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc < 4) {
        std::fprintf(stderr,
                     "Usage: %s <qsbs> <qsdb> <qs_file> [output.bin] [intricacy] [light_source]\n",
                     argv[0]);
        return 1;
    }

    const char* qsbsPath = argv[1];
    const char* qsdbPath = argv[2];
    const char* qsPath = argv[3];
    const char* outPath = argc >= 5 ? argv[4] : "/dev/shm/vnir_bands.bin";
    const int intricacy = argc >= 6 ? std::atoi(argv[5]) : 100;

    uint8_t* qsbsData = nullptr;
    size_t qsbsSize = 0;
    QsErrorcodes err = loadQsbsFile(qsbsPath, &qsbsData, &qsbsSize);
    if (err != QS_ERR_SUCCESS || !qsbsData) {
        std::fprintf(stderr, "[qs_to_bands] ERROR: loadQsbsFile %s err=%d\n", qsbsPath, err);
        return 1;
    }

    QsSpecinvContext* ctx = nullptr;
    size_t specBegin = 0;
    size_t specEnd = 0;
    char** lightSourceList = nullptr;
    size_t lightSourceSize = 0;
    err = initQsSpecinv(&ctx, qsbsData, qsbsSize, qsdbPath,
                        &specBegin, &specEnd,
                        &lightSourceList, &lightSourceSize);
    freeQsData(qsbsData);
    if (err != QS_ERR_SUCCESS || !ctx) {
        std::fprintf(stderr, "[qs_to_bands] ERROR: initQsSpecinv err=%d\n", err);
        return 1;
    }

    if (specBegin > 350 || specEnd < 950) {
        std::fprintf(stderr,
                     "[qs_to_bands] ERROR: SDK spectral range %zu-%zu nm does not cover 350-950 nm\n",
                     specBegin, specEnd);
        deinitQsSpecinv(ctx);
        return 1;
    }

    int lightSource = -1;
    if (argc >= 7) {
        lightSource = std::atoi(argv[6]);
    } else if (lightSourceSize > 0) {
        lightSource = static_cast<int>(lightSourceSize) - 1;
    }
    if (lightSource < -1 || lightSource >= static_cast<int>(lightSourceSize)) {
        std::fprintf(stderr,
                     "[qs_to_bands] ERROR: light_source=%d out of range, count=%zu\n",
                     lightSource, lightSourceSize);
        deinitQsSpecinv(ctx);
        return 1;
    }

    uint8_t* qsData = nullptr;
    size_t qsSize = 0;
    err = loadQsFile(qsPath, &qsData, &qsSize);
    if (err != QS_ERR_SUCCESS || !qsData) {
        std::fprintf(stderr, "[qs_to_bands] ERROR: loadQsFile %s err=%d\n", qsPath, err);
        deinitQsSpecinv(ctx);
        return 1;
    }

    uint8_t* qsiData = nullptr;
    size_t qsiSize = 0;
    err = qsToQsi(ctx, qsData, qsSize,
                  lightSource,
                  intricacy,
                  kBandRanges,
                  kBandNum,
                  &qsiData,
                  &qsiSize);
    freeQsData(qsData);
    if (err != QS_ERR_SUCCESS || !qsiData) {
        std::fprintf(stderr, "[qs_to_bands] ERROR: qsToQsi err=%d\n", err);
        deinitQsSpecinv(ctx);
        return 1;
    }

    double* grayData = nullptr;
    int width = 0;
    int height = 0;
    int (*outRange)[2] = nullptr;
    int outBandNum = 0;
    err = qsiToGray(qsiData, qsiSize, 1.0,
                    &grayData, &width, &height,
                    &outRange, &outBandNum);
    freeQsData(qsiData);
    if (err != QS_ERR_SUCCESS || !grayData) {
        std::fprintf(stderr, "[qs_to_bands] ERROR: qsiToGray err=%d\n", err);
        if (outRange) freeQsData(outRange);
        deinitQsSpecinv(ctx);
        return 1;
    }
    if (outBandNum != kBandNum || width <= 0 || height <= 0) {
        std::fprintf(stderr,
                     "[qs_to_bands] ERROR: unexpected qsi shape bands=%d width=%d height=%d\n",
                     outBandNum, width, height);
        freeQsData(grayData);
        if (outRange) freeQsData(outRange);
        deinitQsSpecinv(ctx);
        return 1;
    }

    bool rangesMatch = true;
    if (outRange) {
        for (int i = 0; i < kBandNum; ++i) {
            if (outRange[i][0] != kBandRanges[i][0] ||
                outRange[i][1] != kBandRanges[i][1]) {
                rangesMatch = false;
            }
        }
    }
    if (!rangesMatch) {
        std::fprintf(stderr, "[qs_to_bands] WARN: SDK returned band ranges differ from request\n");
    }

    const size_t n = static_cast<size_t>(kBandNum) * width * height;
    std::vector<float> f32(n);
    for (size_t i = 0; i < n; ++i) {
        f32[i] = static_cast<float>(grayData[i]);
    }

    const bool ok = writeCube(outPath, f32.data(), width, height);
    std::fprintf(stderr,
                 "[qs_to_bands] %s W=%d H=%d bands=%d range=%zu-%zu light_source=%d intricacy=%d\n",
                 ok ? "OK" : "ERROR", width, height, kBandNum,
                 specBegin, specEnd, lightSource, intricacy);

    freeQsData(grayData);
    if (outRange) freeQsData(outRange);
    deinitQsSpecinv(ctx);
    return ok ? 0 : 1;
}
