# 每日進度日誌

---

## 2026-06-06

**完成：**
- 夜間自主提案：提案 05（光譜溯源護照）、提案 06（手機遠端採集指揮台）生成並 push
- **手機遠端採集指揮台完整實作**（提案 06）：
  - `spectral_capture/control_server.py`：FastAPI start/stop/status API（TDD，15/15 tests pass）
  - `spectral_capture/ui/index.html`：深色主題手機 Web UI，vanilla JS，3 秒自動更新
  - Pi5 systemd service `huyes-control` 設定開機自啟
- **Tailscale 遠端存取設定完成**：
  - Mac Mini 安裝 Tailscale，與 iPhone + Pi5 同一網路
  - VNC 螢幕共享設定，iPhone 透過 RealVNC 成功連線 Mac Mini 桌面
- 個資安全：移除 git 記錄中的 Tailscale IP

**Pi5 採集指揮台使用方式：**
- 手機瀏覽器開 `http://raspberrypi.local:8765`（同 WiFi）
- 外出透過 Tailscale IP 連線

**累計採集：** 812 筆豆子光譜向量

**下一步：**
- 繼續採集更多樣本（目標每品種 1000+ 筆）
- Siamese MLP Phase 2（特徵提取 + pair generation）
- 評估 qsToQab 優化（降低 20s 瓶頸）

---

## 2026-06-05（晚）

**完成：**
- 分析皮帶輸送速度：實測 **4.6 cm/s**，計算多光譜相機需求 **≥ 13 fps**（但實際受 SDK 計算瓶頸限制）
- 完整建立 Pi5 多光譜擷取 pipeline（`spectral_capture/` 目錄）：
  - `qab_parser.py`、`bean_detector.py`（NIR Otsu 分割）、`frame_reader.py`（subprocess driver）
  - `collector.py`（SQLite）、`main.py` 端到端（stub 模式 11/11 tests pass）
- 偵測並排除多個 SDK 問題：
  - `uvc_fix.so` LD_PRELOAD 解決 UVC 裝置初始化
  - `freeQsData()` 是所有 SDK buffer 的正確釋放函式
  - `registerQsCameraCallback + openQsCamera(true)` 為正確的 async 模式
  - `qsToQab` 速度瓶頸：17-20 秒/幀（OpenCV guided filter on Pi5）
- 架構轉向：改用 `capture_one` + `qs_file_processor` 異步管線
  - `capture_one`：0.5 秒/幀擷取 .qs 檔案
  - `qs_file_processor`：C++ 批次處理器，輸出 float32 binary
  - `capture_pipeline.py`：整合 Python 管線 + SQLite 記錄
- **實際採集成果：46 幀，720 筆豆子光譜向量寫入 SQLite** ✅
- 今日 Git commits：17 個（多光譜 pipeline 完整實作）

**關鍵發現：**
- CM020D SDK 版本：QS02-V01.1.251217D-CM020D-L
- QAB 格式：LLBA header + 5-band agriculture data（450/560/650/730/840nm）
- `qsToQab` 在 Pi5 需要 10-20 秒（OpenCV guided filter 未最佳化）
- 植被指數（NDVI/GNDVI/NDRE/OSAVI/LCI）作為 5 個 spectral bands

**下一步：**
- 明天繼續採集更多 bean 樣本（目標 1000+ 筆/品種）
- 評估是否優化 `qsToQab`（多執行緒 / OpenCV NEON）
- 開始 Siamese MLP Phase 2（特徵提取 + pair generation）

---

## 2026-06-04

**完成：**
- 評估 Ruflo（前 claude-flow）安裝適用性 → 決定暫不安裝（overhead > benefit）
- 調查國際咖啡豆多光譜資料庫現況 → 確認商業化產品空白，Huyes 有機會成為全球第一
- 驚喜提案四：「光譜搜尋引擎 — 從分類器到有生命的知識庫」
  - FAISS 向量資料庫：每顆豆的光譜向量成為可搜尋的知識資產
  - 零樣本辨識：新品種無需重訓，靠近鄰繼承標籤
  - QAT 解法：大量真實灰階資料 → FastSAM on Hailo-8 品質等同 CPU

**決定：**
- Kyle 今天開始拍攝大量咖啡豆資料庫
- 資料庫採集時額外記錄：origin / process / roast_level / batch_id

**下一步：**
- 資料庫採集開始
- Siamese MLP 編譯成 Hailo HEF
- FAISS 向量資料庫整合進 agent_receiver

---

## 2026-06-03

**完成（Mac Mini）：**
- Huyes PWA 前端完成（React + Vite + PWA，可加到 iPhone 主畫面）
  - Home / BatchReport / ShareCard / OriginCard 四個頁面
- FastAPI 後端 port 8765（批次管理、QR Code、產地搜尋）
- Agent Receiver port 8081（接收 Pi5 webhook 事件）
- Pi5 ↔ Mac Mini 雙向通訊打通（SSH 金鑰 + webhook）
- Git 同步：兩台共用 huyes-devlog repo，歷史合併完成
- Siamese 訓練 pipeline 完成（model.py / dataset.py / train.py / evaluate.py）
- BQS 系統設計完成（4 分項：缺陷/烘焙/食安/形態）
- SBIR Phase 2 申請書草稿完成（台灣食品數據股份有限公司）
- Hailo-8 SDK 4.20.0 安裝完成，/dev/hailo0 正常
- FastSAM ONNX 匯出（45MB），Docker DFC 環境建置（3.28.0）
- FastSAM HEF 四版量化嘗試（v1-v4），驗證 int8 量化限制
- fastsam_hailo.py：NetworkGroup API + thread queue，23ms 推論速度
- spec_raw.csv → Siamese CSV 轉換腳本（convert_spec_raw.py）
- 59 張真實豆子灰階影像採集，作為量化校正資料

**完成（Pi5）：**
- health_server.py 正式加入 repo（Flask API port 8080）
- PI_CONNECTION.md 正式 commit（含 Tailscale IP）
- DIRECTIVE_FROM_BRAIN.md 確認分工架構

**結論：**
- FastSAM on Hailo-8：int8 量化 + 灰階輸入無法達到 CPU 品質，暫停
- **決定：FastSAM 分割保留 CPU，Hailo-8 專門跑 Siamese MLP**

**驚喜提案：**
- 提案一：BQS Q-Grader 自動化評分系統
- 提案二：SBIR × 嘖嘖 × Computex 三軌並行商業策略
- 提案三：Roast Copilot — 烘焙中即時光譜引導

---

## 2026-06-02

**完成（Mac Mini，首日啟用）：**
- Mac Mini 確認為專案大腦，Pi5 確認為執行端
- 組織架構確立：Kyle（顧問）→ Mac Mini Claude（總負責）→ Pi5（執行）
- PyTorch 2.12.0 MPS 環境建置完成
- Siamese pipeline 測試通過（假資料 val_f1=1.0，MPS 加速正常）
- scripts/export_dataset.py（Pi5 採集資料匯出 CSV）
- DIVISION_OF_LABOR.md 完整分工架構文件

**Pi5 連線：**
- SSH 金鑰授權完成（raspberrypi.local）
- Pi5 health endpoint 確認（port 8080）
- Tailscale 已連線

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
