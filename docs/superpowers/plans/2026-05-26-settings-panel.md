# Settings Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a ⚙ SETTINGS button to the Huyes portrait UI (480×800) that opens a modal overlay for language (EN/ZH) and DSI backlight brightness (Dark/Mid/Bright), with settings persisted to `~/.config/huyes/settings.json`.

**Architecture:** Single-file edit to `main.cpp` — add `AppSettings` global, `tr()` i18n helper, FreeType2 singleton for CJK rendering, `drawSettingsModal()` overlay function, and new `BtnTag` cases in `fireSidebarClick`. The `GRID_BTNS[8]` slot (was END/QUIT) becomes ⚙/SETTINGS; QUIT moves into the modal. When `g_app.settingsOpen == true`, `drawSettingsModal()` clears `g_sidebarBtns` and re-registers only modal buttons, preventing click-through.

**Tech Stack:** C++17, OpenCV 4.6 (system), `opencv_freetype` module, DroidSansFallbackFull.ttf, `/sys/class/backlight/6-0045/brightness`

---

## File Map

| Action | File | What changes |
|--------|------|-------------|
| Modify | `multispectral_demo/CMakeLists.txt` | Add `opencv_freetype` to link libs |
| Modify | `multispectral_demo/main.cpp` | All feature code (9 tasks below) |

`main.cpp` is a single monolithic file. Each task targets a specific region. Build after every task to catch errors early.

**Build command (run from `multispectral_demo/build/`):**
```bash
cmake --build . --target multispectral_demo 2>&1 | tail -5
```
Expected success output:
```
[100%] Linking CXX executable multispectral_demo
[100%] Built target multispectral_demo
```

---

## Task 1: Add `opencv_freetype` to CMakeLists.txt

**Files:**
- Modify: `multispectral_demo/CMakeLists.txt`

- [ ] **Step 1: Add `opencv_freetype` to the link libraries list**

In `CMakeLists.txt`, find the `target_link_libraries(multispectral_demo ...)` block and add `opencv_freetype` after `${OpenCV_LIBS}`:

```cmake
target_link_libraries(multispectral_demo
    ${LIB_CAMERA}
    ${LIB_FILEIO}
    ${LIB_IMGPROC}
    ${LIB_SPECINV}
    ${LIB_AGRI}
    ${OpenCV_LIBS}
    opencv_freetype
    ${X11_LIBRARIES}
    pthread
    dl
)
```

- [ ] **Step 2: Rebuild to verify the new library links cleanly**

```bash
cd /home/kyle/KyleClaude/multispectral_demo/build
cmake --build . --target multispectral_demo 2>&1 | tail -5
```
Expected: `[100%] Built target multispectral_demo` (no linker errors).

- [ ] **Step 3: Commit**

```bash
cd /home/kyle/KyleClaude
git add multispectral_demo/CMakeLists.txt
git commit -m "build: link opencv_freetype for CJK text rendering"
```

---

## Task 2: Add `AppSettings` struct + `load()`/`save()`

**Files:**
- Modify: `multispectral_demo/main.cpp` — insert after the `#include` block, before the `// Constants` section (around line 64)

- [ ] **Step 1: Add `#include <opencv2/freetype.hpp>` after the existing OpenCV include**

Find this line (around line 61):
```cpp
#include <opencv2/opencv.hpp>
```
Add immediately after it:
```cpp
#include <opencv2/freetype.hpp>
```

- [ ] **Step 2: Add `AppSettings` struct after the includes, before `// ─── Constants ───`**

Insert the following block (after the `#include` section ends, before `// Constants`):

