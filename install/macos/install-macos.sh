#!/usr/bin/env bash
# =============================================================================
# install-macos.sh
# Installs silent-screenshot-daemon as a macOS LaunchAgent (runs at login).
#
# Usage:
#   chmod +x install-macos.sh && ./install-macos.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PLIST_TEMPLATE="${SCRIPT_DIR}/com.silent-screenshot-daemon.plist"
AGENT_DIR="${HOME}/Library/LaunchAgents"
PLIST_DEST="${AGENT_DIR}/com.silent-screenshot-daemon.plist"
LABEL="com.silent-screenshot-daemon"
LOG_DIR="${INSTALL_DIR}/logs"

# ── Validate ──────────────────────────────────────────────────────────────────
PYTHON3="$(command -v python3 || true)"
if [ -z "$PYTHON3" ]; then
  echo "ERROR: python3 not found on PATH." >&2; exit 1
fi

if ! "$PYTHON3" -c "import pynput" 2>/dev/null; then
  echo "ERROR: pynput not installed. Run: pip3 install pynput" >&2; exit 1
fi

if [ ! -f "${INSTALL_DIR}/daemon.py" ]; then
  echo "ERROR: daemon.py not found in ${INSTALL_DIR}." >&2; exit 1
fi

# ── Prepare ───────────────────────────────────────────────────────────────────
mkdir -p "${AGENT_DIR}" "${LOG_DIR}"

# ── Unload existing if present ────────────────────────────────────────────────
if launchctl list 2>/dev/null | grep -q "${LABEL}"; then
  echo "Unloading existing LaunchAgent..."
  launchctl unload "${PLIST_DEST}" 2>/dev/null || true
fi

# ── Write plist ───────────────────────────────────────────────────────────────
echo "Writing plist to ${PLIST_DEST}..."
sed \
  -e "s|PYTHON3_BIN|${PYTHON3}|g" \
  -e "s|INSTALL_DIR|${INSTALL_DIR}|g" \
  "${PLIST_TEMPLATE}" > "${PLIST_DEST}"
chmod 644 "${PLIST_DEST}"

# ── Load ──────────────────────────────────────────────────────────────────────
launchctl load -w "${PLIST_DEST}"

echo ""
echo "OK  silent-screenshot-daemon installed and started."
echo "    Plist:    ${PLIST_DEST}"
echo "    Log:      ${LOG_DIR}/daemon.log"
echo ""
echo "IMPORTANT: python3 (or Terminal that launched it) must have"
echo "Accessibility permission in System Settings > Privacy & Security."
