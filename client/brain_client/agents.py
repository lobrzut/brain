from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

from .config import BACKUP_DIR

APPDATA = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
LOCAL = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
HOME = Path.home()

BRAIN_KEYS = {"brain-vault", "brain-library", "brain-rag"}

KNOWN_AGENTS: list[dict[str, Any]] = [
    {
        "id": "claude-desktop",
        "label": "Claude Desktop",
        "configs": [APPDATA / "Claude" / "claude_desktop_config.json"],
        "install_hints": [APPDATA / "Claude"],
        "restart_hint": "Zamknij Claude Desktop (tray → Quit) i otwórz ponownie.",
        "mcp_format": "mcp-remote",
    },
    {
        "id": "antigravity",
        "label": "Antigravity",
        "configs": [
            HOME / ".gemini" / "antigravity" / "mcp_config.json",
            HOME / ".gemini" / "config" / "mcp_config.json",
            HOME / ".gemini" / "antigravity-ide" / "mcp_config.json",
        ],
        "install_hints": [APPDATA / "Antigravity", APPDATA / "Antigravity IDE"],
        "restart_hint": "Zamknij Antigravity i otwórz ponownie.",
        "mcp_format": "antigravity",
    },
    {
        "id": "claude-code",
        "label": "Claude Code",
        "configs": [HOME / ".claude.json"],
        "install_hints": [HOME / ".claude"],
        "restart_hint": "Uruchom ponownie `claude` w terminalu.",
        "mcp_format": "claude-http",
    },
    {
        "id": "cursor",
        "label": "Cursor",
        "configs": [HOME / ".cursor" / "mcp.json"],
        "install_hints": [HOME / ".cursor", LOCAL / "Programs" / "cursor", LOCAL / "Programs" / "Cursor"],
        "restart_hint": "Cursor → Reload Window lub restart.",
        "mcp_format": "url",
    },
    {
        "id": "vscode",
        "label": "VS Code",
        "configs": [APPDATA / "Code" / "User" / "mcp.json"],
        "install_hints": [APPDATA / "Code", LOCAL / "Programs" / "Microsoft VS Code"],
        "mcp_key": "servers",
        "format": "vscode",
        "mcp_format": "vscode-http",
        "restart_hint": "VS Code → MCP: List Servers → Start, lub restart.",
    },
    {
        "id": "windsurf",
        "label": "Windsurf",
        "configs": [HOME / ".codeium" / "windsurf" / "mcp_config.json"],
        "install_hints": [HOME / ".codeium", LOCAL / "Programs" / "Windsurf"],
        "restart_hint": "Zrestartuj Windsurf.",
        "mcp_format": "url",
    },
    {
        "id": "zed",
        "label": "Zed",
        "configs": [HOME / ".config" / "zed" / "settings.json"],
        "install_hints": [HOME / ".config" / "zed"],
        "mcp_key": "context_servers",
        "restart_hint": "Zrestartuj Zed.",
    },
]


def _read_config(path: Path) -> dict | None:
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    return json.loads(raw)


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _backup_config(agent_id: str, path: Path) -> Path | None:
    if not path.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / f"{agent_id}_{ts}{path.suffix}"
    shutil.copy2(path, dest)
    return dest


def is_installed(spec: dict[str, Any]) -> bool:
    for hint in spec.get("install_hints", []):
        if hint.exists():
            return True
    for cfg in spec.get("configs", []):
        if cfg.exists():
            return True
    return False


def _entry_healthy(entry: Any) -> bool:
    """A config key can EXIST yet be silently broken. The classic case: an
    mcp-remote bridge pointing at a non-localhost http:// URL without
    --allow-http — mcp-remote refuses to connect, so the agent shows the
    server but never wires up. Treat such entries as not-wired so the tray
    stops lying '5/5 wired' over a dead config."""
    if not isinstance(entry, dict):
        return False
    args = entry.get("args")
    if not isinstance(args, list):
        return True  # native http/url transport (Cursor, Claude Code, VS Code)
    if "mcp-remote" not in args:
        return True
    url = next(
        (a for a in args if isinstance(a, str) and a.startswith(("http://", "https://"))),
        "",
    )
    if url.startswith("http://") and not any(h in url for h in ("localhost", "127.0.0.1")):
        return "--allow-http" in args
    return True


def brain_status(spec: dict[str, Any], template_keys: set[str]) -> str:
    if not is_installed(spec):
        return "not_installed"
    wired = 0
    for cfg in spec["configs"]:
        data = _read_config(cfg)
        if not data:
            continue
        key = spec.get("mcp_key", "mcpServers")
        servers = data.get(key) or {}
        if all(k in servers for k in template_keys) and all(
            _entry_healthy(servers[k]) for k in template_keys
        ):
            wired += 1
    if wired == 0:
        return "not_wired"
    if wired == len(spec["configs"]):
        return "wired"
    return "partial"


def _vscode_format(servers: dict[str, dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for name, cfg in servers.items():
        if "url" in cfg:
            out[name] = {"type": "http", "url": cfg["url"]}
        else:
            entry: dict[str, Any] = {"type": "stdio", "command": cfg["command"], "args": cfg.get("args", [])}
            if "env" in cfg:
                entry["env"] = cfg["env"]
            out[name] = entry
    return out


def deploy_agent(agent_id: str, template: dict[str, dict]) -> dict[str, Any]:
    spec = next((a for a in KNOWN_AGENTS if a["id"] == agent_id), None)
    if not spec:
        return {"ok": False, "error": "unknown agent"}

    servers = template
    if spec.get("format") == "vscode":
        servers = _vscode_format(template)

    mcp_key = spec.get("mcp_key", "mcpServers")
    results = []
    for cfg_path in spec["configs"]:
        try:
            backup = _backup_config(agent_id, cfg_path)
            existing = _read_config(cfg_path) or {}
            bucket = existing.get(mcp_key) or {}
            for k, v in servers.items():
                bucket[k] = v
            existing[mcp_key] = bucket
            _atomic_write_json(cfg_path, existing)
            results.append(
                {
                    "config": str(cfg_path),
                    "ok": True,
                    "backup": str(backup) if backup else None,
                    "wrote": sorted(bucket.keys()),
                }
            )
        except Exception as exc:
            results.append({"config": str(cfg_path), "ok": False, "error": str(exc)})

    return {
        "ok": all(r["ok"] for r in results),
        "agent": agent_id,
        "results": results,
        "restart_hint": spec.get("restart_hint", ""),
    }


def deploy_all_installed(template: dict[str, dict]) -> dict[str, Any]:
    out = []
    for spec in KNOWN_AGENTS:
        if is_installed(spec):
            out.append(deploy_agent(spec["id"], template))
    return {
        "deployed": len(out),
        "agents": [r["agent"] for r in out if r.get("ok")],
        "results": out,
    }


def list_agents(template_keys: set[str]) -> list[dict[str, Any]]:
    rows = []
    for spec in KNOWN_AGENTS:
        rows.append(
            {
                "id": spec["id"],
                "label": spec["label"],
                "installed": is_installed(spec),
                "brain_status": brain_status(spec, template_keys),
                "config_paths": [str(p) for p in spec["configs"]],
            }
        )
    return rows
