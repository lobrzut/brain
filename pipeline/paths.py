"""Shared path resolution — Windows portable + Linux server data dir."""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent


def repo_root() -> Path:
    return _REPO


def load_config() -> dict:
    cfg_path = _REPO / "config.json"
    if not cfg_path.exists():
        return {}
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def data_root() -> Path:
    env = os.environ.get("BRAIN_DATA_DIR")
    if env:
        return Path(env)
    cfg = load_config()
    if cfg.get("data_dir"):
        return Path(cfg["data_dir"])
    return _REPO / "data"


def logs_dir() -> Path:
    env = os.environ.get("BRAIN_LOGS_DIR")
    if env:
        return Path(env)
    cfg = load_config()
    if cfg.get("edition") == "linux":
        return data_root() / "logs"
    return _REPO / "logs"


def python_executable() -> Path:
    if sys.platform == "win32":
        embedded = _REPO / "bin" / "python" / "python.exe"
        if embedded.exists():
            return embedded
    return Path(sys.executable)
