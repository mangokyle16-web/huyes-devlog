# Huyes Platform — Plan A: Infrastructure Implementation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Set up Mac Mini as Pocketbase server with NAS storage, Caddy reverse proxy, and Cloudflare Tunnel + Zero Trust so the platform is reachable from any device with email authentication.

**Architecture:** Pocketbase runs as a launchd service on Mac Mini, Caddy proxies HTTPS traffic to it, NAS is mounted as a local volume for large file storage, Cloudflare Tunnel exposes the service externally without a static IP.

**Tech Stack:** Pocketbase 0.22+, Caddy 2, Cloudflare Tunnel (cloudflared), Synology NAS DSM 7, macOS Sequoia

---

## Phase 1 — NAS 設定

### Task 1: Synology NAS 初始化

**目標機器：** Mac Mini（透過瀏覽器設定 NAS）

- [ ] **Step 1: 連接 NAS**

  將 NAS 接上電源與網路交換器，等待開機燈號穩定（約 2 分鐘）。

- [ ] **Step 2: 找到 NAS IP**

  在 Mac Mini 終端機執行：
  ```bash
  arp -a | grep -i synology
  # 或用 Synology Assistant：https://www.synology.com/en-global/support/download
  ```
  記下 IP，例如 `192.168.1.100`

- [ ] **Step 3: 開啟 DSM 設定介面**

  瀏覽器開啟 `http://192.168.1.100:5000`，按照精靈完成初始化（建立 admin 帳號、設定磁碟為 RAID 1）。

- [ ] **Step 4: 建立共享資料夾**

  DSM → 控制台 → 共享資料夾 → 新增：
  - 名稱：`huyes-data`
  - 位置：Volume 1
  - 加密：關閉（效能考量）
  - 勾選「啟用資源回收桶」

- [ ] **Step 5: 建立子目錄**

  DSM → File Station → 進入 `huyes-data`，建立以下資料夾：
  ```
  huyes-data/
  ├── ocf/
  ├── bands/
  ├── analysis/
  └── attachments/
  ```

- [ ] **Step 6: 建立 NAS 使用者給 Mac Mini 掛載用**

  DSM → 控制台 → 使用者與群組 → 新增使用者：
  - 帳號：`macmini-mount`
  - 密碼：設強密碼，記下來
  - 群組：`users`
  - 共享資料夾權限：`huyes-data` → 讀寫

---

### Task 2: Mac Mini 掛載 NAS

**目標機器：** Mac Mini

- [ ] **Step 1: 透過 Finder 掛載**

  Finder → 前往 → 連接伺服器（⌘K）：
  ```
  smb://192.168.1.100/huyes-data
  ```
  輸入 `macmini-mount` 帳密，勾選「記住密碼」。

- [ ] **Step 2: 確認掛載路徑**

  ```bash
  ls /Volumes/huyes-data
  # 應顯示：ocf  bands  analysis  attachments
  ```

- [ ] **Step 3: 設定開機自動掛載**

  建立 plist 讓開機自動掛載（取代手動每次連線）：
  ```bash
  cat > ~/Library/LaunchAgents/com.huyes.nas-mount.plist << 'EOF'
  <?xml version="1.0" encoding="UTF-8"?>
  <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
  <plist version="1.0">
  <dict>
    <key>Label</key>
    <string>com.huyes.nas-mount</string>
    <key>ProgramArguments</key>
    <array>
      <string>/bin/sh</string>
      <string>-c</string>
      <string>mount_smbfs //macmini-mount:YOUR_PASSWORD@192.168.1.100/huyes-data /Volumes/huyes-data</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
  </dict>
  </plist>
  EOF
  ```
  將 `YOUR_PASSWORD` 換成實際密碼。

  ```bash
  launchctl load ~/Library/LaunchAgents/com.huyes.nas-mount.plist
  ```

