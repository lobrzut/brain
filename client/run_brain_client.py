"""PyInstaller entry point — no relative imports."""
from brain_client.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
