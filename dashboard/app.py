"""Brain Dashboard backend - FastAPI."""
from __future__ import annotations
import atexit, json, os, re, shutil, signal, subprocess, sys, threading, time, zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
import psutil, requests, httpx
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from mcp_runner import MCPManager

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
from paths import data_root, logs_dir, load_config  # noqa: E402

CONFIG = load_config()
DATA_ROOT = data_root()
STATIC = Path(__file__).resolve().parent / "static"
KEYS_FILE = DATA_ROOT / "api-keys.json"
LIBRARY_DIR = DATA_ROOT / "library"
VAULT_DIR = DATA_ROOT / "vault"
DISTILL_STATUS = DATA_ROOT / "distill-status.json"
DISTILL_SCRIPT = ROOT / "pipeline" / "distill.py"
MCP_CONFIG = ROOT / "pipeline" / "mcp-servers.json"
LOGS_DIR = logs_dir()
BACKUPS_DIR = DATA_ROOT / "backups"
USAGE_FILE = DATA_ROOT / "api-usage.json"
THRESHOLDS_FILE = DATA_ROOT / "api-thresholds.json"

PROVIDER_BASE = {
    "anthropic":  "https://api.anthropic.com",
    "openai":     "https://api.openai.com",
    "google":     "https://generativelanguage.googleapis.com",
    "xai":        "https://api.x.ai",
    "openrouter": "https://openrouter.ai",
}

# Ensure dirs
LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
VAULT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Brain", docs_url=None, redoc_url=None)

@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

_start_time = time.time()
_mcp = MCPManager(MCP_CONFIG, LOGS_DIR)
atexit.register(_mcp.stop_all)

# Transcript distillation subprocess handle
_distill_proc: subprocess.Popen | None = None
_redistill_proc: subprocess.Popen | None = None


# ---------------------------------------------------------------------------
# API providers
# ---------------------------------------------------------------------------
# Only Claude — brain uses it (Haiku) as an optional paid alternative to local
# Ollama for distillation. No multi-provider key vault: brain never called the
# others; agents keep their own keys in their own configs.
PROVIDERS: dict[str, dict[str, Any]] = {
    "anthropic":  {"title": "Claude", "url": "https://console.anthropic.com",
                   "envs": ["ANTHROPIC_API_KEY"], "icon": "claude", "hint": "sk-ant-..."},
}


def _load_keys() -> dict:
    if KEYS_FILE.exists():
        try: return json.loads(KEYS_FILE.read_text(encoding="utf-8-sig"))
        except Exception: return {}
    return {}


def _save_keys(data: dict) -> None:
    KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEYS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _mask(s: str | None) -> str:
    if not s: return ""
    if len(s) <= 8: return "•" * len(s)
    return s[:4] + "…" + s[-4:]


def get_provider_state() -> dict[str, dict[str, Any]]:
    stored = _load_keys()
    # Pull usage + thresholds once
    try:
        usage_data = _load_usage()
        thresholds = _load_thresholds()
        today = datetime.now().strftime("%Y-%m-%d")
    except Exception:
        usage_data, thresholds, today = {}, {}, ""

    out: dict[str, dict[str, Any]] = {}
    for pid, meta in PROVIDERS.items():
        env_val, env_name_hit = None, None
        for n in meta["envs"]:
            v = os.environ.get(n)
            if v: env_val = v; env_name_hit = n; break
        cfg = stored.get(pid, {}) if isinstance(stored.get(pid), dict) else {}
        file_key = cfg.get("key") or ""
        has_key = bool(env_val) or bool(file_key)
        enabled = cfg.get("enabled", bool(env_val))

        u = usage_data.get(pid, {})
        today_n = (u.get("by_day", {}).get(today, {}) or {}).get("total", 0) if today else 0
        limit = (thresholds.get(pid) or {}).get("daily_limit", 0)
        pct = min(100, round(100 * today_n / limit, 1)) if limit else 0

        out[pid] = {
            "id": pid, "title": meta["title"], "url": meta["url"],
            "icon": meta["icon"], "hint": meta["hint"],
            "enabled": bool(enabled), "has_env": bool(env_val),
            "env_name": env_name_hit, "has_file_key": bool(file_key),
            "has_key": has_key, "masked": _mask(env_val or file_key),
            "source": "env" if env_val else ("file" if file_key else None),
            "usage": {
                "today":   today_n,
                "total":   u.get("total", 0),
                "errors":  u.get("errors", 0),
                "last_at": u.get("last_at"),
                "limit":   limit,
                "pct":     pct,
                "over":    bool(limit and today_n >= limit),
            },
        }
    return out


# ---------------------------------------------------------------------------
# Status collectors
# ---------------------------------------------------------------------------
def _rocm_smi_path() -> str | None:
    hip = (CONFIG.get("gpu") or {}).get("HipPath")
    if hip:
        p = Path(hip) / "bin" / "rocm-smi.exe"
        if p.exists(): return str(p)
    return shutil.which("rocm-smi") or shutil.which("rocm-smi.exe")


_gpu_status_cache: dict[str, Any] = {"ts": 0.0, "data": None}

def gpu_status() -> dict[str, Any]:
    """GPU telemetry — cached 5s. Underlying probe (PowerShell Get-Counter,
    rocm-smi, nvidia-smi) spawns a subprocess that takes 3-10s on Windows.
    Without cache, /api/status polled every 2s burns 100%+ CPU on probe alone."""
    global _gpu_status_cache
    now = time.time()
    if _gpu_status_cache["data"] is not None and (now - _gpu_status_cache["ts"]) < 30:
        return _gpu_status_cache["data"]

    info = {
        "vendor": (CONFIG.get("gpu") or {}).get("Vendor", "unknown"),
        "name":   (CONFIG.get("gpu") or {}).get("Name", ""),
        "vram_total_mb": (CONFIG.get("gpu") or {}).get("VramMB", 0),
        "vram_used_mb": 0, "util_pct": 0.0, "temp_c": 0.0,
        "available": False, "telemetry": "none",
    }
    rocm = _rocm_smi_path()
    if rocm:
        try:
            out = subprocess.run([rocm, "--showmeminfo","vram","--showtemp","--showuse","--showproductname","--json"],
                                 capture_output=True, text=True, timeout=4)
            txt = out.stdout.strip()
            if txt.startswith("{"):
                data = json.loads(txt); card = next(iter(data.values()))
                info["available"]=True; info["telemetry"]="rocm-smi"; info["vendor"]="amd"
                info["name"] = card.get("Card series") or card.get("Card model") or info["name"]
                t = int(card.get("VRAM Total Memory (B)") or 0)
                u = int(card.get("VRAM Total Used Memory (B)") or 0)
                if t: info["vram_total_mb"] = t // (1024*1024)
                if u: info["vram_used_mb"] = u // (1024*1024)
                for k in ("Temperature (Sensor edge) (C)","Temperature (Sensor junction) (C)"):
                    if card.get(k): info["temp_c"] = float(card[k]); break
                if card.get("GPU use (%)"): info["util_pct"] = float(card["GPU use (%)"])
                _gpu_status_cache = {"ts": now, "data": info}
                return info
        except Exception: pass

    nv = shutil.which("nvidia-smi")
    if nv:
        try:
            q = "name,memory.total,memory.used,utilization.gpu,temperature.gpu"
            out = subprocess.run([nv, f"--query-gpu={q}", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=4)
            parts = [p.strip() for p in out.stdout.strip().splitlines()[0].split(",")]
            info.update({"vendor":"nvidia","available":True,"telemetry":"nvidia-smi",
                         "name":parts[0],"vram_total_mb":int(parts[1]),"vram_used_mb":int(parts[2]),
                         "util_pct":float(parts[3]),"temp_c":float(parts[4])})
            _gpu_status_cache = {"ts": now, "data": info}
            return info
        except Exception: pass

    try:
        # Sum across all GPU engines (3D + Compute + Video) — Ollama uses Compute
        cmd = ("[System.Threading.Thread]::CurrentThread.CurrentCulture="
               "[System.Globalization.CultureInfo]::InvariantCulture;"
               "$m=(Get-Counter '\\GPU Adapter Memory(*)\\Dedicated Usage' -ErrorAction SilentlyContinue).CounterSamples;"
               "$u3d=(Get-Counter '\\GPU Engine(*engtype_3D)\\Utilization Percentage' -ErrorAction SilentlyContinue).CounterSamples;"
               "$uc=(Get-Counter '\\GPU Engine(*engtype_Compute*)\\Utilization Percentage' -ErrorAction SilentlyContinue).CounterSamples;"
               "$mem=if($m){[math]::Round((($m|Measure-Object CookedValue -Sum).Sum)/1MB)}else{0};"
               "$u3=if($u3d){[math]::Round(($u3d|Measure-Object CookedValue -Sum).Sum,1)}else{0};"
               "$uc2=if($uc){[math]::Round(($uc|Measure-Object CookedValue -Sum).Sum,1)}else{0};"
               "$util=[math]::Round([math]::Min(100,$u3+$uc2),1);"
               "Write-Output (\"BRAIN_GPU:{0};{1}\" -f $mem,$util)")
        # 15s timeout — Get-Counter cold-start can take 7-10s on Windows
        out = subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",cmd],
                             capture_output=True, text=True, timeout=15)
        # Look for our prefixed line (PowerShell may emit warnings/errors above)
        for line in (out.stdout or "").splitlines():
            if line.startswith("BRAIN_GPU:"):
                payload = line[len("BRAIN_GPU:"):].strip()
                mem_mb, util = payload.split(";")
                info.update({"vram_used_mb":int(mem_mb),"util_pct":float(util),
                             "available":True,"telemetry":"perfcounter"})
                break
    except Exception: pass
    _gpu_status_cache = {"ts": now, "data": info}
    return info


_ollama_status_cache: dict[str, Any] = {"ts": 0.0, "data": None}

def ollama_status() -> dict[str, Any]:
    """Ollama probe — cached 5s. Cold call is 1.5-3s (timeout when Ollama down),
    /api/status polls hammer this. 5s cache gives near-realtime UI without burn."""
    global _ollama_status_cache
    now = time.time()
    if _ollama_status_cache["data"] is not None and (now - _ollama_status_cache["ts"]) < 5:
        return _ollama_status_cache["data"]
    port = CONFIG.get("ollama_port", 11434)
    url = f"http://127.0.0.1:{port}"
    try:
        r = requests.get(f"{url}/api/tags", timeout=1.5)
        if r.ok:
            models = r.json().get("models", [])
            embed_models = [m for m in models if "embed" in (m.get("name") or "").lower()]
            chat_models  = [m for m in models if "embed" not in (m.get("name") or "").lower()]
            # Also fetch what's currently loaded in VRAM
            loaded = []
            try:
                pr = requests.get(f"{url}/api/ps", timeout=1.5)
                if pr.ok:
                    for m in pr.json().get("models", []):
                        loaded.append({
                            "name": m.get("name"),
                            "size_gb":      round((m.get("size") or 0) / 1024**3, 2),
                            "size_vram_gb": round((m.get("size_vram") or 0) / 1024**3, 2),
                            "expires_at":   m.get("expires_at"),
                        })
            except Exception:
                pass
            data = {
                "running": True, "url": url,
                "models": [{"name": m.get("name"),
                            "size_gb": round((m.get("size") or 0) / 1024**3, 1),
                            "is_embed": "embed" in (m.get("name") or "").lower()}
                           for m in models],
                "count": len(models),
                "chat_count": len(chat_models),
                "embed_models": [m["name"] for m in embed_models],
                "loaded": loaded,
                "vram_used_gb": round(sum(m["size_vram_gb"] for m in loaded), 2),
            }
            _ollama_status_cache = {"ts": now, "data": data}
            return data
    except Exception: pass
    data = {"running": False, "url": url, "models": [], "count": 0,
            "chat_count": 0, "embed_models": [], "loaded": [], "vram_used_gb": 0}
    _ollama_status_cache = {"ts": now, "data": data}
    return data


_brain_proc_cache: dict[str, Any] = {"ts": 0.0, "data": None}