- [ ] **Step 4: 驗證**

  ```bash
  ls /Volumes/huyes-data/ocf/
  # 應顯示空目錄（無錯誤）
  echo "test" > /Volumes/huyes-data/ocf/test.txt && rm /Volumes/huyes-data/ocf/test.txt
  echo "NAS 讀寫正常"
  ```

---

## Phase 2 — Pocketbase 設定

### Task 3: 安裝 Pocketbase

**目標機器：** Mac Mini

- [ ] **Step 1: 下載 Pocketbase**

  ```bash
  mkdir -p ~/pocketbase
  cd ~/pocketbase
  curl -L https://github.com/pocketbase/pocketbase/releases/download/v0.22.20/pocketbase_0.22.20_darwin_arm64.zip -o pb.zip
  unzip pb.zip && rm pb.zip
  chmod +x pocketbase
  ./pocketbase --version
  # 預期：pocketbase version 0.22.20
  ```

- [ ] **Step 2: 設定資料目錄指向 NAS**

  ```bash
  # pb_data 放本機（元資料快），大檔案另外處理
  mkdir -p ~/pocketbase/pb_data
  ```

- [ ] **Step 3: 第一次啟動**

  ```bash
  ~/pocketbase/pocketbase serve --http="127.0.0.1:8090"
  ```
  瀏覽器開啟 `http://127.0.0.1:8090/_/`，完成 Admin 帳號設定（記下 email + 密碼）。

  完成後 `Ctrl+C` 停止，準備設定 launchd。

- [ ] **Step 4: 建立 launchd service**

  ```bash
  cat > ~/Library/LaunchAgents/com.huyes.pocketbase.plist << 'EOF'
  <?xml version="1.0" encoding="UTF-8"?>
  <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
  <plist version="1.0">
  <dict>
    <key>Label</key>
    <string>com.huyes.pocketbase</string>
    <key>ProgramArguments</key>
    <array>
      <string>/Users/kyle/pocketbase/pocketbase</string>
      <string>serve</string>
      <string>--http=127.0.0.1:8090</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/kyle/pocketbase</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/kyle/pocketbase/pocketbase.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/kyle/pocketbase/pocketbase.log</string>
  </dict>
  </plist>
  EOF

  launchctl load ~/Library/LaunchAgents/com.huyes.pocketbase.plist
  ```

- [ ] **Step 5: 驗證服務正在運行**

  ```bash
  curl -s http://127.0.0.1:8090/api/health | python3 -m json.tool
  # 預期：{"code": 200, "message": "API is healthy."}
  ```

---

### Task 4: 建立 Pocketbase Collections

**目標機器：** Mac Mini 瀏覽器（`http://127.0.0.1:8090/_/`）

- [ ] **Step 1: 建立 `tasks` collection**

  Admin UI → Collections → New Collection：
  - Name: `tasks`
  - Type: Base
  - Fields:
    | 欄位名稱 | 類型 | 必填 |
    |---------|------|------|
    | title | Text | ✓ |
    | description | Editor | |
    | status | Select（待辦/進行中/完成）| ✓ |
    | assignee | Relation → users | |
    | due_date | Date | |
    | tags | Text | |

- [ ] **Step 2: 建立 `notes` collection**

  - Name: `notes`
  - Fields:
    | 欄位名稱 | 類型 | 必填 |
    |---------|------|------|
    | title | Text | ✓ |
    | content | Editor | |
    | author | Relation → users | ✓ |
    | tags | Text | |
    | attachments | File（允許多檔，最大 50MB）| |

- [ ] **Step 3: 建立 `sessions` collection**

  - Name: `sessions`
  - Fields:
    | 欄位名稱 | 類型 | 必填 |
    |---------|------|------|
    | name | Text | ✓ |
    | captured_at | Date | ✓ |
    | device | Text | |
    | bean_count | Number | |
    | exposure_us | Number | |
    | note_id | Relation → notes | |
    | tags | Text | |

