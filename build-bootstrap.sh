#!/usr/bin/env bash
# Regenerate the self-contained bootstrap.sh from the current server.py + index.html.
# Run this whenever you edit those files, then commit/host the new bootstrap.sh.
set -euo pipefail
cd "$(dirname "$0")"

[ -f server.py ]  || { echo "server.py not found"; exit 1; }
[ -f index.html ] || { echo "index.html not found"; exit 1; }

SERVER_B64=$(base64 -w0 server.py)
INDEX_B64=$(base64 -w0 index.html)
OUT=bootstrap.sh

# --- top of bootstrap.sh (literal; no expansion here) ---
cat > "$OUT" <<'HEADER'
#!/usr/bin/env bash
# ============================================================================
#  OpenClaw Setup UI — self-contained installer
#  Installs a localhost-only web UI for first-time OpenClaw setup (Telegram +
#  Codex) and auto-starts it via a systemd user service (falls back to nohup).
#  Self-contained: writes server.py + index.html itself, no other downloads.
#
#  One-liner:   curl -fsSL <url-to-this-file> | bash
#  Customise:   OPENCLAW_UI_PORT=9000 OPENCLAW_UI_KEY=$(openssl rand -hex 8) \
#                 bash bootstrap.sh
# ============================================================================
set -euo pipefail
HEADER

# --- inject the embedded files (base64 is single-quote safe) ---
{
  printf "SERVER_B64='%s'\n" "$SERVER_B64"
  printf "INDEX_B64='%s'\n"  "$INDEX_B64"
} >> "$OUT"

# --- rest of bootstrap.sh (literal; $ expands at install time, not now) ---
cat >> "$OUT" <<'REST'

: "${OPENCLAW_UI_DIR:=$HOME/.openclaw-setup-ui}"
: "${OPENCLAW_UI_PORT:=8765}"
: "${OPENCLAW_UI_HOST:=127.0.0.1}"
: "${OPENCLAW_UI_KEY:=}"

PY=$(command -v python3 || true)
OC=$(command -v openclaw || true)
[ -n "$PY" ] || { echo "ERROR: python3 not found on PATH."; exit 1; }
if [ -z "$OC" ]; then
  echo "WARNING: 'openclaw' is not on PATH yet. Install it first, then re-run,"
  echo "         or edit OPENCLAW_BIN in the service file afterwards."
fi

echo "Installing OpenClaw Setup UI -> $OPENCLAW_UI_DIR"
mkdir -p "$OPENCLAW_UI_DIR"
printf '%s' "$SERVER_B64" | base64 -d > "$OPENCLAW_UI_DIR/server.py"
printf '%s' "$INDEX_B64"  | base64 -d > "$OPENCLAW_UI_DIR/index.html"
chmod +x "$OPENCLAW_UI_DIR/server.py"

install_systemd() {
  command -v systemctl >/dev/null 2>&1 || return 1
  systemctl --user show-environment >/dev/null 2>&1 || return 1
  local unit_dir="$HOME/.config/systemd/user"
  local oc_dir; oc_dir=$(dirname "${OC:-$PY}")
  mkdir -p "$unit_dir"
  cat > "$unit_dir/openclaw-setup-ui.service" <<UNIT
[Unit]
Description=OpenClaw Setup UI
After=network.target

[Service]
Environment=HOST=$OPENCLAW_UI_HOST
Environment=PORT=$OPENCLAW_UI_PORT
Environment=OPENCLAW_BIN=${OC:-openclaw}
Environment=OPENCLAW_UI_KEY=$OPENCLAW_UI_KEY
Environment=PATH=$oc_dir:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=$PY $OPENCLAW_UI_DIR/server.py
WorkingDirectory=$OPENCLAW_UI_DIR
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
UNIT
  loginctl enable-linger "$USER" >/dev/null 2>&1 || true
  systemctl --user daemon-reload >/dev/null 2>&1 || return 1
  systemctl --user enable --now openclaw-setup-ui.service >/dev/null 2>&1 || return 1
  return 0
}

start_nohup() {
  pkill -f "$OPENCLAW_UI_DIR/server.py" 2>/dev/null || true
  HOST="$OPENCLAW_UI_HOST" PORT="$OPENCLAW_UI_PORT" OPENCLAW_BIN="${OC:-openclaw}" \
    OPENCLAW_UI_KEY="$OPENCLAW_UI_KEY" \
    nohup "$PY" "$OPENCLAW_UI_DIR/server.py" >"$OPENCLAW_UI_DIR/ui.log" 2>&1 &
  disown 2>/dev/null || true
}

MODE="nohup"
if install_systemd; then
  MODE="systemd"
else
  echo "systemd user service unavailable — starting with nohup instead."
  echo "(It will run now but NOT restart on reboot. Re-run after enabling linger"
  echo " if you want boot persistence.)"
  start_nohup
fi

KEYQ="/"; [ -n "$OPENCLAW_UI_KEY" ] && KEYQ="/?key=$OPENCLAW_UI_KEY"
sleep 1

echo
echo "============================================================"
echo " OpenClaw Setup UI is running ($MODE)."
echo "   URL:   http://$OPENCLAW_UI_HOST:$OPENCLAW_UI_PORT$KEYQ"
echo "   Bound to $OPENCLAW_UI_HOST only — not internet-facing."
echo
echo " Share it with a client by forwarding the port. From their"
echo " machine (or yours), run:"
echo "   ssh -N -L $OPENCLAW_UI_PORT:127.0.0.1:$OPENCLAW_UI_PORT <user>@<this-server>"
echo " then open  http://localhost:$OPENCLAW_UI_PORT$KEYQ"
echo
if [ "$MODE" = "systemd" ]; then
echo " Manage:  systemctl --user {status|restart|stop} openclaw-setup-ui"
echo "   Logs:  journalctl --user -u openclaw-setup-ui -f"
else
echo " Logs:    tail -f $OPENCLAW_UI_DIR/ui.log"
fi
echo "============================================================"
REST

chmod +x "$OUT"
echo "Wrote $OUT ($(wc -c < "$OUT") bytes)."
