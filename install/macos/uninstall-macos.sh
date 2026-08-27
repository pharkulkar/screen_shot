#!/usr/bin/env bash
# =============================================================================
# uninstall-macos.sh
# Stops and removes the silent-screenshot-daemon LaunchAgent.
#
# Usage:
#   chmod +x uninstall-macos.sh
#   ./uninstall-macos.sh
# =============================================================================
set -euo pipefail

LABEL="com.silent-screenshot-daemon"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"

if [ -f "${PLIST}" ]; then
  echo "Unloading LaunchAgent…"
  launchctl unload -w "${PLIST}" 2>/dev/null || true
  rm -f "${PLIST}"
  echo "✔  Removed ${PLIST}"
else
  echo "LaunchAgent plist not found at ${PLIST} — nothing to remove."
fi

echo "✔  silent-screenshot-daemon uninstalled."
