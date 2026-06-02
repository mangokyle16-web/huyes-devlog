# Portrait UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign `multispectral_demo/main.cpp` from landscape 800×480 (preview+sidebar) to portrait 480×800 (circular preview top, 3×3 button grid middle, bottom bar), matching the reference image at `/home/kyle/Downloads/Gemini_Generated_Image_oqb4r7oqb4r7oqb4.png`.

**Architecture:** Replace `drawSidebar()` with `drawPortraitUI()` which renders everything onto a single 480×800 canvas. Touch handling shifts from x-axis (left=preview, right=sidebar) to y-axis (top=preview, middle=grid, bottom=bar). The existing `g_sidebarBtns` vector is reused to store button rects in absolute screen coordinates.

**Tech Stack:** C++17, OpenCV 4.x, `main.cpp` (3777 lines), build via `./build.sh`

**Spec:** `/home/kyle/KyleClaude/docs/superpowers/specs/2026-05-22-portrait-ui-design.md`

---

## File Map

| Action | Path |
|--------|------|
| Modify | `multispectral_demo/main.cpp` |

---

## Task 1: New constants, UV_SCAN BtnTag, and drawPortraitUI function

Insert the new portrait constants, add the new UV_SCAN BtnTag, and insert three new helper entities (GridBtn struct, isBtnActive, isLiveCamMode, drawPortraitUI) after the existing `rrect()` helper. Old code is kept intact so the build still succeeds.

**Files:**
- Modify: `multispectral_demo/main.cpp`

- [ ] **Step 1: Replace constants block (lines 84–88)**

Replace the 5-line constants block with the new portrait constants. Keep `SB_W` and `SB_FULL_H` for now — `drawSidebar` still needs them to compile (removed in Task 4).

Find:
```cpp
static const int SB_W        = 300;   // sidebar width
static const int SB_FULL_H   = 1200;  // internal draw height (sidebar scrolls within this)
static const int DISP_W      = 800;   // 7" DSI display width
static const int DISP_H      = 480;   // 7" DSI display height
static const int DISP_PREV_W = DISP_W - SB_W;  // preview area width = 500
```

Replace with:
```cpp
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
```

- [ ] **Step 2: Add UV_SCAN to BtnTag enum (line ~378)**

Find the end of the BtnTag enum:
```cpp
    QUIT
};
```

Replace with:
```cpp
    UV_SCAN,
    QUIT
};
```

- [ ] **Step 3: Insert new helpers after rrect() (after line ~1125)**

Insert the following block immediately after the closing brace of `rrect()` (the line that reads `}` on approximately line 1125, right before `static cv::Mat drawSidebar`):

```cpp
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
```

- [ ] **Step 4: Build to verify**

```bash
cd /home/kyle/KyleClaude/multispectral_demo && ./build.sh 2>&1 | tail -20
```