```cpp
// ─────────────────────────────────────────────────────────
// Settings (persisted to ~/.config/huyes/settings.json)
// ─────────────────────────────────────────────────────────

enum class Lang        { EN, ZH };
enum class BrightLevel { DARK = 64, MID = 160, BRIGHT = 255 };

struct AppSettings {
    Lang        lang   = Lang::EN;
    BrightLevel bright = BrightLevel::BRIGHT;

    void load() {
        const char* home = getenv("HOME");
        if (!home) return;
        std::string path = std::string(home) + "/.config/huyes/settings.json";
        std::ifstream f(path);
        if (!f) return;
        std::string line, content;
        while (std::getline(f, line)) content += line;

        auto findStr = [&](const std::string& key) -> std::string {
            auto pos = content.find("\"" + key + "\"");
            if (pos == std::string::npos) return "";
            pos = content.find(':', pos);
            if (pos == std::string::npos) return "";
            pos = content.find('"', pos);
            if (pos == std::string::npos) return "";
            auto end = content.find('"', pos + 1);
            if (end == std::string::npos) return "";
            return content.substr(pos + 1, end - pos - 1);
        };
        auto findInt = [&](const std::string& key) -> int {
            auto pos = content.find("\"" + key + "\"");
            if (pos == std::string::npos) return -1;
            pos = content.find(':', pos);
            if (pos == std::string::npos) return -1;
            pos++;
            while (pos < content.size() &&
                   (content[pos] == ' ' || content[pos] == '\t')) pos++;
            try { return std::stoi(content.substr(pos)); }
            catch (...) { return -1; }
        };

        if (findStr("lang") == "zh") lang = Lang::ZH;
        int b = findInt("brightness");
        if      (b == 64)  bright = BrightLevel::DARK;
        else if (b == 160) bright = BrightLevel::MID;
        else if (b == 255) bright = BrightLevel::BRIGHT;
    }

    void save() const {
        const char* home = getenv("HOME");
        if (!home) return;
        std::string dir = std::string(home) + "/.config/huyes";
        mkdir(dir.c_str(), 0755);
        std::string path = dir + "/settings.json";
        // Write to temp file then rename for atomicity
        std::string tmp = path + ".tmp";
        std::ofstream f(tmp);
        if (!f) return;
        f << "{ \"lang\": \"" << (lang == Lang::ZH ? "zh" : "en")
          << "\", \"brightness\": " << static_cast<int>(bright) << " }\n";
        f.close();
        rename(tmp.c_str(), path.c_str());
    }
};
static AppSettings g_settings;
```

- [ ] **Step 3: Build to verify no compile errors**

```bash
cd /home/kyle/KyleClaude/multispectral_demo/build
cmake --build . --target multispectral_demo 2>&1 | tail -5
```
Expected: `[100%] Built target multispectral_demo`

- [ ] **Step 4: Commit**

```bash
cd /home/kyle/KyleClaude
git add multispectral_demo/main.cpp
git commit -m "feat: add AppSettings struct with load/save for lang and brightness"
```

---

## Task 3: Add FreeType singleton + `ftPut()` helper

**Files:**
- Modify: `multispectral_demo/main.cpp` — insert after the `AppSettings` block from Task 2

- [ ] **Step 1: Add FreeType singleton and helpers immediately after `static AppSettings g_settings;`**

```cpp
// ─────────────────────────────────────────────────────────
// FreeType2 — CJK text rendering
// ─────────────────────────────────────────────────────────

static cv::Ptr<cv::freetype::FreeType2> g_ft;

static void initFreeType() {
    try {
        auto ft = cv::freetype::createFreeType2();
        ft->loadFontData(
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf", 0);
        g_ft = ft;
        std::cout << "[OK] FreeType2 loaded (CJK rendering available)\n";
    } catch (...) {
        g_ft = nullptr;
        std::cout << "[WARN] FreeType2 init failed — falling back to ASCII fonts\n";
    }
}

// Draw text using FreeType if available, otherwise cv::putText.
// org = bottom-left corner of the text (OpenCV convention).
// fontHeight in pixels. thickness=-1 lets FreeType auto-select.
static void ftPut(cv::Mat& img, const std::string& text,
                  cv::Point org, int fontHeight,
                  cv::Scalar color, int thickness = -1) {
    if (!text.empty() && g_ft) {
        g_ft->putText(img, text, org, fontHeight, color,
                      thickness, cv::LINE_AA, false);
    } else {
        double scale = fontHeight / 28.0;
        cv::putText(img, text, org,
                    cv::FONT_HERSHEY_SIMPLEX, scale, color, 1, cv::LINE_AA);
    }
}

// Returns text width in pixels using current font.
static int ftTextWidth(const std::string& text, int fontHeight) {
    if (!text.empty() && g_ft) {
        int baseline = 0;
        cv::Size s = g_ft->getTextSize(text, fontHeight, -1, &baseline);
        return s.width;
    }
    double scale = fontHeight / 28.0;
    int base = 0;
    cv::Size s = cv::getTextSize(text, cv::FONT_HERSHEY_SIMPLEX, scale, 1, &base);
    return s.width;
}
```

