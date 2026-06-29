# Brain AI Hub

[![Latest release](https://img.shields.io/github/v/release/lobrzut/brain)](https://github.com/lobrzut/brain/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

[![Dashboard demo](docs/screenshots/dashboard-demo.gif)](https://github.com/lobrzut/brain)

A **lightweight, self-hosted knowledge vault + semantic search + MCP server** for Claude Code, Cursor, Antigravity, Claude Desktop, and other agents. Built to run anywhere — a $5/mo VPS is enough; no GPU, no local LLM required for the core.

Write-up: [Self-hosted second brain with MCP](https://dev.to/lobrzut/self-hosted-second-brain-with-mcp-59d4) (DEV Community)

| Edition | Target | Install |
|---------|--------|---------|
| **Windows** | Portable folder, USB-copyable | `Install.bat` → `Start.bat` |
| **Linux** | Any VPS/homelab box, LAN or public MCP gateway (SSE) | `curl …/linux/bootstrap.sh \| sudo bash` |

Install scripts support **Polish** and **English** (`locale.env`: `LANG=pl` or `LANG=en`).

---

## What Brain does

1. **Knowledge store** — vault (Markdown/Obsidian), library (PDF/EPUB/DOCX), semantic RAG (sqlite-vec), knowledge graph.
2. **Agent bridge** — MCP servers (`brain-vault`, `brain-library`, `brain-rag`): semantic search, skills, code index, user profile. Bearer-token gated when exposed beyond localhost — see [CONNECT.md](CONNECT.md).
3. **Dashboard** (`:7860`): service control, chat widget, vault/library browser, GPU/VRAM monitor (when present). Single-user **login** and a **4-language UI** — Polski / English / Deutsch / Українська.

**Where the "thinking" happens:** Brain core does not embed or summarize anything itself — it stores and searches what's handed to it. Distillation (chat → structured note) and embedding happen client-side, typically via a companion desktop app running your own Ollama or a cloud API key, then pushed to Brain's vault. This keeps the server cheap to run and trivial to deploy anywhere. (Brain still ships an optional, opt-in local-compute pipeline for people who want server-side Ollama processing instead — see **Advanced: local compute** below. It is disabled by default.)

---

## Screenshots

| Dashboard | Brain (vault / graph) |
|-----------|------------------------|
| ![Dashboard home](docs/screenshots/dashboard-home.png) | ![Brain tab](docs/screenshots/dashboard-brain.png) |

| Pipeline |
|----------|
| ![Pipeline tab](docs/screenshots/dashboard-pipeline.png) |

---

## Quick start — Windows

```
git clone https://github.com/lobrzut/brain.git
cd brain
Install.bat    # first time — Python embed + Ollama + pip deps
Start.bat      # tray icon + dashboard
```

Open **http://127.0.0.1:7860**

| File | Action |
|------|--------|
| `Install.bat` | Download runtime, install deps, create `config.json` |
| `Start.bat` | Launch tray + Ollama + dashboard |
| `Stop.bat` | Stop all Brain processes |
| `windows/Locale.ps1` | PL/EN strings for scripts |

Copy the whole folder to another PC — run `Install.bat` there (models re-pull separately).

---

## Quick start — Linux server

```bash
curl -fsSL https://raw.githubusercontent.com/lobrzut/brain/main/linux/bootstrap.sh | sudo bash
```

Default paths:
- Code: `/opt/brain`
- Data: `/var/lib/brain`
- Dashboard: `http://<host>:7860`
- MCP SSE gateway: `http://<host>:7862` (for remote Cursor/Claude)

Remote Cursor config example: [`linux/docs/cursor-mcp-remote.json`](linux/docs/cursor-mcp-remote.json)

```bash
# Optional: language for install messages
echo 'LANG=en' | sudo tee /opt/brain/locale.env
```

---

## Repository layout

```
brain/
├── Install.bat / Start.bat / Stop.bat   # Windows entrypoints
├── windows/          # install.ps1, start.ps1, stop.ps1, Locale.ps1 (PL/EN)
├── linux/            # bootstrap.sh, install.sh, systemd, MCP gateway
├── dashboard/        # FastAPI backend + static UI
├── client/           # BRAIN Client — tray app that deploys MCP to agents
├── pipeline/         # distill, RAG, agents, scheduler, skills runner
├── skills/           # Brain agentic workflows (SKILL.md)
├── data/             # templates only in git — your vault/library stay local
├── config.example.json
└── CONNECT.md        # integration guide (MCP, proxy, backup)
```

---

## Ports

| Port | Service |
|------|---------|
| `7860` | Dashboard (FastAPI) |
| `7862` | MCP SSE gateway (Linux server edition) |
| `11434` | Ollama |

---

## MCP — connect your IDE

Three servers get wired into your agent:
- `brain-vault` — read/write vault markdown
- `brain-library` — PDF/EPUB library files
- `brain-rag` — semantic search, skills, code index, user profile

### Recommended: copy-paste, not auto-deploy

Every client (Claude Code, Cursor, Antigravity, Claude Desktop, VS Code, Windsurf)
changes its MCP config format between versions — auto-deploy tools tend to break
silently. The recommended path is a companion desktop app that shows you exactly
what's wired and generates a ready-to-paste config per client, but never writes to
your files for you. See [CONNECT.md](CONNECT.md) for the manual snippets per
client and the Bearer-token setup for remote access.

- **Windows (stdio, local):** Dashboard → TOOLS → AGENTS panel.
- **Linux (SSE, LAN or public):** point your client's `mcp.json` at your server — see [`linux/docs/cursor-mcp-remote.json`](linux/docs/cursor-mcp-remote.json) and [CONNECT.md](CONNECT.md) for the Bearer auth proxy.

### Legacy: BRAIN Client (tray app, auto-deploy)

An older tray app (`client/`) that auto-detects installed agents and writes
all three MCP entries in one double-click. Kept for anyone who already
relies on it, but no longer the recommended path — see above for why.
Build from source: `cd client && pip install -r requirements.txt && python -m brain_client tray`.

---

## Public `/stats` endpoint (for external dashboards)

Brain exposes a compact JSON summary at `http://<host>:7860/stats` — designed
for homelab status tiles (e.g. [netdash](https://github.com/lobrzut/netdash)
has a built-in Brain widget that consumes it).

```json
{
  "ok": true,
  "notes": 1693,           // vault .md count
  "sessions": 39,          // vault/sessions count
  "library_docs": 42,      // PDF/EPUB count
  "code_files": 0,         // code index size
  "graph_nodes": 1693,
  "last_session_at": "2026-06-20T13:14:31",
  "activity_7d": [2,1,0,1,0,1,0]   // sessions per day, oldest → newest
}
```

Cached 60 s, no auth. Toggle in **Dashboard → OPTIONS → CONNECTIVITY**
(`/stats` checkbox) — when disabled, the endpoint returns **HTTP 403**.

---

## Advanced: local compute (optional, disabled by default)

Brain ships an opt-in pipeline for server-side distillation and embedding via
a local Ollama install — useful if you'd rather have your Brain server do the
LLM work itself instead of a desktop client:

- **Local LLM** — Ollama (qwen2.5, nomic-embed). OpenAI-compatible API at `:11434/v1`.
- **Pipeline** — transcript distillation from Claude/Cursor/Antigravity → vault notes, redistill, dedupe, code index, all driven by `pipeline/scheduler.py`'s adaptive background jobs (run only when the machine is idle).
- All scheduled tasks **default to disabled** — enable explicitly in Dashboard → PIPELINE if you want this. Requires `ollama serve` reachable and enough VRAM/RAM for your chosen model.

This pipeline is independent of the core vault/search/MCP functionality — leave it off and Brain still does everything described above.

---

## Security notes

- `data/api-keys.json` is **gitignored** — never commit API keys.
- `data/auth.json` (password hash) and `data/.secret` (cookie key) are **gitignored** — per-machine, never committed.
- `data/vault/` is **your private knowledge** — excluded from git.
- Linux dashboard binds to `0.0.0.0` by default — use firewall/VPN for LAN-only access.
- Single-user **login** gates the dashboard once you set a password on first run; `/api/status` and `/stats` stay public (for the tray client and external status tiles). To reset a forgotten password, delete `data/auth.json` and set it again on next load.

---

## Hardware

Core (vault + search + MCP): runs on 1 vCPU / 512MB RAM — any cheap VPS, a Raspberry Pi, or a spare laptop.

GPU is only relevant if you enable **Advanced: local compute** above — AMD RX 6800+ (Vulkan/ROCm) or NVIDIA with CUDA drivers recommended for that path; CPU-only Ollama works too, just slower.

---

## License

MIT — see [LICENSE](LICENSE).

---

## PL — szybki start

**Windows:** `Install.bat` → `Start.bat` → http://127.0.0.1:7860

**Linux:** `curl -fsSL https://raw.githubusercontent.com/lobrzut/brain/main/linux/bootstrap.sh | sudo bash`

**Język skryptów:** utwórz `locale.env` w katalogu brain z linią `LANG=pl` lub `LANG=en`.

Szczegóły integracji MCP i proxy: [CONNECT.md](CONNECT.md)
