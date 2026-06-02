# Raspberry Pi Node — Connection Info

This document is for the Mac Mini (project lead) to connect to and command the Pi5 (executor).

## Organisation

| 角色 | 身份 |
|------|------|
| Kyle | Huyes 公司顧問（最終決策者） |
| Mac Mini | 專案總負責人，負責規劃、指揮、協調 |
| Pi5 | 執行端員工，接受 Mac Mini 指令，回報結果 |

## Node Identity

| Field    | Value                    |
|----------|--------------------------|
| Hostname | `raspberrypi`            |
| Role     | Sensor / Executor (Pi5)  |
| Platform | aarch64 (Raspberry Pi 5) |

## Connection Methods (priority order)

| 方式 | 地址 | 適用情境 |
|------|------|----------|
| Tailscale | `100.65.98.76` | 跨網路，最穩定 |
| mDNS | `raspberrypi.local` | 同 LAN |
| Local IP | `192.168.68.189` | 同 LAN，DHCP 可能變動 |

## API — Pi Agent (port 8080)

```
GET  http://raspberrypi.local:8080/health           # 確認連線
POST http://raspberrypi.local:8080/pipeline/run     # 觸發分析 {"n_beans":51, "callback_url":"..."}
GET  http://raspberrypi.local:8080/pipeline/status/<job_id>
GET  http://raspberrypi.local:8080/pipeline/result/<job_id>
GET  http://raspberrypi.local:8080/pipeline/image/<job_id>/<filename>
GET  http://raspberrypi.local:8080/pipeline/jobs
GET  http://raspberrypi.local:8080/dashboard        # 人工監控介面
GET  http://raspberrypi.local:8080/file/PI_CONNECTION.md
```

## Webhook Push (Pi → Mac Mini)

Pi 在 job 完成後主動 POST 到：
```
http://192.168.68.173:8081/agent/event
```

Payload 格式：
```json
{"event": "job_finished", "job_id": "...", "status": "done", "result_url": "..."}
```

## SSH

```bash
ssh kyle@raspberrypi.local
ssh kyle@100.65.98.76
```

## Working Directory

```
/home/kyle/KyleClaude/
```
