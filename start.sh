#!/bin/bash
# UniPrint — start both backend and frontend
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "🖨️  Starting UniPrint..."

# Backend
echo "→ Starting Flask backend on :5001"
cd "$ROOT/backend"
if [ ! -d venv ]; then
  python3 -m venv venv
  venv/bin/pip install -r requirements.txt -q
fi
venv/bin/python run.py > /tmp/uniprint-backend.log 2>&1 &
BACKEND_PID=$!
echo "  Backend PID: $BACKEND_PID"

# Wait for backend
sleep 2
if ! curl -s http://localhost:5001/health > /dev/null 2>&1; then
  echo "❌ Backend failed to start. Check /tmp/uniprint-backend.log"
  exit 1
fi
echo "  ✅ Backend ready — http://localhost:5001"

# Frontend
echo "→ Starting SvelteKit dashboard on :3000"
cd "$ROOT/frontend"
if [ ! -d node_modules ]; then
  npm install -q
fi
npm run dev -- --port 3000 > /tmp/uniprint-frontend.log 2>&1 &
FRONTEND_PID=$!
echo "  Frontend PID: $FRONTEND_PID"

sleep 2
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🖨️  UniPrint is running!"
echo ""
echo "  Dashboard:    http://localhost:3000"
echo "  Backend API:  http://localhost:5001/api"
echo "  Student page: open student-pages/lan/index.html"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Press Ctrl+C to stop."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; echo 'Stopped.'" INT TERM
wait
