from __future__ import annotations

import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageOps

from .agents import BRAIN_KEYS, list_agents
from .config import load_config, save_config
from .deploy import deploy
from .status import snapshot, tooltip_text
from .bootstrap import installed_binary
from .system_integration import (
    create_desktop_shortcut,
    has_desktop_shortcut,
    running_executable,
    set_autostart,
)


def _resource_path(name: str) -> Path:
    """Locate a bundled asset both under PyInstaller (_MEIPASS) and in dev."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / name
    here = Path(__file__).resolve().parent
    for cand in (here / name, here.parent / name, here.parent.parent / name):
        if cand.exists():
            return cand
    return Path(name)


def _icon(color: str) -> Image.Image:
    """Brain emblem tinted by status color (green / amber / red).

    The whole brain is recolored so status stays legible even at 16 px tray
    size. Falls back to a plain status circle if the icon asset is missing."""
    size = 64
    try:
        rgb = tuple(int(color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        base = Image.open(_resource_path("brain.ico")).convert("RGBA").resize((size, size), Image.LANCZOS)
        alpha = base.split()[3]
        gray = base.convert("L")
        tinted = ImageOps.colorize(
            gray,
            black=(8, 12, 16),
            mid=tuple(int(c * 0.55) for c in rgb),
            white=rgb,
        ).convert("RGBA")
        tinted.putalpha(alpha)
        return tinted
    except Exception:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse((8, 8, 56, 56), fill=color)
        draw.ellipse((22, 22, 42, 42), fill=(255, 255, 255, 220))
        return img


class BrainTray:
    def __init__(self) -> None:
        import pystray

        self._pystray = pystray
        self._icon = None
        self._cfg = load_config()
        self._snap: dict = {}
        self._stop = threading.Event()

    def _color(self) -> str:
        if not self._snap.get("online"):
            return "#e74c3c"
        wired = self._snap.get("agents_wired", 0)
        installed = self._snap.get("agents_installed", 0)
        if installed and wired < installed:
            return "#f39c12"
        return "#2ecc71"

    def _refresh(self) -> None:
        self._cfg = load_config()
        self._snap = snapshot(self._cfg)
        if self._icon:
            self._icon.icon = _icon(self._color())
            self._icon.title = tooltip_text(self._snap)

    def _poll(self) -> None:
        while not self._stop.wait(self._cfg.get("poll_interval_sec", 30)):
            self._refresh()
            if self._icon:
                self._icon.update_menu()

    def _save_bool(self, key: str, value: bool) -> None:
        self._cfg[key] = value
        save_config(self._cfg)

    def _toggle_autostart(self, _icon, _item) -> None:
        enabled = not self._cfg.get("autostart_enabled", True)
        self._save_bool("autostart_enabled", enabled)
        set_autostart(enabled)

    def _toggle_auto_deploy(self, _icon, _item) -> None:
        self._save_bool("auto_deploy_on_start", not self._cfg.get("auto_deploy_on_start", True))

    def _toggle_open_browser(self, _icon, _item) -> None:
        self._save_bool("open_browser_on_start", not self._cfg.get("open_browser_on_start", False))

    def _on_create_shortcut(self, _icon, _item) -> None:
        create_desktop_shortcut()
        if self._icon:
            self._icon.update_menu()

    def _is_installed_location(self) -> bool:
        return running_executable().resolve() == installed_binary().resolve()

    def _on_install_to_folder(self, _icon, _item) -> None:
        exe = running_executable()
        self._stop.set()
        if self._icon:
            self._icon.stop()
        flags = 0
        if hasattr(subprocess, "DETACHED_PROCESS"):
            flags |= subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            flags |= subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        subprocess.Popen([str(exe), "install"], creationflags=flags)

    def _autostart_label(self) -> str:
        if sys.platform == "win32":
            return "Autostart z Windowsem"
        if sys.platform == "darwin":
            return "Autostart z macOS"
        return "Autostart z systemem"

    def _settings_menu(self) -> list:
        shortcut_label = (
            "Skrót na pulpicie (utworzony)"
            if has_desktop_shortcut()
            else "Utwórz skrót na pulpicie"
        )
        return [
            self._pystray.MenuItem(
                self._autostart_label(),
                self._toggle_autostart,
                checked=lambda _item: self._cfg.get("autostart_enabled", True),
            ),
            self._pystray.MenuItem(
                "Deploy MCP przy starcie",
                self._toggle_auto_deploy,
                checked=lambda _item: self._cfg.get("auto_deploy_on_start", True),
            ),
            self._pystray.MenuItem(
                "Otwórz dashboard przy starcie",
                self._toggle_open_browser,
                checked=lambda _item: self._cfg.get("open_browser_on_start", False),
            ),
            self._pystray.Menu.SEPARATOR,
            self._pystray.MenuItem(
                shortcut_label,
                self._on_create_shortcut,
                enabled=not has_desktop_shortcut(),
            ),
            self._pystray.MenuItem(
                "Zainstaluj do folderu użytkownika",
                self._on_install_to_folder,
                enabled=not self._is_installed_location(),
            ),
        ]

    def _menu(self) -> list:
        snap = self._snap
        lines = [
            self._pystray.MenuItem(
                f"Status: {'ONLINE' if snap.get('online') else 'OFFLINE'}",
                None,
                enabled=False,
            ),
            self._pystray.MenuItem(
                f"MCP: {'OK' if snap.get('mcp_online') else 'DOWN'}",
                None,
                enabled=False,
            ),
            self._pystray.MenuItem(
                f"Agents: {snap.get('agents_wired', 0)}/{snap.get('agents_installed', 0)} wired",
                None,
                enabled=False,
            ),
            self._pystray.Menu.SEPARATOR,
            self._pystray.MenuItem("Open BRAIN dashboard", self._open_brain),
            self._pystray.MenuItem("Deploy MCP to all installed", self._deploy_all),
            self._pystray.MenuItem("Ustawienia", self._pystray.Menu(lambda: self._settings_menu())),
            self._pystray.Menu.SEPARATOR,
        ]

        for agent in list_agents(BRAIN_KEYS):
            if not agent["installed"]:
                continue
            status = agent["brain_status"]
            label = f"{agent['label']} [{status}]"
            lines.append(
                self._pystray.MenuItem(
                    label,
                    self._deploy_one(agent["id"]),
                    enabled=status != "wired",
                )
            )

        lines.extend(
            [
                self._pystray.Menu.SEPARATOR,
                self._pystray.MenuItem("Refresh", self._on_refresh),
                self._pystray.MenuItem("Quit", self._on_quit),
            ]
        )
        return lines

    def _open_brain(self, _icon, _item) -> None:
        webbrowser.open(self._cfg.get("brain_url", "http://127.0.0.1:7860"))

    def _deploy_all(self, _icon, _item) -> None:
        deploy(self._cfg)
        self._refresh()

    def _deploy_one(self, agent_id: str) -> Callable:
        def _handler(_icon, _item):
            deploy(self._cfg, agent_id=agent_id)
            self._refresh()

        return _handler

    def _on_refresh(self, _icon, _item) -> None:
        self._refresh()

    def _on_quit(self, _icon, _item) -> None:
        self._stop.set()
        if self._icon:
            self._icon.stop()

    def run(self) -> None:
        self._refresh()
        if self._cfg.get("auto_deploy_on_start"):
            deploy(self._cfg)
            self._refresh()

        if self._cfg.get("open_browser_on_start"):
            webbrowser.open(self._cfg.get("brain_url", "http://127.0.0.1:7860"))

        threading.Thread(target=self._poll, daemon=True).start()

        self._icon = self._pystray.Icon(
            "brain-client",
            _icon(self._color()),
            tooltip_text(self._snap),
            menu=self._pystray.Menu(lambda: self._menu()),
        )
        self._icon.run()
