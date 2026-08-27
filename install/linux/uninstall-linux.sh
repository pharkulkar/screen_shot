#!/usr/bin/env bash
# =============================================================================
# uninstall-linux.sh
# Stops and removes the silent-screenshot-daemon systemd --user service.
#
# Usage:
#   chmod +x uninstall-linux.sh
#   ./uninstall-linux.sh
# =============================================================================
set -euo pipefail

SERVICE="silent-screenshot-daemon"
UNIT="${HOME}/.config/systemd/user/${SERVICE}.service"

if systemctl --user is-active --quiet "${SERVICE}" 2>/dev/null; then
  echo "Stopping service…"
  systemctl --user stop "${SERVICE}"
fi

if systemctl --user is-enabled --quiet "${SERVICE}" 2>/dev/null; then
  echo "Disabling service…"
  systemctl --user disable "${SERVICE}"
fi

if [ -f "${UNIT}" ]; then
  rm -f "${UNIT}"
  systemctl --user daemon-reload
  echo "✔  Removed ${UNIT}"
else
  echo "Unit file not found at ${UNIT} — nothing to remove."
fi

echo "✔  silent-screenshot-daemon uninstalled."
