#!/usr/bin/env bash
# ============================================================================
#  OpenClaw Setup — one-shot runner.
#  Clone this repo, then:   ./start.sh
#  It installs OpenClaw if needed, then launches the setup UI so you can fill
#  in Telegram / Codex / gateway details in the browser.
#
#  Env overrides:  PORT=9000  HOST=127.0.0.1  OPENCLAW_UI_KEY=<secret>
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

: "${PORT:=8765}"
: "${HOST:=127.0.0.1}"

add_openclaw_to_path() {
  # npm global prefix used by OpenClaw's installer
  export PATH="$HOME/.npm-global/bin:$PATH"
  # nvm-managed node global bins (if present)
  for d in "$HOME"/.nvm/versions/node/*/bin; do
    [ -d "$d" ] && export PATH="$d:$PATH"
  done
  # common system location
  export PATH="/usr/local/bin:$PATH"
}

# 1. Install OpenClaw if it isn't already available -------------------------
add_openclaw_to_path
if ! command -v openclaw >/dev/null 2>&1; then
  echo "==> OpenClaw not found. Installing..."
  curl -fsSL https://openclaw.ai/install.sh | bash
  add_openclaw_to_path
fi

if ! command -v openclaw >/dev/null 2>&1; then
  echo "ERROR: 'openclaw' is still not on PATH after install."
  echo "       Add its bin directory to PATH and re-run, e.g.:"
  echo "         export PATH=\"\$HOME/.npm-global/bin:\$PATH\""
  exit 1
fi
echo "==> OpenClaw: $(openclaw --version 2>/dev/null | head -1)"

# 2. Make sure python3 is present (the UI backend) --------------------------
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is required to run the setup UI but was not found."
  exit 1
fi

# 3. Launch the setup UI ----------------------------------------------------
KEYQ="/"; [ -n "${OPENCLAW_UI_KEY:-}" ] && KEYQ="/?key=${OPENCLAW_UI_KEY}"
URL="http://$HOST:$PORT$KEYQ"
echo
echo "==> Starting OpenClaw Setup UI at $URL"
echo "    (bound to $HOST — if this is a remote server, forward the port:"
echo "       ssh -N -L $PORT:127.0.0.1:$PORT <user>@<this-server>  )"
echo

# Best-effort: open a browser if we're on a desktop.
( command -v xdg-open >/dev/null 2>&1 && xdg-open "$URL" >/dev/null 2>&1 ) &
( command -v open     >/dev/null 2>&1 && open     "$URL" >/dev/null 2>&1 ) &

export HOST PORT
exec python3 server.py