- [ ] **Step 2: Build to verify**

```bash
cd /home/kyle/KyleClaude/multispectral_demo/build
cmake --build . --target multispectral_demo 2>&1 | tail -5
```
Expected: `[100%] Built target multispectral_demo`

- [ ] **Step 3: Commit**

```bash
cd /home/kyle/KyleClaude
git add multispectral_demo/main.cpp
git commit -m "feat: add FreeType2 singleton and ftPut helper for CJK rendering"
```

---

## Task 4: Add `tr()` i18n function + `setBacklight()`

**Files:**
- Modify: `multispectral_demo/main.cpp` — insert after `ftTextWidth`, before `// Constants`

- [ ] **Step 1: Add `tr()` immediately after the FreeType block**

```cpp
// ─────────────────────────────────────────────────────────
// i18n — translate UI string based on g_settings.lang
// ─────────────────────────────────────────────────────────

static const char* tr(const char* key) {
    using P = std::pair<const char*, const char*>;
    static const std::unordered_map<std::string, P> T = {
        {"CAPTURE",                {"CAPTURE",                "拍攝"}},
        {"AGTRON",                 {"AGTRON",                 "烘焙度"}},
        {"SEGMENT",                {"SEGMENT",                "分割"}},
        {"MOLD",                   {"MOLD",                   "黴菌"}},
        {"SPECTRUM",               {"SPECTRUM",               "光譜"}},
        {"UV SCAN",                {"UV SCAN",                "紫外掃描"}},
        {"ROI",                    {"ROI",                    "感興趣區"}},
        {"WHITE REF",              {"WHITE REF",              "白平衡"}},
        {"SETTINGS",               {"SETTINGS",               "設定"}},
        {"LANGUAGE",               {"LANGUAGE",               "語言"}},
        {"BRIGHTNESS",             {"BRIGHTNESS",             "亮度"}},
        {"DARK",                   {"DARK",                   "暗"}},
        {"MID",                    {"MID",                    "中"}},
        {"BRIGHT",                 {"BRIGHT",                 "亮"}},
        {"QUIT",                   {"QUIT",                   "離開"}},
        {"Grayscale",              {"Grayscale",              "灰階"}},
        {"Mold Map",               {"Mold Map",               "黴菌圖"}},
        {"Agtron Roast",           {"Agtron Roast",           "烘焙度"}},
        {"Agtron Histogram",       {"Agtron Histogram",       "烘焙分佈"}},
        {"Agtron Pie Chart",       {"Agtron Pie Chart",       "烘焙圓餅"}},
        {"Waiting for camera...", {"Waiting for camera...",  "等待相機..."}},
        {"EXP-",                   {"EXP-",                   "曝光-"}},
        {"EXP+",                   {"EXP+",                   "曝光+"}},
        {"English",                {"English",                "英文"}},
    };
    bool zh = (g_settings.lang == Lang::ZH);
    auto it = T.find(key);
    if (it != T.end()) return zh ? it->second.second : it->second.first;
    return key;
}
```

- [ ] **Step 2: Add `setBacklight()` immediately after `tr()`**

```cpp
// ─────────────────────────────────────────────────────────
// Backlight control — DSI display /sys/class/backlight
// ─────────────────────────────────────────────────────────

static void setBacklight(int value) {
    int fd = ::open("/sys/class/backlight/6-0045/brightness", O_WRONLY);
    if (fd < 0) return;
    std::string s = std::to_string(value) + "\n";
    ::write(fd, s.c_str(), s.size());
    ::close(fd);
}
```

- [ ] **Step 3: Build to verify**

```bash
cd /home/kyle/KyleClaude/multispectral_demo/build
cmake --build . --target multispectral_demo 2>&1 | tail -5
```
Expected: `[100%] Built target multispectral_demo`

- [ ] **Step 4: Add `#include <unordered_map>` to the includes if not already present**

Check if `<unordered_map>` is already included:
```bash
grep "unordered_map" /home/kyle/KyleClaude/multispectral_demo/main.cpp | head -3
```
If not found, add to the includes block:
```cpp
#include <unordered_map>
```

- [ ] **Step 5: Commit**

```bash
cd /home/kyle/KyleClaude
git add multispectral_demo/main.cpp
git commit -m "feat: add tr() i18n function and setBacklight() for DSI"
```