Expected: binary compiles without errors. Warnings about DISP_PREV_W being unused are acceptable (it's removed in Task 4).

- [ ] **Step 5: Commit**

```bash
cd /home/kyle/KyleClaude && git add multispectral_demo/main.cpp
git commit -m "feat: add portrait constants, UV_SCAN tag, and drawPortraitUI function

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: Replace render loop and window init to use drawPortraitUI

Swap out the old composite (hconcat preview + sidebar) calls with `drawPortraitUI`.

**Files:**
- Modify: `multispectral_demo/main.cpp`

- [ ] **Step 1: Replace the window init placeholder (around line 2803)**

Find this block (inside the `// Show placeholder immediately` comment block):
```cpp
    {
        cv::Mat ph(DISP_H, DISP_PREV_W, CV_8UC3, cv::Scalar(28, 28, 28));
        cv::putText(ph, "Giga-Image",
                    cv::Point(80, DISP_H / 2 - 10), cv::FONT_HERSHEY_DUPLEX, 1.4,
                    cv::Scalar(60, 220, 100), 2, cv::LINE_AA);
        cv::putText(ph, "Waiting for camera...",
                    cv::Point(60, DISP_H / 2 + 30), cv::FONT_HERSHEY_SIMPLEX, 0.6,
                    cv::Scalar(160, 160, 160), 1, cv::LINE_AA);
        cv::Mat sb = drawSidebar(DISP_H, g_app);
        cv::Mat composite; cv::hconcat(ph, sb, composite);
        g_previewW = DISP_PREV_W;
        cv::imshow(WIN, composite);
        cv::waitKey(1);  // pump Qt events once so window is actually mapped
    }
```

Replace with:
```cpp
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
```

- [ ] **Step 2: Replace the main render loop composite section (around line 3591)**

Find the block starting with `// Rebuild composite (preview + sidebar) and show at native 800×480`:

```cpp
        // Rebuild composite (preview + sidebar) and show at native 800×480
        if (!displayImg.empty()) {
            cv::Mat preview;
            if (g_app.mode == Mode::AGTRON_HISTOGRAM ||
                g_app.mode == Mode::GRIND_HISTOGRAM) {
                // Letterbox: fit histogram preserving aspect ratio, leave 30px for status bar
                const int BAR_H = 30;
                double sw = (double)DISP_PREV_W / displayImg.cols;
                double sh = (double)(DISP_H - BAR_H) / displayImg.rows;
                double s  = std::min(sw, sh);
                int nw = (int)(displayImg.cols * s);
                int nh = (int)(displayImg.rows * s);
                preview = cv::Mat(DISP_H, DISP_PREV_W, CV_8UC3, cv::Scalar(26, 26, 38));
                cv::Mat scaled;
                cv::resize(displayImg, scaled, cv::Size(nw, nh), 0, 0, cv::INTER_AREA);
                int ox = (DISP_PREV_W - nw) / 2;
                int oy = ((DISP_H - BAR_H) - nh) / 2;
                scaled.copyTo(preview(cv::Rect(ox, oy, nw, nh)));
            } else {
                cv::resize(displayImg, preview, cv::Size(DISP_PREV_W, DISP_H),
                           0, 0, cv::INTER_LINEAR);
            }

            // ── Agtron fixed-ROI circle overlay ───────────────────
            if (g_app.agtronRoiMode || g_app.agtronRoiSaved) {
                double sx = (double)DISP_PREV_W / 1600.0;
                double sy = (double)DISP_H / 1200.0;
                int pcx = (int)(g_app.agtronRoiCx * sx);
                int pcy = (int)(g_app.agtronRoiCy * sy);
                int prx = std::max(1, (int)(g_app.agtronRoiR * sx));
                int pry = std::max(1, (int)(g_app.agtronRoiR * sy));
                cv::Scalar col = g_app.agtronRoiMode
                               ? cv::Scalar(0, 165, 255)   // orange
                               : cv::Scalar(0, 220, 60);   // green
                int thick = g_app.agtronRoiMode ? 3 : 2;
                cv::ellipse(preview, {pcx, pcy}, {prx, pry},
                            0, 0, 360, col, thick, cv::LINE_AA);
                if (g_app.agtronRoiMode) {
                    cv::line(preview, {pcx-8, pcy}, {pcx+8, pcy}, col, 1, cv::LINE_AA);
                    cv::line(preview, {pcx, pcy-8}, {pcx, pcy+8}, col, 1, cv::LINE_AA);
                    cv::putText(preview, "Drag to move  Larger/Smaller in sidebar",
                                {4, DISP_H - 34},
                                cv::FONT_HERSHEY_SIMPLEX, 0.32, col, 1, cv::LINE_AA);
                }
            }

            // Mode info bar: semi-transparent strip at bottom of preview
            {
                cv::Mat roi = preview(cv::Rect{0, DISP_H - 26, DISP_PREV_W, 26});
                cv::Mat dark(26, DISP_PREV_W, CV_8UC3, cv::Scalar(0, 0, 0));
                cv::addWeighted(roi, 0.25, dark, 0.75, 0, roi);
                // Mode name (left)
                const char* modeName = g_app.modeName();
                cv::putText(preview, modeName, {8, DISP_H - 9},
                            cv::FONT_HERSHEY_SIMPLEX, 0.38, {220,220,220}, 1, cv::LINE_AA);
                // Exposure (right)
                char expStr[24];
                snprintf(expStr, sizeof(expStr), "%d us", g_app.exposure);
                int base = 0;
                cv::Size ts = cv::getTextSize(expStr, cv::FONT_HERSHEY_SIMPLEX, 0.38, 1, &base);
                cv::putText(preview, expStr, {DISP_PREV_W - ts.width - 8, DISP_H - 9},
                            cv::FONT_HERSHEY_SIMPLEX, 0.38, {160, 160, 160}, 1, cv::LINE_AA);
            }

            cv::Mat sb = drawSidebar(DISP_H, g_app);
            cv::Mat composite;
            cv::hconcat(preview, sb, composite);
            // Thin separator between preview and sidebar
            cv::line(composite, {DISP_PREV_W, 0}, {DISP_PREV_W, DISP_H},
                     cv::Scalar(58, 56, 62), 1);
            g_previewW = DISP_PREV_W;
            cv::imshow(WIN, composite);
        }
```

Replace with:
```cpp
        // Render portrait UI (480×800 single canvas)
        if (!displayImg.empty()) {
            cv::Mat composite = drawPortraitUI(displayImg, g_app);
            cv::imshow(WIN, composite);
        }
```

- [ ] **Step 3: Build to verify**

```bash
cd /home/kyle/KyleClaude/multispectral_demo && ./build.sh 2>&1 | tail -20
```

Expected: clean build. The old `drawSidebar` is still compiled (but never called now). The UI should render portrait layout on device.

- [ ] **Step 4: Commit**

```bash
cd /home/kyle/KyleClaude && git add multispectral_demo/main.cpp
git commit -m "feat: swap render loop to drawPortraitUI, update window init placeholder

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3: Rewrite onMouse and fireSidebarClick for portrait layout

Replace the x-axis sidebar detection with y-axis region detection. Button rects in `g_sidebarBtns` are now absolute screen coordinates (drawPortraitUI stores them that way), so `fireSidebarClick` no longer needs to subtract `g_previewW`.

**Files:**
- Modify: `multispectral_demo/main.cpp`

- [ ] **Step 1: Replace onMouse function (around line 1804)**

Find the entire `onMouse` function (from `static void onMouse(...)` to its closing `}`):

```cpp
static void onMouse(int event, int x, int y, int flags, void* /*userdata*/) {
    const int maxScroll = std::max(0, SB_FULL_H - DISP_H);
    bool onSidebar = (x >= g_previewW);

    // ── Mouse wheel: always handle to prevent OpenCV zoom ──
    if (event == cv::EVENT_MOUSEWHEEL) {
        int delta = cv::getMouseWheelDelta(flags);
        // Only scroll sidebar; preview area has no zoom interaction
        g_sbScrollY = std::clamp(g_sbScrollY - delta / 3, 0, maxScroll);
        return;
    }

    // ── Touch / drag start ────────────────────────────────
    if (event == cv::EVENT_LBUTTONDOWN) {
        if (!onSidebar && g_app.agtronRoiMode) {
            g_app.agtronRoiDragging = true;
            g_app.agtronRoiCx = std::clamp((int)(x * 1600.0 / DISP_PREV_W), 0, 1600);
            g_app.agtronRoiCy = std::clamp((int)(y * 1200.0 / DISP_H),      0, 1200);
            return;
        }
        if (onSidebar) {
            g_touchStartY     = y;
            g_touchScrollBase = g_sbScrollY;
            g_touchDragged    = false;
        }
        return;
    }

    // ── Touch / drag move ─────────────────────────────────
    if (event == cv::EVENT_MOUSEMOVE && (flags & cv::EVENT_FLAG_LBUTTON)) {
        if (g_app.agtronRoiDragging) {
            g_app.agtronRoiCx = std::clamp((int)(x * 1600.0 / DISP_PREV_W), 0, 1600);
            g_app.agtronRoiCy = std::clamp((int)(y * 1200.0 / DISP_H),      0, 1200);
            return;
        }
        if (onSidebar && g_touchStartY >= 0) {
            int dy = g_touchStartY - y;           // positive = scroll down
            if (std::abs(dy) >= DRAG_THRESHOLD) g_touchDragged = true;
            if (g_touchDragged)
                g_sbScrollY = std::clamp(g_touchScrollBase + dy, 0, maxScroll);
        }
        return;
    }

    // ── Touch / drag end: tap → click, drag → just release ─
    if (event == cv::EVENT_LBUTTONUP) {
        if (g_app.agtronRoiDragging) {
            g_app.agtronRoiDragging = false;
            return;
        }
        bool wasDrag = g_touchDragged;
        g_touchStartY  = -1;
        g_touchDragged = false;
        if (!onSidebar || wasDrag) return;
        fireSidebarClick(x, y);
        return;
    }
}
```

Replace with:
```cpp
static void onMouse(int event, int x, int y, int flags, void* /*userdata*/) {
    // Portrait layout: preview top (y<352), grid middle (352–712), bar bottom (>=712)
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
```

- [ ] **Step 2: Update the top of fireSidebarClick (around line 1863)**

Find:
```cpp
static void fireSidebarClick(int x, int y) {
    if (x < g_previewW) return;
    int sx = x - g_previewW;

    for (auto& b : g_sidebarBtns) {
        if (!b.rect.contains({sx, y})) continue;
```

Replace with:
```cpp
static void fireSidebarClick(int x, int y) {
    for (auto& b : g_sidebarBtns) {
        if (!b.rect.contains({x, y})) continue;
```

- [ ] **Step 3: Replace FULL_ANALYSIS case in fireSidebarClick (remove g_analysisPrompt)**

In the `switch (b.tag)` block, find:
```cpp
        case BtnTag::FULL_ANALYSIS:
            if (!g_app.fullAnalysisRunning && g_app.segDaemonReady)
                g_analysisPrompt = 1;  // show Complete/Quick prompt
            break;
```

Replace with:
```cpp
        case BtnTag::FULL_ANALYSIS:
            if (!g_app.fullAnalysisRunning && g_app.segDaemonReady) {
                g_analysisModeQuick = true;
                g_app.fullAnalysisPending = true;
            }
            break;
```

Note: The portrait UI has no space for the Complete/Quick prompt overlay, so CAPTURE now directly triggers quick-mode full analysis.

- [ ] **Step 4: Add UV_SCAN case before `default:` in fireSidebarClick**

Find (near the end of the switch in fireSidebarClick):
```cpp
        // Legacy keyboard-only buttons (kept for T/U/M shortcuts)
```

Insert before that comment:
```cpp
        case BtnTag::UV_SCAN:
            g_app.statusMsg = "UV: run uv_mold_scan.py in terminal";
            break;
```

- [ ] **Step 5: Remove VEG_TOGGLE case from fireSidebarClick**

Find and delete these two lines inside the switch:
```cpp
        case BtnTag::VEG_TOGGLE:
            g_vegExpanded = !g_vegExpanded;
            break;
```

- [ ] **Step 6: Build to verify**

```bash
cd /home/kyle/KyleClaude/multispectral_demo && ./build.sh 2>&1 | tail -20
```

Expected: clean build.

- [ ] **Step 7: Commit**

```bash
cd /home/kyle/KyleClaude && git add multispectral_demo/main.cpp
git commit -m "feat: rewrite onMouse and fireSidebarClick for portrait y-axis regions

- Touch regions now y-based (preview y<352, grid y 352-712, bar y>=712)
- fireSidebarClick uses absolute screen coords (no g_previewW offset)
- CAPTURE triggers quick analysis directly (no prompt overlay)
- Add UV_SCAN button handler, remove VEG_TOGGLE

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: Remove dead code and final build

Delete `drawSidebar`, the old landscape constants, and the now-unused scroll globals. This is pure deletion — no logic changes.

**Files:**
- Modify: `multispectral_demo/main.cpp`

- [ ] **Step 1: Remove SB_W and SB_FULL_H from constants block**

Find (first two lines of the constants block):
```cpp
static const int SB_W        = 300;   // kept: drawSidebar still references it (removed in cleanup)
static const int SB_FULL_H   = 1200;  // kept: drawSidebar still references it (removed in cleanup)
```

Delete both lines.

- [ ] **Step 2: Delete drawSidebar function**

Delete the entire `drawSidebar` function. It starts at:
```cpp
static cv::Mat drawSidebar(int dispH, AppState& app) {
```
and ends at its closing `}` (approximately 632 lines later, right before the `// Portrait UI helpers` comment block inserted in Task 1).

- [ ] **Step 3: Remove dead scroll globals**

Find and delete these three lines (around lines 388–394):
```cpp
static int  g_sbScrollY       = 0;    // sidebar vertical scroll offset (pixels into SB_FULL_H)
```
```cpp
static int  g_touchScrollBase = 0;  // g_sbScrollY value when touch began
```
```cpp
static bool g_vegExpanded     = false; // Vegetation Index section collapsed/expanded
```

Note: `g_touchStartY`, `g_touchDragged`, `g_previewW`, and `DRAG_THRESHOLD` are still used by the new `onMouse` — do NOT delete those.

- [ ] **Step 4: Final build**

```bash
cd /home/kyle/KyleClaude/multispectral_demo && ./build.sh 2>&1
```

Expected: zero errors, zero new warnings about undefined variables. The binary should be at `build/multispectral_demo` (or wherever `build.sh` places it).

- [ ] **Step 5: Smoke test on device**

Run the binary on the RPi5 with the screen connected. Verify:
1. Window opens at 480×800 with portrait layout
2. Circular preview area shows camera feed (top section)
3. 3×3 button grid is visible (middle section)
4. Bottom bar shows EXP-/EXP+ buttons and exposure value
5. Tapping a grid button (e.g. AGTRON) responds (status message appears)
6. Tapping EXP+/EXP- changes the exposure value shown in the status bar

```bash
/home/kyle/KyleClaude/multispectral_demo/build/multispectral_demo \
    /home/kyle/KyleClaude/camera_new.ocfbs \
    /home/kyle/KyleClaude/db_std.ocfdb
```

- [ ] **Step 6: Commit**

```bash
cd /home/kyle/KyleClaude && git add multispectral_demo/main.cpp
git commit -m "refactor: remove drawSidebar and dead landscape globals

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task covering it |
|-----------------|-----------------|
| DISP_W=480, DISP_H=800 | Task 1 Step 1 |
| Status bar (y:0–32), LUX VISIONS + exposure | Task 1 Step 3 (drawPortraitUI §1) |
| Circular preview center=(240,192) radius=140 | Task 1 Step 3 (drawPortraitUI §2) |
| Label bar (y:320–352), mode/agtron/beans | Task 1 Step 3 (drawPortraitUI §3) |
| 3×3 button grid (y:352–712), 160×120 cells | Task 1 Step 3 (drawPortraitUI §4) |
| Button styles: selected `#3a3a5c` + `#7a7aff` border | Task 1 Step 3 (drawPortraitUI §4) |
| All 9 buttons with correct BtnTag mappings | Task 1 Steps 2 & 3 |
| UV_SCAN new BtnTag | Task 1 Step 2 |
| Bottom bar (y:712–800), EXP±, status, STOP | Task 1 Step 3 (drawPortraitUI §5) |
| Touch y<352 → preview ROI | Task 3 Step 1 |
| Touch y∈[352,712) → button grid | Task 3 Step 2 |
| Touch y>=712 → bottom bar | Task 3 Step 2 |
| Camera coord mapping cam_x = x*1600/480 | Task 3 Step 1 |
| Camera coord mapping cam_y = (y-32)*1200/288 | Task 3 Step 1 |
| Remove drawSidebar, SB_W, SB_FULL_H, scroll | Task 4 |
| `hconcat` → single canvas | Task 2 Step 2 |
| Color palette (#1a1a1a, #1e1e2e, etc.) | Task 1 Step 3 (verified with BGR values) |

**Placeholder scan:** None found.

**Type consistency:**
- `drawPortraitUI` takes `const cv::Mat& camImg` — matches all call sites in Task 2 where `displayImg` is passed
- `g_sidebarBtns` reused with `SidebarBtn {cv::Rect rect; BtnTag tag;}` — absolute coords now, `fireSidebarClick` uses `{x,y}` directly ✓
- `GRID_BTNS[9]` rows 0→2 match spec table exactly ✓
- `isBtnActive` covers all 7 tagged active states ✓
