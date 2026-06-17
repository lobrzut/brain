"""MCP server runner — manages subprocess lifecycle for configured MCP servers.

Config file: brain/pipeline/mcp-servers.json (list of server descriptors).
Logs: brain/logs/mcp-{id}.log
"""
from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path


class MCPManager:
    def __init__(self, config_path: Path, logs_dir: Path):
        self.config_path = Path(config_path)
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.procs: dict[str, subprocess.Popen] = {}

    # --- config persistence ---
    def list_config(self) -> list[dict]:
        if not self.config_path.exists():
            return []
        try:
            return json.loads(self.config_path.read_text(encoding="utf-8-sig"))
        except Exception:
            return []

    def save_config(self, servers: list[dict]) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(servers, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def upsert(self, server: dict) -> None:
        servers = self.list_config()
        sid = server["id"]
        existing = next((s for s in servers if s["id"] == sid), None)
        if existing:
            existing.update(server)
        else:
            servers.append(server)
        self.save_config(servers)

    def delete(self, sid: str) -> None:
        self.stop(sid)
        servers = [s for s in self.list_config() if s["id"] != sid]
        self.save_config(servers)

    # --- runtime ---
    def list(self) -> list[dict]:
        config = self.list_config()
        out = []
        for s in config:
            sid = s["id"]
            running = False
            pid = None
            if sid in self.procs:
                p = self.procs[sid]
                if p.poll() is None:
                    running = True; pid = p.pid
                else:
                    del self.procs[sid]
            out.append({
                **s,
                "running": running,
                "pid": pid,
                "log_path": str(self.logs_dir / f"mcp-{sid}.log"),
            })
        return out

    def start(self, sid: str) -> dict:
        cfg = {s["id"]: s for s in self.list_config()}
        if sid not in cfg:
            raise ValueError(f"unknown server: {sid}")
        if sid in self.procs and self.procs[sid].poll() is None:
            return {"already_running": True, "pid": self.procs[sid].pid}
        s = cfg[sid]
        log_path = self.logs_dir / f"mcp-{sid}.log"
        log_file = open(log_path, "ab")
        env = os.environ.copy()
        env.update(s.get("env", {}))
        cmd = [s["command"]] + s.get("args", [])
        try:
            kwargs = {"stdout": log_file, "stderr": log_file, "env": env, "cwd": s.get("cwd")}
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            proc = subprocess.Popen(cmd, **kwargs)
            self.procs[sid] = proc
            return {"started": True, "pid": proc.pid}
        except FileNotFoundError as e:
            return {"started": False, "error": f"command not found: {s['command']}"}
        except Exception as e:
            return {"started": False, "error": str(e)}

    def stop(self, sid: str) -> dict:
        if sid not in self.procs:
            return {"stopped": False, "reason": "not tracked"}
        p = self.procs[sid]
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
        del self.procs[sid]
        return {"stopped": True}

    def stop_all(self) -> None:
        for sid in list(self.procs.keys()):
            self.stop(sid)

    def tail_log(self, sid: str, lines: int = 200) -> str:
        log_path = self.logs_dir / f"mcp-{sid}.log"
        if not log_path.exists():
            return ""
        try:
            with open(log_path, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                read = min(size, max(8192, lines * 200))
                f.seek(size - read)
                content = f.read().decode("utf-8", errors="replace")
            return "\n".join(content.splitlines()[-lines:])
        except Exception as e:
            return f"[log read error: {e}]"
