#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# UniPrint — macOS launchd Service Installer
# Installs UniPrint backend as a LaunchAgent (runs on login, auto-restart).
# Usage: chmod +x install-macos-service.sh && ./install-macos-service.sh
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

LABEL="com.uniprint.backend"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_PYTHON="${BACKEND_DIR}/venv/bin/python"
RUN_SCRIPT="${BACKEND_DIR}/run.py"
LOG_DIR="${HOME}/Library/Logs/UniPrint"
PLIST_DIR="${HOME}/Library/LaunchAgents"
PLIST_FILE="${PLIST_DIR}/${LABEL}.plist"

# ── Checks ────────────────────────────────────────────────────────────────────
if [ ! -f "${VENV_PYTHON}" ]; then
  echo "❌ Python venv not found at: ${VENV_PYTHON}"
  echo "   Run: cd ${BACKEND_DIR} && python3 -m venv venv && venv/bin/pip install -r requirements.txt"
  exit 1
fi

if [ ! -f "${RUN_SCRIPT}" ]; then
  echo "❌ run.py not found at: ${RUN_SCRIPT}"
  exit 1
fi

mkdir -p "${LOG_DIR}" "${PLIST_DIR}"

# ── Write plist ───────────────────────────────────────────────────────────────
cat > "${PLIST_FILE}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>

  <key>ProgramArguments</key>
  <array>
    <string>${VENV_PYTHON}</string>
    <string>${RUN_SCRIPT}</string>
  </array>

  <key>WorkingDirectory</key>
  <string>${BACKEND_DIR}</string>

  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>${BACKEND_DIR}/venv/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>

  <key>RunAtLoad</key>
  <true/>

  <key>KeepAlive</key>
  <true/>

  <key>ThrottleInterval</key>
  <integer>10</integer>

  <key>StandardOutPath</key>
  <string>${LOG_DIR}/uniprint.log</string>

  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/uniprint-error.log</string>
</dict>
</plist>
EOF

# ── Load ──────────────────────────────────────────────────────────────────────
launchctl unload "${PLIST_FILE}" 2>/dev/null || true
launchctl load -w "${PLIST_FILE}"

echo ""
echo "✅ UniPrint service installed and started!"
echo "   Logs : ${LOG_DIR}/"
echo "   Stop : launchctl unload ${PLIST_FILE}"
echo "   Start: launchctl load -w ${PLIST_FILE}"
echo "   URL  : http://localhost:5001"