---

## Task 5: Add new `BtnTag` entries + `settingsOpen` to `AppState`

**Files:**
- Modify: `multispectral_demo/main.cpp`

- [ ] **Step 1: Add new BtnTags to the `enum class BtnTag` block**

Find the `enum class BtnTag {` definition (around line 365). Add before the closing `}`:

```cpp
    SETTINGS_OPEN,
    SETTINGS_CLOSE,
    LANG_EN, LANG_ZH,
    BRIGHT_DARK, BRIGHT_MID, BRIGHT_BRIGHT,
```

The end of the enum should look like:
```cpp
    UV_SCAN,
    QUIT,
    SETTINGS_OPEN,
    SETTINGS_CLOSE,
    LANG_EN, LANG_ZH,
    BRIGHT_DARK, BRIGHT_MID, BRIGHT_BRIGHT,
};
```

- [ ] **Step 2: Add `settingsOpen` field to `AppState`**

Find `struct AppState {` (around line 176). Add `settingsOpen` near the other boolean fields:

```cpp
    bool settingsOpen{false};   // settings modal visible
```

A good place is after the existing `bool` group (e.g., after `agtronRoiMode`).

- [ ] **Step 3: Change `GRID_BTNS[8]` from END/QUIT to ⚙/SETTINGS_OPEN**

Find:
```cpp
    {"END", "QUIT",      BtnTag::QUIT},
```
Replace with:
```cpp
    {"SET", tr("SETTINGS"), BtnTag::SETTINGS_OPEN},
```

**Note:** `GRID_BTNS` is `static const` but `tr()` is called at render time (step below), not here. Change to:
```cpp
    {"SET", "SETTINGS",  BtnTag::SETTINGS_OPEN},
```
The label "SETTINGS" is the translation key; `tr("SETTINGS")` is called during rendering in Task 6.

- [ ] **Step 4: Build to verify**

```bash
cd /home/kyle/KyleClaude/multispectral_demo/build
cmake --build . --target multispectral_demo 2>&1 | tail -5
```
Expected: `[100%] Built target multispectral_demo`

- [ ] **Step 5: Commit**

```bash
cd /home/kyle/KyleClaude
git add multispectral_demo/main.cpp
git commit -m "feat: add settings BtnTags, settingsOpen state, swap END for SET button"
```

---

## Task 6: Wire `tr()` into `drawPortraitUI` button rendering

**Files:**
- Modify: `multispectral_demo/main.cpp` — the `drawPortraitUI` function (around line 1174)

- [ ] **Step 1: Change grid button label rendering to use `tr()` + `ftPut()`**

Find the grid rendering loop (around lines 1292–1299):
```cpp
            cv::Size is = cv::getTextSize(gb.icon, cv::FONT_HERSHEY_DUPLEX, 0.70, 1, &base);
            cv::putText(canvas, gb.icon, {bx + (bw - is.width) / 2, by + 55},
                        cv::FONT_HERSHEY_DUPLEX, 0.70,
                        active ? ACCENT : TXT1, 1, cv::LINE_AA);
            cv::Size ls = cv::getTextSize(gb.label, cv::FONT_HERSHEY_SIMPLEX, 0.33, 1, &base);
            cv::putText(canvas, gb.label, {bx + (bw - ls.width) / 2, by + 82},
                        cv::FONT_HERSHEY_SIMPLEX, 0.33,
                        active ? TXT1 : TXT2, 1, cv::LINE_AA);
```

Replace with:
```cpp
            // Icon (short code — always ASCII, use putText)
            cv::Size is = cv::getTextSize(gb.icon, cv::FONT_HERSHEY_DUPLEX, 0.70, 1, &base);
            cv::putText(canvas, gb.icon, {bx + (bw - is.width) / 2, by + 55},
                        cv::FONT_HERSHEY_DUPLEX, 0.70,
                        active ? ACCENT : TXT1, 1, cv::LINE_AA);
            // Label — translated, rendered with FreeType for CJK support
            std::string lbl = tr(gb.label);
            int lw = ftTextWidth(lbl, 12);
            ftPut(canvas, lbl, {bx + (bw - lw) / 2, by + 84},
                  12, active ? TXT1 : TXT2);
```

- [ ] **Step 2: Change bottom bar EXP buttons to use `tr()`**

