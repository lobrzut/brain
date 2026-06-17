# Brain — Linux server edition

One-command install on Debian / Ubuntu homelab:

```bash
curl -fsSL https://raw.githubusercontent.com/lobrzut/brain/main/linux/bootstrap.sh | sudo bash
```

## Paths

| Path | Purpose |
|------|---------|
| `/opt/brain` | Application code (git clone) |
| `/var/lib/brain` | User data: vault, library, API keys |
| `/opt/brain/.venv` | Python virtualenv |

## Services

| Unit | Port | Role |
|------|------|------|
| `brain-dashboard` | 7860 | FastAPI dashboard + API |
| `brain-mcp-gateway` | 7862 | MCP over SSE (supergateway) |
| `ollama` | 11434 | Local LLM (system package) |

```bash
sudo systemctl status brain-dashboard brain-mcp-gateway
sudo journalctl -u brain-dashboard -f
```

## Remote MCP (Cursor)

Copy [`docs/cursor-mcp-remote.json`](docs/cursor-mcp-remote.json) into `~/.cursor/mcp.json` on your workstation. Replace `YOUR_SERVER_IP` with the homelab LAN address.

## Language (PL / EN)

Install messages respect `/opt/brain/locale.env`:

```bash
echo 'LANG=pl' | sudo tee /opt/brain/locale.env
```

## Environment overrides

```bash
BRAIN_DIR=/opt/brain BRAIN_DATA=/var/lib/brain \
BRAIN_DASHBOARD_PORT=7860 BRAIN_MCP_PORT=7862 \
BRAIN_BIND=0.0.0.0 BRAIN_MODEL=qwen2.5:14b \
  bash linux/install.sh
```

## Firewall

Allow LAN access only:

```bash
sudo ufw allow from 192.168.1.0/24 to any port 7860
sudo ufw allow from 192.168.1.0/24 to any port 7862
```

Dashboard has **no built-in authentication** — do not expose to the public internet without a reverse proxy and auth.
