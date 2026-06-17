---
title: Self-hosted second brain with MCP
published: true
canonical_url: https://dev.to/lobrzut/self-hosted-second-brain-with-mcp-59d4
description: Brain AI Hub — local Ollama, vault, RAG, and MCP servers for Cursor and Claude Code. Windows portable or Linux homelab install.
tags: mcp, ollama, homelab, rag, selfhosted, ai
cover_image: https://raw.githubusercontent.com/lobrzut/brain/main/docs/screenshots/dashboard-home.png
---

I run IT and cybersecurity ops by day and tinker in a homelab at night. The problem I kept hitting: useful context from Cursor and Claude Code sessions evaporates when the chat ends. Notes end up scattered. RAG demos are cloud-first. I wanted something I own.

So I built [Brain AI Hub](https://github.com/lobrzut/brain) — a portable second brain with a local LLM, markdown vault, semantic search, and MCP hooks for IDE agents.

## What it does

1. **Local LLM** — Ollama (qwen2.5, nomic-embed). OpenAI-compatible API on `:11434`.
2. **Knowledge store** — Obsidian-style vault, PDF/EPUB library, sqlite-vec RAG, lightweight knowledge graph.
3. **Agent bridge** — three MCP servers (`brain-vault`, `brain-library`, `brain-rag`) with one-click deploy to Cursor, Claude Code, VS Code.
4. **Transcript pipeline** — distills exports from Claude/Cursor/Antigravity into vault markdown, dedupes, indexes code, runs scheduled jobs.
5. **Dashboard** — FastAPI UI on `:7860` for services, chat, GPU/VRAM, API keys, pipeline status.

## Two editions

| Edition | Install |
|---------|---------|
| **Windows portable** | `Install.bat` → `Start.bat` — copy the folder, run on another PC |
| **Linux server** | `curl -fsSL …/linux/bootstrap.sh \| sudo bash` — systemd + MCP SSE gateway on `:7862` for LAN clients |

Install scripts speak English and Polish (`locale.env`: `LANG=en` or `LANG=pl`).

## MCP in practice

On Windows, Brain deploys stdio MCP configs from the dashboard. On Linux, point Cursor at the SSE gateway:

```json
{
  "mcpServers": {
    "brain-rag": {
      "url": "http://192.168.1.10:7862/sse/brain-rag"
    }
  }
}
```

Agents can search your vault, pull library chunks, and run skills without sending data to a third-party memory API.

## Why MCP instead of only RAG?

RAG answers retrieval. MCP gives agents **tools** — write a note, list vault files, trigger a skill, query the code index. That matches how Cursor and Claude Code actually work: function calls mid-session, not a single embedding search at prompt time.

## Stack

Python, FastAPI, Ollama, sqlite-vec, PowerShell (Windows), systemd (Linux). Homelab-friendly: MikroTik/UniFi networking, WireGuard, Docker where it helps.

## Try it

```bash
git clone https://github.com/lobrzut/brain.git
cd brain
# Windows: Install.bat && Start.bat
# Linux:  curl -fsSL https://raw.githubusercontent.com/lobrzut/brain/main/linux/bootstrap.sh | sudo bash
```

Open `http://127.0.0.1:7860`, connect MCP from the Tools tab, drop a PDF in the library, run a distill job on an old chat export.

Related homelab projects: [AI Studio](https://github.com/lobrzut/ai-studio) (ComfyUI + ACE-Step) and [NetDash](https://github.com/lobrzut/netdash) (LAN service dashboard).

Feedback and issues welcome on GitHub.