Find:
```cpp
        cv::putText(canvas, "EXP-", {em.x + 10, em.y + 32},
                    cv::FONT_HERSHEY_SIMPLEX, 0.38, TXT1, 1, cv::LINE_AA);
```
Replace with:
```cpp
        ftPut(canvas, tr("EXP-"), {em.x + 10, em.y + 32}, 13, TXT1);
```

Find:
```cpp
        cv::putText(canvas, "EXP+", {ep.x + 10, ep.y + 32},
                    cv::FONT_HERSHEY_SIMPLEX, 0.38, TXT1, 1, cv::LINE_AA);
```
Replace with:
```cpp
        ftPut(canvas, tr("EXP+"), {ep.x + 10, ep.y + 32}, 13, TXT1);
```

- [ ] **Step 3: Change status bar "HUYES" brand label rendering to use `ftPut()`**

Find (around line 1190):
```cpp
    cv::putText(canvas, "HUYES", {8, 22},
                cv::FONT_HERSHEY_SIMPLEX, 0.45, TXT1, 1, cv::LINE_AA);
```
Replace with:
```cpp
    ftPut(canvas, "HUYES", {8, 22}, 14, TXT1);
```

- [ ] **Step 4: Change mode label (the "Grayscale" / "Mold Map" etc. text in the label bar) to use `tr()` + `ftPut()`**

Find the label bar rendering. Look for where `modeName()` or `modeLabel()` is used in `drawPortraitUI` around line 1259–1270:
```cpp
        cv::putText(canvas, mn, {(DISP_W - ts.width) / 2, 341},
```
The surrounding code reads `modeLabel()` result into a variable (likely `mn`). Update this block to:
```cpp
        std::string mn = tr(modeLabel(app).c_str());
        int mnw = ftTextWidth(mn, 13);
        ftPut(canvas, mn, {(DISP_W - mnw) / 2, 343}, 13, TXT1);
```
(Remove the old `cv::getTextSize` + `cv::putText` calls for `mn`.)

- [ ] **Step 5: Change placeholder "Waiting for camera..." to use `tr()` + `ftPut()`**

Find (around line 2378):
```cpp
        cv::putText(ph, "Waiting for camera...",
                    cv::Point((DISP_W - 200) / 2, DISP_H / 2 + 30),
                    cv::FONT_HERSHEY_SIMPLEX, 0.50,
                    cv::Scalar(160, 160, 160), 1, cv::LINE_AA);
```
Replace with:
```cpp
        std::string waiting = tr("Waiting for camera...");
        int ww = ftTextWidth(waiting, 14);
        ftPut(ph, waiting, cv::Point((DISP_W - ww) / 2, DISP_H / 2 + 30),
              14, cv::Scalar(160, 160, 160));
```

- [ ] **Step 6: Build to verify**

```bash
cd /home/kyle/KyleClaude/multispectral_demo/build
cmake --build . --target multispectral_demo 2>&1 | tail -5
```
Expected: `[100%] Built target multispectral_demo`

- [ ] **Step 7: Commit**

```bash
cd /home/kyle/KyleClaude
git add multispectral_demo/main.cpp
git commit -m "feat: wire tr() and ftPut() into drawPortraitUI for i18n rendering"
```

---

## Task 7: Add `drawSettingsModal()`

**Files:**
- Modify: `multispectral_demo/main.cpp` — add new function before `drawPortraitUI`, and call it at the end of `drawPortraitUI`

- [ ] **Step 1: Add `drawSettingsModal()` immediately before the `drawPortraitUI` function definition**

Find the line:
```cpp
static cv::Mat drawPortraitUI(const cv::Mat& camImg, AppState& app) {
```
Insert this entire function just before it:

