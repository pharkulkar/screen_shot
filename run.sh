#!/usr/bin/env bash
# =============================================================================
# run.sh — start both the daemon and the viewer server (macOS / Linux).
# Run from Terminal.app (not from an IDE terminal) so Accessibility
# permission is correctly evaluated against Terminal.
#
# Usage:
#   chmod +x run.sh
#   ./run.sh
# =============================================================================
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$(command -v python3 || true)"

if [ -z "$PYTHON" ]; then
  echo "ERROR: python3 not found on PATH." >&2; exit 1
fi

for mod in pynput flask; do
  if ! "$PYTHON" -c "import $mod" 2>/dev/null; then
    echo "ERROR: Python module '$mod' not installed." >&2
    echo "Run:   pip3 install -r $DIR/requirements.txt" >&2
    exit 1
  fi
done

echo "Starting screenshot daemon..."
"$PYTHON" "$DIR/daemon.py" &
DAEMON_PID=$!

sleep 1   # give daemon a moment to write its PID file

echo "Starting screenshot viewer server..."
"$PYTHON" "$DIR/server.py" &
SERVER_PID=$!

echo ""
echo "  Daemon PID : $DAEMON_PID"
echo "  Server PID : $SERVER_PID"
echo "  Gallery    : http://localhost:5000"
echo "  Log        : $DIR/logs/daemon.log"
echo ""
echo "Press Ctrl-C to stop both."

# Wait for either process to exit, then kill the other.
trap "kill $DAEMON_PID $SERVER_PID 2>/dev/null; echo 'Stopped.'" EXIT INT TERM
wait
