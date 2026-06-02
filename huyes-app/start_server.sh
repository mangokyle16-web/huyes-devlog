#!/bin/bash
REPO="$HOME/KyleClaude"
cd "$REPO"
source venv/bin/activate

if [ ! -f "$REPO/huyes-app/frontend/dist/index.html" ]; then
  echo "Building PWA..."
  cd "$REPO/huyes-app/frontend" && npm run build && cd "$REPO"
fi

echo "=================================="
echo " Huyes API         → port 8765"
echo " Pi5 Agent Receiver → port 8081"
echo " Pi5 → Brain webhook: 192.168.68.173:8081/agent/event"
echo "=================================="

cd "$REPO/huyes-app/backend"
uvicorn main:app --host 0.0.0.0 --port 8765 --log-level warning &
uvicorn agent_receiver:app --host 0.0.0.0 --port 8081 --log-level warning &
wait