```cpp
static void drawSettingsModal(cv::Mat& canvas) {
    // ── Semi-transparent backdrop ──────────────────────────
    cv::Mat dark(canvas.size(), canvas.type(), cv::Scalar(0, 0, 0));
    cv::addWeighted(dark, 0.70, canvas, 0.30, 0, canvas);

    // ── Modal box ─────────────────────────────────────────
    const int MX = 60, MY = 200, MW = 360, MH = 224;
    cv::Rect modal{MX, MY, MW, MH};
    cv::rectangle(canvas, modal, cv::Scalar(26, 26, 46), -1);
    cv::rectangle(canvas, modal, cv::Scalar(80, 80, 100), 1, cv::LINE_AA);

    // ── Title row (MY … MY+40) ────────────────────────────
    cv::rectangle(canvas, cv::Rect{MX, MY, MW, 40},
                  cv::Scalar(20, 20, 38), -1);
    std::string title = std::string("SET  ") + tr("SETTINGS");
    int tw = ftTextWidth(title, 15);
    ftPut(canvas, title, {MX + (MW - tw) / 2, MY + 27}, 15,
          cv::Scalar(60, 220, 100));

    // ── Language row (MY+40 … MY+108) ─────────────────────
    ftPut(canvas, tr("LANGUAGE"),
          {MX + 12, MY + 60}, 12, cv::Scalar(160, 160, 160));

    struct LangBtn { const char* key; bool active; BtnTag tag; int x; };
    LangBtn langBtns[2] = {
        {"English", g_settings.lang == Lang::EN, BtnTag::LANG_EN, MX + 10},
        {"\xe4\xb8\xad\xe6\x96\x87",  // "中文" UTF-8
         g_settings.lang == Lang::ZH, BtnTag::LANG_ZH, MX + 190},
    };
    for (auto& lb : langBtns) {
        cv::Rect r{lb.x, MY + 66, 170, 34};
        cv::Scalar bg  = lb.active ? cv::Scalar(26, 58, 26) : cv::Scalar(37, 37, 64);
        cv::Scalar txt = lb.active ? cv::Scalar(60, 220, 100) : cv::Scalar(136, 136, 136);
        cv::Scalar bdr = lb.active ? cv::Scalar(60, 150, 60) : cv::Scalar(60, 60, 90);
        cv::rectangle(canvas, r, bg, -1);
        cv::rectangle(canvas, r, bdr, 1);
        int lw = ftTextWidth(lb.key, 14);
        ftPut(canvas, lb.key, {r.x + (r.width - lw) / 2, r.y + 24}, 14, txt);
        g_sidebarBtns.push_back({r, lb.tag});
    }

    // ── Brightness row (MY+108 … MY+176) ──────────────────
    ftPut(canvas, tr("BRIGHTNESS"),
          {MX + 12, MY + 122}, 12, cv::Scalar(160, 160, 160));

    struct BrightBtn { const char* key; BrightLevel level; BtnTag tag; int x; };
    BrightBtn brightBtns[3] = {
        {tr("DARK"),   BrightLevel::DARK,   BtnTag::BRIGHT_DARK,   MX + 10},
        {tr("MID"),    BrightLevel::MID,    BtnTag::BRIGHT_MID,    MX + 130},
        {tr("BRIGHT"), BrightLevel::BRIGHT, BtnTag::BRIGHT_BRIGHT, MX + 250},
    };
    for (auto& bb : brightBtns) {
        bool active = (g_settings.bright == bb.level);
        cv::Rect r{bb.x, MY + 128, 110, 34};
        cv::Scalar bg  = active ? cv::Scalar(26, 58, 26) : cv::Scalar(37, 37, 64);
        cv::Scalar txt = active ? cv::Scalar(60, 220, 100) : cv::Scalar(136, 136, 136);
        cv::Scalar bdr = active ? cv::Scalar(60, 150, 60) : cv::Scalar(60, 60, 90);
        cv::rectangle(canvas, r, bg, -1);
        cv::rectangle(canvas, r, bdr, 1);
        int bw2 = ftTextWidth(bb.key, 14);
        ftPut(canvas, bb.key, {r.x + (r.width - bw2) / 2, r.y + 24}, 14, txt);
        g_sidebarBtns.push_back({r, bb.tag});
    }

    // ── QUIT button (MY+176 … MY+224) ─────────────────────
    cv::Rect qr{MX + 10, MY + 178, MW - 20, 36};
    cv::rectangle(canvas, qr, cv::Scalar(50, 20, 20), -1);
    cv::rectangle(canvas, qr, cv::Scalar(120, 60, 60), 1);
    std::string ql = tr("QUIT");
    int qw = ftTextWidth(ql, 15);
    ftPut(canvas, ql, {qr.x + (qr.width - qw) / 2, qr.y + 25}, 15,
          cv::Scalar(100, 100, 220));
    g_sidebarBtns.push_back({qr, BtnTag::QUIT});

    // ── Backdrop close regions (outside modal box) ─────────
    // These are added AFTER modal buttons so modal buttons match first.
    if (MY > 0)
        g_sidebarBtns.push_back({{0, 0, DISP_W, MY},
                                   BtnTag::SETTINGS_CLOSE});
    if (MY + MH < DISP_H)
        g_sidebarBtns.push_back({{0, MY + MH, DISP_W, DISP_H - MY - MH},
                                   BtnTag::SETTINGS_CLOSE});
    if (MX > 0)
        g_sidebarBtns.push_back({{0, MY, MX, MH},
                                   BtnTag::SETTINGS_CLOSE});
    if (MX + MW < DISP_W)
        g_sidebarBtns.push_back({{MX + MW, MY, DISP_W - MX - MW, MH},
                                   BtnTag::SETTINGS_CLOSE});
}
```

