from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def running_executable() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return Path(sys.argv[0]).resolve()


def _windows_startup_cmd() -> Path:
    appdata = os.environ.get("APPDATA", "")
    return Path(appdata) / "Microsoft/Windows/Start Menu/Programs/Startup/BRAIN Client.cmd"


def _linux_autostart_desktop() -> Path:
    return Path.home() / ".config/autostart/brain-client.desktop"


def _macos_launch_agent() -> Path:
    return Path.home() / "Library/LaunchAgents/com.brain.client.plist"


def autostart_entry_path() -> Path | None:
    if sys.platform == "win32":
        return _windows_startup_cmd()
    if sys.platform == "linux":
        return _linux_autostart_desktop()
    if sys.platform == "darwin":
        return _macos_launch_agent()
    return None


def is_autostart_enabled() -> bool:
    entry = autostart_entry_path()
    return bool(entry and entry.exists())


def set_autostart(enabled: bool, exe: Path | None = None) -> None:
    exe = exe or running_executable()
    entry = autostart_entry_path()
    if entry is None:
        return

    if sys.platform == "win32":
        if enabled:
            entry.parent.mkdir(parents=True, exist_ok=True)
            entry.write_text(f'@echo off\r\nstart "" "{exe}"\r\n', encoding="ascii")
        elif entry.exists():
            entry.unlink()
        return

    if sys.platform == "linux":
        if enabled:
            entry.parent.mkdir(parents=True, exist_ok=True)
            entry.write_text(
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=BRAIN Client\n"
                f"Exec={exe}\n"
                "X-GNOME-Autostart-enabled=true\n",
                encoding="utf-8",
            )
        elif entry.exists():
            entry.unlink()
        return

    if sys.platform == "darwin":
        plist = entry
        if enabled:
            plist.parent.mkdir(parents=True, exist_ok=True)
            plist.write_text(
                f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.brain.client</string>
  <key>ProgramArguments</key><array><string>{exe}</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><false/>
</dict></plist>""",
                encoding="utf-8",
            )
            subprocess.run(["launchctl", "load", str(plist)], check=False)
        else:
            if plist.exists():
                subprocess.run(["launchctl", "unload", str(plist)], check=False)
                plist.unlink()


def desktop_dir() -> Path:
    if sys.platform == "win32":
        for candidate in (
            Path(os.environ.get("USERPROFILE", "")) / "Desktop",
            Path(os.environ.get("OneDrive", "")) / "Desktop",
            Path.home() / "Desktop",
        ):
            if candidate.exists():
                return candidate
        return Path.home() / "Desktop"

    if sys.platform == "darwin":
        return Path.home() / "Desktop"

    # XDG user dirs — fall back to ~/Desktop
    xdg = Path.home() / ".config/user-dirs.dirs"
    if xdg.exists():
        for line in xdg.read_text(encoding="utf-8").splitlines():
            if line.startswith("XDG_DESKTOP_DIR="):
                raw = line.split("=", 1)[1].strip().strip('"')
                raw = raw.replace("$HOME", str(Path.home()))
                return Path(raw)
    return Path.home() / "Desktop"


def desktop_shortcut_path() -> Path:
    if sys.platform == "win32":
        return desktop_dir() / "BRAIN Client.lnk"
    return desktop_dir() / "BRAIN Client.desktop"


def has_desktop_shortcut() -> bool:
    return desktop_shortcut_path().exists()


def create_desktop_shortcut(exe: Path | None = None) -> bool:
    exe = exe or running_executable()
    target = desktop_shortcut_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    if sys.platform == "win32":
        ps = (
            "$s = New-Object -ComObject WScript.Shell; "
            f"$sc = $s.CreateShortcut('{target}'); "
            f"$sc.TargetPath = '{exe}'; "
            f"$sc.WorkingDirectory = '{exe.parent}'; "
            f"$sc.IconLocation = '{exe},0'; "
            f"$sc.Description = 'BRAIN Client'; "
            "$sc.Save()"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0 and target.exists()

    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=BRAIN Client\n"
        f"Exec={exe}\n"
        "Terminal=false\n"
        "Categories=Utility;\n"
    )
    target.write_text(content, encoding="utf-8")
    if sys.platform != "win32":
        try:
            target.chmod(0o755)
        except OSError:
            pass
    return target.exists()


def apply_install_preferences(cfg: dict, exe: Path | None = None) -> None:
    exe = exe or running_executable()
    if cfg.get("autostart_enabled", True):
        set_autostart(True, exe)
    else:
        set_autostart(False, exe)

    if cfg.get("desktop_shortcut_on_install", True) and not has_desktop_shortcut():
        create_desktop_shortcut(exe)
