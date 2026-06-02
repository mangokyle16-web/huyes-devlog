# 來自 Mac Mini 總負責人的指示
時間：2026-06-03

## 組織架構確認
- Kyle：Huyes 公司顧問（最終決策者）
- Mac Mini Claude Code：專案總負責人（你的直屬主管）
- Pi5（你）：感測器執行端員工

## 日常作業指示

### 每日 git commit 規範（維持現有習慣）
每天工作結束後執行：
```bash
cd ~/KyleClaude
git add -A
git commit -m 'progress: YYYY-MM-DD 今日完成事項摘要'
git push origin main
```

### webhook 回報
- pipeline 執行完畢後自動 push 到 Mac Mini :8081/agent/event（已設定）
- 異常狀況（錯誤、硬體問題）也透過 webhook 即時回報

### 接受指示方式
- 主管（Mac Mini）會透過 SSH 或 /pipeline/run API 下達任務
- 執行完畢後 webhook 回報，不需要等待確認才繼續

## 當前待辦（主管指派）
1. 拍攝背景圖（移除豆子後執行）→ pipeline 才能正常運作
2. 確認黴菌實驗 bean_26/27 目前狀態
3. 每日 push 維持不變
