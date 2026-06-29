"""brain-rag MCP server — exposes search_library tool to MCP clients.

Run: bin/python/python.exe dashboard/mcp_rag.py
Configured in Claude Desktop config or any MCP client.
"""
from __future__ import annotations
import asyncio, importlib, json, sys
from pathlib import Path

# Force UTF-8 for stdio — Polish chars in filenames otherwise crash
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import rag  # noqa
import skills as _skills  # noqa
import codeindex as _codeindex  # noqa

def _reload_rag():
    """Hot-reload modules so edits take effect without restarting Claude Desktop."""
    global rag, _skills, _codeindex
    try:
        rag = importlib.reload(rag)
        _skills = importlib.reload(_skills)
        _codeindex = importlib.reload(_codeindex)
    except Exception:
        pass

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

server = Server("brain-rag")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_library",
            description=(
                "Semantic search over the user's entire brain — ONE shared vector index covering both: "
                "(a) distilled conversation notes (data/vault/distilled/*.md from Claude.ai, Grok, "
                "Claude Code, Antigravity) AND (b) PDFs/EPUBs/DOCXs in data/library/. "
                "Returns top matching chunks with source filename + page. "
                "Use this WHENEVER the user asks 'what did I discuss about X', 'find that conversation "
                "about Y', 'what do my notes say about Z', or any factual question that might be in "
                "their personal knowledge base. Optional source filter narrows to vault-only or "
                "library-only when you specifically need notes vs. books."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query":  {"type": "string",
                               "description": "Natural-language search query"},
                    "top_k":  {"type": "integer", "default": 5,
                               "description": "How many results to return (default 5, max 20)"},
                    "source": {"type": "string", "enum": ["all", "vault", "library"],
                               "default": "all",
                               "description": "Filter: 'vault' = only conversation notes, 'library' = only books/PDFs, 'all' = both (default)"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="library_status",
            description=(
                "Returns summary of the indexed library: number of PDFs, "
                "number of chunks, list of file names."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="list_skills",
            description=(
                "List all available brain skills (reusable LLM workflows). "
                "Each skill is a markdown file in brain/skills/ with declarative "
                "context gathering + a prompt. Returns name, description, model, "
                "expected inputs."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="search_code",
            description=(
                "Semantic search over the user's source code projects (separate index "
                "from brain knowledge base — see codeindex.py). Returns top matching "
                "code chunks with filename, line numbers, language, extracted symbols "
                "(functions/classes), and score. Use this when user asks about THEIR "
                "code: 'find that function that did X', 'show me where I implemented Y', "
                "'what scripts use Z'. Does NOT search brain notes — use search_library "
                "for that."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural-language code query"},
                    "top_k": {"type": "integer", "default": 10,
                              "description": "Max results (default 10, max 30)"},
                    "lang":  {"type": "string",
                              "description": "Optional file extension filter (e.g. '.py', '.ts', '.pine')"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="code_status",
            description=(
                "Returns code index status: number of watched paths, indexed files, "
                "chunks, language distribution."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="save_conversation",
            description=(
                "Save the current conversation to the brain vault as a structured note. "
                "CRITICAL: If the user says 'zapisz do brain', 'zapisz do braim', 'zapisz rozmowę', "
                "'zapisz', 'save to brain', or similar, you MUST immediately invoke this tool. "
                "Read the entire conversation history, extract ALL arguments directly from the context. "
                "\n\n"
                "QUALITY RULES — these notes are read months later, generalizations are USELESS:\n"
                "• Prefer CONCRETE over abstract. 'Edited dashboard/app.py:2154 to add /api/agents/deploy' "
                "beats 'updated dashboard'.\n"
                "• Include exact file paths with line numbers, exact commands run, exact URLs/IPs/ports, "
                "exact error messages (HTTP codes, stack lines).\n"
                "• Record what was TRIED AND FAILED in attempts_failed — anti-solutions are gold for "
                "future debugging.\n"
                "• Root cause ≠ solution. Put the WHY in root_causes (e.g. 'mcp-proxy expects /mcp, "
                "Antigravity sent /sse'), the FIX in solutions (e.g. 'changed serverUrl to /mcp')."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "source":    {"type": "string",
                                  "description": "Which AI assistant — 'antigravity', 'claude-desktop', 'claude-code', 'cursor', etc."},
                    "topic":     {"type": "string",
                                  "description": "Short topic/title (e.g. 'Brain MCP audit + Antigravity config fix')"},
                    "summary":   {"type": "string",
                                  "description": "2-4 sentence high-level summary — what happened, why, outcome"},
                    "decisions": {"type": "array", "items": {"type": "string"},
                                  "description": "Concrete decisions made (bullet form). Include rationale: 'Chose X over Y because Z'"},
                    "solutions": {"type": "array", "items": {"type": "string"},
                                  "description": "Working FIXES with concrete details (file:line, exact command, config diff). What actually worked."},
                    "root_causes": {"type": "array", "items": {"type": "string"},
                                  "description": "WHY things broke (separate from solutions). 'X expected Y but got Z because W'. Future-debugging gold."},
                    "attempts_failed": {"type": "array", "items": {"type": "string"},
                                  "description": "Anti-solutions — what was tried and DIDN'T work, and why. Prevents wasted future attempts."},
                    "files_touched": {"type": "array", "items": {"type": "string"},
                                  "description": "Concrete files edited or referenced with paths and (when relevant) line numbers. E.g. 'dashboard/app.py:2154-2203 (api_agents endpoints)'"},
                    "commands_run": {"type": "array", "items": {"type": "string"},
                                  "description": "Exact commands executed (bash, powershell, curl, git). Include flags and output snippets if relevant."},
                    "endpoints_urls_ips": {"type": "array", "items": {"type": "string"},
                                  "description": "All URLs, hostnames, IPs, ports, paths discussed/used. E.g. 'http://192.168.1.201:7862/mcp (mcp-proxy streamable-http)'."},
                    "errors_seen": {"type": "array", "items": {"type": "string"},
                                  "description": "Exact error messages observed (HTTP codes, stack snippets, log lines). Critical for future grep."},
                    "facts":     {"type": "array", "items": {"type": "string"},
                                  "description": "Non-obvious facts learned: terms, behaviors, gotchas, version quirks. Things you didn't know before this session."},
                    "open_questions": {"type": "array", "items": {"type": "string"},
                                        "description": "Questions still unanswered. Mark with owner/next-step where possible."},
                    "msg_count": {"type": "integer", "default": 0,
                                  "description": "Approximate number of messages in this session"},
                },
                "required": ["source", "topic", "summary"],
            },
        ),
        Tool(
            name="run_skill",
            description=(
                "Execute a brain skill by name. The skill gathers context from "
                "vault/library (RAG hits, recent notes, filtered files), formats "
                "its prompt with the user's inputs, calls Ollama, and optionally "
                "saves output to vault/digests/. Returns the LLM output text. "
                "Use this when the user asks 'zrób digest tradingowy', 'update CV', "
                "'zbierz konfig MikroTika' itp."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name":   {"type": "string",
                               "description": "Skill name (e.g. 'trading-digest', 'cv-update', 'mikrotik-config', 'dedupe-vault', 'inbox-process')"},
                    "inputs": {"type": "object",
                               "description": "Key-value inputs to override skill defaults",
                               "default": {}},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="get_user_profile",
            description=(
                "Read the user's persistent profile (vault/USER.md). "
                "ALWAYS call this at the start of any non-trivial session so you know who you're talking to: "
                "technical background, communication preferences, income constraints, things to avoid. "
                "Returns §-delimited profile entries with char usage."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="memory",
            description=(
                "Add, replace or remove an entry in the user's persistent profile (vault/USER.md). "
                "Call this DURING conversation when you learn something worth remembering permanently: "
                "preferences, corrections, new tech they use, things to avoid, income constraints. "
                "SKIP trivial/obvious facts and session-specific ephemera. "
                "actions: 'add' = new §-entry, 'replace' = update via substring match, 'remove' = delete via substring match. "
                "categories: 'user' (personal/prefs), 'tech' (tools/stack), 'comm' (communication style), 'income' (money constraints). "
                "Returns updated profile + char count (max 2000)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "action":   {"type": "string", "enum": ["add", "replace", "remove"],
                                 "description": "add=new entry, replace=update existing substring, remove=delete substring"},
                    "content":  {"type": "string",
                                 "description": "The memory content to add, or the substring to find for replace/remove"},
                    "new_content": {"type": "string",
                                    "description": "For replace action: the new content to put in place of the matched substring"},
                    "category": {"type": "string", "enum": ["user", "tech", "comm", "income"],
                                 "default": "user",
                                 "description": "Which §-section to add to (for 'add' action)"},
                },
                "required": ["action", "content"],
            },
        ),
        Tool(
            name="list_cli_skills",
            description=(
                "List all available CLI expertise skills from ~/.claude/skills/. "
                "These are expert-knowledge injections (NOT LLM workflows) covering: "
                "security (recon, web, exploit, malware, cloud), networking (MikroTik, "
                "Cisco, BGP, WireGuard, UniFi, VLANs), programming (Python, frontend), "
                "trading (algo, crypto, Pine Script). "
                "Returns name + description for each. Use get_skill(name) to load full expertise."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_skill",
            description=(
                "Fetch the full expertise prompt for a CLI skill from ~/.claude/skills/. "
                "Loading this gives YOU (the agent) deep domain knowledge for the current task. "
                "Use when the conversation topic matches: "
                "MikroTik/RouterOS → 'mikrotik-routeros', "
                "web hacking/bug bounty → '09-web-security', "
                "Cisco IOS → 'cisco-ios-patterns', "
                "Python programming → 'advanced-programming', "
                "WireGuard VPN → 'homelab-wireguard-vpn', "
                "recon/OSINT → '01-recon-osint', "
                "network traffic/IDS → '08-network-security', "
                "exploit dev → '03-exploit-development', "
                "algo trading → 'algorithmic-trading-expert', "
                "crypto trading → 'crypto-trading-analysis'. "
                "Call list_cli_skills first if unsure of exact name."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string",
                             "description": "Skill folder name (e.g. 'mikrotik-routeros', '09-web-security', 'cisco-ios-patterns')"},
                },
                "required": ["name"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "search_library":
        q = arguments.get("query", "").strip()
        if not q:
            return [TextContent(type="text", text="error: empty query")]
        top_k = min(20, max(1, int(arguments.get("top_k", 5))))
        source = arguments.get("source", "all")
        if source not in ("all", "vault", "library"):
            source = "all"
        _reload_rag()
        try:
            hits = rag.search(q, top_k, source=source)
        except Exception as e:
            return [TextContent(type="text", text=f"search error: {e}")]
        if not hits:
            return [TextContent(type="text",
                    text="No matches. Index may be empty — run reindex from Brain dashboard or `python pipeline/rag.py index`.")]
        parts = []
        for h in hits:
            parts.append(f"### {h['pdf']} · page {h['page']} (score {h['score']})\n{h['text']}")
        return [TextContent(type="text", text="\n\n---\n\n".join(parts))]

    if name == "library_status":
        s = rag.status()
        out = {
            "indexed_chunks": s.get("index_chunks", 0),
            "indexed_pdfs":   s.get("index_pdfs", 0),
            "files":          s.get("files", []),
            "db_path":        s.get("db_path", ""),
        }
        return [TextContent(type="text", text=json.dumps(out, indent=2, ensure_ascii=False))]

    if name == "search_code":
        q = arguments.get("query", "").strip()
        if not q:
            return [TextContent(type="text", text="error: empty query")]
        top_k = min(30, max(1, int(arguments.get("top_k", 10))))
        lang = arguments.get("lang")
        _reload_rag()
        try:
            hits = _codeindex.search(q, top_k, lang)
        except Exception as e:
            return [TextContent(type="text", text=f"code search error: {e}")]
        if not hits:
            return [TextContent(type="text",
                    text="No code matches. Add a watched path + run scan via dashboard "
                         "(TOOLS → CODE INDEX) or `python pipeline/codeindex.py add <path>` "
                         "then `... scan`.")]
        parts = []
        for h in hits:
            syms = f" [symbols: {', '.join(h['symbols'][:5])}]" if h['symbols'] else ""
            parts.append(f"### {h['file']} L{h['lines']} ({h['lang']}) score={h['score']}{syms}\n```\n{h['text']}\n```")
        return [TextContent(type="text", text="\n\n---\n\n".join(parts))]

    if name == "code_status":
        _reload_rag()
        s = _codeindex.status()
        return [TextContent(type="text", text=json.dumps(s, indent=2, ensure_ascii=False))]

    if name == "save_conversation":
        import datetime, re
        src             = (arguments.get("source") or "unknown").strip().lower()
        topic           = (arguments.get("topic") or "untitled").strip()
        summary         = (arguments.get("summary") or "").strip()
        decisions       = arguments.get("decisions") or []
        solutions       = arguments.get("solutions") or []
        root_causes     = arguments.get("root_causes") or []
        attempts_failed = arguments.get("attempts_failed") or []
        files_touched   = arguments.get("files_touched") or []
        commands_run    = arguments.get("commands_run") or []
        endpoints       = arguments.get("endpoints_urls_ips") or []
        errors_seen     = arguments.get("errors_seen") or []
        facts           = arguments.get("facts") or []
        questions       = arguments.get("open_questions") or []
        msg_count       = int(arguments.get("msg_count") or 0)

        # Sanitize topic for filename — keep alphanumerics + underscores
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", topic)[:60].strip("_") or "session"
        date = datetime.datetime.now().strftime("%Y-%m-%d")
        time_part = datetime.datetime.now().strftime("%H-%M")
        filename  = f"{date}_{src}_{slug}_{time_part}.md"

        sessions_dir = ROOT / "data" / "vault" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        out_path = sessions_dir / filename

        def _bullets(items):
            return "\n".join(f"- {x}" for x in items) if items else "- _(none)_"

        # Build optional sections — only render if there's content (avoid noise notes)
        def _section(title: str, items) -> str:
            if not items:
                return ""
            return f"\n## {title}\n{_bullets(items)}\n"

        content = f"""---
source: {src}
project: {topic}
date: {date}
session_id: {time_part}
msg_count: {msg_count}
saved_via: mcp_save_conversation
schema_version: 2
---

# {date} · {src} · {topic}

## Summary
{summary}

## Decisions
{_bullets(decisions)}

## Root causes
{_bullets(root_causes)}

## Solutions
{_bullets(solutions)}
{_section("Attempts that failed", attempts_failed)}{_section("Files touched", files_touched)}{_section("Commands run", commands_run)}{_section("Endpoints / URLs / IPs", endpoints)}{_section("Errors seen", errors_seen)}
## Facts
{_bullets(facts)}

## Open questions
{_bullets(questions)}
"""
        try:
            tmp = out_path.with_suffix(".md.tmp")
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(out_path)
        except Exception as e:
            return [TextContent(type="text", text=f"save failed: {e}")]

        return [TextContent(
            type="text",
            text=(f"✓ Saved to vault/sessions/{filename}\n"
                  f"Will appear on knowledge graph within 30s.\n"
                  f"Searchable via search_library after next reindex.")
        )]

    if name == "list_skills":
        _reload_rag()
        out = _skills.list_skills()
        return [TextContent(type="text", text=json.dumps(out, indent=2, ensure_ascii=False))]

    if name == "run_skill":
        _reload_rag()
        skill = arguments.get("name", "").strip()
        if not skill:
            return [TextContent(type="text", text="error: skill name required")]
        inputs = arguments.get("inputs") or {}
        try:
            r = _skills.run_skill(skill, inputs)
        except Exception as e:
            return [TextContent(type="text", text=f"skill run error: {e}")]
        if not r.get("ok"):
            return [TextContent(type="text", text=f"skill failed: {r.get('error', 'unknown')}")]
        header = (f"skill={r['skill']} model={r['model']} duration={r['duration']}s "
                  f"saved={r.get('saved_to') or '-'}\n\n")
        return [TextContent(type="text", text=header + (r.get("output") or ""))]

    USER_MD = ROOT / "data" / "vault" / "USER.md"
    USER_MAX = 2200  # like Hermes USER.md limit

    if name == "get_user_profile":
        if not USER_MD.exists():
            return [TextContent(type="text", text="No user profile yet. Call memory(add,...) to create entries.")]
        content = USER_MD.read_text(encoding="utf-8", errors="replace")
        used = len(content)
        pct  = int(used / USER_MAX * 100)
        return [TextContent(type="text", text=f"[USER PROFILE — {used}/{USER_MAX} chars ({pct}%)]\n\n{content}")]

    if name == "memory":
        action  = arguments.get("action", "").strip()
        content = arguments.get("content", "").strip()
        new_c   = arguments.get("new_content", "").strip()
        cat_map = {"user": "PROFIL", "tech": "TECH", "comm": "KOMUNIKACJA", "income": "ZAROBEK"}
        cat_key = cat_map.get(arguments.get("category", "user"), "PROFIL")

        if not content:
            return [TextContent(type="text", text="error: content required")]

        current = USER_MD.read_text(encoding="utf-8", errors="replace") if USER_MD.exists() else ""

        if action == "add":
            # Find the right section or append to end
            section = f"§ {cat_key}"
            if section in current:
                # Insert at end of that section (before next § or end)
                idx = current.find(section)
                next_sec = current.find("\n§ ", idx + 1)
                insert_at = next_sec if next_sec != -1 else len(current)
                # Add to section: append to block
                block_end = current.rfind("\n", idx, insert_at)
                new_text = current[:block_end+1] + content + "\n" + current[block_end+1:]
            else:
                new_text = current.rstrip() + f"\n\n§ {cat_key}\n{content}\n"

        elif action == "replace":
            if content not in current:
                return [TextContent(type="text", text=f"Substring not found: '{content[:60]}...'")]
            new_text = current.replace(content, new_c, 1)

        elif action == "remove":
            if content not in current:
                return [TextContent(type="text", text=f"Substring not found: '{content[:60]}...'")]
            new_text = current.replace(content, "", 1)
            # Clean up double newlines
            import re as _re2
            new_text = _re2.sub(r'\n{3,}', '\n\n', new_text)
        else:
            return [TextContent(type="text", text=f"Unknown action: {action}")]

        if len(new_text) > USER_MAX:
            over = len(new_text) - USER_MAX
            return [TextContent(type="text",
                text=f"Profile full! {over} chars over limit ({USER_MAX}). "
                     f"Remove or consolidate existing entries first.\n\nCurrent:\n{current}")]

        tmp = USER_MD.with_suffix(".md.tmp")
        tmp.write_text(new_text, encoding="utf-8")
        tmp.replace(USER_MD)

        used = len(new_text)
        pct  = int(used / USER_MAX * 100)
        return [TextContent(type="text",
            text=f"✓ Profile updated ({action}) — {used}/{USER_MAX} chars ({pct}%)\n\n{new_text}")]

    if name == "list_cli_skills":
        import re as _re
        cli_dir = Path.home() / ".claude" / "skills"
        result = []
        if cli_dir.exists():
            for folder in sorted(cli_dir.iterdir()):
                if folder.is_dir():
                    sf = folder / "SKILL.md"
                    if sf.exists():
                        txt = sf.read_text(encoding="utf-8", errors="replace")
                        dm = _re.search(r'^description:\s*(.+)$', txt, _re.MULTILINE)
                        nm = _re.search(r'^name:\s*(.+)$', txt, _re.MULTILINE)
                        result.append({
                            "id":          folder.name,
                            "name":        nm.group(1).strip() if nm else folder.name,
                            "description": dm.group(1).strip() if dm else "",
                        })
        return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

    if name == "get_skill":
        import re as _re
        skill_name = arguments.get("name", "").strip()
        if not skill_name:
            return [TextContent(type="text", text="error: skill name required")]
        cli_dir = Path.home() / ".claude" / "skills"
        skill_file = cli_dir / skill_name / "SKILL.md"
        if not skill_file.exists():
            available = sorted(d.name for d in cli_dir.iterdir() if d.is_dir()) if cli_dir.exists() else []
            return [TextContent(type="text",
                    text=f"Skill '{skill_name}' not found.\nAvailable: {', '.join(available)}")]
        content = skill_file.read_text(encoding="utf-8", errors="replace")
        return [TextContent(type="text", text=content)]

    return [TextContent(type="text", text=f"unknown tool: {name}")]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
