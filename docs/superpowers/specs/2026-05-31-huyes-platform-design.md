# Huyes 內部協作平台 — 設計規格

**日期：** 2026-05-31  
**版本：** v1.0  
**範圍：** 全端 Web 平台，10 人以內小團隊，多光譜資料庫 + Notion 式協作

---

## 1. 系統目標

建立一個內部 Web 平台，讓 Huyes 團隊成員（員工 + 協力者）能夠：
- 管理開發任務進度（Kanban 看板）
- 撰寫與共享技術筆記（Markdown + 附件）
- 上傳、瀏覽、下載多光譜採集資料（.ocf 原始檔 + band PNG + 分析結果）
- 即時同步訊息，不需要手動刷新

---

## 2. 架構總覽

```
使用者（手機/電腦）
    │ HTTPS
    ▼
Cloudflare Zero Trust Access   ← 第一道防線，Email OTP 驗證
    │
Cloudflare Tunnel
    │
Mac Mini（主 Server）
├── Caddy（反向代理，HTTPS 終止，Rate Limiting）
├── Pocketbase（後端 API + SQLite DB + Auth + Realtime）
└── SvelteKit（前端靜態檔案）
    │ SMB/NFS（本機網路）
    ▼
NAS（Synology，RAID 1）
└── /huyes-data/
    ├── ocf/          ← .ocf 原始檔
    ├── bands/        ← band PNG（10 個/session）
    ├── analysis/     ← 分析結果圖、JSON
    └── attachments/  ← 筆記附件

RPi5（相機端，獨立）
└── Python 分析完成 → Pocketbase API 上傳
```

---

## 3. 硬體規格

| 設備 | 角色 | 規格建議 |
|------|------|----------|
| Mac Mini | 主 Server | 現有 Mac Mini，有線網路，常開 |
| NAS | 資料後台 | Synology 2-bay（DS223 或 DS723+），RAID 1，2×4TB HDD |
| RPi5 | 相機開發端 | 現有，不作 server 用途 |
| Cloudflare | 網路層 | 免費方案（Tunnel + Zero Trust，最多 50 人）|

**NAS 掛載方式：**  
Mac Mini 透過 SMB 掛載 NAS 為 `/Volumes/HuyesNAS`，Pocketbase 設定檔案儲存路徑指向此掛載點。

---

## 4. 後端：Pocketbase

**版本：** 最新穩定版（Go single binary）  
**部署：** Mac Mini，以 `launchd` 服務開機自動啟動  
**資料路徑：** `~/pocketbase/pb_data/`

### 4.1 Collections（資料表）

| Collection | 欄位 | 說明 |
|-----------|------|------|
| `users` | name, email, role, avatar | 內建 Auth collection 擴展 |
| `tasks` | title, description, status, assignee, due_date, tags | 任務看板 |
| `notes` | title, content (Markdown), author, tags, attachments | 技術筆記 |
| `sessions` | name, captured_at, device, bean_count, exposure_us, note_id | 採集 session 中繼資料 |
| `session_files` | session_id, type (ocf/band/analysis), filename, file_path, size_bytes | 檔案索引 |
| `bean_results` | session_id, bean_id, agtron, mold_score, fl_norm, ndiff | 逐顆分析結果 |

### 4.2 即時訂閱

Pocketbase 內建 SSE（Server-Sent Events）即時推送：
- 任務狀態變更 → 即時更新看板
- 新筆記建立 → 即時出現在列表
- 新 session 上傳 → 即時出現在資料庫

### 4.3 檔案儲存策略

- 小檔案（筆記附件 < 50MB）：存入 Pocketbase 原生 storage（`pb_data/storage/`），掛載到 NAS
- 大檔案（.ocf、band PNG）：存入 NAS `/huyes-data/`，Pocketbase `session_files` 只記錄路徑與 metadata
- 前端下載大檔案：透過 Caddy 直接 serve NAS 掛載路徑，不經過 Pocketbase

---

## 5. 前端：SvelteKit

**框架：** SvelteKit（靜態 build，`adapter-static`）  
**部署：** Caddy serve 靜態檔案  
**主題：** 深色系（與現有 Demo App 一致），Tailwind CSS

### 5.1 頁面結構

