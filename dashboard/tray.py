"""Brain system-tray app — Windows tray icon AS LIFE-CONTROLLER.

The tray icon IS the application. Single source of truth:
  TRAY ICON VISIBLE  → Brain is running
  TRAY ICON GONE     → Brain is fully stopped

How it works:
  1. brain.bat → tray.py (pythonw, no console)
  2. tray.main() spawns Ollama + dashboard as CHILD subprocesses
  3. Heartbeat thread writes data/tray.heartbeat every 5s
  4. Dashboard's tray-watchdog thread reads heartbeat — if stale >30s, self-shutdown
  5. Tray's QUIT → terminate children → delete heartbeat → exit

Net effect: kill tray any way (taskkill, shell crash, user quit) and within
~30s the dashboard self-terminates. Within seconds Ollama follows
(no parent → orphaned, taskkill -F via shutdown handler).

Icon color reflects state:
  CYAN/MAGENTA ring  = healthy (dashboard + ollama OK)
  AMBER ring         = degraded (one of them down)
  RED ring           = critical (will exit if not recovered)
"""
from __future__ import annotations
import os, subprocess, sys, threading, time, webbrowser
from pathlib import Path

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    print("pystray / Pillow missing — tray app disabled. Install: pip install pystray pillow")
    sys.exit(0)

import requests

ROOT          = Path(__file__).resolve().parent.parent
DASHBOARD_URL = "http://127.0.0.1:7860"
OLLAMA_URL    = "http://127.0.0.1:11434"
HEARTBEAT_F   = ROOT / "data" / "tray.heartbeat"

# Child processes spawned by tray
_ollama_proc:    subprocess.Popen | None = None
_dashboard_proc: subprocess.Popen | None = None

STATE = {"dashboard": False, "ollama": False}

# Win32 CREATE_NO_WINDOW so spawned procs don't pop up cmd windows
NO_WIN = 0x08000000 if sys.platform == "win32" else 0


# ---------------------------------------------------------------------------
# Icon rendering
# ---------------------------------------------------------------------------
def make_icon(state: str = "healthy") -> Image.Image:
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if state == "healthy":
        outer = (0, 225, 255, 255); inner = (255, 43, 214, 220)
    elif state == "degraded":
        outer = (255, 182, 39, 255); inner = (255, 182, 39, 180)
    else:  # critical
        outer = (255, 77, 109, 255); inner = (255, 77, 109, 200)
    d.ellipse([4, 4, 60, 60], outline=outer, width=4)
    d.ellipse([16, 16, 48, 48], outline=inner, width=3)
    d.ellipse([26, 26, 38, 38], fill=(255, 255, 255, 240))
    return img


# ---------------------------------------------------------------------------
# Spawn / restart children
# ---------------------------------------------------------------------------
def _kill_existing_on_port(port: int) -> None:
    """Pre-flight: kill any stale uvicorn/ollama on our ports."""
    try:
        import psutil
        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cmd = " ".join(str(c) for c in (p.info.get("cmdline") or []))
                if str(port) in cmd and ("uvicorn" in cmd or "app:app" in cmd
                                          or "ollama" in cmd.lower()):
                    p.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception:
        pass


def start_ollama() -> bool:
    global _ollama_proc
    if _ollama_proc and _ollama_proc.poll() is None:
        return True  # already running
    exe = ROOT / "bin" / "ollama" / "ollama.exe"
    if not exe.exists():
        return False
    env = os.environ.copy()
    env["OLLAMA_MODELS"]     = str(ROOT / "data" / "ollama-models")
    env["OLLAMA_HOST"]       = "127.0.0.1:11434"
    env["OLLAMA_KEEP_ALIVE"] = "30m"
    env["OLLAMA_VULKAN"]     = "1"
    try:
        log = open(ROOT / "logs" / "ollama.err.log", "ab")
        _ollama_proc = subprocess.Popen(
            [str(exe), "serve"],
            stdout=log, stderr=log, env=env, creationflags=NO_WIN,
        )
        (ROOT / "logs" / "ollama.pid").write_text(str(_ollama_proc.pid))
        return True
    except Exception as e:
        print(f"start_ollama failed: {e}", flush=True)
        return False


