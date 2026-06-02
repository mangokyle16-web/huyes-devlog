#!/bin/bash
# Mac Mini：啟動 Huyes API + 確保 PWA 已 build
# 用法：bash ~/KyleClaude/huyes-app/start_server.sh

REPO="$HOME/KyleClaude"
cd "$REPO"
source venv/bin/activate

# 確保 PWA 已 build
if [ ! -f "$REPO/huyes-app/frontend/dist/index.html" ]; then
  echo "Building PWA..."
  cd "$REPO/huyes-app/frontend" && npm run build
  cd "$REPO"
fi

echo "=================================="
echo " Huyes API starting on port 8765"
echo " Mac Mini: kyleckagentdeMac-mini-2.local:8765"
echo "=================================="

cd "$REPO/huyes-app/backend"
uvicorn main:app --host 0.0.0.0 --port 8765