- [ ] **Step 4: 建立 `session_files` collection**

  - Name: `session_files`
  - Fields:
    | 欄位名稱 | 類型 | 必填 |
    |---------|------|------|
    | session_id | Relation → sessions | ✓ |
    | type | Select（ocf/band/analysis）| ✓ |
    | filename | Text | ✓ |
    | file_path | Text | ✓ |
    | size_bytes | Number | |

- [ ] **Step 5: 建立 `bean_results` collection**

  - Name: `bean_results`
  - Fields:
    | 欄位名稱 | 類型 | 必填 |
    |---------|------|------|
    | session_id | Relation → sessions | ✓ |
    | bean_id | Number | ✓ |
    | agtron | Number | |
    | mold_score | Number | |
    | fl_norm | Number | |
    | ndiff | Number | |

- [ ] **Step 6: 設定 API 規則**

  每個 collection → API Rules：
  - List/View：`@request.auth.id != ""`（需登入才能讀）
  - Create/Update/Delete：`@request.auth.id != "" && @request.auth.collectionName = "users"`

- [ ] **Step 7: 建立 API Token 給 RPi5 用**

  Admin UI → Settings → API keys → Add key：
  - 名稱：`rpi5-upload`
  - 複製 token，儲存到安全地方

- [ ] **Step 8: 驗證 API 可用**

  ```bash
  # 測試登入
  curl -s -X POST http://127.0.0.1:8090/api/collections/users/auth-with-password \
    -H "Content-Type: application/json" \
    -d '{"identity":"your@email.com","password":"yourpassword"}' \
    | python3 -m json.tool | grep token
  # 預期：顯示 "token": "eyJ..."
  ```

---

## Phase 3 — Caddy 反向代理

### Task 5: 安裝並設定 Caddy

**目標機器：** Mac Mini

- [ ] **Step 1: 安裝 Caddy**

  ```bash
  brew install caddy
  caddy version
  # 預期：v2.x.x
  ```

- [ ] **Step 2: 建立 Caddyfile**

  ```bash
  mkdir -p ~/caddy
  cat > ~/caddy/Caddyfile << 'EOF'
  # 本機開發用（Cloudflare Tunnel 設定完成後這裡會加上 domain）
  :8080 {
      # 速率限制（需要 caddy-ratelimit 模組，先跳過）
      
      # Pocketbase Admin — 只允許本機
      @admin {
          path /_/*
      }
      handle @admin {
          @not_local {
              not remote_ip 127.0.0.1
          }
          respond @not_local "Forbidden" 403
          reverse_proxy 127.0.0.1:8090
      }

      # Pocketbase API
      handle /api/* {
          reverse_proxy 127.0.0.1:8090
      }

      # 大檔案直接 serve（NAS 掛載路徑）
      handle /files/* {
          uri strip_prefix /files
          root * /Volumes/huyes-data
          file_server
      }

      # 前端靜態檔案（SvelteKit build，之後再設）
      handle {
          root * /var/www/huyes
          try_files {path} /index.html
          file_server
      }
  }
  EOF
  ```

- [ ] **Step 3: 建立前端目錄佔位**

  ```bash
  sudo mkdir -p /var/www/huyes
  echo "<h1>Huyes Platform — Coming Soon</h1>" | sudo tee /var/www/huyes/index.html
  ```

- [ ] **Step 4: 啟動 Caddy**

  ```bash
  caddy start --config ~/caddy/Caddyfile
  ```

- [ ] **Step 5: 驗證**

  ```bash
  curl -s http://localhost:8080/api/health | python3 -m json.tool
  # 預期：{"code": 200, "message": "API is healthy."}

  curl -s http://localhost:8080/
  # 預期：<h1>Huyes Platform — Coming Soon</h1>
  ```

