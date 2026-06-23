from __future__ import annotations

import json
import os
import platform
from pathlib import Path
from typing import Any

DEFAULT_BRAIN_URL = os.environ.get("BRAIN_URL", "http://127.0.0.1:7860")
DEFAULT_MCP_URL = os.environ.get("BRAIN_MCP_URL", "http://127.0.0.1:7862")

CONFIG_DIR = Path.home() / ".brain"
CONFIG_PATH = CONFIG_DIR / "client.json"
BACKUP_DIR = CONFIG_DIR / "agent-configs-backup"


def default_config() -> dict[str, Any]:
    return {
        "brain_url": DEFAULT_BRAIN_URL,
        "mcp_url": DEFAULT_MCP_URL,
        "transport": "http",  # http | ssh
        "ssh_host": "user@brain-host",
        "ssh_key": "",
        "ssh_password": "",
        "ssh_hostkey": "",
        "auto_deploy_on_start": True,
        "poll_interval_sec": 30,
        "open_browser_on_start": False,
        "autostart_enabled": True,
        "desktop_shortcut_on_install": True,
    }


def load_config() -> dict[str, Any]:
    cfg = default_config()
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update(data)
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def platform_name() -> str:
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    if system == "darwin":
        return "mac"
    return "linux"