def _brain_process_stats() -> dict[str, Any]:
    """Sum CPU% and RAM across all brain-owned processes.
       psutil.cpu_percent is delta-based — first call returns 0. So we:
         1. Find brain procs (fast filter on cmdline)
         2. Prime cpu_percent on each (returns 0)
         3. Sleep 0.3s
         4. Read cpu_percent again — now has real %
       Cached 5s so the 0.3s cost is amortised across many requests."""
    global _brain_proc_cache
    now = time.time()
    if _brain_proc_cache["data"] and (now - _brain_proc_cache["ts"]) < 5:
        return _brain_proc_cache["data"]

    brain_str = str(ROOT).lower()
    matched: list[psutil.Process] = []
    ram_sum = 0
    try:
        for p in psutil.process_iter(["name", "exe", "cmdline", "memory_info"]):
            try:
                info = p.info
                exe = (info.get("exe") or "").lower()
                cmd = " ".join(str(c) for c in (info.get("cmdline") or [])).lower()
                is_brain = brain_str in exe or brain_str in cmd or \
                           "ollama" in (info.get("name") or "").lower()
                if is_brain:
                    matched.append(p)
                    mi = info.get("memory_info")
                    if mi:
                        ram_sum += mi.rss
                    # Prime cpu_percent — first call returns 0, just resets the counter
                    try: p.cpu_percent(interval=None)
                    except Exception: pass
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception:
        pass

    # Tiny sleep, then second read gives actual delta
    time.sleep(0.3)
    cpu_sum = 0.0
    for p in matched:
        try:
            cpu_sum += float(p.cpu_percent(interval=None))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    n_cores = psutil.cpu_count(logical=True) or 1
    data = {
        "brain_cpu_pct":  round(cpu_sum / n_cores, 1),
        "brain_ram_mb":   round(ram_sum / 1024**2, 0),
        "brain_procs":    len(matched),
    }
    _brain_proc_cache = {"ts": now, "data": data}
    return data


def system_status() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    du = psutil.disk_usage(str(ROOT))
    brain = _brain_process_stats()
    return {
        "cpu_pct": psutil.cpu_percent(interval=None),
        "ram_used_gb": round(vm.used/1024**3, 1), "ram_total_gb": round(vm.total/1024**3, 1),
        "disk_used_gb": round(du.used/1024**3, 1), "disk_total_gb": round(du.total/1024**3, 1),
        "uptime_sec": int(time.time() - _start_time),
        **brain,
    }


_vault_status_cache: dict[str, Any] = {"ts": 0.0, "data": None}

