"""Agent detection + brain MCP deployment.

Each known agent has:
  - id, label, icon
  - config_paths (list, primary first)
  - mcp_key — JSON path where MCP servers live (usually 'mcpServers' top-level)
  - install_hints — extra paths/dirs that signal "installed" even without config

Public API:
  detect(agent_id)        → dict for one agent
  detect_all()            → list of dicts (cached 60s)
  deploy(agent_id)        → wire brain MCP, atomic + backup
  undeploy(agent_id)      → remove brain-* entries
  deploy_all_installed()  → bulk

Cache: detect_all() is hit by /api/agents on every dashboard refresh.
"""
from __future__ import annotations
import json, os, shutil, sys, time
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT     = Path(__file__).resolve().parent.parent
from paths import data_root, python_executable  # noqa: E402
BACKUPS  = data_root() / "agent-configs-backup"
APPDATA  = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
LOCAL    = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
HOME     = Path.home()


# ---------------------------------------------------------------------------
# Brain MCP template — what we deploy to each agent
# ---------------------------------------------------------------------------
def brain_mcp_template() -> dict:
    """Returns the 3 brain MCP server entries with current paths."""
    py     = python_executable()
    rag_py = ROOT / "dashboard" / "mcp_rag.py"
    vault  = data_root() / "vault"
    library = data_root() / "library"
    return {
        "brain-vault": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", str(vault)],
        },
        "brain-library": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", str(library)],
        },
        "brain-rag": {
            "command": str(py),
            "args":    [str(rag_py)],
            "env": {
                "OLLAMA_HOST":      "127.0.0.1:11434",
                "PYTHONIOENCODING": "utf-8",
            },
        },
    }


BRAIN_KEYS = {"brain-vault", "brain-library", "brain-rag"}


# ---------------------------------------------------------------------------
# Per-agent format transformations
# ---------------------------------------------------------------------------
# VS Code uses `servers` (not `mcpServers`) with `type: "stdio"` field.
# Cursor uses `mcpServers` like Claude Desktop.
# Windsurf uses `mcpServers` (same as Claude Desktop).
def _vscode_format(brain_servers: dict) -> dict:
    """VS Code MCP format: {servers: {<name>: {type: 'stdio', command, args, env}}}"""
    out = {}
    for name, cfg in brain_servers.items():
        entry = {"type": "stdio", "command": cfg["command"], "args": cfg["args"]}
        if "env" in cfg:
            entry["env"] = cfg["env"]
        out[name] = entry
    return out


