#!/usr/bin/env python3
"""
OpenClaw first-time setup UI — a minimal, zero-dependency backend.

Drives the OpenClaw CLI on behalf of a small HTML page:
  * Telegram  -> `openclaw channels add --channel telegram --token <BOT_TOKEN>`
                 (+ optional `config set commands.ownerAllowFrom [...]`)
  * Codex     -> `openclaw models auth login --provider openai --method oauth`
                 (interactive: shows the auth URL, takes the pasted code)
  * Gateway   -> `openclaw gateway restart`

The Codex login needs a real TTY, so it is run inside a pseudo-terminal (pty).
Only the Python standard library is used — no npm install, no pip install.

Run:   python3 server.py            # http://127.0.0.1:8765
       PORT=9000 python3 server.py  # custom port
"""

import fcntl
import json
import os
import re
import select
import signal
import struct
import subprocess
import sys
import termios
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, urlencode

HERE = os.path.dirname(os.path.abspath(__file__))
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8765"))
OPENCLAW = os.environ.get("OPENCLAW_BIN", "openclaw")
# Pass through e.g. PROFILE=dev to isolate state while testing.
PROFILE = os.environ.get("OPENCLAW_PROFILE", "").strip()
# Optional shared secret. When set, every request must carry ?key=<value>.
# Leave unset for localhost-only use; set it before exposing the UI.
UI_KEY = os.environ.get("OPENCLAW_UI_KEY", "").strip()

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|[\x00-\x08\x0b\x0c\x0e-\x1f]")
URL_RE = re.compile(r"https://auth\.openai\.com/oauth/authorize\?[^\s\"'<>]+")


def strip_ansi(text: str) -> str:
    """Remove ANSI escapes / control chars so output is readable in the browser."""
    return ANSI_RE.sub("", text).replace("\r", "")


def base_args():
    return [OPENCLAW] + (["--profile", PROFILE] if PROFILE else [])


def run_cmd(args, timeout=120):
    """Run a non-interactive openclaw command and capture combined output."""
    try:
        proc = subprocess.run(
            base_args() + args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            text=True,
        )
        return {"ok": proc.returncode == 0, "exitCode": proc.returncode,
                "output": strip_ansi(proc.stdout or "")}
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "exitCode": None,
                "output": strip_ansi(exc.output or "") + "\n[timed out]"}
    except FileNotFoundError:
        return {"ok": False, "exitCode": None,
                "output": f"Command not found: {OPENCLAW}. Is OpenClaw installed and on PATH?"}


# ---------------------------------------------------------------------------
# Telegram Bot API helper — validate the token + send a confirmation message
# directly (no gateway needed), so the connection can be tested before adding.
# ---------------------------------------------------------------------------

def tg_call(token, method, params=None, timeout=15):
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urlencode(params).encode() if params else None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode())
        except Exception:
            return {"ok": False, "description": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"ok": False, "description": str(exc)}