def vault_status() -> dict[str, Any]:
    """Vault file scan — cached 10s. Walks ~1000 .md files which costs ~2s
    on each call; /api/status polling every 2s burned ~50% CPU on this alone."""
    global _vault_status_cache
    now = time.time()
    if _vault_status_cache["data"] is not None and (now - _vault_status_cache["ts"]) < 10:
        return _vault_status_cache["data"]
    notes, total_size, recent = 0, 0, []
    if VAULT_DIR.exists():
        files = []
        for p in VAULT_DIR.rglob("*.md"):
            try:
                files.append((p, p.stat().st_mtime, p.stat().st_size))
                notes += 1; total_size += p.stat().st_size
            except OSError: pass
        files.sort(key=lambda x: x[1], reverse=True)
        for p, m, s in files[:8]:
            recent.append({"name": p.name, "path": str(p),
                           "rel": str(p.relative_to(VAULT_DIR)),
                           "size_kb": s // 1024, "mtime": m})
    data = {"notes": notes, "size_kb": total_size // 1024,
            "path": str(VAULT_DIR), "recent": recent}
    _vault_status_cache = {"ts": now, "data": data}
    return data


def vectordb_status() -> dict[str, Any]:
    db = ROOT / "data" / "vectordb"
    files = list(db.glob("*.db")) if db.exists() else []
    size = sum(f.stat().st_size for f in files)
    return {"files": len(files), "size_mb": round(size/1024**2, 1)}


LIBRARY_EXT = {".pdf", ".epub", ".mobi", ".azw", ".azw3",
               ".docx", ".txt", ".md", ".html", ".htm"}


def library_status() -> dict[str, Any]:
    if not LIBRARY_DIR.exists():
        return {"pdfs": 0, "files_count": 0, "size_mb": 0.0, "files": [],
                "needs_reindex": False, "latest_mtime": 0}
    files = []
    total = 0
    latest_mtime = 0
    for p in LIBRARY_DIR.rglob("*"):
        if not p.is_file(): continue
        if p.suffix.lower() not in LIBRARY_EXT: continue
        try:
            st = p.stat()
            total += st.st_size
            latest_mtime = max(latest_mtime, st.st_mtime)
            files.append({"name": p.name, "rel": str(p.relative_to(LIBRARY_DIR)),
                          "size_mb": round(st.st_size / 1024**2, 2),
                          "ext": p.suffix.lower().lstrip(".")})
        except OSError:
            pass
    files.sort(key=lambda x: -x["size_mb"])

    # Check if any files are newer than the last RAG index
    last_indexed = 0
    if RAG_STATUS.exists():
        try:
            st = json.loads(RAG_STATUS.read_text(encoding="utf-8-sig"))
            last_indexed = st.get("finished_at", 0)
        except Exception:
            pass
    # 10s grace period to avoid triggering reindex while file is still being copied
    needs_reindex = bool(files) and latest_mtime > last_indexed and (time.time() - latest_mtime) > 10

    return {
        "pdfs": len(files),            # legacy field — now means "indexable files"
        "files_count": len(files),
        "size_mb": round(total / 1024**2, 2),
        "files": files[:50],
        "path": str(LIBRARY_DIR),
        "latest_mtime": latest_mtime,
        "last_indexed": last_indexed,
        "needs_reindex": needs_reindex,
    }


_distill_running_cache: dict[str, Any] = {"ts": 0.0, "value": False}

def _is_distill_running() -> bool:
    """Check for ACTIVE distill (only 'run'/'distill' actions, not quick 'sources'/'status').

    Fast path: own subprocess handle (0ms).
    Slow path: psutil.process_iter (~4s on Windows — scans all processes).
    Cached for 5s to prevent ~/api/transcripts/status polling from burning CPU.
    """
    global _distill_proc, _distill_running_cache
    # Fast path: own handle is authoritative when present
    if _distill_proc is not None and _distill_proc.poll() is None:
        return True

    # Slow path with 60s cache — psutil.process_iter is ~4s on Windows,
    # would burn ~30% CPU if called per /api/transcripts/status poll.
    now = time.time()
    if (now - _distill_running_cache["ts"]) < 60:
        return _distill_running_cache["value"]

    found = False
    try:
        for p in psutil.process_iter(["name", "cmdline"]):
            try:
                cmd = p.info.get("cmdline") or []
                cmd_str = " ".join(str(c) for c in cmd)
                if "distill.py" in cmd_str and any(
                    action in cmd_str.split() for action in ("run", "distill", "collect")
                ):
                    found = True
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception:
        pass

    _distill_running_cache = {"ts": now, "value": found}
    return found


def distill_status() -> dict[str, Any]:
    running = _is_distill_running()
    status = {}
    if DISTILL_STATUS.exists():
        try: status = json.loads(DISTILL_STATUS.read_text(encoding="utf-8-sig"))
        except Exception: pass
    # Auto-correct stale "distilling" state when no process is actually running
    if not running and status.get("state") == "distilling":
        status["state"] = "idle"
        status["stale"] = True
        # Persist correction so subsequent reads stay consistent
        try:
            DISTILL_STATUS.write_text(json.dumps(status, indent=2), encoding="utf-8")
        except Exception: pass
    status["proc_running"] = running
    return status


# ---------------------------------------------------------------------------
# Routes — main status
# ---------------------------------------------------------------------------
@app.get("/api/status")
def api_status() -> dict[str, Any]:
    return {
        "ollama": ollama_status(),
        "gpu": gpu_status(),
        "system": system_status(),
        "vault": vault_status(),
        "vectordb": vectordb_status(),
        "library": library_status(),
        "apis": get_provider_state(),
        "config": {"model": CONFIG.get("default_model"),
                   "ollama_port": CONFIG.get("ollama_port"),
                   "edition": CONFIG.get("edition", "windows"),
                   "root": str(ROOT),
                   "data_dir": str(DATA_ROOT)},
        "time": time.time(),
    }


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------
@app.get("/api/keys")
def api_get_keys() -> dict[str, Any]:
    return {"providers": get_provider_state(), "keys_file": str(KEYS_FILE)}


class KeyUpdate(BaseModel):
    enabled: bool
    key: str | None = None


@app.post("/api/keys/{provider}")
def api_set_key(provider: str, body: KeyUpdate) -> dict[str, Any]:
    if provider not in PROVIDERS: raise HTTPException(404, f"unknown provider: {provider}")
    data = _load_keys()
    if not isinstance(data.get(provider), dict): data[provider] = {}
    data[provider]["enabled"] = bool(body.enabled)
    if body.key is not None:
        if body.key == "": data[provider].pop("key", None)
        else: data[provider]["key"] = body.key
    _save_keys(data)
    return {"ok": True, "providers": get_provider_state()}


@app.post("/api/keys/{provider}/test")
def api_test_key(provider: str) -> dict[str, Any]:
    if provider not in PROVIDERS: raise HTTPException(404, "unknown provider")
    state = get_provider_state()[provider]
    if not state["has_key"]: return {"ok": False, "error": "no key configured"}
    key = None
    for n in PROVIDERS[provider]["envs"]:
        if os.environ.get(n): key = os.environ[n]; break
    if not key: key = _load_keys().get(provider, {}).get("key")
    if not key: return {"ok": False, "error": "key not resolvable"}
    try:
        endpoints = {
            "anthropic":  ("GET", "https://api.anthropic.com/v1/models",
                           {"x-api-key": key, "anthropic-version": "2023-06-01"}),
            "openai":     ("GET", "https://api.openai.com/v1/models",
                           {"Authorization": f"Bearer {key}"}),
            "google":     ("GET", f"https://generativelanguage.googleapis.com/v1beta/models?key={key}", {}),
            "xai":        ("GET", "https://api.x.ai/v1/models", {"Authorization": f"Bearer {key}"}),
            "openrouter": ("GET", "https://openrouter.ai/api/v1/models", {"Authorization": f"Bearer {key}"}),
        }
        method, url, headers = endpoints[provider]
        r = requests.request(method, url, headers=headers, timeout=8)
        return {"ok": r.ok, "status": r.status_code,
                "info": "model list ok" if r.ok else r.text[:200]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------
@app.get("/api/logs/list")
def api_logs_list() -> dict[str, Any]:
    files = []
    if LOGS_DIR.exists():
        for f in sorted(LOGS_DIR.glob("*.log")):
            try:
                s = f.stat()
                files.append({"name": f.stem, "filename": f.name,
                              "size_kb": s.st_size // 1024, "mtime": s.st_mtime})
            except OSError: pass
    return {"logs": files}


@app.get("/api/logs/tail")
def api_logs_tail(name: str, lines: int = 200) -> dict[str, Any]:
    # whitelist by directory listing
    safe = re.sub(r"[^a-zA-Z0-9_\-.]", "", name)
    candidates = [LOGS_DIR / f"{safe}.log", LOGS_DIR / f"{safe}.err.log",
                  LOGS_DIR / f"{safe}.out.log", LOGS_DIR / safe]
    path = next((c for c in candidates if c.exists() and c.is_file()), None)
    if not path:
        raise HTTPException(404, f"log not found: {name}")
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            read = min(size, max(8192, lines * 250))
            f.seek(size - read)
            content = f.read().decode("utf-8", errors="replace")
        return {"name": name, "path": str(path),
                "size_bytes": size,
                "lines": content.splitlines()[-lines:]}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/logs/clear")
def api_logs_clear(name: str) -> dict[str, Any]:
    safe = re.sub(r"[^a-zA-Z0-9_\-.]", "", name)
    candidates = [LOGS_DIR / f"{safe}.log", LOGS_DIR / f"{safe}.err.log",
                  LOGS_DIR / f"{safe}.out.log", LOGS_DIR / safe]
    cleared = []
    for c in candidates:
        if c.exists():
            try: c.write_text(""); cleared.append(str(c))
            except Exception: pass
    return {"cleared": cleared}


# ---------------------------------------------------------------------------
# Vault + Graph
# ---------------------------------------------------------------------------
WIKILINK_RE = re.compile(r"\[\[([^\]\|#]+)(?:#[^\]\|]+)?(?:\|[^\]]+)?\]\]")
YAML_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class SaveChatRequest(BaseModel):
    title: str
    model: str | None = None
    messages: list[dict]  # [{role, content}, ...]


@app.post("/api/vault/save-chat")
def api_vault_save_chat(body: SaveChatRequest) -> dict[str, Any]:
    """Save chat widget conversation as markdown note in vault/chats/."""
    chats_dir = VAULT_DIR / "chats"
    chats_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    safe_title = re.sub(r"[^a-zA-Z0-9\- _]", "", body.title or "chat")[:60].strip() or "chat"
    fname = f"{date_str}_{safe_title.replace(' ', '_')}.md"
    path = chats_dir / fname

    md = (f"---\nsource: chat-widget\nmodel: {body.model or 'unknown'}\n"
          f"date: {date_str}\nmessages: {len(body.messages)}\n---\n\n"
          f"# {body.title or 'Chat session'}\n\n")
    for m in body.messages:
        role = m.get("role", "?")
        content = m.get("content", "")
        md += f"## {role}\n\n{content}\n\n"

    path.write_text(md, encoding="utf-8")
    return {"ok": True, "path": str(path), "rel": str(path.relative_to(VAULT_DIR))}


@app.get("/api/vault/notes")
def api_vault_notes(limit: int = 50) -> dict[str, Any]:
    if not VAULT_DIR.exists(): return {"notes": []}
    notes = []
    for p in VAULT_DIR.rglob("*.md"):
        try:
            s = p.stat()
            notes.append({
                "name": p.stem, "filename": p.name,
                "rel": str(p.relative_to(VAULT_DIR)),
                "path": str(p),
                "size_kb": s.st_size // 1024, "mtime": s.st_mtime,
            })
        except OSError: pass
    notes.sort(key=lambda n: n["mtime"], reverse=True)
    return {"notes": notes[:limit], "total": len(notes), "vault": str(VAULT_DIR)}


def _open_folder(path: Path) -> dict[str, Any]:
    """Open a folder in Windows Explorer. Works even when dashboard runs
    as a hidden-window subprocess (where os.startfile silently no-ops)."""
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            subprocess.Popen(["xdg-open", str(path)])
            return {"opened": True, "via": "xdg-open"}
        except Exception as e:
            return {"opened": False, "error": str(e)}
    try:
        # explorer.exe with a path argument works reliably from any session
        subprocess.Popen(["explorer.exe", str(path)])
        return {"opened": True, "via": "explorer"}
    except Exception as e:
        return {"opened": False, "error": str(e)}


@app.post("/api/vault/open")
def api_vault_open() -> dict[str, Any]:
    return _open_folder(VAULT_DIR)


# ---------------------------------------------------------------------------
# USER PROFILE (Hermes-style USER.md)
# ---------------------------------------------------------------------------
USER_MD = VAULT_DIR / "USER.md"
USER_MAX = 2200

@app.get("/api/user-profile")
def api_user_profile_get() -> dict[str, Any]:
    if not USER_MD.exists():
        return {"content": "", "chars": 0, "max": USER_MAX, "pct": 0}
    content = USER_MD.read_text(encoding="utf-8", errors="replace")
    chars   = len(content)
    return {"content": content, "chars": chars, "max": USER_MAX, "pct": round(chars/USER_MAX*100)}

class UserProfileUpdate(BaseModel):
    content: str

@app.post("/api/user-profile/save")
def api_user_profile_save(body: UserProfileUpdate) -> dict[str, Any]:
    content = body.content or ""
    if len(content) > USER_MAX:
        return {"ok": False, "error": f"Przekracza limit {USER_MAX} znaków"}
    tmp = USER_MD.with_suffix(".md.tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(USER_MD)
    return {"ok": True, "chars": len(content), "pct": round(len(content)/USER_MAX*100)}

@app.post("/api/user-profile/update-from-sessions")
def api_user_profile_update() -> dict[str, Any]:
    """Run update-user-profile skill via Ollama to refresh USER.md from recent sessions."""
    try:
        sys.path.insert(0, str(ROOT / "pipeline"))
        import importlib
        skills_mod = importlib.import_module("skills")
        result = skills_mod.run_skill("update-user-profile", {})
        if result.get("ok") and result.get("output"):
            output = result["output"].strip()
            # Extract content between first § and end
            if "§" in output:
                start = output.find("§")
                output = output[start:]
            if len(output) <= USER_MAX:
                tmp = USER_MD.with_suffix(".md.tmp")
                tmp.write_text(output, encoding="utf-8")
                tmp.replace(USER_MD)
                return {"ok": True, "chars": len(output), "preview": output[:300]}
        return {"ok": False, "error": result.get("error", "Skill failed — sprawdź czy Ollama działa")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/vault/quality")
def api_vault_quality() -> dict[str, Any]:
    """Distillation quality breakdown. Helps user see how many notes need re-distill."""
    distilled = VAULT_DIR / "distilled"
    if not distilled.exists():
        return {"total": 0}
    import re as _re
    solid, weak, tiny, stub = 0, 0, 0, 0
    for f in distilled.glob("*.md"):
        try:
            size = f.stat().st_size
            if size < 350:
                tiny += 1
                continue
            if size < 2000:  # only check small files for stub
                try:
                    if "## _Stub_" in f.read_text(encoding="utf-8", errors="replace"):
                        stub += 1
                        continue
                except Exception: pass
            if size < 600:
                weak += 1
            else:
                solid += 1
        except OSError: pass
    total = solid + weak + tiny + stub
    out = {
        "total":  total,
        "solid":  solid,
        "weak":   weak,
        "tiny":   tiny,
        "stub":   stub,
        "needs_redistill": weak + tiny + stub,
        "solid_pct": round(100 * solid / max(1, total), 0),
    }
    # Merge deep audit (note_quality.py) if present
    nq_path = ROOT / "data" / "note-quality.json"
    if nq_path.exists():
        try:
            nq = json.loads(nq_path.read_text(encoding="utf-8")).get("summary", {})
            out["deep"] = {
                "avg_score":   nq.get("avg_score"),
                "verdicts":    nq.get("verdicts", {}),
                "by_source":   nq.get("by_source", {}),
                "audit_mtime": nq_path.stat().st_mtime,
                "analyzed":    nq.get("analyzed", 0),
            }
        except Exception: pass
    return out


@app.post("/api/vault/quality/deep-audit")
def api_vault_deep_audit() -> dict[str, Any]:
    """Trigger pipeline/note_quality.py audit in background."""
    script = ROOT / "pipeline" / "note_quality.py"
    if not script.exists():
        return {"ok": False, "error": "pipeline/note_quality.py missing"}
    log_path = LOGS_DIR / "note-quality.log"
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        proc = subprocess.Popen(
            [sys.executable, "-X", "utf8", str(script), "audit"],
            stdout=open(log_path, "ab"), stderr=subprocess.STDOUT,
            creationflags=flags,
        )
        return {"ok": True, "pid": proc.pid, "log": str(log_path),
                "msg": "Audyt jakości uruchomiony — odśwież za ~30s"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


class RedistillRun(BaseModel):
    model: str = "qwen2.5:14b"
    limit: int = 5


@app.post("/api/vault/redistill/run")
def api_vault_redistill_run(body: RedistillRun) -> dict[str, Any]:
    sched = _load_scheduler()
    if sched._run_lock.locked():
        return {"ok": False, "error": "Scheduler is currently running a background task. Please pause AUTO SCHEDULE first to run large batches manually."}
        
    global _redistill_proc
    if _redistill_proc and _redistill_proc.poll() is None:
        return {"ok": False, "error": "already running", "pid": _redistill_proc.pid}
    
    script_path = ROOT / "pipeline" / "redistill.py"
    args = [_python_exe(), str(script_path), "batch", str(body.limit), body.model]
    
    log_path = LOGS_DIR / "redistill.log"
    log_file = open(log_path, "ab")
    env = os.environ.copy()
    env["OLLAMA_HOST"] = f"127.0.0.1:{CONFIG.get('ollama_port',11434)}"
    
    kwargs = {"stdout": log_file, "stderr": log_file, "env": env}
    if os.name == "nt": kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    
    _redistill_proc = subprocess.Popen(args, **kwargs)
    _redistill_proc._brain_t0 = time.time()  # for jobs panel elapsed display
    return {"ok": True, "pid": _redistill_proc.pid, "log": str(log_path), "cmd": " ".join(args)}


@app.post("/api/vault/redistill/stop")
def api_vault_redistill_stop() -> dict[str, Any]:
    global _redistill_proc
    killed = []
    if _redistill_proc and _redistill_proc.poll() is None:
        try:
            _redistill_proc.terminate()
            try: _redistill_proc.wait(timeout=3)
            except subprocess.TimeoutExpired: _redistill_proc.kill()
            killed.append(_redistill_proc.pid)
        except Exception: pass
        
    try:
        import psutil
        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cmd = p.info.get("cmdline") or []
                if any("redistill.py" in str(c) for c in cmd):
                    if p.info["pid"] not in killed:
                        p.terminate()
                        killed.append(p.info["pid"])
            except Exception: pass
    except Exception: pass
    
    _redistill_proc = None
    
    status_f = ROOT / "data" / "redistill-status.json"
    if status_f.exists():
        try:
            s = json.loads(status_f.read_text(encoding="utf-8-sig"))
            s["state"] = "stopped"
            s["stopped_at"] = time.time()
            status_f.write_text(json.dumps(s, indent=2), encoding="utf-8")
        except Exception: pass

    return {"ok": True, "stopped": bool(killed), "killed_pids": killed}


@app.get("/api/vault/redistill/status")
def api_vault_redistill_status() -> dict[str, Any]:
    status_f = ROOT / "data" / "redistill-status.json"
    if status_f.exists():
        try: return json.loads(status_f.read_text(encoding="utf-8-sig"))
        except Exception: pass
    return {"state": "idle", "done": 0, "total": 0}


@app.get("/api/vault/read")
def api_vault_read(path: str) -> Any:
    """Read a note from vault by relative path. Used by graph node click panel."""
    from fastapi.responses import PlainTextResponse
    # Reject anything that tries to escape vault
    rel = Path(path)
    if rel.is_absolute() or ".." in rel.parts:
        return PlainTextResponse("forbidden", status_code=403)
    full = (VAULT_DIR / rel).resolve()
    try:
        full.relative_to(VAULT_DIR.resolve())
    except ValueError:
        return PlainTextResponse("outside vault", status_code=403)
    if not full.exists() or not full.is_file():
        return PlainTextResponse("not found", status_code=404)
    try:
        return PlainTextResponse(full.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        return PlainTextResponse(f"error: {e}", status_code=500)


# ---------------------------------------------------------------------------
# Vault dedup — knowledge lifecycle (claude-os style, minus Redis)
# ---------------------------------------------------------------------------
class DedupPair(BaseModel):
    a: str
    b: str
    strategy: str = "newer"   # 'newer' | 'longer'


@app.post("/api/vault/dedupe/scan")
def api_vault_dedupe_scan() -> dict[str, Any]:
    """Run dedup scan: cosine on mean-embedding + Jaccard on 5-gram word shingles
       + title-word similarity. Returns candidate pairs. Slow on first run
       (~5-10s on 1000 files), then cached in dedup-candidates.json."""
    sys.path.insert(0, str(ROOT / "pipeline"))
    try:
        import importlib
        if "dedupe" in sys.modules:
            importlib.reload(sys.modules["dedupe"])
        from dedupe import scan as _scan
        return _scan()
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/vault/dedupe/candidates")
def api_vault_dedupe_candidates() -> dict[str, Any]:
    sys.path.insert(0, str(ROOT / "pipeline"))
    try:
        import importlib
        if "dedupe" in sys.modules:
            importlib.reload(sys.modules["dedupe"])
        from dedupe import load_candidates
        return load_candidates()
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/vault/dedupe/merge")
def api_vault_dedupe_merge(body: DedupPair) -> dict[str, Any]:
    sys.path.insert(0, str(ROOT / "pipeline"))
    try:
        import importlib
        if "dedupe" in sys.modules:
            importlib.reload(sys.modules["dedupe"])
        from dedupe import merge as _merge
        return _merge(body.a, body.b, body.strategy)
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/vault/dedupe/dismiss")
def api_vault_dedupe_dismiss(body: DedupPair) -> dict[str, Any]:
    sys.path.insert(0, str(ROOT / "pipeline"))
    try:
        import importlib
        if "dedupe" in sys.modules:
            importlib.reload(sys.modules["dedupe"])
        from dedupe import dismiss as _dismiss
        return _dismiss(body.a, body.b)
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Skills — agentic OS layer (claude-os style)
# ---------------------------------------------------------------------------
class SkillRunRequest(BaseModel):
    name: str
    inputs: dict[str, Any] = {}
    model_override: str | None = None


@app.get("/api/skills/list")
def api_skills_list() -> dict[str, Any]:
    sys.path.insert(0, str(ROOT / "pipeline"))
    try:
        import importlib
        if "skills" in sys.modules:
            importlib.reload(sys.modules["skills"])
        from skills import list_skills
        return {"skills": list_skills()}
    except Exception as e:
        return {"skills": [], "error": str(e)}


@app.post("/api/skills/open")
def api_skills_open() -> dict[str, Any]:
    return _open_folder(ROOT / "skills")


def _load_skills():
    """Keep skills module loaded — DO NOT reload (would wipe _stop_event, _current_skill)."""
    sys.path.insert(0, str(ROOT / "pipeline"))
    import importlib
    if "skills" in sys.modules:
        return sys.modules["skills"]
    return importlib.import_module("skills")


@app.post("/api/skills/run")
def api_skills_run(body: SkillRunRequest) -> dict[str, Any]:
    try:
        return _load_skills().run_skill(body.name, body.inputs, body.model_override)
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/skills/stop")
def api_skills_stop() -> dict[str, Any]:
    try:
        return _load_skills().request_stop_skill()
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/skills/current")
def api_skills_current() -> dict[str, Any]:
    try:
        return _load_skills().current_skill_status()
    except Exception as e:
        return {"name": None, "error": str(e)}


# ---------------------------------------------------------------------------
# CLI Skills (Claude Code)
# ---------------------------------------------------------------------------
@app.get("/api/cli-skills/list")
def api_cli_skills_list() -> dict[str, Any]:
    try:
        skills_dir = Path.home() / ".claude" / "skills"
        if not skills_dir.exists():
            return {"skills": []}
        
        out = []
        for p in skills_dir.iterdir():
            if p.is_dir() and (p / "SKILL.md").exists():
                content = (p / "SKILL.md").read_text(encoding="utf-8", errors="ignore")
                name = p.name
                desc = "No description"
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        yaml_str = parts[1]
                        for line in yaml_str.splitlines():
                            if line.startswith("name:"): name = line.split(":", 1)[1].strip().strip('"').strip("'")
                            if line.startswith("description:"): desc = line.split(":", 1)[1].strip().strip('"').strip("'")
                out.append({"id": p.name, "name": name, "description": desc, "path": str(p)})
        return {"skills": sorted(out, key=lambda x: x["name"].lower())}
    except Exception as e:
        import traceback
        return {"skills": [], "error": str(e), "traceback": traceback.format_exc()}

@app.post("/api/cli-skills/open")
def api_cli_skills_open() -> dict[str, Any]:
    skills_dir = Path.home() / ".claude" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    return _open_folder(skills_dir)


# ---------------------------------------------------------------------------
# Code indexing — RAG over user's source projects (separate vectordb)
# ---------------------------------------------------------------------------
class CodePath(BaseModel):
    path: str


class CodeSearch(BaseModel):
    query: str
    top_k: int = 10
    lang: str | None = None


CODE_SCRIPT = ROOT / "pipeline" / "codeindex.py"
_code_proc: subprocess.Popen | None = None


def _load_codeindex():
    sys.path.insert(0, str(ROOT / "pipeline"))
    import importlib
    if "codeindex" in sys.modules:
        importlib.reload(sys.modules["codeindex"])
    import codeindex
    return codeindex


@app.get("/api/code/status")
def api_code_status() -> dict[str, Any]:
    global _code_proc
    try:
        ci = _load_codeindex()
        s = ci.status()
    except Exception as e:
        return {"error": str(e), "files": 0, "chunks": 0, "watches": []}
    s["scan_running"] = _code_proc is not None and _code_proc.poll() is None
    return s


@app.post("/api/code/watch/add")
def api_code_watch_add(body: CodePath) -> dict[str, Any]:
    try:
        ci = _load_codeindex()
        return ci.add_watch(body.path)
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/code/watch/remove")
def api_code_watch_remove(body: CodePath) -> dict[str, Any]:
    try:
        ci = _load_codeindex()
        return ci.remove_watch(body.path)
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/code/scan")
def api_code_scan() -> dict[str, Any]:
    """Trigger scan in background (so HTTP returns immediately)."""
    global _code_proc
    if _code_proc and _code_proc.poll() is None:
        return {"ok": False, "error": "scan already running", "pid": _code_proc.pid}
    args = [sys.executable, str(CODE_SCRIPT), "scan"]
    log_path = LOGS_DIR / "codeindex.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = open(log_path, "ab")
    _code_proc = subprocess.Popen(args, stdout=log, stderr=log,
                                  creationflags=subprocess.CREATE_NO_WINDOW
                                  if hasattr(subprocess, "CREATE_NO_WINDOW") else 0)
    _code_proc._brain_t0 = time.time()
    return {"ok": True, "pid": _code_proc.pid}


@app.post("/api/code/stop")
def api_code_stop() -> dict[str, Any]:
    """Stop running code index scan."""
    global _code_proc
    if not _code_proc or _code_proc.poll() is not None:
        return {"ok": False, "error": "no scan running"}
    try:
        _code_proc.terminate()
        try: _code_proc.wait(timeout=3)
        except subprocess.TimeoutExpired: _code_proc.kill()
        pid = _code_proc.pid
        _code_proc = None
        return {"ok": True, "killed_pid": pid}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/code/search")
def api_code_search(body: CodeSearch) -> dict[str, Any]:
    try:
        ci = _load_codeindex()
        hits = ci.search(body.query, body.top_k, body.lang)
        return {"hits": hits}
    except Exception as e:
        return {"error": str(e), "hits": []}


@app.get("/api/graph")
def api_graph() -> dict[str, Any]:
    """Build a rich force-graph payload from vault: nodes colored by source,
    sized by msg_count, plus implicit clustering by source."""
    if not VAULT_DIR.exists():
        return {"nodes": [], "edges": [], "stats": {"notes": 0, "links": 0}}

    nodes: dict[str, dict] = {}
    edges = []
    source_centers: dict[str, str] = {}   # source → synthetic hub node id

    for p in VAULT_DIR.rglob("*.md"):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        # Parse YAML frontmatter
        meta = {}
        m = YAML_FRONTMATTER_RE.match(text)
        if m:
            for line in m.group(1).splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()

        name = p.stem
        source = meta.get("source", "unknown")
        if source == "unknown" and "digests" in p.parts:
            source = "workflow"
        try: msg_count = int(meta.get("msg_count", 1))
        except Exception: msg_count = 1
        date = meta.get("date", "")
        project = meta.get("project", "")
        session = meta.get("session", "")

        # Smart label: extract clean topic from filename
        clean_name = re.sub(r'^\d{4}-\d{2}-\d{2}_', '', name)
        clean_name = re.sub(r'^[a-z]+_', '', clean_name)
        clean_name = re.sub(r'_\d{2}-?\d{2}(\d{2})?$', '', clean_name)
        label = (clean_name.replace('_', ' ') or name)[:60]

        nodes.setdefault(name, {
            "id":       name,
            "label":    label,
            "source":   source,
            "msgs":     msg_count,
            "size":     max(3, min(20, msg_count // 5 + 3)),
            "date":     date,
            "path":     str(p),
            "rel":      str(p.relative_to(VAULT_DIR)),
        })

        # Implicit clustering: each source gets a hub node, all notes link to hub
        hub_id = f"__hub__{source}"
        if source not in source_centers:
            source_centers[source] = hub_id
            nodes[hub_id] = {
                "id": hub_id, "label": source.upper(),
                "source": source, "msgs": 0, "size": 24,
                "is_hub": True,
            }
        edges.append({"source": name, "target": hub_id, "is_cluster": True})
        # Bump hub size
        nodes[hub_id]["size"] = min(40, nodes[hub_id]["size"] + 0.3)

        # Explicit wiki-links
        for m in WIKILINK_RE.finditer(text):
            tgt = m.group(1).strip()
            if not tgt: continue
            nodes.setdefault(tgt, {
                "id": tgt, "label": tgt[:40],
                "source": "link", "msgs": 0, "size": 4,
            })
            edges.append({"source": name, "target": tgt})

    # Source breakdown for legend
    src_counts = {}
    for n in nodes.values():
        if n.get("is_hub"): continue
        s = n.get("source", "unknown")
        src_counts[s] = src_counts.get(s, 0) + 1

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "stats": {
            "notes":  sum(1 for n in nodes.values() if not n.get("is_hub")),
            "hubs":   len(source_centers),
            "links":  len(edges),
            "sources": src_counts,
        },
    }


# ---------------------------------------------------------------------------
# Library (PDFs)
# ---------------------------------------------------------------------------
@app.get("/api/library")
def api_library() -> dict[str, Any]:
    return library_status()


@app.post("/api/library/open")
def api_library_open() -> dict[str, Any]:
    return _open_folder(LIBRARY_DIR)


@app.post("/api/transcripts/inbox/open")
def api_transcripts_inbox_open() -> dict[str, Any]:
    inbox = ROOT / "data" / "brain-raw" / "inbox"
    return _open_folder(inbox)


# ---- Drag-drop upload ----
import re as _re_safe

def _safe_filename(name: str) -> str:
    """Strip dangerous chars from uploaded filename, keep extension."""
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = _re_safe.sub(r'[<>:"|?*\x00-\x1f]', "_", name)
    return name[:200] or "uploaded.bin"


async def _save_upload(file: UploadFile, dest_dir: Path, max_mb: int = 500) -> dict:
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = _safe_filename(file.filename or "uploaded.bin")
    dest = dest_dir / name
    size = 0
    with open(dest, "wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk: break
            size += len(chunk)
            if size > max_mb * 1024 * 1024:
                out.close(); dest.unlink(missing_ok=True)
                raise HTTPException(413, f"file too large (max {max_mb} MB)")
            out.write(chunk)
    return {"ok": True, "name": name, "size_mb": round(size / 1024**2, 2),
            "path": str(dest)}


@app.post("/api/library/upload")
async def api_library_upload(file: UploadFile = File(...)) -> dict[str, Any]:
    """Drag-drop endpoint for LIBRARY (books/PDFs)."""
    return await _save_upload(file, LIBRARY_DIR, max_mb=500)


@app.post("/api/transcripts/inbox/upload")
async def api_inbox_upload(file: UploadFile = File(...)) -> dict[str, Any]:
    """Drag-drop endpoint for INBOX (chat exports)."""
    inbox = ROOT / "data" / "brain-raw" / "inbox"
    return await _save_upload(file, inbox, max_mb=500)


# --- RAG / reindex ---
RAG_SCRIPT = ROOT / "pipeline" / "rag.py"
RAG_STATUS = ROOT / "data" / "rag-status.json"
_rag_proc: subprocess.Popen | None = None


@app.get("/api/library/status")
def api_library_rag_status() -> dict[str, Any]:
    global _rag_proc
    running = _rag_proc is not None and _rag_proc.poll() is None
    s = {}
    if RAG_STATUS.exists():
        try: s = json.loads(RAG_STATUS.read_text(encoding="utf-8-sig"))
        except Exception: pass
    s["proc_running"] = running
    # Add live chunk count from DB (matches what rag.py status command returns)
    try:
        import sqlite3, sqlite_vec
        idb = ROOT / "data" / "vectordb" / "library.db"
        if idb.exists():
            db = sqlite3.connect(str(idb))
            try:
                db.enable_load_extension(True)
                sqlite_vec.load(db)
                db.enable_load_extension(False)
                s["index_chunks"] = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
                s["index_pdfs"]   = db.execute("SELECT COUNT(DISTINCT pdf_path) FROM chunks").fetchone()[0]
            finally:
                db.close()
        else:
            s["index_chunks"] = 0
            s["index_pdfs"]   = 0
    except Exception:
        # Fall back to status file's counter
        s["index_chunks"] = s.get("indexed_chunks", 0)
        s["index_pdfs"]   = s.get("done_pdfs", 0)
    return s


@app.post("/api/library/reindex")
def api_library_reindex() -> dict[str, Any]:
    global _rag_proc
    if _rag_proc and _rag_proc.poll() is None:
        return {"ok": False, "error": "indexing already running", "pid": _rag_proc.pid}
    args = [sys.executable, str(RAG_SCRIPT), "index"]
    log_path = LOGS_DIR / "rag.log"
    log_file = open(log_path, "ab")
    env = os.environ.copy()
    env["OLLAMA_HOST"] = f"127.0.0.1:{CONFIG.get('ollama_port', 11434)}"
    kwargs = {"stdout": log_file, "stderr": log_file, "env": env}
    if os.name == "nt": kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    _rag_proc = subprocess.Popen(args, **kwargs)
    _rag_proc._brain_t0 = time.time()
    return {"ok": True, "pid": _rag_proc.pid, "log": str(log_path)}


@app.post("/api/library/reindex/stop")
def api_library_reindex_stop() -> dict[str, Any]:
    """Stop running library reindex."""
    global _rag_proc
    if not _rag_proc or _rag_proc.poll() is not None:
        return {"ok": False, "error": "no reindex running"}
    try:
        _rag_proc.terminate()
        try: _rag_proc.wait(timeout=3)
        except subprocess.TimeoutExpired: _rag_proc.kill()
        pid = _rag_proc.pid
        _rag_proc = None
        return {"ok": True, "killed_pid": pid}
    except Exception as e:
        return {"ok": False, "error": str(e)}


class RagSearchRequest(BaseModel):
    query: str
    top_k: int = 5
    source: str = "all"   # all | vault | library


@app.post("/api/library/search")
def api_library_search(body: RagSearchRequest) -> dict[str, Any]:
    """Direct HTTP search (alternative to MCP). Useful for testing."""
    sys.path.insert(0, str(ROOT / "pipeline"))
    try:
        import importlib
        if "rag" in sys.modules: importlib.reload(sys.modules["rag"])
        else: import rag
        from rag import search
        try:
            src = body.source if body.source in ("all", "vault", "library") else "all"
            hits = search(body.query, max(1, min(20, body.top_k)), source=src)
            return {"ok": True, "hits": hits, "count": len(hits), "source": src}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"import failed: {e}"}


# ---------------------------------------------------------------------------
# MCP servers
# ---------------------------------------------------------------------------
class MCPServer(BaseModel):
    id: str
    title: str | None = None
    command: str
    args: list[str] = []
    env: dict[str, str] = {}
    cwd: str | None = None
    enabled: bool = True
    note: str | None = None


@app.get("/api/mcp/list")
def api_mcp_list() -> dict[str, Any]:
    return {"servers": _mcp.list(), "config_path": str(MCP_CONFIG)}


@app.post("/api/mcp/save")
def api_mcp_save(server: MCPServer) -> dict[str, Any]:
    _mcp.upsert(server.dict())
    return {"ok": True, "servers": _mcp.list()}


@app.post("/api/mcp/delete/{sid}")
def api_mcp_delete(sid: str) -> dict[str, Any]:
    _mcp.delete(sid)
    return {"ok": True, "servers": _mcp.list()}


@app.post("/api/mcp/start/{sid}")
def api_mcp_start(sid: str) -> dict[str, Any]:
    try:
        r = _mcp.start(sid)
        return {"ok": True, "result": r, "servers": _mcp.list()}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/mcp/stop/{sid}")
def api_mcp_stop(sid: str) -> dict[str, Any]:
    return {"ok": True, "result": _mcp.stop(sid), "servers": _mcp.list()}


@app.get("/api/mcp/logs/{sid}")
def api_mcp_logs(sid: str, lines: int = 200) -> dict[str, Any]:
    return {"sid": sid, "log": _mcp.tail_log(sid, lines)}


# ---------------------------------------------------------------------------
# Transcripts / distillation
# ---------------------------------------------------------------------------
import threading as _threading

_sources_cache: dict[str, Any] = {"data": None, "ts": 0.0, "error": None}
_sources_lock = _threading.Lock()

def _refresh_sources_loop():
    """Background daemon that polls list_sources() once per 60s and updates
    the cache. Was previously: subprocess spawn PER REQUEST (~12s each), with
    a frontend polling /api/transcripts/sources several times per second from
    multiple components → constant CPU burn. Now the endpoint never blocks."""
    sys.path.insert(0, str(ROOT / "pipeline"))
    while True:
        try:
            import importlib
            if "distill" in sys.modules:
                distill = sys.modules["distill"]
            else:
                distill = importlib.import_module("distill")
            data = distill.list_sources()
            with _sources_lock:
                _sources_cache["data"]  = {"sources": data}
                _sources_cache["ts"]    = time.time()
                _sources_cache["error"] = None
        except Exception as e:
            with _sources_lock:
                _sources_cache["error"] = str(e)
        time.sleep(60)

# Start background refresher
_threading.Thread(target=_refresh_sources_loop, daemon=True).start()


# ---------------------------------------------------------------------------
# Adaptive Scheduler — runs background tasks when system is idle / at night
# ---------------------------------------------------------------------------
def _scheduler_loop():
    """Tick the scheduler every 60s. Sleeps 8s first so dashboard finishes init.
    Module is loaded ONCE — reloading would reset _global_pause, _run_lock,
    and the worker would never see STOP signals."""
    time.sleep(8)
    sys.path.insert(0, str(ROOT / "pipeline"))
    import importlib
    if "scheduler" not in sys.modules:
        importlib.import_module("scheduler")
    scheduler = sys.modules["scheduler"]
    while True:
        try:
            scheduler.tick()
        except Exception as e:
            print(f"[scheduler] tick error: {e}", flush=True)
        time.sleep(60)


_threading.Thread(target=_scheduler_loop, daemon=True).start()


# Self-aware advisor — periodically scans brain state for suggested actions
def _self_aware_loop():
    time.sleep(30)
    sys.path.insert(0, str(ROOT / "pipeline"))
    import importlib
    if "scheduler" not in sys.modules:
        importlib.import_module("scheduler")
    sched = sys.modules["scheduler"]
    while True:
        try:
            sched.self_aware_check()
        except Exception as e:
            print(f"[self-aware] {e}", flush=True)
        time.sleep(300)  # 5 min


_threading.Thread(target=_self_aware_loop, daemon=True).start()


# ---------------------------------------------------------------------------
# Tray-parent watchdog — dashboard self-shutdown if tray dies
# ---------------------------------------------------------------------------
def _tray_watchdog_loop():
    """If we were spawned by tray.py (BRAIN_TRAY_PARENT env set), check the
    tray heartbeat file. If it disappears OR goes stale >20s, the tray died.
    Self-shutdown so we don't run orphaned.

    Detection time: ~5-15s after tray quit/crash.
    Runs only when BRAIN_TRAY_PARENT is set (standalone mode = never)."""
    if not os.environ.get("BRAIN_TRAY_PARENT"):
        return
    hb = ROOT / "data" / "tray.heartbeat"
    time.sleep(15)  # grace period — let tray write its first heartbeat
    misses = 0
    while True:
        try:
            if not hb.exists():
                # Tray explicitly deleted it (quit_brain) — immediate shutdown
                misses = 99
            else:
                age = time.time() - hb.stat().st_mtime
                misses = misses + 1 if age > 20 else 0
        except Exception:
            misses += 1
        if misses >= 2:
            print("[tray-watchdog] tray heartbeat lost — killing Ollama + self.",
                  flush=True)
            # Take Ollama down too — we own the whole brain lifecycle now
            try:
                subprocess.run(["taskkill", "/F", "/IM", "ollama.exe"],
                               capture_output=True,
                               creationflags=subprocess.CREATE_NO_WINDOW
                               if hasattr(subprocess, "CREATE_NO_WINDOW") else 0)
            except Exception:
                pass
            try:
                import signal as _sig
                os.kill(os.getpid(), _sig.SIGTERM)
            except Exception:
                os._exit(0)
            return
        time.sleep(5)


_threading.Thread(target=_tray_watchdog_loop, daemon=True).start()


# ---------------------------------------------------------------------------
# Vault sessions watcher — detect new save_conversation calls
# ---------------------------------------------------------------------------
_sessions_watcher: dict[str, Any] = {
    "ts": 0.0,           # last scan time
    "seen": set(),       # filenames already noticed
    "recent_notifs": [], # list of {name, source, ts, age_sec} max 20
}

def _sessions_watcher_loop():
    """Every 10s scan vault/sessions/ for new files. New file → notification
    pushed to /api/notifications. Lightweight — just stat() on dir + set diff."""
    time.sleep(12)
    sessions_dir = ROOT / "data" / "vault" / "sessions"
    # Seed with existing files (so we don't fire on startup)
    if sessions_dir.exists():
        _sessions_watcher["seen"] = {p.name for p in sessions_dir.glob("*.md")}
    while True:
        try:
            if sessions_dir.exists():
                current = {p.name for p in sessions_dir.glob("*.md")}
                new_files = current - _sessions_watcher["seen"]
                for name in new_files:
                    # Parse source from filename: <date>_<source>_<topic>_<time>.md
                    parts = name.split("_", 2)
                    source = parts[1] if len(parts) >= 2 else "unknown"
                    entry = {
                        "name":   name,
                        "source": source,
                        "ts":     time.time(),
                        "age_sec": 0,
                    }
                    _sessions_watcher["recent_notifs"].insert(0, entry)
                    _sessions_watcher["recent_notifs"] = _sessions_watcher["recent_notifs"][:20]
                    print(f"[sessions-watcher] NEW: {name} (source={source})", flush=True)
                _sessions_watcher["seen"] = current
        except Exception as e:
            print(f"[sessions-watcher] error: {e}", flush=True)
        time.sleep(10)


_threading.Thread(target=_sessions_watcher_loop, daemon=True).start()


@app.get("/api/jobs/active")
def api_jobs_active() -> dict[str, Any]:
    """Unified view of every long-running task brain knows about.
    Each item has: id, label, kind, started_at, stop_url."""
    global _distill_proc, _code_proc, _rag_proc
    jobs = []

    # 1. Distillation — check both: our subprocess handle + status file
    # (latter catches external distill runs like `python distill.py distill ...`)
    if _distill_proc and _distill_proc.poll() is None:
        jobs.append({
            "id":         "distill",
            "kind":       "subprocess",
            "label":      "Transcript distillation",
            "pid":        _distill_proc.pid,
            "started_at": getattr(_distill_proc, "_brain_t0", None),
            "stop_url":   "/api/transcripts/stop",
            "stop_method": "POST",
        })
        
    global _redistill_proc
    if _redistill_proc and _redistill_proc.poll() is None:
        # Read progress from redistill-status.json so jobs panel shows real status
        prog = {}
        last_err = ""
        try:
            sf = ROOT / "data" / "redistill-status.json"
            if sf.exists():
                st = json.loads(sf.read_text(encoding="utf-8-sig"))
                done  = st.get("done", 0)
                total = st.get("total", 0)
                prog = {"done": done, "total": total,
                        "label": st.get("last_file", "")[:60],
                        "errors": st.get("errors", 0)}
                last_err = (st.get("last_err") or st.get("error") or "")[:200]
        except Exception:
            pass
        label = "Vault redistillation"
        if prog.get("total"):
            err_part = f" · {prog['errors']} err" if prog.get("errors") else ""
            label = f"Vault redistill {prog['done']}/{prog['total']}{err_part}"
        jobs.append({
            "id":         "redistill",
            "kind":       "subprocess",
            "label":      label,
            "pid":        _redistill_proc.pid,
            "started_at": getattr(_redistill_proc, "_brain_t0", None),
            "progress":   prog,
            "warning":    last_err,
            "stop_url":   "/api/vault/redistill/stop",
            "stop_method": "POST",
        })
    else:
        # Read status file — could be running as separate CLI process
        try:
            status_f = ROOT / "data" / "distill-status.json"
            if status_f.exists():
                st = json.loads(status_f.read_text(encoding="utf-8"))
                if st.get("state") == "distilling":
                    done  = st.get("done", 0)
                    total = st.get("total", 0)
                    pct = f"{done}/{total}" if total else f"{done}"
                    jobs.append({
                        "id":         "distill_external",
                        "kind":       "distill",
                        "label":      f"Distill (CLI): {pct} · {st.get('model','?')}",
                        "started_at": st.get("started_at"),
                        "progress":   {"done": done, "total": total,
                                       "label": st.get("current", "")},
                        "stop_url":   "/api/transcripts/stop",
                        "stop_method": "POST",
                    })
        except Exception:
            pass

    # 2. Library reindex
    if _rag_proc and _rag_proc.poll() is None:
        prog = {}
        try:
            sf = RAG_STATUS
            if sf.exists():
                st = json.loads(sf.read_text(encoding="utf-8-sig"))
                done  = st.get("done_pdfs", 0)
                total = st.get("total_pdfs", 0)
                prog = {"done": done, "total": total,
                        "label": st.get("current", "")[:60]}
        except Exception:
            pass
        label = "Library reindex (RAG)"
        if prog.get("total"):
            label = f"Library reindex {prog['done']}/{prog['total']}"
        jobs.append({
            "id":         "library_reindex",
            "kind":       "subprocess",
            "label":      label,
            "pid":        _rag_proc.pid,
            "started_at": getattr(_rag_proc, "_brain_t0", None),
            "progress":   prog,
            "stop_url":   "/api/library/reindex/stop",
            "stop_method": "POST",
        })

    # 3. Code index scan
    if _code_proc and _code_proc.poll() is None:
        prog = {}
        try:
            sf = ROOT / "data" / "code-status.json"
            if sf.exists():
                st = json.loads(sf.read_text(encoding="utf-8-sig"))
                done  = st.get("files_done", 0)
                total = st.get("files_total", 0)
                prog = {"done": done, "total": total,
                        "label": st.get("current", "")[:60]}
        except Exception:
            pass
        label = "Code index scan"
        if prog.get("total"):
            label = f"Code scan {prog['done']}/{prog['total']}"
        jobs.append({
            "id":         "code_scan",
            "kind":       "subprocess",
            "label":      label,
            "pid":        _code_proc.pid,
            "started_at": getattr(_code_proc, "_brain_t0", None),
            "progress":   prog,
            "stop_url":   "/api/code/stop",
            "stop_method": "POST",
        })

    # 4. Skill running (inline)
    try:
        sys.path.insert(0, str(ROOT / "pipeline"))
        import importlib
        if "skills" in sys.modules:
            cur = sys.modules["skills"].current_skill_status()
            if cur.get("name"):
                jobs.append({
                    "id":         f"skill:{cur['name']}",
                    "kind":       "skill",
                    "label":      f"Skill: {cur['name']}",
                    "started_at": cur.get("started_at"),
                    "stop_url":   "/api/skills/stop",
                    "stop_method": "POST",
                    "stop_requested": cur.get("stop_requested", False),
                })
    except Exception:
        pass

    # 5. Scheduler task running
    try:
        sys.path.insert(0, str(ROOT / "pipeline"))
        if "scheduler" in sys.modules:
            sched_status = sys.modules["scheduler"].status()
            running = sched_status.get("currently_running")
            if running:
                jobs.append({
                    "id":         f"scheduler:{running}",
                    "kind":       "scheduler",
                    "label":      f"Scheduler: {running}",
                    "started_at": sched_status.get("currently_started"),
                    "stop_url":   "/api/schedule/stop",
                    "stop_method": "POST",
                    "stop_requested": sched_status.get("stop_requested", False),
                })
    except Exception:
        pass

    # 6. Ollama models in VRAM (treat each as a job — UNLOAD = stop)
    try:
        port = CONFIG.get("ollama_port", 11434)
        r = requests.get(f"http://127.0.0.1:{port}/api/ps", timeout=2)
        if r.ok:
            for m in r.json().get("models", []):
                size_vram_gb = round((m.get("size_vram") or 0) / 1024**3, 2)
                if size_vram_gb < 0.01:
                    continue  # skip phantom entries with 0 VRAM
                jobs.append({
                    "id":         f"ollama:{m.get('name')}",
                    "kind":       "vram",
                    "label":      f"Model w VRAM: {m.get('name')} ({size_vram_gb} GB)",
                    "stop_url":   f"/api/ollama/unload?model={m.get('name')}",
                    "stop_method": "POST",
                })
    except Exception:
        pass

    return {"jobs": jobs, "count": len(jobs), "now": time.time()}


@app.get("/api/notifications")
def api_notifications() -> dict[str, Any]:
    """Polled by frontend — returns recent vault/sessions notifications."""
    now = time.time()
    items = [
        {**e, "age_sec": int(now - e["ts"])}
        for e in _sessions_watcher.get("recent_notifs", [])
    ]
    return {"recent": items}


def _load_scheduler():
    """NOTE: do NOT importlib.reload — that would wipe scheduler's runtime state
    (_global_pause, _run_lock, _stop_event, _currently_running). Once loaded,
    keep the module instance for the dashboard's lifetime."""
    sys.path.insert(0, str(ROOT / "pipeline"))
    import importlib
    if "scheduler" in sys.modules:
        return sys.modules["scheduler"]
    return importlib.import_module("scheduler")


class ScheduleTaskRequest(BaseModel):
    task_id: str
    enabled: bool | None = None


@app.get("/api/schedule/status")
def api_schedule_status() -> dict[str, Any]:
    try:
        return _load_scheduler().status()
    except Exception as e:
        return {"error": str(e), "tasks": []}


@app.post("/api/schedule/toggle")
def api_schedule_toggle(body: ScheduleTaskRequest) -> dict[str, Any]:
    try:
        return _load_scheduler().toggle(body.task_id, body.enabled)
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/schedule/run")
def api_schedule_run(body: ScheduleTaskRequest) -> dict[str, Any]:
    try:
        return _load_scheduler().run_now(body.task_id)
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/schedule/stop")
def api_schedule_stop() -> dict[str, Any]:
    try:
        return _load_scheduler().request_stop()
    except Exception as e:
        return {"ok": False, "error": str(e)}


class PauseRequest(BaseModel):
    seconds: int = 3600  # default 1h


@app.post("/api/schedule/pause-all")
def api_schedule_pause_all(body: PauseRequest) -> dict[str, Any]:
    """Stop the running task AND prevent any task from restarting for N seconds."""
    try:
        return _load_scheduler().pause_all(body.seconds)
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/schedule/resume")
def api_schedule_resume() -> dict[str, Any]:
    try:
        return _load_scheduler().resume_all()
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/schedule/self-aware")
def api_schedule_self_aware() -> dict[str, Any]:
    """What does brain think you should run? Pure suggestions, never auto-fires."""
    try:
        sched = _load_scheduler()
        # Refresh if older than 60s
        cached = sched.get_self_aware()
        if cached.get("age_sec", 999) > 60:
            sched.self_aware_check()
            cached = sched.get_self_aware()
        return cached
    except Exception as e:
        return {"advice": [], "error": str(e)}


@app.post("/api/schedule/clear-cooldown")
def api_schedule_clear_cooldown(body: ScheduleTaskRequest) -> dict[str, Any]:
    """Clear the STOP cooldown for a specific task — lets it run again immediately."""
    try:
        sched = _load_scheduler()
        tasks = sched.load_tasks()
        for t in tasks:
            if t["id"] == body.task_id:
                t.pop("last_stop_at", None)
        sched.save_tasks(tasks)
        return {"ok": True, "cleared": body.task_id}
    except Exception as e:
        return {"ok": False, "error": str(e)}


class ScheduleModelUpdate(BaseModel):
    task_id: str
    model: str


# ---------------------------------------------------------------------------
# Agents — auto-deploy brain MCP to Claude Desktop / Antigravity / etc
# ---------------------------------------------------------------------------
def _load_agents():
    sys.path.insert(0, str(ROOT / "pipeline"))
    import importlib
    if "agents" in sys.modules:
        return importlib.reload(sys.modules["agents"])
    return importlib.import_module("agents")


class AgentRequest(BaseModel):
    agent_id: str


@app.get("/api/agents")
def api_agents() -> dict[str, Any]:
    try:
        return {"agents": _load_agents().detect_all()}
    except Exception as e:
        return {"agents": [], "error": str(e)}


@app.post("/api/agents/deploy")
def api_agents_deploy(body: AgentRequest) -> dict[str, Any]:
    try:
        return _load_agents().deploy(body.agent_id)
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/agents/undeploy")
def api_agents_undeploy(body: AgentRequest) -> dict[str, Any]:
    try:
        return _load_agents().undeploy(body.agent_id)
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/agents/deploy-all")
def api_agents_deploy_all() -> dict[str, Any]:
    try:
        return _load_agents().deploy_all_installed()
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/agents/inject-prompt")
def api_agents_inject_prompt(body: AgentRequest) -> dict[str, Any]:
    """Inject brain MCP system-prompt block into agent's instruction file
    (Claude Code's CLAUDE.md, Cursor's .cursorrules). Makes the agent
    automatically use brain-rag.search_library before tasks and
    brain-rag.save_conversation at end."""
    try:
        return _load_agents().deploy_system_prompt(body.agent_id)
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/agents/remove-prompt")
def api_agents_remove_prompt(body: AgentRequest) -> dict[str, Any]:
    try:
        return _load_agents().undeploy_system_prompt(body.agent_id)
    except Exception as e:
        return {"ok": False, "error": str(e)}
@app.post("/api/schedule/set_model")
def api_schedule_set_model(body: ScheduleModelUpdate) -> dict[str, Any]:
    """Update per-task model selection (saved in schedule-config.json)."""
    try:
        sched = _load_scheduler()
        tasks = sched.load_tasks()
        updated = False
        for t in tasks:
            if t["id"] == body.task_id:
                t.setdefault("action_args", {})["model"] = body.model
                updated = True
        if updated:
            sched.save_tasks(tasks)
            return {"ok": True, "task_id": body.task_id, "model": body.model}
        return {"ok": False, "error": "task not found"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/transcripts/sources")
def api_transcripts_sources() -> dict[str, Any]:
    """Non-blocking — returns cached value (refreshed every 60s by background
    daemon). First request after startup may return empty until daemon
    completes its first poll (~12s)."""
    with _sources_lock:
        if _sources_cache["data"] is not None:
            return _sources_cache["data"]
        if _sources_cache["error"]:
            return {"sources": {}, "error": _sources_cache["error"], "warming": True}
    return {"sources": {}, "warming": True}


@app.get("/api/transcripts/status")
def api_transcripts_status() -> dict[str, Any]:
    return distill_status()


class DistillRun(BaseModel):
    mode: str = "run"          # collect | distill | run
    model: str = "qwen2.5:14b"
    limit: int | None = None


@app.post("/api/transcripts/run")
def api_transcripts_run(body: DistillRun) -> dict[str, Any]:
    sched = _load_scheduler()
    if sched._run_lock.locked():
        return {"ok": False, "error": "Scheduler is currently running a background task. Please pause AUTO SCHEDULE first to run large batches manually."}
        
    global _distill_proc
    if _distill_proc and _distill_proc.poll() is None:
        return {"ok": False, "error": "already running",
                "pid": _distill_proc.pid}
    if body.mode not in ("collect", "distill", "run"):
        raise HTTPException(400, "mode must be: collect | distill | run")
    args = [_python_exe(), str(DISTILL_SCRIPT), body.mode]
    if body.mode in ("distill", "run"):
        args += ["--model", body.model]
        if body.limit: args += ["--limit", str(body.limit)]
        args += ["--only-missing"]
    log_path = LOGS_DIR / "distill.log"
    log_file = open(log_path, "ab")
    env = os.environ.copy()
    env["OLLAMA_HOST"] = f"127.0.0.1:{CONFIG.get('ollama_port',11434)}"
    kwargs = {"stdout": log_file, "stderr": log_file, "env": env}
    if os.name == "nt": kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    _distill_proc = subprocess.Popen(args, **kwargs)
    return {"ok": True, "pid": _distill_proc.pid, "log": str(log_path),
            "cmd": " ".join(args)}


@app.post("/api/transcripts/stop")
def api_transcripts_stop() -> dict[str, Any]:
    """Stop distillation. Handles both in-memory handle AND stray processes."""
    global _distill_proc
    killed = []
    # 1) Kill in-memory handle
    if _distill_proc and _distill_proc.poll() is None:
        try:
            _distill_proc.terminate()
            try: _distill_proc.wait(timeout=3)
            except subprocess.TimeoutExpired: _distill_proc.kill()
            killed.append(_distill_proc.pid)
        except Exception: pass
    # 2) Kill any other distill.py processes (orphans from previous dashboard restarts)
    try:
        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cmd = p.info.get("cmdline") or []
                if any("distill.py" in str(c) for c in cmd):
                    if p.info["pid"] not in killed:
                        p.terminate()
                        killed.append(p.info["pid"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception: pass

    _distill_proc = None
    # Force-update status to idle
    if DISTILL_STATUS.exists():
        try:
            s = json.loads(DISTILL_STATUS.read_text(encoding="utf-8-sig"))
            s["state"] = "idle"
            s["stopped_at"] = time.time()
            DISTILL_STATUS.write_text(json.dumps(s, indent=2), encoding="utf-8")
        except Exception: pass

    return {"ok": True, "stopped": bool(killed), "killed_pids": killed}


def _python_exe() -> str:
    return sys.executable


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------
BACKUP_EXCLUDE_DIRS = {"bin", "ollama-models", "brain-raw", "vectordb",
                       "logs", "__pycache__", ".git", "venv", "backups", "node_modules"}
BACKUP_EXCLUDE_FILES = {"api-keys.json", "api-usage.json"}  # secrets — opt-in

class BackupRequest(BaseModel):
    include_keys: bool = False
    include_distilled: bool = True

@app.post("/api/backup")
def api_backup(body: BackupRequest = BackupRequest()) -> dict[str, Any]:
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"brain-{ts}.zip"
    out = BACKUPS_DIR / name
    excluded_files = set() if body.include_keys else set(BACKUP_EXCLUDE_FILES)
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in ROOT.rglob("*"):
            if p.is_dir(): continue
            try: rel = p.relative_to(ROOT)
            except ValueError: continue
            if any(part in BACKUP_EXCLUDE_DIRS for part in rel.parts): continue
            if rel.name in excluded_files: continue
            if not body.include_distilled and "distilled" in rel.parts: continue
            try:
                zf.write(p, rel); count += 1
            except (OSError, PermissionError):
                pass
    size_mb = round(out.stat().st_size / 1024**2, 2)
    return {"ok": True, "name": name, "path": str(out),
            "size_mb": size_mb, "files": count,
            "download_url": f"/api/backup/download/{name}",
            "warning": "INCLUDES API KEYS - guard this file" if body.include_keys else None}

@app.get("/api/backup/list")
def api_backup_list() -> dict[str, Any]:
    if not BACKUPS_DIR.exists(): return {"backups": []}
    out = []
    for f in sorted(BACKUPS_DIR.glob("*.zip"), key=lambda p: -p.stat().st_mtime):
        s = f.stat()
        out.append({"name": f.name, "size_mb": round(s.st_size/1024**2, 2),
                    "created": s.st_mtime,
                    "download_url": f"/api/backup/download/{f.name}"})
    return {"backups": out}

@app.get("/api/backup/download/{name}")
def api_backup_download(name: str):
    safe = re.sub(r"[^a-zA-Z0-9_\-.]", "", name)
    p = BACKUPS_DIR / safe
    if not p.exists() or p.suffix != ".zip":
        raise HTTPException(404, "backup not found")
    return FileResponse(p, media_type="application/zip", filename=safe)

@app.post("/api/backup/delete/{name}")
def api_backup_delete(name: str) -> dict[str, Any]:
    safe = re.sub(r"[^a-zA-Z0-9_\-.]", "", name)
    p = BACKUPS_DIR / safe
    if p.exists(): p.unlink()
    return {"ok": True}


# ---------------------------------------------------------------------------
# API usage tracking
# ---------------------------------------------------------------------------
def _load_usage() -> dict:
    if USAGE_FILE.exists():
        try: return json.loads(USAGE_FILE.read_text(encoding="utf-8-sig"))
        except Exception: pass
    return {}

def _save_usage(d: dict) -> None:
    USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    USAGE_FILE.write_text(json.dumps(d, indent=2), encoding="utf-8")

def _track_usage(provider: str, status: int = 200, bytes_in: int = 0, bytes_out: int = 0) -> None:
    data = _load_usage()
    today = datetime.now().strftime("%Y-%m-%d")
    p = data.setdefault(provider, {"total": 0, "errors": 0, "by_day": {}, "bytes_in": 0, "bytes_out": 0})
    p["total"] = p.get("total", 0) + 1
    if status >= 400: p["errors"] = p.get("errors", 0) + 1
    p["bytes_in"]  = p.get("bytes_in", 0)  + bytes_in
    p["bytes_out"] = p.get("bytes_out", 0) + bytes_out
    day = p["by_day"].setdefault(today, {"total": 0, "errors": 0})
    day["total"] += 1
    if status >= 400: day["errors"] += 1
    p["last_at"] = time.time()
    _save_usage(data)

def _load_thresholds() -> dict:
    if THRESHOLDS_FILE.exists():
        try: return json.loads(THRESHOLDS_FILE.read_text(encoding="utf-8-sig"))
        except Exception: pass
    return {}

def _save_thresholds(d: dict) -> None:
    THRESHOLDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    THRESHOLDS_FILE.write_text(json.dumps(d, indent=2), encoding="utf-8")

def _compute_alerts() -> dict:
    """For each provider with a daily limit set, compute status."""
    usage = _load_usage()
    thresholds = _load_thresholds()
    today = datetime.now().strftime("%Y-%m-%d")
    out = {}
    for pid, t in thresholds.items():
        limit = int(t.get("daily_limit") or 0)
        if limit <= 0: continue
        u = usage.get(pid, {})
        used = (u.get("by_day", {}).get(today, {}) or {}).get("total", 0)
        pct = min(100, round(100 * used / limit, 1)) if limit else 0
        out[pid] = {
            "limit": limit, "used": used, "pct": pct,
            "over": used >= limit,
            "warning": (used / limit) >= 0.8 if limit else False,
        }
    return out

@app.get("/api/usage")
def api_usage() -> dict[str, Any]:
    return {"usage": _load_usage(), "thresholds": _load_thresholds(),
            "alerts": _compute_alerts(),
            "today": datetime.now().strftime("%Y-%m-%d")}

@app.post("/api/usage/reset")
def api_usage_reset(provider: str | None = None) -> dict[str, Any]:
    data = _load_usage()
    if provider:
        data.pop(provider, None)
    else:
        data = {}
    _save_usage(data)
    return {"ok": True}


class ThresholdUpdate(BaseModel):
    daily_limit: int | None = None  # 0 or None = disabled


@app.post("/api/usage/threshold/{provider}")
def api_threshold_set(provider: str, body: ThresholdUpdate) -> dict[str, Any]:
    if provider not in PROVIDER_BASE:
        raise HTTPException(404, f"unknown provider: {provider}")
    data = _load_thresholds()
    if not body.daily_limit or body.daily_limit <= 0:
        data.pop(provider, None)
    else:
        data[provider] = {"daily_limit": int(body.daily_limit)}
    _save_thresholds(data)
    return {"ok": True, "thresholds": _load_thresholds()}


# ---------------------------------------------------------------------------
# Local API proxy
# ---------------------------------------------------------------------------
def _resolve_key(provider: str) -> str | None:
    if provider not in PROVIDERS: return None
    for n in PROVIDERS[provider]["envs"]:
        v = os.environ.get(n)
        if v: return v
    return _load_keys().get(provider, {}).get("key")

HOP_BY_HOP = {"connection","keep-alive","proxy-authenticate","proxy-authorization",
              "te","trailers","transfer-encoding","upgrade","content-encoding"}

@app.api_route("/proxy/{provider}/{rest:path}",
               methods=["GET","POST","PUT","DELETE","PATCH","OPTIONS"])
async def proxy(provider: str, rest: str, request: Request):
    if provider not in PROVIDER_BASE:
        raise HTTPException(404, f"unknown provider: {provider}")
    key = _resolve_key(provider)
    if not key:
        raise HTTPException(401, f"no key configured for {provider} — set in OPTIONS or env var")

    _bump_activity()
    base = PROVIDER_BASE[provider]
    url = f"{base}/{rest}"

    drop = HOP_BY_HOP | {"host", "authorization", "x-api-key", "content-length"}
    fwd_headers = {k: v for k, v in request.headers.items() if k.lower() not in drop}

    params = dict(request.query_params)
    if provider == "anthropic":
        fwd_headers["x-api-key"] = key
        fwd_headers.setdefault("anthropic-version", "2023-06-01")
    elif provider == "google":
        params["key"] = key
    else:
        fwd_headers["Authorization"] = f"Bearer {key}"

    body = await request.body()

    try:
        client = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=15.0))
        upstream = await client.send(
            client.build_request(request.method, url,
                                 headers=fwd_headers, params=params, content=body),
            stream=True,
        )

        _track_usage(provider, upstream.status_code, len(body or b""), 0)

        async def gen():
            try:
                async for chunk in upstream.aiter_bytes():
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()

        resp_headers = {k: v for k, v in upstream.headers.items()
                        if k.lower() not in HOP_BY_HOP}
        return StreamingResponse(gen(), status_code=upstream.status_code, headers=resp_headers)
    except httpx.RequestError as e:
        _track_usage(provider, 599, len(body or b""), 0)
        raise HTTPException(502, f"upstream error: {e}")


# ---------------------------------------------------------------------------
# Ollama VRAM control + idle watcher
# ---------------------------------------------------------------------------
IDLE_CONFIG_FILE = ROOT / "data" / "idle-config.json"
_last_activity = time.time()  # bumped by chat/proxy calls
_idle_thread_stop = threading.Event()


def _load_idle_config() -> dict:
    if IDLE_CONFIG_FILE.exists():
        try: return json.loads(IDLE_CONFIG_FILE.read_text(encoding="utf-8-sig"))
        except Exception: pass
    return {"auto_unload_enabled": False, "idle_minutes": 10}


def _save_idle_config(d: dict) -> None:
    IDLE_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    IDLE_CONFIG_FILE.write_text(json.dumps(d, indent=2), encoding="utf-8")


def _bump_activity() -> None:
    global _last_activity
    _last_activity = time.time()


def _unload_all_models() -> dict[str, Any]:
    """Force Ollama to evict all loaded models from VRAM via keep_alive:0."""
    port = CONFIG.get("ollama_port", 11434)
    url = f"http://127.0.0.1:{port}"
    try:
        ps = requests.get(f"{url}/api/ps", timeout=2).json().get("models", [])
    except Exception as e:
        return {"ok": False, "error": str(e), "unloaded": []}
    unloaded = []
    for m in ps:
        name = m.get("name")
        if not name: continue
        try:
            requests.post(f"{url}/api/generate",
                          json={"model": name, "prompt": "", "keep_alive": 0},
                          timeout=10)
            unloaded.append(name)
        except Exception:
            pass
    return {"ok": True, "unloaded": unloaded, "count": len(unloaded)}


def _idle_watcher_loop():
    """Background thread: every 30s, check idle config + auto-reindex library."""
    global _rag_proc
    last_unload = 0
    last_reindex_check = 0
    while not _idle_thread_stop.is_set():
        # --- Auto-unload models from VRAM after idle ---
        # SKIP unload if distillation or reindex is actively running (they use Ollama)
        try:
            cfg = _load_idle_config()
            busy = _is_distill_running() or (_rag_proc is not None and _rag_proc.poll() is None)
            if cfg.get("auto_unload_enabled") and not busy:
                idle_min = max(1, int(cfg.get("idle_minutes", 10)))
                idle_sec = time.time() - _last_activity
                if idle_sec >= idle_min * 60 and (time.time() - last_unload > 120):
                    try:
                        port = CONFIG.get("ollama_port", 11434)
                        ps = requests.get(f"http://127.0.0.1:{port}/api/ps", timeout=2).json().get("models", [])
                        if ps:
                            _unload_all_models()
                            last_unload = time.time()
                    except Exception:
                        pass
        except Exception:
            pass

        # --- Auto-reindex library when new files appear (debounced) ---
        try:
            already_running = _rag_proc is not None and _rag_proc.poll() is None
            if not already_running and (time.time() - last_reindex_check > 30):
                lib = library_status()
                if lib.get("needs_reindex"):
                    # Fire reindex via the same path as the manual button
                    api_library_reindex()
                    last_reindex_check = time.time()
                    print(f"[auto-reindex] triggered: {lib.get('files_count')} files, latest_mtime > last_indexed",
                          flush=True)
        except Exception as e:
            pass

        _idle_thread_stop.wait(30)


# Start the watcher
_idle_thread = threading.Thread(target=_idle_watcher_loop, daemon=True)
_idle_thread.start()


def _prewarm_embed_model():
    """Pre-load nomic-embed-text into VRAM so the first MCP search_library call
    from Claude Desktop doesn't have to wait 20-40s for cold model load.
    Runs in background thread on dashboard startup."""
    time.sleep(8)  # let Ollama settle after dashboard start
    try:
        port = CONFIG.get("ollama_port", 11434)
        # Check if embed model exists locally first
        tags = requests.get(f"http://127.0.0.1:{port}/api/tags", timeout=3).json()
        names = [m.get("name", "") for m in tags.get("models", [])]
        embed = next((n for n in names if "embed" in n.lower()), None)
        if not embed: return
        # Trigger load by embedding empty string (keep_alive 30m so it stays warm)
        requests.post(
            f"http://127.0.0.1:{port}/api/embed",
            json={"model": embed, "input": "warmup", "keep_alive": "30m"},
            timeout=120,
        )
        print(f"[prewarm] embed model {embed} loaded into VRAM", flush=True)
    except Exception as e:
        print(f"[prewarm] failed: {e}", flush=True)


threading.Thread(target=_prewarm_embed_model, daemon=True).start()


@app.get("/api/ollama/loaded")
def api_ollama_loaded() -> dict[str, Any]:
    """What's currently sitting in VRAM."""
    port = CONFIG.get("ollama_port", 11434)
    try:
        r = requests.get(f"http://127.0.0.1:{port}/api/ps", timeout=2)
        if r.ok:
            return {"ok": True, "loaded": r.json().get("models", [])}
    except Exception as e:
        return {"ok": False, "error": str(e), "loaded": []}
    return {"ok": False, "loaded": []}


@app.post("/api/ollama/unload")
def api_ollama_unload(model: str | None = None) -> dict[str, Any]:
    """Unload model (or all if name omitted) from VRAM."""
    port = CONFIG.get("ollama_port", 11434)
    url = f"http://127.0.0.1:{port}"
    if model:
        try:
            r = requests.post(f"{url}/api/generate",
                              json={"model": model, "prompt": "", "keep_alive": 0},
                              timeout=10)
            return {"ok": r.ok, "unloaded": [model]}
        except Exception as e:
            return {"ok": False, "error": str(e), "unloaded": []}
    return _unload_all_models()


@app.post("/api/panic")
def api_panic() -> dict[str, Any]:
    """🚨 STOP-ALL: kills every brain-managed background process AND unloads GPU.
    Use when you need full GPU/CPU instantly for something else.

    What it stops:
      - Scheduler (pauses 1h to prevent auto-restart)
      - distill subprocess + redistill subprocess + RAG reindex subprocess
      - codeindex subprocess + skill subprocess
      - Ollama models in VRAM (keep_alive=0 forces unload)
    """
    stopped: list[str] = []
    errors:  list[str] = []

    # 1) Pause scheduler 1h — this also signals stop to any running task
    try:
        sched = _load_scheduler()
        sched.pause_all(seconds=3600)
        stopped.append("scheduler (paused 1h)")
    except Exception as e:
        errors.append(f"scheduler: {e}")

    # 2) Kill known long-running subprocesses we track
    procs = [
        ("_distill_proc",   "distill"),
        ("_rag_proc",       "library reindex"),
        ("_code_proc",      "code index"),
        ("_skill_proc",     "skill"),
    ]
    g = globals()
    for var, label in procs:
        p = g.get(var)
        try:
            if p and hasattr(p, "poll") and p.poll() is None:
                p.terminate()
                try: p.wait(timeout=2)
                except subprocess.TimeoutExpired: p.kill()
                stopped.append(f"{label} (PID {p.pid})")
                g[var] = None
        except Exception as e:
            errors.append(f"{label}: {e}")

    # 3) Best-effort kill any orphan python.exe running brain pipeline scripts
    if os.name == "nt":
        for script in ("distill.py", "redistill.py", "rag.py", "codeindex.py",
                        "note_quality.py"):
            try:
                # WMIC-style: filter by command-line contains <script>
                ps = (f'Get-CimInstance Win32_Process | Where-Object '
                      f'{{ $_.CommandLine -like "*{script}*" -and '
                      f'   $_.ProcessId -ne {os.getpid()} }} | '
                      f'ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force; $_.ProcessId }}')
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps],
                    capture_output=True, text=True, timeout=8,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                killed = [l.strip() for l in (r.stdout or "").splitlines() if l.strip().isdigit()]
                if killed:
                    stopped.append(f"orphan {script} ({len(killed)} pids)")
            except Exception as e:
                errors.append(f"orphan {script}: {e}")

    # 4) Unload ALL Ollama models from VRAM
    try:
        u = _unload_all_models()
        if u.get("unloaded"):
            stopped.append(f"ollama models ({len(u['unloaded'])} unloaded)")
    except Exception as e:
        errors.append(f"ollama unload: {e}")

    return {"ok": True, "stopped": stopped, "errors": errors,
            "msg": f"Zatrzymano {len(stopped)} elementów. GPU wolne."}


@app.get("/api/idle/config")
def api_idle_get() -> dict[str, Any]:
    cfg = _load_idle_config()
    cfg["last_activity_at"] = _last_activity
    cfg["idle_sec"] = int(time.time() - _last_activity)
    return cfg


class IdleConfigUpdate(BaseModel):
    auto_unload_enabled: bool
    idle_minutes: int = 10


@app.post("/api/idle/config")
def api_idle_set(body: IdleConfigUpdate) -> dict[str, Any]:
    cfg = {"auto_unload_enabled": bool(body.auto_unload_enabled),
           "idle_minutes": max(1, int(body.idle_minutes))}
    _save_idle_config(cfg)
    return cfg


# ---------------------------------------------------------------------------
# CONNECTIVITY — Ollama URL + SMB mount
# ---------------------------------------------------------------------------
OPTIONS_FILE = ROOT / "data" / "options.json"


def _load_options() -> dict:
    if OPTIONS_FILE.exists():
        try: return json.loads(OPTIONS_FILE.read_text(encoding="utf-8"))
        except Exception: pass
    return {}


def _save_options(d: dict) -> None:
    OPTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = OPTIONS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(OPTIONS_FILE)


def _dpapi_protect(plain: str) -> str:
    """Windows DPAPI per-user encryption. Returns base64 ciphertext."""
    if not plain: return ""
    try:
        import win32crypt, base64
        blob = win32crypt.CryptProtectData(plain.encode("utf-8"), None, None, None, None, 0)
        return base64.b64encode(blob).decode("ascii")
    except Exception:
        # Fallback: just base64 (NOT encrypted — better than plain text in logs)
        import base64
        return "B64:" + base64.b64encode(plain.encode("utf-8")).decode("ascii")


def _dpapi_unprotect(ct: str) -> str:
    if not ct: return ""
    try:
        import base64
        if ct.startswith("B64:"):
            return base64.b64decode(ct[4:]).decode("utf-8", errors="replace")
        import win32crypt
        blob = base64.b64decode(ct)
        _, plain = win32crypt.CryptUnprotectData(blob, None, None, None, 0)
        return plain.decode("utf-8", errors="replace")
    except Exception:
        return ""


@app.get("/api/options")
def api_options_get() -> dict[str, Any]:
    o = _load_options()
    # Never return the encrypted blob — just whether one is set
    smb = o.get("smb", {})
    return {
        "ollama_url":     o.get("ollama_url", "http://127.0.0.1:11434"),
        "smb_share":      smb.get("share", ""),
        "smb_letter":     smb.get("letter", "S:"),
        "smb_user":       smb.get("user", ""),
        "smb_has_pass":   bool(smb.get("pass_enc")),
        "cases_source":   o.get("cases_source", "local"),
    }


class OptionsBody(BaseModel):
    ollama_url:   str | None = None
    smb_share:    str | None = None
    smb_letter:   str | None = None
    smb_user:     str | None = None
    smb_pass:     str | None = None  # if "" → clear; if not provided → keep existing
    cases_source: str | None = None


@app.post("/api/options")
def api_options_save(body: OptionsBody) -> dict[str, Any]:
    o = _load_options()
    if body.ollama_url is not None:
        url = body.ollama_url.strip() or "http://127.0.0.1:11434"
        if not url.startswith(("http://", "https://")):
            url = "http://" + url
        o["ollama_url"] = url
    if body.cases_source is not None:
        o["cases_source"] = body.cases_source if body.cases_source in ("local","smb") else "local"
    smb = o.get("smb", {})
    if body.smb_share is not None:  smb["share"]  = body.smb_share.strip()
    if body.smb_letter is not None: smb["letter"] = body.smb_letter.strip()
    if body.smb_user is not None:   smb["user"]   = body.smb_user.strip()
    if body.smb_pass is not None:
        if body.smb_pass == "":
            smb.pop("pass_enc", None)
        else:
            smb["pass_enc"] = _dpapi_protect(body.smb_pass)
    o["smb"] = smb
    _save_options(o)
    return {"ok": True}


@app.post("/api/options/ollama/test")
def api_options_ollama_test() -> dict[str, Any]:
    o = _load_options()
    url = o.get("ollama_url", "http://127.0.0.1:11434").rstrip("/")
    try:
        r = requests.get(f"{url}/api/tags", timeout=5)
        if r.ok:
            tags = r.json().get("models", [])
            return {"ok": True, "url": url, "models": len(tags)}
        return {"ok": False, "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _net_use_cleanup(target: str) -> list[str]:
    """Disconnect ALL existing sessions to the SMB server, including Explorer's
    invisible IPC$ session that triggers error 1219.

    Strategy: try 3 methods in order, each more aggressive:
      1) Win32 API WNetCancelConnection2 on \\\\server  (kills IPC$ too)
      2) Parse `net use` output and disconnect matching entries
      3) `net use \\\\server\\IPC$ /delete /y` explicitly

    Returns list of removed connection identifiers (for logging).
    """
    removed: list[str] = []
    # Extract server portion: \\server\share\folder → \\server
    try:
        srv = target.replace("/", "\\")
        if not srv.startswith("\\\\"): return removed
        parts = srv.lstrip("\\").split("\\")
        if not parts: return removed
        srv_name = parts[0]
        srv_root = "\\\\" + srv_name
    except Exception:
        return removed

    # Method 1: Win32 API — disconnects EVERYTHING for that server (incl. IPC$)
    try:
        import win32wnet  # type: ignore
        # Force=True kills active handles; UpdateProfile=False keeps user prefs
        try:
            win32wnet.WNetCancelConnection2(srv_root, 0, True)
            removed.append(f"{srv_root} (WNet)")
        except Exception:
            pass
        # Also try common variants
        for variant in (srv_root + "\\IPC$", srv_root.lower(), srv_root.upper()):
            try:
                win32wnet.WNetCancelConnection2(variant, 0, True)
                removed.append(f"{variant} (WNet)")
            except Exception:
                pass
    except ImportError:
        pass

    # Method 2: parse `net use` output (covers persistent mappings)
    try:
        r = subprocess.run(["net", "use"], capture_output=True, text=True, timeout=8,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for line in (r.stdout or "").splitlines():
            ls = line.strip()
            if not ls or "\\\\" not in ls: continue
            for tok in ls.split():
                if tok.lower().startswith(srv_root.lower()):
                    subprocess.run(["net", "use", tok, "/delete", "/y"],
                                    capture_output=True, text=True, timeout=8,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    removed.append(tok)
                    break
    except Exception:
        pass

    # Method 3: explicit IPC$ kill (covers Explorer's hidden session)
    try:
        subprocess.run(["net", "use", srv_root + "\\IPC$", "/delete", "/y"],
                        capture_output=True, text=True, timeout=8,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception: pass

    return removed


@app.post("/api/shutdown")
def api_shutdown() -> dict[str, Any]:
    """Graceful shutdown — used by tray and brain.bat."""
    def _kill_later():
        time.sleep(0.5)
        _idle_thread_stop.set()
        try: _mcp.stop_all()
        except Exception: pass
        os.kill(os.getpid(), signal.SIGTERM)
    threading.Thread(target=_kill_later, daemon=True).start()
    return {"ok": True, "shutting_down": True}



class ChatMessage(BaseModel):
    role: str
    content: str

class ChatReq(BaseModel):
    model: str
    messages: list[ChatMessage]
    stream: bool = False

# ---------------------------------------------------------------------------
# Brain Agent tools exposed to Ollama (function calling)
# ---------------------------------------------------------------------------
BRAIN_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_brain",
            "description": (
                "Search the brain knowledge base — vault notes, past conversations, "
                "library books, technical knowledge. Call this when you need to recall "
                "information about the user, previous decisions, or any factual context."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language search query (Polish or English)"
                    }
                },
                "required": ["query"]
            }
        }
    }
]


def _brain_tool_search(query: str) -> str:
    """Execute brain RAG search and return formatted results."""
    try:
        import importlib
        sys.path.insert(0, str(ROOT / "pipeline"))
        import rag
        importlib.reload(rag)
        results = rag.search(query, top_k=5)
        if not results:
            return "No results found in brain."
        parts = []
        for i, r in enumerate(results):
            parts.append(f"[{i+1}] {r.get('path', '?')}\n{r.get('text', '')[:600]}")
        return "\n\n".join(parts)
    except Exception as e:
        return f"Search error: {e}"


@app.post("/api/chat")
async def api_chat(body: ChatReq, request: Request):
    _bump_activity()
    o = _load_options()
    ollama_url = o.get("ollama_url", "http://127.0.0.1:11434").rstrip("/")
    url = f"{ollama_url}/api/chat"

    messages = [m.dict() for m in body.messages]

    # Inject USER profile + Brain Agent persona as system message (once per new conversation)
    if not any(m["role"] == "system" for m in messages):
        profile = ""
        try:
            profile = USER_MD.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass
        sys_content = (
            "Jesteś Brain Agent — osobistym asystentem AI z dostępem do bazy wiedzy użytkownika.\n"
            "Używaj narzędzia search_brain gdy potrzebujesz przypomnieć sobie informacje z poprzednich "
            "rozmów, notatek lub biblioteki technicznej. Odpowiadaj po polsku.\n"
        )
        if profile:
            sys_content += f"\nPROFIL UŻYTKOWNIKA:\n{profile}"
        messages.insert(0, {"role": "system", "content": sys_content})

    loop_msgs = list(messages)

    # Models that don't support function calling — skip tool loop entirely for speed
    _NO_TOOLS = ('vision', 'llava', 'moondream', 'bakllava', 'cogvlm', 'minicpm-v', 'minicpm_v')
    supports_tools = not any(x in body.model.lower() for x in _NO_TOOLS)

    if supports_tools:
        # Async agentic tool-calling loop (non-blocking — uses httpx not requests)
        async with httpx.AsyncClient() as _tc:
            for _round in range(3):
                try:
                    _r = await _tc.post(url, json={
                        "model": body.model,
                        "messages": loop_msgs,
                        "stream": False,
                        "tools": BRAIN_TOOLS,
                    }, timeout=60.0)
                    if _r.status_code != 200:
                        break  # Model doesn't support tools or error — stream plain
                    _data = _r.json()
                except Exception:
                    break

                tool_calls = (_data.get("message") or {}).get("tool_calls") or []
                if not tool_calls:
                    break  # No tool calls — stream final response below

                # Append assistant turn with tool_calls
                loop_msgs.append({
                    "role": "assistant",
                    "content": (_data.get("message") or {}).get("content") or "",
                    "tool_calls": tool_calls,
                })
                # Execute each requested tool
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    args = fn.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}
                    if fn.get("name") == "search_brain":
                        result = _brain_tool_search(args.get("query", ""))
                    else:
                        result = f"Unknown tool: {fn.get('name')}"
                    loop_msgs.append({"role": "tool", "content": result})

    # Deliver final response
    if body.stream:
        # Re-send the resolved conversation as a streaming response
        stream_payload = {"model": body.model, "messages": loop_msgs, "stream": True}

        async def stream_generator():
            async with httpx.AsyncClient() as client:
                try:
                    async with client.stream(
                        "POST", url, json=stream_payload, timeout=120.0
                    ) as response:
                        if response.status_code != 200:
                            yield json.dumps({"error": f"Ollama {response.status_code}"}).encode() + b"\n"
                            return
                        async for chunk in response.aiter_bytes():
                            yield chunk
                except Exception as e:
                    yield json.dumps({"error": str(e)}).encode() + b"\n"

        return StreamingResponse(stream_generator(), media_type="application/x-ndjson")

    return last_data or {"error": "No response from Ollama"}

# Static frontend last

app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")