# ---------------------------------------------------------------------------
# Known agents
# ---------------------------------------------------------------------------
KNOWN_AGENTS: list[dict] = [
    {
        "id":      "claude-desktop",
        "label":   "Claude Desktop",
        "icon":    "🤖",
        "configs": [APPDATA / "Claude" / "claude_desktop_config.json"],
        "install_hints": [APPDATA / "Claude"],
        "restart_hint":  "Zamknij Claude Desktop (system tray → Quit) i otwórz ponownie.",
    },
    {
        "id":      "antigravity",
        "label":   "Antigravity (Google IDE)",
        "icon":    "🚀",
        # antigravity-ide is the live one + .gemini/config is shared
        "configs": [HOME / ".gemini" / "config" / "mcp_config.json",
                    HOME / ".gemini" / "antigravity-ide" / "mcp_config.json"],
        "install_hints": [APPDATA / "Antigravity"],
        "restart_hint":  "Zamknij Antigravity (File → Exit) i otwórz ponownie. MCP serwery przeładują się.",
    },
    {
        "id":      "claude-code",
        "label":   "Claude Code (CLI)",
        "icon":    "💻",
        # Claude Code uses ~/.claude.json (root mcpServers key) for global MCP
        "configs": [HOME / ".claude.json"],
        "install_hints": [HOME / ".claude"],
        "restart_hint":  "Następne uruchomienie `claude` w terminalu załaduje nowe MCP. Aktywne sesje muszą się restartować.",
    },
    {
        "id":      "cursor",
        "label":   "Cursor",
        "icon":    "✦",
        # Cursor MCP — global config
        "configs": [HOME / ".cursor" / "mcp.json"],
        "install_hints": [HOME / ".cursor",
                          LOCAL / "Programs" / "cursor",
                          LOCAL / "Programs" / "Cursor"],
        "restart_hint":  "Cursor → Ctrl+Shift+P → 'Developer: Reload Window', albo restart Cursor.",
    },
    {
        "id":      "vscode",
        "label":   "VS Code",
        "icon":    "📝",
        # VS Code 1.103+ supports MCP natively. User-level config:
        "configs": [APPDATA / "Code" / "User" / "mcp.json"],
        "install_hints": [APPDATA / "Code", LOCAL / "Programs" / "Microsoft VS Code"],
        # Custom format — uses `servers` key with type: stdio
        "mcp_key": "servers",
        "format":  "vscode",
        "restart_hint":  "VS Code → Ctrl+Shift+P → 'MCP: List Servers' → uruchom każdy 'Start Server', albo restart VS Code.",
    },

    {
        "id":      "claude-free",
        "label":   "Free Claude Code (proxy)",
        "icon":    "🦝",
        # free-claude-code (github.com/Alishahryar1/free-claude-code) is a local
        # FastAPI proxy that intercepts Claude Code CLI → routes to free providers
        # (OpenRouter, Gemini, NVIDIA NIM, DeepSeek, Mistral …).
        #
        # How it works:
        #   fcc-server   — proxy on http://127.0.0.1:8082  (Admin UI: /admin)
        #   fcc-claude   — wrapper: sets ANTHROPIC_BASE_URL + runs real `claude`
        #
        # MCP config: identical to claude-code (~/.claude.json) because fcc-claude
        # just calls the real `claude` binary with env vars set. No separate MCP file.
        "configs": [HOME / ".claude.json"],
        "install_hints": [
            # uv tool install free-claude-code  (most common)
            APPDATA / "uv" / "tools" / "free-claude-code",
            LOCAL   / "uv" / "tools" / "free-claude-code",
            HOME    / ".local" / "share" / "uv" / "tools" / "free-claude-code",
            # pip install → Scripts\fcc-server.exe
            LOCAL   / "Programs" / "Python" / "Scripts" / "fcc-server.exe",
            APPDATA / "Python" / "Scripts" / "fcc-server.exe",
            # pipx install
            HOME    / ".local" / "bin" / "fcc-server",
            LOCAL   / "pipx" / "venvs" / "free-claude-code",
        ],
        "restart_hint": (
            "Zatrzymaj fcc-server (Ctrl+C w terminalu gdzie działa) i uruchom ponownie: fcc-server\n"
            "Admin UI: http://127.0.0.1:8082/admin\n"
            "Uruchamianie Claude przez proxy: fcc-claude (zamiast claude)"
        ),
        # Extra metadata used by dashboard to show proxy status + link
        "proxy_url":  "http://127.0.0.1:8082",
        "admin_url":  "http://127.0.0.1:8082/admin",
        "install_cmd": "irm \"https://github.com/Alishahryar1/free-claude-code/blob/main/scripts/install.ps1?raw=1\" | iex",
    },
]


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------
def _is_installed(spec: dict) -> bool:
    if any(p.exists() for p in spec.get("configs", [])):
        return True
    return any(p.exists() for p in spec.get("install_hints", []))


