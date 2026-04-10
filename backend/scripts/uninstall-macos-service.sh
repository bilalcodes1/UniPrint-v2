#!/usr/bin/env bash
# UniPrint — macOS launchd Service Uninstaller
set -euo pipefail

LABEL="com.uniprint.backend"
PLIST_FILE="${HOME}/Library/LaunchAgents/${LABEL}.plist"

if [ -f "${PLIST_FILE}" ]; then
  launchctl unload "${PLIST_FILE}" 2>/dev/null || true
  rm -f "${PLIST_FILE}"
  echo "✅ UniPrint service uninstalled."
else
  echo "ℹ️  Service plist not found — already uninstalled."
fi
