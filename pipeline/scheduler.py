"""Adaptive scheduler — runs background tasks when system is idle or at night.

Inspired by Windows Update / OneDrive sync: only do heavy work when the user is
not actively using the machine. Pure local, no external service.

Each task = dict with eligibility predicates:
  - window:   "night" (22-06) | "day" | "any"
  - require_idle_sec:  user must be idle ≥ this many seconds (mouse/keyboard)
  - require_cpu_below: system-wide CPU% must be below
  - interval_sec:      minimum time between runs
  - action:            registered handler name (see ACTIONS dict)
  - action_args:       kwargs passed to the handler

The scheduler tick (every 60s) inspects all enabled tasks. If a task's gates
all pass, it dispatches the action in a worker thread and updates last_run.
Only ONE action runs at a time (lock) — we don't want to launch 3 LLM jobs
simultaneously and tank the GPU.

State:
  - data/schedule-config.json — task definitions (user-editable via UI)
  - data/schedule-log.json    — last 100 runs (id, ts, ok, summary)
"""
from __future__ import annotations
import ctypes, json, sys, threading, time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT     = Path(__file__).resolve().parent.parent
CONFIG_F = ROOT / "data" / "schedule-config.json"
LOG_F    = ROOT / "data" / "schedule-log.json"


# ---------------------------------------------------------------------------
# Defaults — sensible starting tasks. User can toggle/edit in UI.
# ---------------------------------------------------------------------------
DEFAULT_TASKS: list[dict[str, Any]] = [
    # IMPORTANT: All tasks default to enabled=False — opt-in by user.
    # The earlier defaults of enabled=True caused tasks to fire at night
    # while the user was actively working.
    #
    # NOTE: server-side distillation tasks (redistill_thin, distill_missing,
    # inbox_collect) were removed — distillation now happens client-side
    # (e.g. via Reliqua's host-side pipeline) and is deployed to brain as
    # finished notes. See brain-light-reliqua-heavy in project memory.
    {
        "id":        "nightly_backup",
        "name":      "Backup vault + config (nocą)",
        "description": "Codziennie nocą tworzy ZIP backup data/vault/ + data/api-keys.json + skills/ + config. Zapisuje do data/backups/. Auto-rotuje (max 7 backupów).",
        "enabled":   False,
        "window":    "night",
        "require_idle_sec":  0,
        "require_cpu_below": 60,
        "interval_sec":      86400,  # 1/day
        "action":      "nightly_backup",
        "action_args": {"max_keep": 7},
    },
    {
        "id":        "dedupe_scan",
        "name":      "Skanuj duplikaty w vault",
        "description": "Lekki task (~15s) — odświeża listę kandydatów do merge. Może lecieć gdy aktywny (niski CPU cost).",
        "enabled":   False,
        "window":    "night",
        "require_idle_sec":  60,  # was 0
        "require_cpu_below": 60,
        "interval_sec":      86400,  # 24h
        "action":      "dedupe_scan",
        "action_args": {},
    },
    {
        "id":        "note_quality_audit",
        "name":      "Audyt merytoryczny notatek (note_quality.py)",
        "description": "Lekki task (~30s na 1600 notatek) — liczy score 0-10 per notatka, zapisuje data/note-quality.json + raport. Tile DEEP QUALITY w dashboard się odswieża.",
        "enabled":   False,
        "window":    "any",
        "require_idle_sec":  120,
        "require_cpu_below": 70,
        "interval_sec":      86400,  # 1/day
        "action":      "note_quality_audit",
        "action_args": {},
    },
]


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def load_tasks() -> list[dict]:
    if CONFIG_F.exists():
        try:
            tasks = json.loads(CONFIG_F.read_text(encoding="utf-8"))
            # Migrate: drop persisted tasks whose action no longer exists (e.g.
            # redistill_thin/distill_missing/inbox_collect — removed along with
            # the server-side distillation pipeline). tick() already no-ops on
            # unknown actions, but pruning keeps the UI task list honest instead
            # of showing entries that can never run.
            removed = [t for t in tasks if t.get("action") not in ACTIONS]
            if removed:
                tasks = [t for t in tasks if t.get("action") in ACTIONS]
                print(f"[scheduler] pruned {len(removed)} task(s) with removed action(s): "
                      f"{[t.get('id') for t in removed]}", flush=True)
            # Migrate: ensure new default tasks added if user has older file
            ids = {t["id"] for t in tasks}
            for d in DEFAULT_TASKS:
                if d["id"] not in ids:
                    tasks.append(d.copy())
            if removed:
                save_tasks(tasks)
            return tasks
        except Exception:
            pass
    CONFIG_F.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_F.write_text(json.dumps(DEFAULT_TASKS, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    return [t.copy() for t in DEFAULT_TASKS]


def save_tasks(tasks: list[dict]) -> None:
    CONFIG_F.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_F.write_text(json.dumps(tasks, indent=2, ensure_ascii=False),
                        encoding="utf-8")


def log_run(entry: dict) -> None:
    """Append to circular log (keep last 100)."""
    entry["ts"] = time.time()
    log = []
    if LOG_F.exists():
        try: log = json.loads(LOG_F.read_text(encoding="utf-8"))
        except Exception: pass
    log.append(entry)
    log = log[-100:]
    LOG_F.parent.mkdir(parents=True, exist_ok=True)
    LOG_F.write_text(json.dumps(log, indent=2, ensure_ascii=False),
                     encoding="utf-8")


def read_log(n: int = 20) -> list[dict]:
    if not LOG_F.exists():
        return []
    try:
        log = json.loads(LOG_F.read_text(encoding="utf-8"))
        return log[-n:][::-1]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Idle detection (Windows GetLastInputInfo)
# ---------------------------------------------------------------------------
def user_idle_seconds() -> float:
    """Seconds since last user input (mouse/keyboard). 0 on non-Windows."""
    if sys.platform != "win32":
        return 0.0
    try:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
        ms_since = ctypes.windll.kernel32.GetTickCount() - info.dwTime
        return ms_since / 1000.0
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Eligibility logic
# ---------------------------------------------------------------------------
def in_window(window: str, now: datetime | None = None) -> bool:
    if window == "any":
        return True
    now = now or datetime.now()
    h = now.hour
    if window == "night":
        return h >= 22 or h < 6
    if window == "day":
        return 6 <= h < 22
    return True


def eligibility(task: dict, cpu_pct: float | None = None) -> tuple[bool, list[str]]:
    """Returns (eligible, list_of_reasons_blocked)."""
    reasons: list[str] = []
    if not task.get("enabled", True):
        reasons.append("disabled")
        return False, reasons

    # Global pause from "Pause all" button
    now_ts = time.time()
    pause_until = _global_pause.get("until", 0.0)
    if pause_until and now_ts < pause_until:
        mins_left = int((pause_until - now_ts) / 60) + 1
        reasons.append(f"scheduler paused ({mins_left} min left)")
        return False, reasons

    # STOP cooldown — user pressed STOP, don't restart this task for STOP_COOLDOWN_SEC
    last_stop = task.get("last_stop_at", 0)
    if last_stop:
        elapsed = now_ts - last_stop
        if elapsed < STOP_COOLDOWN_SEC:
            mins_left = int((STOP_COOLDOWN_SEC - elapsed) / 60) + 1
            reasons.append(f"stopped {mins_left} min ago (cooldown {STOP_COOLDOWN_SEC//60} min)")
            return False, reasons

    # Window
    win = task.get("window", "any")
    if not in_window(win):
        h = datetime.now().hour
        reasons.append(f"window={win} (current {h:02d}:??)")

    # Interval cooldown
    last = task.get("last_run", 0) or 0
    interval = task.get("interval_sec", 3600)
    now = time.time()
    if now - last < interval:
        wait_min = int((interval - (now - last)) / 60) + 1
        reasons.append(f"cooldown {wait_min} min")

    # Idle gate
    req_idle = task.get("require_idle_sec", 0)
    if req_idle > 0:
        idle = user_idle_seconds()
        if idle < req_idle:
            reasons.append(f"user active (idle {int(idle)}s / need {req_idle}s)")

    # CPU gate
    req_cpu = task.get("require_cpu_below", 100)
    if req_cpu < 100:
        try:
            import psutil
            cpu = cpu_pct if cpu_pct is not None else psutil.cpu_percent(interval=None)
            if cpu > req_cpu:
                reasons.append(f"cpu busy ({cpu:.0f}% > {req_cpu}%)")
        except Exception:
            pass

    return (len(reasons) == 0, reasons)


# ---------------------------------------------------------------------------
# Action registry
# ---------------------------------------------------------------------------
def _action_nightly_backup(**kwargs) -> dict:
    """Create a ZIP backup of vault + config + skills. Rotate old backups."""
    import zipfile as _zip
    from datetime import datetime as _dt
    backups_dir = ROOT / "data" / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    ts = _dt.now().strftime("%Y-%m-%d_%H-%M")
    backup_name = f"brain_auto_{ts}.zip"
    backup_path = backups_dir / backup_name

    include = [
        ROOT / "data" / "vault",
        ROOT / "skills",
        ROOT / "data" / "api-keys.json",
        ROOT / "data" / "schedule-config.json",
        ROOT / "data" / "code-watches.json",
        ROOT / "config.json",
    ]

    n_files = 0
    try:
        with _zip.ZipFile(backup_path, "w", _zip.ZIP_DEFLATED) as zf:
            for src in include:
                if not src.exists():
                    continue
                if src.is_file():
                    zf.write(src, src.relative_to(ROOT))
                    n_files += 1
                else:
                    for f in src.rglob("*"):
                        if f.is_file():
                            try:
                                zf.write(f, f.relative_to(ROOT))
                                n_files += 1
                            except Exception:
                                pass
    except Exception as e:
        return {"ok": False, "error": str(e)}

    # Rotate — keep only the newest N (default 7)
    max_keep = int(kwargs.get("max_keep", 7))
    auto_backups = sorted(backups_dir.glob("brain_auto_*.zip"),
                          key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    for old in auto_backups[max_keep:]:
        try:
            old.unlink()
            removed += 1
        except Exception:
            pass

    return {
        "name":         backup_name,
        "size_mb":      round(backup_path.stat().st_size / 1024**2, 1),
        "files":        n_files,
        "kept":         min(len(auto_backups) + 1, max_keep),
        "rotated_out":  removed,
    }


def _action_dedupe_scan(**kwargs) -> dict:
    import importlib
    sys.path.insert(0, str(ROOT / "pipeline"))
    if "dedupe" in sys.modules:
        dedupe = importlib.reload(sys.modules["dedupe"])
    else:
        dedupe = importlib.import_module("dedupe")
    r = dedupe.scan()
    return {"scanned": r["scanned"], "pairs": len(r.get("pairs", []))}


def _action_note_quality_audit(**kwargs) -> dict:
    """Run note_quality.py audit → updates data/note-quality.json + raport."""
    import importlib
    sys.path.insert(0, str(ROOT / "pipeline"))
    if "note_quality" in sys.modules:
        nq = importlib.reload(sys.modules["note_quality"])
    else:
        nq = importlib.import_module("note_quality")
    audit = nq.audit_all()
    if "error" in audit:
        return {"error": audit["error"]}
    out_md = ROOT / "data" / "vault" / "notes" / "_note-quality-audit.md"
    out_md.parent.mkdir(parents=True, exist_ok=True)
    nq.write_report(audit, out_md)
    out_json = ROOT / "data" / "note-quality.json"
    out_json.write_text(json.dumps(audit, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    s = audit.get("summary", {})
    return {"analyzed": s.get("analyzed", 0),
            "avg_score": s.get("avg_score"),
            "verdicts":  s.get("verdicts", {})}


ACTIONS: dict[str, Callable[..., dict]] = {
    "dedupe_scan":        _action_dedupe_scan,
    "nightly_backup":     _action_nightly_backup,
    "note_quality_audit": _action_note_quality_audit,
}


# ---------------------------------------------------------------------------
# Tick loop (called from dashboard background thread)
# ---------------------------------------------------------------------------
_run_lock = threading.Lock()
_stop_event = threading.Event()
_self_aware: dict = {"last_advice": [], "ts": 0.0}


def self_aware_check() -> list[dict]:
    """Periodically scans brain state and SUGGESTS new tasks the user might want.
    Pure suggestion — does NOT auto-enable anything. UI shows these as hints.

    Server-side distillation suggestions (missing sessions, thin notes, inbox
    backlog) were removed along with the distillation pipeline — distillation
    now happens client-side. This currently has nothing to suggest; kept as an
    extension point for future lightweight, non-LLM suggestions (e.g. stale
    RAG index, vault size warnings).
    """
    suggestions: list[dict] = []
    _self_aware["last_advice"] = suggestions
    _self_aware["ts"] = time.time()
    return suggestions


def get_self_aware() -> dict:
    """For UI: cached advice + age."""
    return {
        "advice": _self_aware.get("last_advice", []),
        "ts":     _self_aware.get("ts", 0),
        "age_sec": int(time.time() - _self_aware.get("ts", time.time())),
    }
_currently_running: dict[str, Any] = {
    "task_id": None, "started_at": 0.0,
    "progress_done": 0, "progress_total": 0, "progress_label": "",
}


def estimate_remaining(task: dict) -> dict:
    """How much work is queued + ETA based on per-model rate."""
    action = task.get("action")
    if action == "dedupe_scan":
        return {"pending": 1, "eta_sec": 15}
    return {"pending": None, "eta_sec": None}


STOP_COOLDOWN_SEC = 3600  # 1h cooldown — task can't auto-restart for this long after STOP

def request_stop() -> dict:
    """Signal the currently running task to stop ASAP. Also marks the task with
    a STOP cooldown so the scheduler doesn't immediately re-fire it on next tick."""
    if not _run_lock.locked():
        return {"ok": False, "error": "no task running"}
    _stop_event.set()
    task_id = _currently_running.get("task_id")
    # Mark cooldown so eligibility() blocks restart for STOP_COOLDOWN_SEC
    try:
        tasks = load_tasks()
        for t in tasks:
            if t["id"] == task_id:
                t["last_stop_at"] = time.time()
        save_tasks(tasks)
    except Exception:
        pass
    return {"ok": True, "stop_requested": task_id,
            "cooldown_sec": STOP_COOLDOWN_SEC}


_global_pause: dict = {"until": 0.0}


def pause_all(seconds: int = 3600) -> dict:
    """Pause the entire scheduler for N seconds. Stops any running task too."""
    _global_pause["until"] = time.time() + max(60, int(seconds))
    if _run_lock.locked():
        _stop_event.set()
    return {"ok": True, "paused_until": _global_pause["until"],
            "duration_sec": seconds}


def resume_all() -> dict:
    _global_pause["until"] = 0.0
    return {"ok": True}


def update_progress(done: int = 0, total: int = 0, label: str = "") -> None:
    """Workers call this to publish their progress for the UI."""
    _currently_running["progress_done"]  = done
    _currently_running["progress_total"] = total
    _currently_running["progress_label"] = label


def stop_requested() -> bool:
    return _stop_event.is_set()


def tick() -> dict:
    """One scheduler iteration. Returns summary of what happened.

    - Skips immediately if another task is running.
    - Picks the first eligible task (priority = order in tasks list).
    - Dispatches in a worker thread; returns immediately.
    """
    if _run_lock.locked():
        return {"action": "skip", "reason": "another task running",
                "currently": _currently_running.get("task_id")}

    tasks = load_tasks()
    candidate = None
    for t in tasks:
        ok, _reasons = eligibility(t)
        if ok:
            candidate = t
            break

    if candidate is None:
        return {"action": "skip", "reason": "no eligible tasks"}

    action_name = candidate.get("action")
    handler = ACTIONS.get(action_name)
    if handler is None:
        return {"action": "skip", "reason": f"unknown action {action_name!r}"}

    def _worker():
        with _run_lock:
            _stop_event.clear()
            _currently_running["task_id"]    = candidate["id"]
            _currently_running["started_at"] = time.time()
            _currently_running["progress_done"]  = 0
            _currently_running["progress_total"] = 0
            _currently_running["progress_label"] = ""
            t0 = time.time()
            entry = {"task_id": candidate["id"], "name": candidate["name"]}
            try:
                result = handler(**(candidate.get("action_args") or {}))
                entry["ok"]       = True
                entry["result"]   = result
                entry["duration"] = round(time.time() - t0, 1)
            except Exception as e:
                entry["ok"]       = False
                entry["error"]    = str(e)
                entry["duration"] = round(time.time() - t0, 1)
            log_run(entry)
            # Update last_run on the task
            tasks_now = load_tasks()
            for t in tasks_now:
                if t["id"] == candidate["id"]:
                    t["last_run"]    = time.time()
                    t["last_status"] = "ok" if entry.get("ok") else "error"
            save_tasks(tasks_now)
            _currently_running["task_id"]    = None
            _currently_running["started_at"] = 0.0

    threading.Thread(target=_worker, daemon=True).start()
    return {"action": "dispatched", "task_id": candidate["id"]}


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------
def status() -> dict:
    """Snapshot for UI: tasks + per-task eligibility + currently running + log."""
    tasks = load_tasks()
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=None)
    except Exception:
        cpu = None
    idle_s = user_idle_seconds()

    out_tasks = []
    for t in tasks:
        ok, reasons = eligibility(t, cpu_pct=cpu)
        eta = estimate_remaining(t)
        out_tasks.append({**t, "eligible_now": ok, "block_reasons": reasons,
                          "estimate": eta})

    return {
        "tasks":              out_tasks,
        "system_cpu_pct":     cpu,
        "user_idle_sec":      round(idle_s, 0),
        "currently_running":  _currently_running.get("task_id"),
        "currently_started":  _currently_running.get("started_at"),
        "currently_progress": {
            "done":  _currently_running.get("progress_done", 0),
            "total": _currently_running.get("progress_total", 0),
            "label": _currently_running.get("progress_label", ""),
        },
        "stop_requested":     _stop_event.is_set(),
        "global_paused":      _global_pause.get("until", 0.0) > time.time(),
        "paused_until":       _global_pause.get("until", 0.0),
        "stop_cooldown_sec":  STOP_COOLDOWN_SEC,
        "now":                time.time(),
        "log":                read_log(10),
    }


def run_now(task_id: str) -> dict:
    """Force-run a task ignoring all eligibility gates (for UI 'Run now' button)."""
    if _run_lock.locked():
        return {"ok": False, "error": "another task is running"}
    tasks = load_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        return {"ok": False, "error": f"unknown task {task_id}"}
    action = ACTIONS.get(task.get("action"))
    if not action:
        return {"ok": False, "error": f"no handler for {task.get('action')}"}

    def _worker():
        with _run_lock:
            _stop_event.clear()
            _currently_running["task_id"]    = task["id"]
            _currently_running["started_at"] = time.time()
            _currently_running["progress_done"]  = 0
            _currently_running["progress_total"] = 0
            _currently_running["progress_label"] = ""
            t0 = time.time()
            entry = {"task_id": task["id"], "name": task["name"], "manual": True}
            try:
                r = action(**(task.get("action_args") or {}))
                entry["ok"] = True; entry["result"] = r
            except Exception as e:
                entry["ok"] = False; entry["error"] = str(e)
            entry["duration"] = round(time.time() - t0, 1)
            log_run(entry)
            tasks_now = load_tasks()
            for t in tasks_now:
                if t["id"] == task_id:
                    t["last_run"]    = time.time()
                    t["last_status"] = "ok" if entry.get("ok") else "error"
            save_tasks(tasks_now)
            _currently_running["task_id"]    = None
            _currently_running["started_at"] = 0.0

    threading.Thread(target=_worker, daemon=True).start()
    return {"ok": True, "dispatched": task_id}


def toggle(task_id: str, enabled: bool | None = None) -> dict:
    tasks = load_tasks()
    for t in tasks:
        if t["id"] == task_id:
            t["enabled"] = (not t.get("enabled", True)) if enabled is None else bool(enabled)
            save_tasks(tasks)
            return {"ok": True, "enabled": t["enabled"]}
    return {"ok": False, "error": "not found"}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: scheduler.py status | tick | run <task_id> | toggle <task_id>")
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "status":
        s = status()
        print(f"CPU: {s.get('system_cpu_pct')}% · idle: {s.get('user_idle_sec')}s")
        print(f"Running: {s.get('currently_running') or '(none)'}")
        print("\nTasks:")
        for t in s["tasks"]:
            flag = "✓" if t["eligible_now"] else "✗"
            print(f"  [{flag}] {t['id']:<25} {t['name']}")
            if not t["eligible_now"]:
                print(f"         blocked: {', '.join(t['block_reasons'])}")
        print("\nRecent log:")
        for e in s["log"][:5]:
            ts = datetime.fromtimestamp(e["ts"]).strftime("%H:%M:%S")
            print(f"  {ts}  {e['task_id']:<25}  {'OK' if e.get('ok') else 'ERR'}")
    elif cmd == "tick":
        print(json.dumps(tick(), indent=2))
    elif cmd == "run" and len(sys.argv) >= 3:
        print(json.dumps(run_now(sys.argv[2]), indent=2))
    elif cmd == "toggle" and len(sys.argv) >= 3:
        print(json.dumps(toggle(sys.argv[2]), indent=2))
    else:
        print("bad args"); sys.exit(2)