- [ ] **Step 6: 設定 launchd 讓 Caddy 開機啟動**

  ```bash
  cat > ~/Library/LaunchAgents/com.huyes.caddy.plist << 'EOF'
  <?xml version="1.0" encoding="UTF-8"?>
  <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
  <plist version="1.0">
  <dict>
    <key>Label</key>
    <string>com.huyes.caddy</string>
    <key>ProgramArguments</key>
    <array>
      <string>/opt/homebrew/bin/caddy</string>
      <string>run</string>
      <string>--config</string>
      <string>/Users/kyle/caddy/Caddyfile</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/kyle/caddy/caddy.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/kyle/caddy/caddy.log</string>
  </dict>
  </plist>
  EOF

  launchctl load ~/Library/LaunchAgents/com.huyes.caddy.plist
  ```

---

## Phase 4 — Cloudflare Tunnel + Zero Trust

### Task 6: 安裝 cloudflared

**目標機器：** Mac Mini  
**前提：** 需要有 Cloudflare 帳號（免費），並擁有一個 domain（或使用 Cloudflare 提供的 trycloudflare.com 臨時 URL）

- [ ] **Step 1: 安裝 cloudflared**

  ```bash
  brew install cloudflare/cloudflare/cloudflared
  cloudflared --version
  # 預期：cloudflared version 2024.x.x
  ```

- [ ] **Step 2: 登入 Cloudflare**

  ```bash
  cloudflared tunnel login
  # 會開啟瀏覽器，選擇你的 domain（或建立新的）
  # 完成後 ~/.cloudflared/cert.pem 會被建立
  ```

- [ ] **Step 3: 建立 Tunnel**

  ```bash
  cloudflared tunnel create huyes-platform
  # 記下輸出的 Tunnel ID，例如：a1b2c3d4-...
  # 憑證檔會存在 ~/.cloudflared/<TUNNEL_ID>.json
  ```

- [ ] **Step 4: 建立設定檔**

  ```bash
  cat > ~/.cloudflared/config.yml << 'EOF'
  tunnel: <YOUR_TUNNEL_ID>
  credentials-file: /Users/kyle/.cloudflared/<YOUR_TUNNEL_ID>.json

  ingress:
    - hostname: platform.yourdomain.com
      service: http://localhost:8080
    - service: http_status:404
  EOF
  ```
  將 `<YOUR_TUNNEL_ID>` 和 `yourdomain.com` 換成實際值。

- [ ] **Step 5: 設定 DNS**

  ```bash
  cloudflared tunnel route dns huyes-platform platform.yourdomain.com
  # 預期：Added CNAME record...
  ```

- [ ] **Step 6: 測試 Tunnel**

  ```bash
  cloudflared tunnel run huyes-platform
  # 應顯示：Registered tunnel connection...
  ```
  另開終端機：
  ```bash
  curl -s https://platform.yourdomain.com/api/health
  # 預期：{"code": 200, "message": "API is healthy."}
  ```
  確認後 `Ctrl+C` 停止。

- [ ] **Step 7: 設定 launchd 開機啟動**

  ```bash
  sudo cloudflared service install
  sudo launchctl start com.cloudflare.cloudflared
  ```

---

### Task 7: 設定 Cloudflare Zero Trust Access

**目標：** 瀏覽器操作 Cloudflare Dashboard

- [ ] **Step 1: 開啟 Zero Trust**

  瀏覽器 → `https://one.dash.cloudflare.com` → 選擇你的帳號

- [ ] **Step 2: 建立 Access Application**

  Zero Trust → Access → Applications → Add an application → Self-hosted：
  - Application name：`Huyes Platform`
  - Session duration：`24 hours`
  - Application domain：`platform.yourdomain.com`

- [ ] **Step 3: 建立 Access Policy**

  Policy name：`Team Members`
  - Action：Allow
  - Rule：
    - Selector：`Emails`
    - Value：輸入所有允許的 email（每行一個），例如：
      ```
      kyle@huyes.com
      collaborator@example.com
      ```

