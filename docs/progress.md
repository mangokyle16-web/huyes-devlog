# 每日進度日誌

---

## 2026-05-31

**完成：**
- 新 SDK（OCF_SDK_10Band）完整分析
- 驗證白板過爆問題（1250us 飽和，312us 正常）
- 三種曝光白板 `.ocf` 檔案已製作並轉換（bands_white）
- 分析報告 `OCF_SDK_analysis_report.md` 已完成，準備寄廠商
- 建立 Huyes 分豆機專案 Roadmap
- 建立 Dev Log 網站（本站）

**結論：**
- 新 SDK 因 per-band AGC 問題，無法用於 Agtron 計算（最佳 CV R²=0.18）
- 繼續沿用舊 SDK（R²=0.92），等廠商提供光譜重建版本

**下一步：**
- 寄 OCF 廠商分析報告（A5）
- 採購電子零件 BOM（B1）
- 確認 bean_26/27 黴菌菌落（A2）

---

## 2026-06-01（更新）

**完成：**
- 儲存方案決策：因硬碟與記憶體漲價，放棄實體 NAS，改用 Backblaze B2 雲端儲存
- Plan A Phase 1 全面改寫：Synology DSM 設定 → B2 Bucket 建立 + rclone 掛載
- 所有路徑從 `/Volumes/huyes-data` 更新為 `/Users/kyle/huyes-data`
- RPi5 上傳方式從 `scp` 改為 `rclone copy`
- Spec 硬體表與費用估算更新（NT$12,500 一次性 → ~NT$18/月）
- 設定 RPi5 開機自動啟動 Claude Code（labwc autostart）

**費用比較：**
- 原方案：Synology DS223 + WD Red 4TB×2 = NT$12,500 一次性
- 新方案：B2 ~NT$18/月（100GB），出流量透過 Cloudflare 免費

**下一步：**
- 申請 Backblaze B2 帳號，建立 `huyes-data` bucket
- 帶回 Mac Mini → 安裝 rclone，設定 B2 掛載
- 執行 Plan A Task 3~8（Pocketbase + Caddy + Cloudflare）

---

## 2026-06-01（晚）

**完成：**
- 閱讀並分析論文：Hu et al. 2025, *Siamese networks for few-shot coffee bean defect detection*（LWT 235, 118631）
- 決定將 Siamese 方法移植到多光譜版本（10-band 光譜向量取代 RGB 圖）
- 完成 Siamese 多光譜豆子瑕疵偵測系統完整開發計畫
  - 計畫文件：`docs/superpowers/plans/2026-06-01-siamese-bean-defect.md`
  - Phase 1：採集監控器（RPi5，沿用現有互動式系統）
  - Phase 2：特徵提取 + z-score 標準化 + 配對生成（含 bean-level data split）
  - Phase 3：SiameseMLP 訓練腳本（Mac Mini MPS，預計 30 秒/50 epochs）
  - Phase 4：推理模組（reference-set 比對）
- RPi5 設定開機自動啟動 Claude Code（labwc autostart）

**設計重點：**
- Train/val/test 以 bean_id 切割，避免同一顆豆的 10 次 pass 造成 data leakage
- 每類 50 顆 × 10 次 = 500 樣本/類，超過論文的 240 樣本/類
- Mac Mini Apple Silicon MPS 完全足夠（模型只有 ~15k 參數）

**明天待辦（帶回 Mac Mini）：**
- 安裝 PyTorch + rclone
- 執行 Plan A（Pocketbase + Caddy + Cloudflare + B2 掛載）
- 開始採集第一批豆子資料（至少 normal 類 10 顆）

---

## 2026-05-31（下午）

**完成：**
- 建立 GitHub repo（huyes-devlog）+ Docsify Dev Log 網站上線
- 所有文件供應商名稱 QS → OCF 替換完成（7 個檔案）
- 內部協作平台完整設計：架構 / 安全 / UI / 資料表
  - 架構：Mac Mini（Pocketbase + SvelteKit + Caddy）+ NAS + Cloudflare Tunnel
  - 安全：四層防護（CF Zero Trust / Caddy Rate Limit / PB Auth / NAS 隔離）
  - UI：左側欄 + Dashboard 首頁，四個主頁面（Dashboard / 任務 / 筆記 / 資料庫）
- 設計規格文件：`docs/superpowers/specs/2026-05-31-huyes-platform-design.md`
- Plan A 實作計劃：`docs/superpowers/plans/2026-05-31-huyes-platform-infra.md`

**待採購：**
- Synology DS224+（NT$8,500）+ WD Red Plus 4TB × 2（NT$5,600）= NT$14,100

**下一步（明天）：**
- 帶回 Mac Mini → 執行 Plan A Task 3~8（Pocketbase + Caddy + Cloudflare）
- 確認 domain 名稱給我填入設定檔
- NAS 採購後執行 Task 1~2
