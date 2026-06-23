from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .config import load_config, save_config
from .deploy import deploy
from .status import snapshot
from .tray import BrainTray


def _maybe_bootstrap() -> None:
    if getattr(sys, "frozen", False):
        from .bootstrap import ensure_installed

        ensure_installed()


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if argv and argv[0] == "install":
        from .bootstrap import install_to_user_dir

        return 0 if install_to_user_dir() else 1

    _maybe_bootstrap()
    parser = argparse.ArgumentParser(prog="brain-client", description="BRAIN tray agent + MCP deploy")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("tray", help="Run tray icon (default)")
    sub.add_parser("install", help="Copy to ~/.brain/client (quit tray first)")
    p_status = sub.add_parser("status", help="Print BRAIN status JSON")
    p_status.add_argument("--pretty", action="store_true")

    p_deploy = sub.add_parser("deploy", help="Deploy MCP to installed agents")
    p_deploy.add_argument("--agent", help="Deploy only one agent id")
    p_deploy.add_argument("--transport", choices=["http", "ssh"], help="Override transport")

    p_cfg = sub.add_parser("config", help="Show or set config")
    p_cfg.add_argument("--set", nargs=2, metavar=("KEY", "VALUE"), action="append")

    args = parser.parse_args(argv)
    cmd = args.cmd or "tray"

    if cmd == "status":
        print(json.dumps(snapshot(), indent=2 if args.pretty else None))
        return 0

    if cmd == "deploy":
        cfg = load_config()
        if args.transport:
            cfg["transport"] = args.transport
        result = deploy(cfg, agent_id=args.agent)
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok", True) else 1

    if cmd == "config":
        cfg = load_config()
        if args.set:
            for key, value in args.set:
                if value.lower() in {"true", "false"}:
                    cfg[key] = value.lower() == "true"
                elif value.isdigit():
                    cfg[key] = int(value)
                else:
                    cfg[key] = value
            save_config(cfg)
        print(json.dumps(cfg, indent=2))
        return 0

    BrainTray().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