- [ ] **Step 2: Call `drawSettingsModal()` at the end of `drawPortraitUI`, before `return canvas`**

Find the `return canvas;` at the end of `drawPortraitUI` and add before it:

```cpp
    // ── Settings modal overlay (when active) ──────────────
    if (app.settingsOpen) {
        g_sidebarBtns.clear();   // remove grid + bottom bar buttons
        drawSettingsModal(canvas);
    }

    return canvas;
```

- [ ] **Step 3: Build to verify**

```bash
cd /home/kyle/KyleClaude/multispectral_demo/build
cmake --build . --target multispectral_demo 2>&1 | tail -5
```
Expected: `[100%] Built target multispectral_demo`

- [ ] **Step 4: Commit**

```bash
cd /home/kyle/KyleClaude
git add multispectral_demo/main.cpp
git commit -m "feat: add drawSettingsModal overlay with language and brightness controls"
```

---

## Task 8: Wire `fireSidebarClick` + `onMouse` intercept

**Files:**
- Modify: `multispectral_demo/main.cpp` — the `fireSidebarClick` function (around line 1434)

- [ ] **Step 1: Add cases for new BtnTags in `fireSidebarClick`**

Find the `switch (b.tag)` inside `fireSidebarClick`. Add these cases (a good place is after the `case BtnTag::UV_SCAN:` case and before `case BtnTag::QUIT:`):

```cpp
        case BtnTag::SETTINGS_OPEN:
            g_app.settingsOpen = true;
            break;

        case BtnTag::SETTINGS_CLOSE:
            g_app.settingsOpen = false;
            break;

        case BtnTag::LANG_EN:
            g_settings.lang = Lang::EN;
            g_settings.save();
            break;

        case BtnTag::LANG_ZH:
            g_settings.lang = Lang::ZH;
            g_settings.save();
            break;

        case BtnTag::BRIGHT_DARK:
            g_settings.bright = BrightLevel::DARK;
            g_settings.save();
            setBacklight(static_cast<int>(BrightLevel::DARK));
            break;

        case BtnTag::BRIGHT_MID:
            g_settings.bright = BrightLevel::MID;
            g_settings.save();
            setBacklight(static_cast<int>(BrightLevel::MID));
            break;

        case BtnTag::BRIGHT_BRIGHT:
            g_settings.bright = BrightLevel::BRIGHT;
            g_settings.save();
            setBacklight(static_cast<int>(BrightLevel::BRIGHT));
            break;
```

- [ ] **Step 2: Add `settingsOpen` guard at the top of `onMouse` to block ROI dragging when modal is open**

Find `onMouse` function. After the first line (`if (event == cv::EVENT_MOUSEWHEEL) return;`), add:

```cpp
    // When settings modal is open, block all non-click events
    // (ROI dragging, etc.) to prevent interaction with background UI.
    if (g_app.settingsOpen &&
        event != cv::EVENT_LBUTTONUP && event != cv::EVENT_LBUTTONDOWN)
        return;
```

- [ ] **Step 3: Build to verify**

```bash
cd /home/kyle/KyleClaude/multispectral_demo/build
cmake --build . --target multispectral_demo 2>&1 | tail -5
```
Expected: `[100%] Built target multispectral_demo`

- [ ] **Step 4: Commit**

```bash
cd /home/kyle/KyleClaude
git add multispectral_demo/main.cpp
git commit -m "feat: wire fireSidebarClick cases for settings, language, and brightness"
```

---

## Task 9: Startup wiring — load settings, set backlight, init FreeType

