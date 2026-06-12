#ifndef SPECTRAL_CAPTURE_CAPTURE_FAST_GRAY_H_
#define SPECTRAL_CAPTURE_CAPTURE_FAST_GRAY_H_

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <vector>

namespace fast_gray_detail {
constexpr int kRawW = 1600;
constexpr int kRawH = 1200;
constexpr int kMosaicN = 3;
constexpr int kOutW = kRawW / kMosaicN;
constexpr int kOutH = kRawH / kMosaicN;
constexpr size_t kRawBytes = static_cast<size_t>(kRawW) * kRawH * 2;

inline uint16_t readLe16(const uint8_t* p) {
    return static_cast<uint16_t>(p[0] | (static_cast<uint16_t>(p[1]) << 8));
}

inline const uint8_t* rawPayloadFromQs(const uint8_t* qsData, size_t qsSize) {
    if (!qsData) return nullptr;
    if (qsSize == kRawBytes) return qsData;
    if (qsSize >= 8 + kRawBytes && std::memcmp(qsData, "LLSQ", 4) == 0) {
        return qsData + 8;
    }
    return nullptr;
}

inline uint8_t stretchToU8(uint16_t value, int low, int high) {
    if (high <= low) {
        return static_cast<uint8_t>(std::min<int>(255, value >> 2));
    }
    if (value <= low) return 0;
    if (value >= high) return 255;
    const int scaled = ((static_cast<int>(value) - low) * 255 + (high - low) / 2) /
                       (high - low);
    return static_cast<uint8_t>(std::max(0, std::min(255, scaled)));
}
}  // namespace fast_gray_detail

inline bool fastGrayFromRaw(const uint8_t* qsData, size_t qsSize,
                            uint8_t** out, int* w, int* h) {
    if (!out || !w || !h) return false;
    *out = nullptr;
    *w = 0;
    *h = 0;

    const uint8_t* raw = fast_gray_detail::rawPayloadFromQs(qsData, qsSize);
    if (!raw) return false;

    constexpr int outW = fast_gray_detail::kOutW;
    constexpr int outH = fast_gray_detail::kOutH;
    constexpr size_t outPixels = static_cast<size_t>(outW) * outH;

    std::vector<uint16_t> avg(outPixels);

#pragma omp parallel for schedule(static)
    for (int oy = 0; oy < outH; ++oy) {
        for (int ox = 0; ox < outW; ++ox) {
            uint32_t sum = 0;
            const int rawY = oy * fast_gray_detail::kMosaicN;
            const int rawX = ox * fast_gray_detail::kMosaicN;
            for (int dy = 0; dy < fast_gray_detail::kMosaicN; ++dy) {
                const size_t rowBase =
                    (static_cast<size_t>(rawY + dy) * fast_gray_detail::kRawW + rawX) * 2;
                for (int dx = 0; dx < fast_gray_detail::kMosaicN; ++dx) {
                    sum += fast_gray_detail::readLe16(raw + rowBase + dx * 2);
                }
            }
            avg[static_cast<size_t>(oy) * outW + ox] =
                static_cast<uint16_t>(sum / (fast_gray_detail::kMosaicN *
                                             fast_gray_detail::kMosaicN));
        }
    }

    std::array<size_t, 256> hist{};
    for (uint16_t v : avg) {
        ++hist[std::min<size_t>(255, v >> 2)];
    }

    const size_t lowTarget = outPixels / 100;
    const size_t highTarget = (outPixels * 99) / 100;
    size_t cumulative = 0;
    int lowBin = 0;
    int highBin = 255;
    bool sawLow = false;
    for (int i = 0; i < 256; ++i) {
        cumulative += hist[static_cast<size_t>(i)];
        if (!sawLow && cumulative >= lowTarget) {
            lowBin = i;
            sawLow = true;
        }
        if (cumulative >= highTarget) {
            highBin = i;
            break;
        }
    }

    const int low = lowBin * 4;
    const int high = highBin * 4 + 3;
    uint8_t* gray = static_cast<uint8_t*>(std::malloc(outPixels));
    if (!gray) return false;

#pragma omp parallel for schedule(static)
    for (int i = 0; i < static_cast<int>(outPixels); ++i) {
        gray[i] = fast_gray_detail::stretchToU8(avg[static_cast<size_t>(i)], low, high);
    }

    *out = gray;
    *w = outW;
    *h = outH;
    return true;
}

#endif  // SPECTRAL_CAPTURE_CAPTURE_FAST_GRAY_H_