def _parse_json_blob(text):
    """Pull the first JSON object out of CLI output (which may have log lines)."""
    text = strip_ansi(text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return None


def telegram_pairing_list():
    """List pending Telegram pairing requests (people who messaged the bot)."""
    try:
        proc = subprocess.run(
            base_args() + ["pairing", "list", "telegram", "--json"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=60, text=True,
        )
    except Exception as exc:
        return {"ok": False, "requests": [], "output": str(exc)}
    data = _parse_json_blob(proc.stdout)
    if data is None:
        msg = strip_ansi(proc.stderr or proc.stdout or "Could not read pairing requests.")
        return {"ok": False, "requests": [], "output": msg.strip()}
    return {"ok": True, "requests": data.get("requests", [])}


def telegram_approve(body):
    code = (body.get("code") or "").strip()
    if not code:
        return {"ok": False, "output": "Pairing code is required."}
    return run_cmd(["pairing", "approve", "telegram", code, "--notify"], timeout=60)


def telegram_test(body):
    token = (body.get("botToken") or "").strip()
    owners_raw = (body.get("ownerIds") or "").strip()
    if not token:
        return {"ok": False, "output": "Bot token is required."}

    me = tg_call(token, "getMe")
    if not me.get("ok"):
        return {"ok": False, "output": f"Token rejected by Telegram: {me.get('description', 'invalid token')}"}

    bot = me.get("result", {})
    uname = bot.get("username", "?")
    lines = [f"✓ Token valid — bot @{uname} (id {bot.get('id')})"]

    ids = [i for i in re.split(r"[,\s]+", owners_raw) if i.strip()]
    all_ok = True
    if not ids:
        lines.append("No user ID entered — skipped the confirmation message.")
        lines.append("Add your numeric user ID above to receive a test message.")
        return {"ok": True, "output": "\n".join(lines), "bot": uname}

    text = (f"✅ OpenClaw setup\nYour bot @{uname} is connected and can message you. "
            f"You're all set to add it as a channel.")
    for cid in ids:
        res = tg_call(token, "sendMessage", {"chat_id": cid, "text": text})
        if res.get("ok"):
            lines.append(f"✓ Confirmation message sent to {cid}")
        else:
            all_ok = False
            desc = (res.get("description") or "failed").strip()
            hint = ""
            low = desc.lower()
            if "chat not found" in low or "initiate" in low or "forbidden" in low or "blocked" in low:
                hint = f"  → In Telegram, open @{uname} and press Start, then test again."
            lines.append(f"✗ Could not message {cid}: {desc}{hint}")
    return {"ok": all_ok, "output": "\n".join(lines), "bot": uname}


# ---------------------------------------------------------------------------
# Interactive Codex OAuth driven through a pseudo-terminal.
# ---------------------------------------------------------------------------

class PtySession:
    def __init__(self, args):
        self.args = args
        self.pid = None
        self.fd = None
        self.buf = ""
        self.lock = threading.Lock()
        self.done = False
        self.exit_code = None

    def start(self):
        import pty
        self.pid, self.fd = pty.fork()
        if self.pid == 0:  # child
            # A real-looking terminal so the prompt library (clack) renders
            # normally instead of in raw/fallback mode.
            os.environ["TERM"] = "xterm-256color"
            try:
                os.execvp(self.args[0], self.args)
            except Exception:
                os._exit(127)
        # Give the PTY a sane window size. Without this the terminal is treated
        # as zero-width, clack wraps every character, and a pasted redirect URL
        # gets mangled in the input field so it never submits.
        try:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
        except Exception:
            pass
        return self.pid

    def _drain(self, idle=0.4, deadline=12.0, until=None, settle=1.0):
        """Read PTY output.

        Stops when: `until` regex matches the buffer (then reads `settle` more
        seconds to flush the following prompt), OR the process exits, OR — only
        once some output has arrived — it stays quiet for `idle` seconds, OR
        `deadline` passes. The "output has arrived" guard matters because
        OpenClaw takes several seconds to emit its first byte.
        """
        end = time.time() + deadline
        last = time.time()
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], 0.2)
            if r:
                try:
                    chunk = os.read(self.fd, 4096)
                except OSError:
                    self._reap()
                    break
                if not chunk:
                    self._reap()
                    break
                with self.lock:
                    self.buf += chunk.decode("utf-8", "replace")
                last = time.time()
                if until and until.search(self.buf):
                    self._settle(settle)
                    break
            elif until is None and self.buf and time.time() - last >= idle:
                # Idle-break only when not waiting for a specific pattern;
                # otherwise a quiet gap before the target text ends us early.
                break
            self._poll_exit()
            if self.done:
                break

    def _settle(self, seconds):
        """After the target text appears, briefly keep reading trailing output."""
        end = time.time() + seconds
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], 0.2)
            if not r:
                continue
            try:
                chunk = os.read(self.fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            with self.lock:
                self.buf += chunk.decode("utf-8", "replace")

    def _poll_exit(self):
        try:
            wpid, status = os.waitpid(self.pid, os.WNOHANG)
            if wpid == self.pid:
                self.done = True
                self.exit_code = os.waitstatus_to_exitcode(status)
        except ChildProcessError:
            self.done = True

    def _reap(self):
        self._poll_exit()
        self.done = True

    def write_line(self, text):
        # clack runs the terminal in raw mode, where Enter is carriage-return
        # (\r), not newline (\n). Sending \n leaves the value unsubmitted.
        os.write(self.fd, (text + "\r").encode())

    def clean(self):
        with self.lock:
            return strip_ansi(self.buf)

    def kill(self):
        try:
            os.kill(self.pid, signal.SIGTERM)
        except Exception:
            pass


SESSIONS = {}
SESSIONS_LOCK = threading.Lock()


def codex_start():
    args = base_args() + ["models", "auth", "login", "--provider", "openai", "--method", "oauth"]
    sess = PtySession(args)
    sess.start()
    sess._drain(deadline=35.0, until=URL_RE, settle=1.2)  # read until the auth URL appears
    text = sess.clean()
    match = URL_RE.search(text)
    sid = uuid.uuid4().hex
    with SESSIONS_LOCK:
        SESSIONS[sid] = sess
    return {"ok": match is not None, "sessionId": sid,
            "url": match.group(0) if match else None,
            "output": text, "done": sess.done}


def codex_submit(sid, code):
    with SESSIONS_LOCK:
        sess = SESSIONS.get(sid)
    if not sess:
        return {"ok": False, "output": "No active Codex login session. Click 'Start Codex login' again."}
    if sess.done:
        return {"ok": False, "output": "Session already finished. Start a new login if needed."}
    before = len(sess.buf)
    sess.write_line(code.strip())
    # Wait for the process to exit (success) or, if it re-prompts, fall back to
    # an idle timeout. Token exchange has network gaps, so keep idle generous.
    sess._drain(idle=3.0, deadline=60.0)
    text = sess.clean()
    new_output = strip_ansi(sess.buf[before:])
    ok = sess.done and (sess.exit_code in (0, None)) and "error" not in new_output.lower()
    if sess.done:
        with SESSIONS_LOCK:
            SESSIONS.pop(sid, None)
    return {"ok": ok, "output": text, "done": sess.done, "exitCode": sess.exit_code}


# ---------------------------------------------------------------------------
# HTTP handlers
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):  # quiet
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj))

    def _authed(self):
        """When a key is configured, require it as ?key=… on every request."""
        if not UI_KEY:
            return True
        q = parse_qs(urlparse(self.path).query)
        return (q.get("key", [""])[0] == UI_KEY)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return {}

    def do_GET(self):
        if not self._authed():
            return self._send(401, b"Unauthorized: missing or wrong ?key=")
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            try:
                with open(os.path.join(HERE, "index.html"), "rb") as fh:
                    self._send(200, fh.read(), "text/html; charset=utf-8")
            except FileNotFoundError:
                self._send(404, b"index.html not found")
        elif path == "/api/status":
            self._json(run_cmd(["status"], timeout=60))
        elif path == "/api/channels":
            self._json(run_cmd(["channels", "status"], timeout=60))
        elif path == "/api/telegram/pairing":
            self._json(telegram_pairing_list())
        else:
            self._send(404, b"not found")

    def do_POST(self):
        if not self._authed():
            return self._send(401, b"Unauthorized: missing or wrong ?key=")
        path = urlparse(self.path).path
        body = self._read_json()
        if path == "/api/telegram/test":
            self._json(telegram_test(body))
        elif path == "/api/telegram/approve":
            self._json(telegram_approve(body))
        elif path == "/api/telegram":
            self._json(self._telegram(body))
        elif path == "/api/codex/start":
            self._json(codex_start())
        elif path == "/api/codex/submit":
            self._json(codex_submit(body.get("sessionId", ""), body.get("code", "")))
        elif path == "/api/gateway/restart":
            self._json(self._gateway_apply())
        else:
            self._send(404, b"not found")

    def _gateway_apply(self):
        """Bring the gateway up (first-time install + start) or restart it.

        Idempotent: ensures gateway.mode=local, (re)installs the service, then
        restarts it. On a fresh box a plain `gateway restart` fails because no
        service exists yet, so we install first.
        """
        steps = [
            ("config set gateway.mode local", ["config", "set", "gateway.mode", "local"]),
            ("gateway install --force",       ["gateway", "install", "--force"]),
            ("gateway restart",               ["gateway", "restart"]),
        ]
        out, ok = [], True
        for label, args in steps:
            res = run_cmd(args, timeout=120)
            out.append(f"$ openclaw {label}\n{res['output'].strip()}")
            ok = ok and res["ok"]
        return {"ok": ok, "output": "\n\n".join(out)}

    def _telegram(self, body):
        token = (body.get("botToken") or "").strip()
        owners_raw = (body.get("ownerIds") or "").strip()
        if not token:
            return {"ok": False, "output": "Bot token is required."}
        steps = []
        add = run_cmd(["channels", "add", "--channel", "telegram", "--token", token])
        steps.append(("channels add", add))
        ok = add["ok"]
        if owners_raw:
            ids = [i.strip() for i in re.split(r"[,\s]+", owners_raw) if i.strip()]
            if ids:
                cfg = run_cmd(["config", "set", "commands.ownerAllowFrom", json.dumps(ids)])
                steps.append(("config set ownerAllowFrom", cfg))
                ok = ok and cfg["ok"]
        output = "\n".join(f"$ openclaw {label}\n{res['output'].strip()}" for label, res in steps)
        return {"ok": ok, "output": output}


def main():
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    label = f"--profile {PROFILE} " if PROFILE else ""
    keyq = f"/?key={UI_KEY}" if UI_KEY else "/"
    print(f"OpenClaw setup UI  ->  http://{HOST}:{PORT}{keyq}   (driving: {OPENCLAW} {label}...)")
    print(f"Auth: {'key required' if UI_KEY else 'none (localhost only)'}.  Press Ctrl+C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        srv.shutdown()


if __name__ == "__main__":
    main()