**Files:**
- Modify: `multispectral_demo/main.cpp` — the `main()` function startup sequence

- [ ] **Step 1: Call `g_settings.load()`, `setBacklight()`, and `initFreeType()` at App startup**

Find the startup sequence in `main()`. Look for the line that prints `=== Multispectral Camera Demo ===` (around line 2270). Add immediately after that block (after the calibration/DB paths are printed):

```cpp
    // ── Load persisted settings ────────────────────────────
    g_settings.load();
    setBacklight(static_cast<int>(g_settings.bright));
    initFreeType();
```

- [ ] **Step 2: Build final binary**

```bash
cd /home/kyle/KyleClaude/multispectral_demo/build
cmake --build . --target multispectral_demo 2>&1 | tail -5
```
Expected: `[100%] Built target multispectral_demo`

- [ ] **Step 3: Commit**

```bash
cd /home/kyle/KyleClaude
git add multispectral_demo/main.cpp
git commit -m "feat: wire settings load, backlight, and FreeType init at startup"
```

---

## Task 10: Run & Visual Verification

- [ ] **Step 1: Launch App**

```bash
SDK=/home/kyle/KyleClaude/sdk_extract/linux-sdk-arm64/qssdk-20250817
LD_LIBRARY_PATH=$SDK/libarm64/opencv/lib:$SDK/libarm64/spinvcore:$SDK/libarm64:$SDK:$LD_LIBRARY_PATH \
  DISPLAY=:0 WAYLAND_DISPLAY=wayland-0 \
  /home/kyle/KyleClaude/multispectral_demo/build/multispectral_demo \
  /home/kyle/KyleClaude/camera_new.ocfbs \
  /home/kyle/KyleClaude/db_std.ocfdb > /tmp/msdemo.log 2>&1 &
sleep 6 && grim -o DSI-1 /tmp/verify_main.png
```

- [ ] **Step 2: Verify main screen — check SET button replaces END**

Read `/tmp/verify_main.png` and confirm:
- Bottom-right grid cell shows "SET" icon and "SETTINGS" label (or "設定" if ZH)
- No "END" / "QUIT" visible in the main grid

- [ ] **Step 3: Test settings modal — click SET button on DSI screen, then screenshot**

After clicking the SET button on device:
```bash
sleep 3 && grim -o DSI-1 /tmp/verify_modal.png
```
Confirm in `/tmp/verify_modal.png`:
- Semi-transparent backdrop covering main UI
- Modal box visible with LANGUAGE and BRIGHTNESS rows
- Active language button highlighted green
- Active brightness button highlighted green
- QUIT button at the bottom of modal

- [ ] **Step 4: Test language switch**

On device: tap 中文 in the modal. After ~1 second:
```bash
grim -o DSI-1 /tmp/verify_zh.png
```
Confirm: button labels switch to Chinese (拍攝, 烘焙度, 分割 etc.), 中文 button is highlighted.

- [ ] **Step 5: Test brightness change**

On device: tap 暗 in the modal. DSI backlight should visibly dim.
Verify settings file saved:
```bash
cat ~/.config/huyes/settings.json
```
Expected: `{ "lang": "zh", "brightness": 64 }` (or whatever was last set)

- [ ] **Step 6: Test persistence — kill and relaunch App**

```bash
kill $(pgrep multispectral_demo)
sleep 2
SDK=/home/kyle/KyleClaude/sdk_extract/linux-sdk-arm64/qssdk-20250817
LD_LIBRARY_PATH=$SDK/libarm64/opencv/lib:$SDK/libarm64/spinvcore:$SDK/libarm64:$SDK:$LD_LIBRARY_PATH \
  DISPLAY=:0 WAYLAND_DISPLAY=wayland-0 \
  /home/kyle/KyleClaude/multispectral_demo/build/multispectral_demo \
  /home/kyle/KyleClaude/camera_new.ocfbs \
  /home/kyle/KyleClaude/db_std.ocfdb > /tmp/msdemo.log 2>&1 &
sleep 6 && grim -o DSI-1 /tmp/verify_persist.png
```
Confirm: language and brightness from previous session are restored on relaunch.

- [ ] **Step 7: Commit final state**

```bash
cd /home/kyle/KyleClaude
git add multispectral_demo/main.cpp multispectral_demo/CMakeLists.txt
git commit -m "feat: settings panel complete — lang/brightness modal with persistence"
```
