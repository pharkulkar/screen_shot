#!/usr/bin/env bash
# =============================================================================
# install-linux.sh
# Installs silent-screenshot-daemon as a systemd --user service so it starts
# automatically with the graphical session.
#
# Usage:
#   chmod +x install-linux.sh
#   ./install-linux.sh
#
# Requirements:
#   - systemd with --user instance running (most modern desktop distros)
#   - Node.js ≥ 18 on PATH
#   - 'npm install' run in the project root first
#   - A graphical session (X11 or Wayland) for screenshot-desktop to work
# =============================================================================
set -euo pipefail

# ── Resolve paths ─────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SERVICE_TEMPLATE="${SCRIPT_DIR}/silent-screenshot-daemon.service"
UNIT_DIR="${HOME}/.config/systemd/user"
SERVICE_DEST="${UNIT_DIR}/silent-screenshot-daemon.service"
LOG_DIR="${INSTALL_DIR}/logs"

# ── Validate environment ──────────────────────────────────────────────────────
if ! command -v node &>/dev/null; then
  echo "ERROR: 'node' not found on PATH. Install Node.js ≥ 18 first." >&2
  exit 1
fi
NODE_BIN="$(command -v node)"

if ! command -v systemctl &>/dev/null; then
  echo "ERROR: systemctl not found. This script requires systemd." >&2
  exit 1
fi

if [ ! -f "${INSTALL_DIR}/index.js" ]; then
  echo "ERROR: index.js not found in ${INSTALL_DIR}." >&2
  exit 1
fi

if [ ! -d "${INSTALL_DIR}/node_modules" ]; then
  echo "ERROR: node_modules not found. Run 'npm install' in ${INSTALL_DIR} first." >&2
  exit 1
fi

# ── Prepare directories ───────────────────────────────────────────────────────
mkdir -p "${UNIT_DIR}"
mkdir -p "${LOG_DIR}"

# ── Stop existing service if running ─────────────────────────────────────────
if systemctl --user is-active --quiet silent-screenshot-daemon 2>/dev/null; then
  echo "Stopping existing service…"
  systemctl --user stop silent-screenshot-daemon
fi

# ── Write unit file with real paths substituted ───────────────────────────────
echo "Writing service unit to ${SERVICE_DEST}…"
sed \
  -e "s|INSTALL_DIR|${INSTALL_DIR}|g" \
  -e "s|NODE_BIN|${NODE_BIN}|g" \
  "${SERVICE_TEMPLATE}" > "${SERVICE_DEST}"

# ── Enable and start ──────────────────────────────────────────────────────────
# Enable lingering so the --user instance starts even without a login session.
loginctl enable-linger "$(whoami)" 2>/dev/null || true

systemctl --user daemon-reload
systemctl --user enable --now silent-screenshot-daemon

echo ""
echo "✔  silent-screenshot-daemon installed and started."
echo "   Unit:     ${SERVICE_DEST}"
echo "   Status:   systemctl --user status silent-screenshot-daemon"
echo "   Log file: ${INSTALL_DIR}/logs/daemon.log"
echo ""
echo "NOTE: The daemon requires access to the display (DISPLAY / WAYLAND_DISPLAY)."
echo "If it fails to capture screenshots, check that those environment variables"
echo "are available to systemd --user services on your distro."
