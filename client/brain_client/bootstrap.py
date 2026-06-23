from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _install_dir() -> Path:
    return Path.home() / ".brain" / "client"


def _binary_name() -> str:
    if sys.platform == "win32":
        return "BrainClient.exe"
    return "BrainClient"


def installed_binary() -> Path:
    return _install_dir() / _binary_name()


def _installed_binary() -> Path:
    return installed_binary()


def _write_default_config() -> None:
    from .config import CONFIG_PATH, default_config, save_config

    if CONFIG_PATH.exists():
        return
    cfg = default_config()
    if os.environ.get("BRAIN_URL"):
        cfg["brain_url"] = os.environ["BRAIN_URL"]
        cfg["mcp_url"] = os.environ.get("BRAIN_MCP_URL", cfg["brain_url"].replace(":7860", ":7862"))
    save_config(cfg)


def _apply_preferences(exe: Path) -> None:
    from .config import load_config
    from .system_integration import apply_install_preferences

    apply_install_preferences(load_config(), exe)


def _launch(exe: Path) -> None:
    subprocess.Popen(
        [str(exe), *sys.argv[1:]],
        cwd=str(exe.parent),
        close_fds=True,
    )


def install_to_user_dir() -> bool:
    """Copy to ~/.brain/client — run as `BrainClient.exe install` when app is closed."""
    if not getattr(sys, "frozen", False):
        print("Install works only with the packaged BrainClient.exe", file=sys.stderr)
        return False

    src = Path(sys.executable).resolve()
    target = _installed_binary().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    if src != target:
        try:
            shutil.copy2(src, target)
        except OSError as exc:
            print(f"Install failed: {exc}", file=sys.stderr)
            print("Close any running BRAIN Client and try again.", file=sys.stderr)
            return False

    _write_default_config()
    _apply_preferences(target)
    print(f"Installed: {target}")
    return True


def ensure_installed() -> Path:
    """Prepare config and shortcuts. No hidden .cmd copy (avoids antivirus false positives)."""
    if not getattr(sys, "frozen", False):
        return Path(sys.executable)

    here = Path(sys.executable).resolve()
    target = _installed_binary().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    if sys.platform != "win32":
        try:
            os.chmod(here, 0o755)
        except OSError:
            pass

    _write_default_config()

    # Canonical install location
    if here == target:
        _apply_preferences(target)
        return target

    # Stable copy already installed — start it instead of duplicating
    if target.exists():
        _launch(target)
        sys.exit(0)

    # First run from Downloads etc. — run in place, no self-copy
    _apply_preferences(here)
    return here