def start_dashboard() -> bool:
    global _dashboard_proc
    if _dashboard_proc and _dashboard_proc.poll() is None:
        return True
    pyExe = ROOT / "bin" / "python" / "python.exe"
    if not pyExe.exists():
        return False
    _kill_existing_on_port(7860)
    env = os.environ.copy()
    # Mark child so dashboard knows to self-shutdown when tray heartbeat is stale
    env["BRAIN_TRAY_PARENT"] = str(os.getpid())
    env["PYTHONIOENCODING"]  = "utf-8"
    try:
        log = open(ROOT / "logs" / "dashboard.err.log", "ab")
        _dashboard_proc = subprocess.Popen(
            [str(pyExe), "-m", "uvicorn", "app:app",
             "--host", "127.0.0.1", "--port", "7860"],
            cwd=str(ROOT / "dashboard"),
            stdout=log, stderr=log, env=env, creationflags=NO_WIN,
        )
        (ROOT / "logs" / "dashboard.pid").write_text(str(_dashboard_proc.pid))
        return True
    except Exception as e:
        print(f"start_dashboard failed: {e}", flush=True)
        return False


def restart_ollama(icon=None, item=None):
    global _ollama_proc
    try:
        if _ollama_proc and _ollama_proc.poll() is None:
            _ollama_proc.terminate()
            try: _ollama_proc.wait(timeout=5)
            except subprocess.TimeoutExpired: _ollama_proc.kill()
        subprocess.run(["taskkill", "/F", "/IM", "ollama.exe"],
                       capture_output=True, creationflags=NO_WIN)
    except Exception: pass
    time.sleep(1)
    start_ollama()


def restart_dashboard(icon=None, item=None):
    global _dashboard_proc
    try:
        if _dashboard_proc and _dashboard_proc.poll() is None:
            _dashboard_proc.terminate()
            try: _dashboard_proc.wait(timeout=5)
            except subprocess.TimeoutExpired: _dashboard_proc.kill()
    except Exception: pass
    time.sleep(1)
    start_dashboard()


# ---------------------------------------------------------------------------
# UI actions
# ---------------------------------------------------------------------------
def open_dashboard(icon=None, item=None):
    webbrowser.open(DASHBOARD_URL)


def _open(path):
    path = Path(path); path.mkdir(parents=True, exist_ok=True)
    try: subprocess.Popen(["explorer.exe", str(path)])
    except Exception as e: print(f"explorer open failed: {e}", flush=True)


def open_vault(icon=None, item=None):    _open(ROOT / "data" / "vault")
def open_root(icon=None, item=None):     _open(ROOT)
def open_library(icon=None, item=None):  _open(ROOT / "data" / "library")
def open_inbox(icon=None, item=None):    _open(ROOT / "data" / "brain-raw" / "inbox")
def open_logs(icon=None, item=None):     _open(ROOT / "logs")


# ---------------------------------------------------------------------------
# Shutdown — kill everything tray owns
# ---------------------------------------------------------------------------
def _kill_children() -> None:
    global _ollama_proc, _dashboard_proc
    # Dashboard first — graceful shutdown via API
    try:
        requests.post(f"{DASHBOARD_URL}/api/shutdown", timeout=2)
    except Exception: pass
    time.sleep(1)

    for proc, name in [(_dashboard_proc, "dashboard"), (_ollama_proc, "ollama")]:
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try: proc.kill()
                except Exception: pass
            except Exception: pass

    # Belt-and-braces: kill any stragglers by name
    try:
        subprocess.run(["taskkill", "/F", "/IM", "ollama.exe"],
                       capture_output=True, creationflags=NO_WIN)
    except Exception: pass

    # Remove heartbeat so any orphan dashboard self-shuts-down
    try:
        if HEARTBEAT_F.exists(): HEARTBEAT_F.unlink()
    except Exception: pass