```
/ (Dashboard)
├── /tasks          任務看板（Kanban）
├── /notes          技術筆記列表
│   └── /notes/:id  筆記詳頁（Markdown 編輯器）
├── /data           多光譜資料庫
│   └── /data/:id   Session 詳頁（band 瀏覽 + 下載）
└── /settings       成員管理
```

### 5.2 版面結構（A+B 組合）

```
┌──────────────────────────────────────────┐
│  左側欄（固定 180px）  │  主內容區         │
│  🫘 Huyes             │                   │
│  ─────────────────    │  ① Dashboard：    │
│  🏠 首頁              │     本週任務進度   │
│  📋 任務              │     採集量統計     │
│  📝 筆記              │     最新活動 feed  │
│  🔬 資料庫            │                   │
│  📊 分析              │  ② 各子頁面       │
│  ─────────────────    │                   │
│  成員頭像列表          │                   │
└──────────────────────────────────────────┘
```

### 5.3 各頁面功能細節

**Dashboard**
- 本週任務完成率（進度環）
- 採集 session 總數 + 本月新增
- 最新活動 feed（上傳/完成/留言）
- 快速連結（新增任務、新建筆記、上傳資料）

**任務看板**
- 三欄 Kanban：待辦 / 進行中 / 完成
- 任務卡片：標題、指派人、截止日、標籤（A1~D3 等）
- 拖拉移動狀態
- 點擊展開詳細描述 + 留言

**技術筆記**
- 左側：筆記列表（可搜尋、標籤篩選）
- 右側：Markdown 編輯器（TipTap 或 SimpleMDE）
- 支援圖片貼上（自動上傳到 Pocketbase）
- 可關聯到 session（筆記 ↔ 採集資料 雙向連結）

**多光譜資料庫**
- 卡片式列表，依日期排序
- 每張卡片：session 名稱、日期、豆子數、Agtron 均值、標籤
- 頻譜預覽：10 個 band 的縮圖條（band_00~band_09）
- 詳頁：逐顆 bean 結果表格、下載 .ocf 原始檔、下載分析報告
- 篩選：類型（Agtron/黴菌/白板）、日期範圍、Agtron 範圍

---

## 6. 安全架構（四層）

| 層 | 工具 | 功能 |
|----|------|------|
| 第一層 | Cloudflare Zero Trust Access | Email OTP 驗證，非指定 Email 看不到登入頁 |
| 第二層 | Caddy | Rate limiting（60 req/min/IP），Admin 路由只開本機 |
| 第三層 | Pocketbase | JWT Auth，角色權限（admin/member/viewer），2FA |
| 第四層 | NAS | 只開放本機 SMB，RAID 1 備份，存取日誌 |

**角色權限：**
- `admin`：全部功能，含成員管理
- `member`（員工）：建立/編輯任務、筆記、上傳資料
- `viewer`（協力廠商）：唯讀，只能看指定 collection

---

## 7. RPi5 上傳流程

分析完成後，Python 腳本呼叫 Pocketbase API：

```
分析完成
  → 建立 session record（POST /api/collections/sessions/records）
  → 上傳 band PNG × 10（POST /api/collections/session_files/records）
  → 上傳 bean_results（POST /api/collections/bean_results/records）
  → 大檔案（.ocf）直接 scp 到 NAS，只在 session_files 記路徑
```

---

## 8. 部署步驟概覽

1. **NAS 設定**：建立共享資料夾，Mac Mini 掛載
2. **Pocketbase**：下載 binary，設定 collections，建立 launchd service
3. **SvelteKit**：開發、build，靜態檔案放入 `/var/www/huyes/`
4. **Caddy**：設定反向代理（`/api/*` → Pocketbase，`/*` → 靜態）
5. **Cloudflare**：建立 Tunnel，設定 Zero Trust Access Policy
6. **RPi5**：設定上傳腳本的 API token 與 endpoint

---

## 9. 不在本次範圍

- 多人即時共同編輯同一筆記（類 Google Docs）
- 行動 App（原生 iOS/Android）
- 自動備份到雲端（S3）
- 多光譜影像線上視覺化播放器（第二階段）

---

## 10. 硬體採購清單

| 項目 | 型號建議 | 估價 |
|------|----------|------|
| NAS 主機 | Synology DS223 | NT$6,000 |
| NAS 硬碟 × 2 | WD Red Plus 4TB × 2 | NT$6,000 |
| 網路交換器（選配）| TP-Link 5-port Gigabit | NT$500 |
| **合計** | | **NT$12,500** |
