# GitHub Repository Profile — lobrzut/brain

## Repository name

`brain`

## Description (short)

Brain AI Hub — portable second brain: Ollama, vault, RAG, MCP. Windows portable + Linux server (PL/EN).

## Website

`http://127.0.0.1:7860` (after `Start.bat` or Linux bootstrap)

## Topics

```
ollama
mcp
rag
fastapi
second-brain
knowledge-management
homelab
self-hosted
windows
linux
powershell
python
cursor
claude
```

## Social preview

Use `docs/screenshots/dashboard-home.png`

## Long about

**Brain** is a self-hosted personal AI platform:

- Local LLM via **Ollama** (offline, GPU)
- **Vault** + **Library** + semantic **RAG** (sqlite-vec)
- **Transcript distillation** from Claude Code / Cursor / Antigravity
- **MCP** servers for IDE agents (`brain-vault`, `brain-library`, `brain-rag`)
- **Dashboard** at `:7860` — chat, pipeline, agent deploy, GPU monitor

**Windows:** portable folder — `Install.bat` → `Start.bat`

**Linux:** `curl -fsSL …/linux/bootstrap.sh | sudo bash` — systemd + MCP SSE gateway on `:7862`
