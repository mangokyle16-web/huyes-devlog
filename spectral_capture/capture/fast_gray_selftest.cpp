#include "fast_gray.h"

#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <vector>

namespace {
constexpr int kRawW = 1600;
constexpr int kRawH = 1200;

void putLe16(uint8_t* dst, uint16_t value) {
    dst[0] = static_cast<uint8_t>(value & 0xff);
    dst[1] = static_cast<uint8_t>((value >> 8) & 0xff);
}

void fillRamp(uint8_t* raw) {
    for (int y = 0; y < kRawH; ++y) {
        for (int x = 0; x < kRawW; ++x) {
            uint16_t v = static_cast<uint16_t>(67 + ((x + y) % (1024 - 67)));
            putLe16(raw + (static_cast<size_t>(y) * kRawW + x) * 2, v);
        }
    }
}

void assertNonDegenerate(const uint8_t* gray, int w, int h) {
    uint8_t lo = gray[0];
    uint8_t hi = gray[0];
    for (size_t i = 1, n = static_cast<size_t>(w) * h; i < n; ++i) {
        if (gray[i] < lo) lo = gray[i];
        if (gray[i] > hi) hi = gray[i];
    }
    assert(hi > lo);
}
}  // namespace

int main() {
    std::vector<uint8_t> qs(8 + static_cast<size_t>(kRawW) * kRawH * 2);
    std::memcpy(qs.data(), "LLSQ", 4);
    fillRamp(qs.data() + 8);

    uint8_t* gray = nullptr;
    int w = 0;
    int h = 0;
    assert(fastGrayFromRaw(qs.data(), qs.size(), &gray, &w, &h));
    assert(gray != nullptr);
    assert(w == 533);
    assert(h == 400);
    assertNonDegenerate(gray, w, h);
    std::free(gray);

    std::vector<uint8_t> raw(static_cast<size_t>(kRawW) * kRawH * 2);
    fillRamp(raw.data());
    gray = nullptr;
    w = 0;
    h = 0;
    assert(fastGrayFromRaw(raw.data(), raw.size(), &gray, &w, &h));
    assert(gray != nullptr);
    assert(w == 533);
    assert(h == 400);
    assertNonDegenerate(gray, w, h);
    std::free(gray);

    std::cout << "fast_gray_selftest PASS\n";
    return 0;
}
