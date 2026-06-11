# OpenClaw Setup UI

A minimal, zero-dependency web UI for first-time OpenClaw setup. It drives the
`openclaw` CLI for you so you can configure **Telegram** and **Codex (ChatGPT/
OpenAI OAuth)** from a browser, then restart the gateway.

No npm/pip install — it uses only the Python 3 standard library (the OAuth login
needs a real terminal, so the backend runs it inside a pseudo-terminal).

## Quick start (clone → one command)

On a fresh server: clone this repo and run `start.sh`. It **installs OpenClaw
if it's missing**, puts it on `PATH`, then launches the UI — open the URL and
fill in the details.

```bash
git clone <this-repo> && cd "<repo>/OPenclaw setup ui"
./start.sh                      # installs OpenClaw if needed, then opens the UI
# custom port:  PORT=9000 ./start.sh
```

`start.sh` runs, in order:

```bash
# installs OpenClaw if `openclaw` isn't found:
curl -fsSL https://openclaw.ai/install.sh | bash
export PATH="$HOME/.npm-global/bin:$PATH"
openclaw --version
# then starts the UI:  python3 server.py  (http://127.0.0.1:8765)
```

If `openclaw` is already installed you can also just run `python3 server.py`.
Python 3 is the only requirement for the UI itself (standard library only —
the OAuth login needs a real terminal, so the backend runs it in a pty).

## What each step does

| Step | Command run |
| --- | --- |
| **1. Telegram** | `openclaw channels add --channel telegram --token <BOT_TOKEN>` (+ `config set commands.ownerAllowFrom '[...]'` for owner IDs). The **Test** button validates the token via Telegram and sends a confirmation message first. |
| **2. Approve users** | `openclaw pairing list telegram --json` / `openclaw pairing approve telegram <code> --notify` — approve people who message the bot |
| **3. Codex** | `openclaw models auth login --provider openai --method oauth` — shows the auth URL, you paste back the code / redirect URL |
| **4. Gateway** | `openclaw config set gateway.mode local` → `gateway install --force` → `gateway restart` (installs + starts on first run) |

### Telegram
- **Bot token** — from [@BotFather](https://t.me/BotFather) (required).
- **Owner / user ID(s)** — your numeric Telegram user ID(s), comma-separated
  (optional). These are allowed to approve actions.

### Codex
1. Click **Start Codex login**. The auth URL appears.
2. Open it in your local browser and sign in with your ChatGPT/Codex account.
3. Copy the authorization code (or the full `localhost:1455/...` redirect URL the
   browser lands on) and paste it into **Step B**, then **Submit code**.

### Gateway
Click **Restart gateway** to apply the new config. If the gateway service isn't
installed yet, the output will tell you (run `openclaw gateway install` once, or
`openclaw gateway` to run it in the foreground).

## Deploy on a new server (auto-start)

`bootstrap.sh` is a **self-contained installer** — it carries `server.py` and
`index.html` inside itself (base64), writes them to `~/.openclaw-setup-ui`,
installs a **systemd user service** that auto-starts on boot (falls back to
`nohup` if user-systemd isn't available), and prints the URL. It downloads
nothing else, so it works even on a locked-down or offline-ish box.

After you've installed OpenClaw on the new server, run **one** of:

```bash
# A) one-liner, if the repo is public (folder has a space -> %20):
curl -fsSL "https://raw.githubusercontent.com/miteshdabhi-e2m/client-brain-ui/E2m-AI-Brain-test/OPenclaw%20setup%20ui/bootstrap.sh" | bash

# B) private repo / no git auth — copy the file over and run it:
scp "OPenclaw setup ui/bootstrap.sh" user@server:/tmp/ && ssh user@server 'bash /tmp/bootstrap.sh'
```

Options (env vars):

| Var | Default | Purpose |
| --- | --- | --- |
| `OPENCLAW_UI_PORT` | `8765` | Port to listen on |
| `OPENCLAW_UI_HOST` | `127.0.0.1` | Bind address (keep loopback) |
| `OPENCLAW_UI_KEY` | _(none)_ | Shared secret — when set, the URL needs `?key=…` |
| `OPENCLAW_UI_DIR` | `~/.openclaw-setup-ui` | Install location |

```bash
# example: pick a port and lock it with a random key
OPENCLAW_UI_PORT=9000 OPENCLAW_UI_KEY=$(openssl rand -hex 8) bash bootstrap.sh
```

Manage the service:
```bash
systemctl --user restart openclaw-setup-ui      # restart
systemctl --user stop openclaw-setup-ui          # stop
journalctl --user -u openclaw-setup-ui -f        # logs
```

> Edited `server.py`/`index.html`? Re-run `./build-bootstrap.sh` to regenerate
> `bootstrap.sh`, then re-host/commit it.

## Sharing the URL with a client

The UI binds to `127.0.0.1` only — it is **not** internet-facing. To let a
client use it, forward the port (no firewall changes, nothing exposed):

```bash
# run from the client's machine (or yours), then open http://localhost:8765
ssh -N -L 8765:127.0.0.1:8765 user@your-server
```

If you instead put it behind your own reverse proxy / tunnel, set
`OPENCLAW_UI_KEY` first and hand the client the `…/?key=<secret>` URL — the
backend rejects any request without the key.

## Notes
- The server binds to `127.0.0.1` only — it is not exposed to the network.
- Tokens are sent to the local backend and handed straight to `openclaw`; they
  are not stored by this app.
- To test against an isolated config, set `OPENCLAW_PROFILE=dev`.