def _read_config(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _brain_status(mcp_servers: dict, fmt: str = "default") -> tuple[str, list[str]]:
    """Returns (status_label, list_of_missing_brain_keys)."""
    if not mcp_servers:
        return ("not_wired", list(BRAIN_KEYS))
    template = brain_mcp_template()
    if fmt == "vscode":
        template = _vscode_format(template)
    missing, mismatched = [], []
    for key, expected in template.items():
        actual = mcp_servers.get(key)
        if not actual:
            missing.append(key); continue
        if actual.get("command") != expected["command"]:
            mismatched.append(key); continue
        if actual.get("args") != expected["args"]:
            mismatched.append(key); continue
    bad = missing + mismatched
    if not bad:
        return ("wired", [])
    if len(bad) < len(BRAIN_KEYS):
        return ("partial", bad)
    return ("not_wired", bad)


def detect(agent_id: str) -> dict:
    spec = next((a for a in KNOWN_AGENTS if a["id"] == agent_id), None)
    if not spec:
        return {"id": agent_id, "error": "unknown agent"}
    installed = _is_installed(spec)
    primary_config = spec["configs"][0]
    config_exists = primary_config.exists()
    data = _read_config(primary_config) or {}
    mcp_key = spec.get("mcp_key", "mcpServers")
    mcp = data.get(mcp_key) or {}
    fmt = spec.get("format", "default")
    status, issues = _brain_status(mcp, fmt)
    result: dict = {
        "id":           spec["id"],
        "label":        spec["label"],
        "icon":         spec["icon"],
        "installed":    installed,
        "config_path":  str(primary_config),
        "config_exists": config_exists,
        "all_servers":  list(mcp.keys()),
        "brain_status": status,
        "brain_issues": issues,
        "restart_hint": spec.get("restart_hint", ""),
        "format":       fmt,
    }
    # Special: for free-claude-code, 'installed' should reflect whether fcc-server
    # binary is present — not whether the config file exists (config is shared with
    # claude-code so it always exists). This lets the dashboard show an INSTALL button.
    if spec["id"] == "claude-free":
        import shutil
        fcc_found = bool(shutil.which("fcc-server")) or any(
            p.exists() for p in spec.get("install_hints", [])
        )
        result["fcc_binary_found"] = fcc_found
        result["installed"]  = fcc_found   # card uses this to toggle INSTALL vs CONFIGURE
        result["mcp_wired"]  = (status == "wired")  # keep real MCP status accessible
    return result


# Cache: 60s
_cache: dict = {"ts": 0.0, "data": None}


def detect_all(force_refresh: bool = False) -> list[dict]:
    now = time.time()
    if not force_refresh and _cache["data"] and (now - _cache["ts"]) < 60:
        return _cache["data"]
    out = [detect(spec["id"]) for spec in KNOWN_AGENTS]
    _cache["data"] = out
    _cache["ts"]   = now
    return out


# ---------------------------------------------------------------------------
# Deploy / undeploy
# ---------------------------------------------------------------------------
def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(path)


def _backup_config(agent_id: str, path: Path) -> Path | None:
    if not path.exists():
        return None
    BACKUPS.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    dest = BACKUPS / f"{agent_id}_{ts}{path.suffix}"
    shutil.copy2(path, dest)
    return dest


def deploy(agent_id: str) -> dict:
    """Wire brain MCP to all configs of this agent. Preserves user's other
    MCP servers. Atomic write + backup original."""
    spec = next((a for a in KNOWN_AGENTS if a["id"] == agent_id), None)
    if not spec:
        return {"ok": False, "error": "unknown agent"}
    template = brain_mcp_template()
    if spec.get("format") == "vscode":
        template = _vscode_format(template)
    mcp_key = spec.get("mcp_key", "mcpServers")

    results = []
    for cfg_path in spec["configs"]:
        try:
            backup = _backup_config(agent_id, cfg_path)
            existing = _read_config(cfg_path) or {}
            servers = existing.get(mcp_key) or {}
            # Merge: brain entries override, user's other entries preserved
            for k, v in template.items():
                servers[k] = v
            existing[mcp_key] = servers
            _atomic_write_json(cfg_path, existing)
            results.append({
                "config":  str(cfg_path),
                "ok":      True,
                "backup":  str(backup) if backup else None,
                "wrote":   sorted(servers.keys()),
            })
        except Exception as e:
            results.append({"config": str(cfg_path), "ok": False, "error": str(e)})

    # Invalidate cache so next status call sees fresh state
    _cache["ts"] = 0
    return {"ok": all(r["ok"] for r in results),
            "agent": agent_id, "results": results,
            "restart_hint": spec.get("restart_hint", "")}


def undeploy(agent_id: str) -> dict:
    """Remove brain-* entries from all configs of this agent."""
    spec = next((a for a in KNOWN_AGENTS if a["id"] == agent_id), None)
    if not spec:
        return {"ok": False, "error": "unknown agent"}
    mcp_key = spec.get("mcp_key", "mcpServers")

    results = []
    for cfg_path in spec["configs"]:
        if not cfg_path.exists():
            continue
        try:
            backup = _backup_config(agent_id, cfg_path)
            existing = _read_config(cfg_path) or {}
            servers = existing.get(mcp_key) or {}
            removed = []
            for k in list(servers.keys()):
                if k in BRAIN_KEYS:
                    servers.pop(k)
                    removed.append(k)
            existing[mcp_key] = servers
            _atomic_write_json(cfg_path, existing)
            results.append({"config": str(cfg_path), "ok": True,
                            "removed": removed,
                            "backup":  str(backup) if backup else None})
        except Exception as e:
            results.append({"config": str(cfg_path), "ok": False, "error": str(e)})

    _cache["ts"] = 0
    return {"ok": all(r["ok"] for r in results),
            "agent": agent_id, "results": results}


def deploy_all_installed() -> dict:
    """Bulk deploy to every installed agent. Skips not-installed."""
    out = []
    for spec in KNOWN_AGENTS:
        if _is_installed(spec):
            out.append(deploy(spec["id"]))
    _cache["ts"] = 0
    return {"deployed": len(out),
            "agents":   [r["agent"] for r in out],
            "results":  out}


# ---------------------------------------------------------------------------
# System-prompt deployment — agent-specific persistent instructions
# ---------------------------------------------------------------------------
# Maps agent id → list of (target_path, description). If a target file exists
# we backup it; if not we create. Convention markers (#### BRAIN MCP / ####
# /BRAIN MCP) let us update without nuking user's other prompt content.
SYSTEM_PROMPT_TARGETS: dict[str, list[Path]] = {
    "claude-code":     [HOME / ".claude" / "CLAUDE.md"],
    "cursor":          [],  # Handled dynamically in deploy_system_prompt
    "antigravity-cli": [HOME / ".antigravity-cli" / "AGENTS.md"],
    "claude-free":     [HOME / ".claude-free" / "INSTRUCTIONS.md",
                        HOME / ".claude-memory" / "INSTRUCTIONS.md"],
    # Note: VS Code / Antigravity (IDE) / Windsurf don't have a standard global system-prompt file.
    # For those, user pastes the brain workflow ribbon prompts manually OR uses workspace files.
}

BRAIN_MARK_START = "<!-- BRAIN-MCP-INSTRUCTIONS START — managed by brain/pipeline/agents.py -->"
BRAIN_MARK_END   = "<!-- BRAIN-MCP-INSTRUCTIONS END -->"


def _agent_prompt_body() -> str:
    src = ROOT / "data" / "agent-system-prompt.md"
    if src.exists():
        return src.read_text(encoding="utf-8")
    return ("# Brain MCP\nUse brain-rag.search_library before tasks, "
            "brain-rag.save_conversation at end.")


def _get_workspace_targets(app_name: str, file_name: str) -> list[Path]:
    import urllib.parse
    targets = []
    ws_dir = APPDATA / app_name / "User" / "workspaceStorage"
    if ws_dir.exists():
        for d in ws_dir.iterdir():
            wp = d / "workspace.json"
            if wp.exists():
                try:
                    data = json.loads(wp.read_text(encoding="utf-8"))
                    if "folder" in data:
                        folder_uri = data["folder"]
                        if folder_uri.startswith("file:///"):
                            path_str = urllib.parse.unquote(folder_uri[8:])
                            if path_str.startswith("/") and len(path_str) > 2 and path_str[2] == ":":
                                path_str = path_str[1:]
                            p = Path(path_str)
                            if p.exists() and p.is_dir():
                                targets.append(p / file_name)
                except Exception:
                    pass
    return targets


def _get_cursor_targets() -> list[Path]:
    import urllib.parse
    targets = [HOME / ".cursorrules"]
    ws_dir = APPDATA / "Cursor" / "User" / "workspaceStorage"
    if ws_dir.exists():
        for d in ws_dir.iterdir():
            wp = d / "workspace.json"
            if wp.exists():
                try:
                    data = json.loads(wp.read_text(encoding="utf-8"))
                    if "folder" in data:
                        folder_uri = data["folder"]
                        if folder_uri.startswith("file:///"):
                            path_str = urllib.parse.unquote(folder_uri[8:])
                            if path_str.startswith("/") and len(path_str) > 2 and path_str[2] == ":":
                                path_str = path_str[1:]
                            p = Path(path_str)
                            if p.exists() and p.is_dir():
                                targets.append(p / ".cursor" / "rules" / "brain-mcp.mdc")
                except Exception:
                    pass
    return targets


def _get_vscode_targets() -> list[Path]:
    return _get_workspace_targets("Code", ".clinerules")


def _get_antigravity_targets() -> list[Path]:
    return _get_workspace_targets("Antigravity", ".clinerules")


def _get_windsurf_targets() -> list[Path]:
    return _get_workspace_targets("Windsurf", ".windsurfrules")


def deploy_system_prompt(agent_id: str) -> dict:
    """Inject brain MCP instructions into agent's system-prompt file
       (Claude Code's CLAUDE.md, Cursor's .cursorrules, etc).
       Uses BRAIN-MCP-INSTRUCTIONS markers — replaces only that block,
       preserving user's other content."""
    if agent_id == "cursor":
        targets = _get_cursor_targets()
    elif agent_id == "vscode":
        targets = _get_vscode_targets()
    elif agent_id == "antigravity":
        targets = _get_antigravity_targets()
    elif agent_id == "windsurf":
        targets = _get_windsurf_targets()
    else:
        targets = SYSTEM_PROMPT_TARGETS.get(agent_id, [])
    if not targets:
        return {"ok": False, "agent": agent_id,
                "error": "no system-prompt target for this agent"}

    block = (f"{BRAIN_MARK_START}\n"
             f"<!-- This block is auto-managed. Edit data/agent-system-prompt.md\n"
             f"     in brain folder, then re-deploy from TOOLS → AGENTS. -->\n\n"
             f"{_agent_prompt_body()}\n\n"
             f"{BRAIN_MARK_END}\n")

    results = []
    for path in targets:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
            if BRAIN_MARK_START in existing:
                # Replace existing managed block
                import re
                pattern = re.compile(
                    re.escape(BRAIN_MARK_START) + r".*?" + re.escape(BRAIN_MARK_END),
                    re.DOTALL,
                )
                new_content = pattern.sub(block.rstrip(), existing)
            else:
                # Append to end
                sep = "\n\n" if existing and not existing.endswith("\n\n") else ""
                new_content = existing + sep + block

            # Atomic write
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(new_content, encoding="utf-8")
            tmp.replace(path)
            results.append({"path": str(path), "ok": True,
                            "size_after": path.stat().st_size})
        except Exception as e:
            results.append({"path": str(path), "ok": False, "error": str(e)})
    return {"ok": all(r["ok"] for r in results),
            "agent": agent_id, "results": results}


def undeploy_system_prompt(agent_id: str) -> dict:
    """Remove brain MCP block from agent's system-prompt file. Keeps user's
       other content."""
    if agent_id == "cursor":
        targets = _get_cursor_targets()
    elif agent_id == "vscode":
        targets = _get_vscode_targets()
    elif agent_id == "antigravity":
        targets = _get_antigravity_targets()
    elif agent_id == "windsurf":
        targets = _get_windsurf_targets()
    else:
        targets = SYSTEM_PROMPT_TARGETS.get(agent_id, [])
    if not targets:
        return {"ok": False, "error": "no target for this agent"}
    results = []
    for path in targets:
        if not path.exists():
            results.append({"path": str(path), "ok": True, "skipped": True})
            continue
        try:
            import re
            existing = path.read_text(encoding="utf-8")
            pattern = re.compile(
                re.escape(BRAIN_MARK_START) + r".*?" + re.escape(BRAIN_MARK_END) + r"\n?",
                re.DOTALL,
            )
            cleaned = pattern.sub("", existing).rstrip() + "\n"
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(cleaned, encoding="utf-8")
            tmp.replace(path)
            results.append({"path": str(path), "ok": True})
        except Exception as e:
            results.append({"path": str(path), "ok": False, "error": str(e)})
    return {"ok": all(r["ok"] for r in results),
            "agent": agent_id, "results": results}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        for a in detect_all(force_refresh=True):
            inst = "✓" if a["installed"] else " "
            print(f"  [{inst}] {a['icon']} {a['label']:<26} {a['brain_status']:<10}  {a['config_path']}")
            if a["brain_issues"]:
                print(f"          issues: {', '.join(a['brain_issues'])}")
    elif cmd == "deploy" and len(sys.argv) > 2:
        print(json.dumps(deploy(sys.argv[2]), indent=2, ensure_ascii=False))
    elif cmd == "deploy-all":
        print(json.dumps(deploy_all_installed(), indent=2, ensure_ascii=False))
    elif cmd == "undeploy" and len(sys.argv) > 2:
        print(json.dumps(undeploy(sys.argv[2]), indent=2, ensure_ascii=False))
    else:
        print("usage: agents.py status | deploy <id> | undeploy <id> | deploy-all")
        sys.exit(2)