def quit_brain(icon=None, item=None):
    """Full shutdown: dashboard + ollama + tray. The 'real' exit."""
    _kill_children()
    try:
        if icon: icon.stop()
    except Exception: pass
    time.sleep(0.5)
    os._exit(0)


# ---------------------------------------------------------------------------
# Heartbeat & health loop
# ---------------------------------------------------------------------------
def heartbeat_loop():
    """Touch heartbeat file every 5s. Dashboard checks this and self-terminates
    if file is stale >30s (tray died/crashed/closed)."""
    HEARTBEAT_F.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            HEARTBEAT_F.write_text(str(time.time()), encoding="utf-8")
        except Exception: pass
        time.sleep(5)


def health_loop(icon: "pystray.Icon"):
    """Passive monitor + auto-recovery for child processes."""
    time.sleep(8)  # give children time to bind ports
    dash_fails, oll_fails = 0, 0
    while True:
        # Check via HTTP (tolerant of slow responses during heavy work)
        try:
            r = requests.get(f"{DASHBOARD_URL}/api/status", timeout=10.0)
            dash_fails = 0 if r.ok else dash_fails + 1
        except Exception:
            dash_fails += 1
        try:
            r = requests.get(f"{OLLAMA_URL}/api/version", timeout=5.0)
            oll_fails = 0 if r.ok else oll_fails + 1
        except Exception:
            oll_fails += 1

        # If our subprocess handle reports dead, that's authoritative
        proc_dash_dead = _dashboard_proc and _dashboard_proc.poll() is not None
        proc_oll_dead  = _ollama_proc    and _ollama_proc.poll() is not None

        if proc_dash_dead:
            print("[tray] dashboard subprocess died — restarting", flush=True)
            start_dashboard()
        if proc_oll_dead:
            print("[tray] ollama subprocess died — restarting", flush=True)
            start_ollama()

        ok_dash = dash_fails < 2 and not proc_dash_dead
        ok_oll  = oll_fails  < 2 and not proc_oll_dead
        STATE["dashboard"] = ok_dash
        STATE["ollama"]    = ok_oll

        if ok_dash and ok_oll:
            new_state, tip = "healthy", "Brain · OK · dashboard + ollama"
        elif ok_dash:
            new_state, tip = "degraded", f"Brain · ollama DOWN ({oll_fails}x)"
        elif ok_oll:
            new_state, tip = "degraded", f"Brain · dashboard DOWN ({dash_fails}x)"
        else:
            new_state, tip = "critical", "Brain · BOTH DOWN — check tray menu"

        try:
            icon.icon = make_icon(new_state)
            icon.title = tip
        except Exception: pass

        time.sleep(10)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    # 1. Spawn children FIRST
    print("[tray] starting Ollama …", flush=True)
    start_ollama()
    print("[tray] starting dashboard …", flush=True)
    start_dashboard()

    # 2. Build menu
    icon = pystray.Icon(
        "brain",
        make_icon("healthy"),
        "Brain AI Hub (starting…)",
        menu=pystray.Menu(
            pystray.MenuItem("Open Dashboard", open_dashboard, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open Vault Folder",      open_vault),
            pystray.MenuItem("Open Library Folder",    open_library),
            pystray.MenuItem("Open Inbox (transcripts)", open_inbox),
            pystray.MenuItem("Open Logs Folder",       open_logs),
            pystray.MenuItem("Open Brain Folder",      open_root),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Restart Ollama",      restart_ollama),
            pystray.MenuItem("Restart Dashboard",   restart_dashboard),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("QUIT BRAIN (stop everything)", quit_brain),
        ),
    )

    # 3. Start background threads
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    threading.Thread(target=health_loop, args=(icon,), daemon=True).start()

    # 4. Run icon event loop (blocks until quit)
    try:
        icon.run()
    finally:
        # Failsafe — if icon.run exits abnormally (taskkill, shell crash),
        # still try to clean up children before we go.
        _kill_children()


if __name__ == "__main__":
    main()
