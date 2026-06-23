from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path
from typing import Any

from .agents import BRAIN_KEYS, deploy_agent, is_installed, list_agents
from .config import CONFIG_DIR, load_config, platform_name


def _npx_command() -> tuple[str, list[str]]:
    found = shutil.which("npx")
    if found:
        return found, []

    if platform.system() == "Windows":
        for candidate in (
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs" / "npx.cmd",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "nodejs" / "npx.cmd",
            Path(os.environ.get("APPDATA", "")) / "npm" / "npx.cmd",
        ):
            if candidate.exists():
                return str(candidate), []
        return "cmd", ["/c", "npx"]

    return "npx", []


def _endpoints(mcp_url: str, transport: str = "sse") -> dict[str, str]:
    base = mcp_url.rstrip("/")
    path = "mcp" if transport == "streamable-http" else "sse"
    return {
        "brain-rag": f"{base}/{path}",
        "brain-vault": f"{base}/servers/brain-vault/{path}",
        "brain-library": f"{base}/servers/brain-library/{path}",
    }


def http_template(mcp_url: str, mcp_format: str = "mcp-remote") -> dict[str, dict]:
    if mcp_format in {"antigravity", "claude-http", "mcp-remote"}:
        transport = "streamable-http"
    else:
        transport = "sse"
    endpoints = _endpoints(mcp_url, transport=transport)
    out: dict[str, dict] = {}

    if mcp_format == "url":
        return {name: {"url": url} for name, url in endpoints.items()}

    if mcp_format == "antigravity":
        return {
            name: {"type": "streamable-http", "serverUrl": url}
            for name, url in endpoints.items()
        }

    if mcp_format == "serverUrl":
        return {name: {"serverUrl": url} for name, url in endpoints.items()}

    if mcp_format == "claude-http":
        return {
            name: {"type": "http", "url": url}
            for name, url in endpoints.items()
        }

    if mcp_format == "vscode-http":
        return {
            name: {"type": "http", "url": url}
            for name, url in endpoints.items()
        }

    cmd, prefix = _npx_command()
    need_allow_http = mcp_url.lower().startswith("http://") and not any(
        h in mcp_url for h in ("localhost", "127.0.0.1")
    )
    for name, url in endpoints.items():
        args = [*prefix, "-y", "mcp-remote", url]
        if need_allow_http:
            args.append("--allow-http")
        out[name] = {"command": cmd, "args": args}
    return out


def ssh_template(cfg: dict[str, Any]) -> dict[str, dict]:
    host = cfg.get("ssh_host", "user@brain-host")
    key = cfg.get("ssh_key", "")
    ssh = shutil.which("ssh") or "ssh"
    base_args: list[str] = ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
    if key:
        base_args.extend(["-i", key, "-o", "IdentitiesOnly=yes"])

    def remote_cmd(*parts: str) -> list[str]:
        return [ssh, *base_args, host, " ".join(parts)]

    return {
        "brain-vault": {
            "command": ssh,
            "args": [*base_args, host, "npx", "-y", "@modelcontextprotocol/server-filesystem", "/opt/BRAIN/data/vault"],
        },
        "brain-library": {
            "command": ssh,
            "args": [*base_args, host, "npx", "-y", "@modelcontextprotocol/server-filesystem", "/opt/BRAIN/data/library"],
        },
        "brain-rag": {
            "command": ssh,
            "args": [
                *base_args,
                host,
                "OLLAMA_HOST=127.0.0.1:11434",
                "/opt/BRAIN/venv/bin/python",
                "/opt/BRAIN/dashboard/mcp_rag.py",
            ],
        },
    }


def plink_template(cfg: dict[str, Any]) -> dict[str, dict]:
    wrapper = CONFIG_DIR / "brain-ssh.cmd"
    if not wrapper.exists():
        password = cfg.get("ssh_password", "")
        hostkey = cfg.get("ssh_hostkey", "")
        plink = r"C:\Program Files\PuTTY\plink.exe"
        if not Path(plink).exists():
            plink = "plink"
        hostkey_arg = f"-hostkey {hostkey} " if hostkey else ""
        lines = [
            "@echo off",
            f'"{plink}" -batch -ssh {cfg.get("ssh_host", "user@brain-host")} -pw {password} {hostkey_arg}%*',
            "",
        ]
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        wrapper.write_text("\n".join(lines), encoding="utf-8")

    cmd = str(wrapper)
    return {
        "brain-vault": {
            "command": cmd,
            "args": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/opt/BRAIN/data/vault"],
        },
        "brain-library": {
            "command": cmd,
            "args": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/opt/BRAIN/data/library"],
        },
        "brain-rag": {
            "command": cmd,
            "args": [
                "env",
                "OLLAMA_HOST=127.0.0.1:11434",
                "PYTHONIOENCODING=utf-8",
                "/opt/BRAIN/venv/bin/python",
                "/opt/BRAIN/dashboard/mcp_rag.py",
            ],
        },
    }


def build_template(cfg: dict[str, Any], mcp_format: str = "mcp-remote") -> dict[str, dict]:
    transport = cfg.get("transport", "http")
    mcp_url = cfg.get("mcp_url", "http://127.0.0.1:7862")

    if transport == "http":
        return http_template(mcp_url, mcp_format=mcp_format)
    if transport == "ssh":
        if platform_name() == "windows" and cfg.get("ssh_password"):
            return plink_template(cfg)
        return ssh_template(cfg)
    raise ValueError(f"Unknown transport: {transport}")


def deploy(cfg: dict[str, Any] | None = None, agent_id: str | None = None) -> dict[str, Any]:
    cfg = cfg or load_config()
    if agent_id:
        from .agents import KNOWN_AGENTS

        spec = next((a for a in KNOWN_AGENTS if a["id"] == agent_id), None)
        fmt = (spec or {}).get("mcp_format", "mcp-remote")
        template = build_template(cfg, mcp_format=fmt)
        return deploy_agent(agent_id, template)

    results = []
    from .agents import KNOWN_AGENTS

    for spec in KNOWN_AGENTS:
        if not is_installed(spec):
            continue
        fmt = spec.get("mcp_format", "mcp-remote")
        template = build_template(cfg, mcp_format=fmt)
        results.append(deploy_agent(spec["id"], template))

    return {
        "deployed": len(results),
        "agents": [r["agent"] for r in results if r.get("ok")],
        "results": results,
    }
