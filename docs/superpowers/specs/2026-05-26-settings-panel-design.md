# Settings Panel — Design Spec
Date: 2026-05-26
Feature: Settings icon + modal panel (language & brightness)

---

## Overview

Add a ⚙ SETTINGS button to the Huyes portrait UI (480×800). Replace the current END/QUIT grid button (position [2,2]) with ⚙/SETTINGS. QUIT moves inside the settings modal. The modal is a semi-transparent overlay that controls language and DSI backlight brightness, with settings persisted to disk.

---

## 1. Data Structure & Config File

### `AppSettings` struct (new, global singleton)

```cpp
enum class Lang        { EN, ZH };
enum class BrightLevel { DARK = 64, MID = 160, BRIGHT = 255 };

struct AppSettings {
    Lang        lang   = Lang::EN;
    BrightLevel bright = BrightLevel::BRIGHT;
    void load();  // reads ~/.config/huyes/settings.json
    void save();  // writes back atomically
};
static AppSettings g_settings;
```

### Config file path
`~/.config/huyes/settings.json`

```json
{ "lang": "en", "brightness": 255 }
```

- `load()` called once at App startup (before `drawPortraitUI` first runs)
- `save()` called immediately on every user change (lang or brightness)
- If file missing or malformed, silently use defaults

---

## 2. Internationalisation (i18n)

### `tr()` function

```cpp
const char* tr(const char* key);
```

- Looks up `key` in a static translation table
- Returns EN or ZH string based on `g_settings.lang`
- Falls back to `key` itself if not found (safe for unknown keys)

### Strings to translate

| Key | English | 中文 |
|-----|---------|------|
| CAPTURE | CAPTURE | 拍攝 |
| AGTRON | AGTRON | 烘焙度 |
| SEGMENT | SEGMENT | 分割 |
| MOLD | MOLD | 黴菌 |
| SPECTRUM | SPECTRUM | 光譜 |
| UV SCAN | UV SCAN | 紫外掃描 |
| ROI | ROI | 感興趣區 |
| WHITE REF | WHITE REF | 白平衡 |
| SETTINGS | SETTINGS | 設定 |
| LANGUAGE | LANGUAGE | 語言 |
| BRIGHTNESS | BRIGHTNESS | 亮度 |
| DARK | DARK | 暗 |
| MID | MID | 中 |
| BRIGHT | BRIGHT | 亮 |
| QUIT | QUIT | 離開 |
| Grayscale | Grayscale | 灰階 |
| Mold Map | Mold Map | 黴菌圖 |
| Agtron Roast | Agtron Roast | 烘焙度 |
| Waiting for camera... | Waiting for camera... | 等待相機... |

`GRID_BTNS` small labels call `tr()`. All hardcoded display strings in `drawPortraitUI` use `tr()`.

---

## 3. Settings Modal UI

### Trigger
- `AppState` gains `bool settingsOpen = false`
- `GRID_BTNS[8]` changes from `{"END","QUIT",BtnTag::QUIT}` → `{"⚙","SETTINGS",BtnTag::SETTINGS_OPEN}`

### New BtnTags
```cpp
SETTINGS_OPEN,
SETTINGS_CLOSE,
LANG_EN, LANG_ZH,
BRIGHT_DARK, BRIGHT_MID, BRIGHT_BRIGHT,
// QUIT already exists — reused inside modal
```

### Modal geometry (within 480×800 canvas)

| Element | x | y | w | h |
|---------|---|---|---|---|
| Backdrop | 0 | 0 | 480 | 800 | (rgba 0,0,0,0.7) |
| Modal box | 60 | 200 | 360 | 220 | bg #1a1a2e, border #444 |
| Title row | 60 | 200 | 360 | 40 | "⚙ SETTINGS" centred |
| Language row | 60 | 240 | 360 | 60 | label + [English][中文] toggles |
| Brightness row | 60 | 300 | 360 | 60 | label + [暗][中][亮] toggles |
| QUIT button | 60 | 360 | 360 | 56 | red tint bg #3a1a1a, text #e07070 |

Active toggle: highlighted bg `#1a3a2a`, text `#7ee8a2`. Inactive: `#252540`, text `#888`.

### Rendering

New function:
```cpp
void drawSettingsModal(cv::Mat& canvas);
```

Called at the end of `drawPortraitUI` when `g_app.settingsOpen == true`. Registers modal buttons into `g_sidebarBtns` (same mechanism as existing buttons).

### Interaction

| Action | Result |
|--------|--------|
| Click ⚙SET grid button | `settingsOpen = true` |
| Click backdrop (outside modal) | `settingsOpen = false` |
| Click `[English]` / `[中文]` | `g_settings.lang = …; g_settings.save()` |
| Click `[暗]` / `[中]` / `[亮]` | `g_settings.bright = …; g_settings.save(); setBacklight(value)` |
| Click ⏻ QUIT | `g_app.running = false` |

`onMouse`: when `settingsOpen == true`, intercepts all clicks. Only modal buttons are processed; clicks outside modal box close it. No click-through to main grid.

### Backlight control

```cpp
void setBacklight(int value) {
    // write value to /sys/class/backlight/6-0045/brightness
    // silently ignore if file not writable
}
```

Backlight node: `/sys/class/backlight/6-0045/brightness` (max 255, confirmed on device).

---

## 4. Brightness Levels

| Label | Value | % of max |
|-------|-------|----------|
| 暗 DARK | 64 | 25% |
| 中 MID | 160 | 63% |
| 亮 BRIGHT | 255 | 100% |

---

## 5. Out of Scope

- More than 2 languages
- Font substitution for CJK (OpenCV's built-in `FONT_HERSHEY_*` does not render CJK glyphs — ZH button labels that cannot render will fall back to transliteration or abbreviated EN. A proper CJK font solution is deferred.)
- Animated slide-in transition for modal

---

## 6. CJK Rendering

OpenCV built-in fonts do not support Chinese. Use `cv::freetype` (confirmed available: `-lopencv_freetype` in SDK) with the device's pre-installed font:

- Font path: `/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf`
- Confirmed present on device, supports Traditional Chinese

Implementation: create a `cv::Ptr<cv::freetype::FreeType2>` singleton at startup. Use it for all `tr()`-sourced strings. Fall back to `cv::putText` (EN) if font load fails.
