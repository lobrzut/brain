from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .agents import BRAIN_KEYS, list_agents
from .config import load_config


def fetch_json(url: str, timeout: float = 5.0) -> dict[str, Any] | None:
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def check_mcp_reachable(mcp_url: str, timeout: float = 2.0) -> bool:
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(mcp_url)
    host = parsed.hostname
    port = parsed.port or 7862
    if not host:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def snapshot(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or load_config()
    brain_url = cfg.get("brain_url", "http://127.0.0.1:7860").rstrip("/")
    mcp_url = cfg.get("mcp_url", "http://127.0.0.1:7862")

    status = fetch_json(f"{brain_url}/api/status")
    agents = list_agents(BRAIN_KEYS)
    installed = [a for a in agents if a["installed"]]
    wired = [a for a in installed if a["brain_status"] == "wired"]

    return {
        "online": status is not None,
        "mcp_online": check_mcp_reachable(mcp_url),
        "brain_url": brain_url,
        "mcp_url": mcp_url,
        "model": (status or {}).get("config", {}).get("model"),
        "uptime_sec": (status or {}).get("system", {}).get("uptime_sec"),
        "agents_installed": len(installed),
        "agents_wired": len(wired),
        "agents": agents,
    }


def tooltip_text(snap: dict[str, Any]) -> str:
    if not snap["online"]:
        return "BRAIN Client — serwer offline"
    model = snap.get("model") or "?"
    wired = snap.get("agents_wired", 0)
    installed = snap.get("agents_installed", 0)
    mcp = "MCP OK" if snap.get("mcp_online") else "MCP brak"
    return f"BRAIN · {model} · {wired}/{installed} agentów · {mcp}"