- [ ] **Step 4: 驗證 Zero Trust 生效**

  用手機或其他瀏覽器（無登入狀態）開啟 `https://platform.yourdomain.com`。

  應看到 Cloudflare Access 頁面：「Enter your email to continue」。

  輸入允許清單內的 email → 收到 OTP → 輸入 → 進入平台。

  輸入不在清單的 email → 顯示「Access denied」。

---

## Phase 5 — 整合驗證

### Task 8: 端對端測試

- [ ] **Step 1: 確認所有服務都在運行**

  ```bash
  # Pocketbase
  curl -s http://127.0.0.1:8090/api/health | python3 -m json.tool

  # Caddy
  curl -s http://localhost:8080/api/health | python3 -m json.tool

  # NAS 掛載
  ls /Volumes/huyes-data/

  # Cloudflare Tunnel
  sudo launchctl list | grep cloudflare
  ```

- [ ] **Step 2: 測試 NAS 大檔案 serve**

  ```bash
  echo "test_data" > /Volumes/huyes-data/ocf/test.ocf
  curl -s http://localhost:8080/files/ocf/test.ocf
  # 預期：test_data
  rm /Volumes/huyes-data/ocf/test.ocf
  ```

- [ ] **Step 3: 測試 Pocketbase API 建立 task**

  ```bash
  # 先取得 auth token
  TOKEN=$(curl -s -X POST http://127.0.0.1:8090/api/collections/users/auth-with-password \
    -H "Content-Type: application/json" \
    -d '{"identity":"your@email.com","password":"yourpassword"}' \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

  # 建立一筆 task
  curl -s -X POST http://127.0.0.1:8090/api/collections/tasks/records \
    -H "Authorization: $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"title":"測試任務","status":"待辦","tags":"test"}' \
    | python3 -m json.tool | grep id
  # 預期：顯示 "id": "..."
  ```

- [ ] **Step 4: 清理測試資料**

  ```bash
  # 取得 task id 後刪除
  TASK_ID=$(curl -s -H "Authorization: $TOKEN" \
    "http://127.0.0.1:8090/api/collections/tasks/records?filter=tags='test'" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['items'][0]['id'])")

  curl -s -X DELETE "http://127.0.0.1:8090/api/collections/tasks/records/$TASK_ID" \
    -H "Authorization: $TOKEN"
  echo "清理完成"
  ```

- [ ] **Step 5: Commit 設定檔到版本控制**

  ```bash
  cd ~/KyleClaude
  mkdir -p infra
  cp ~/caddy/Caddyfile infra/Caddyfile
  # 注意：不要 commit ~/.cloudflared/ 內的憑證檔案
  cat > infra/README.md << 'EOF'
  # Infrastructure 設定

  - Pocketbase: ~/pocketbase/（binary + pb_data/）
  - Caddy: ~/caddy/Caddyfile
  - Cloudflare: ~/.cloudflared/config.yml（含敏感憑證，不進版本控制）
  - NAS 掛載: /Volumes/huyes-data → 192.168.1.100/huyes-data
  EOF

  git add infra/
  git commit -m "feat: add infrastructure config files (Caddy, README)"
  git -c credential.helper='!f(){ echo "username=mangokyle16-web"; echo "password=$(gh auth token)"; };f' push
  ```

---

## 完成標準

Plan A 完成後，以下應全部成立：
- [ ] `https://platform.yourdomain.com/api/health` 回傳 200
- [ ] 未授權 email 連線被 Cloudflare 擋下
- [ ] 授權 email 通過 OTP 後可進入（目前顯示 Coming Soon 頁面）
- [ ] Pocketbase Admin 在 `http://127.0.0.1:8090/_/` 本機可用，外網不可存取
- [ ] NAS 大檔案透過 `/files/` 路徑可下載
- [ ] 重開 Mac Mini 後所有服務自動啟動

**下一步：Plan B（SvelteKit 前端）**
