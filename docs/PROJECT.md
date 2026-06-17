# Brain — project overview

## Editions

| Edition | Directory | Install | Data |
|---------|-----------|---------|------|
| **Windows** | Portable repo folder | `Install.bat` | `<brain>/data/` |
| **Linux** | `/opt/brain` | `linux/bootstrap.sh` | `/var/lib/brain` |

Set language for scripts: `locale.env` with `LANG=pl` or `LANG=en`.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Dashboard :7860 (FastAPI + static UI)                   │
│  - Service status, chat widget, pipeline controls       │
│  - Agent MCP deploy, API key vault, backup              │
└────────────┬────────────────────────────────────────────┘
             │
    ┌────────┴────────┬──────────────┬─────────────────┐
    ▼                 ▼              ▼                 ▼
 Ollama :11434    pipeline/      MCP stdio       MCP SSE :7862
 (local LLM)      distill,rag    (Windows)      (Linux LAN)
                  scheduler      Cursor local   remote Cursor
```

## MCP servers

| Server | Transport | Tools |
|--------|-----------|-------|
| `brain-vault` | filesystem | Read/write vault markdown |
| `brain-library` | filesystem | PDF/EPUB library files |
| `brain-rag` | Python MCP | search_library, run_skill, code search, user profile |

## Data layout (not in git)

```
data/
├── vault/          # Your notes (Obsidian-compatible)
├── library/        # PDFs, EPUBs for RAG
├── api-keys.json   # Cloud provider keys (gitignored)
├── brain-raw/      # Normalized transcripts (regenerable)
└── vectordb/       # sqlite-vec index
```

## Roadmap ideas

- Dashboard PL/EN UI switcher (scripts already bilingual)
- HTTPS + basic auth for Linux LAN exposure
- Automated vault sync (git/Syncthing) wizard in UI
- Publish `brain-setup.ps1` generator as optional fat installer

## Related repos (separate products)

See [HOMELAB-PROJECTS.md](HOMELAB-PROJECTS.md) for ports, screenshots, and posting rules.

| Project | Repo | Role |
|---------|------|------|
| AI Studio | [ai-studio](https://github.com/lobrzut/ai-studio) | ComfyUI + ACE-Step creative stack (`:7880`) |
| NetDash | [netdash](https://github.com/lobrzut/netdash) | Homelab service dashboard (`:18787`) |
