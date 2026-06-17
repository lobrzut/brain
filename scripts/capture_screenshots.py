"""Capture Brain dashboard screenshots for README (requires playwright)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
BASE = os.environ.get("BRAIN_SCREENSHOT_URL", "http://127.0.0.1:7860")


def capture() -> None:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    vp = {"width": 1440, "height": 900}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=vp)
        page.goto(BASE, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector(".topbar", timeout=30000)
        page.wait_for_timeout(3000)
        page.screenshot(path=str(OUT / "dashboard-home.png"), full_page=False)

        page.click('button.tab[data-view="brain"]')
        # Knowledge graph fetches /api/graph and renders canvas — can take 10–60s on large vaults
        page.wait_for_function(
            """() => {
              const stats = document.querySelector('#graph-stats');
              if (stats && /\\d+\\s+nodes/.test(stats.textContent || '')) return true;
              return !!document.querySelector('#graph-canvas canvas');
            }""",
            timeout=120000,
        )
        page.wait_for_timeout(2500)
        page.screenshot(path=str(OUT / "dashboard-brain.png"), full_page=False)

        page.click('button.tab[data-view="pipeline"]')
        page.wait_for_timeout(1500)
        page.screenshot(path=str(OUT / "dashboard-pipeline.png"), full_page=False)

        browser.close()


def main() -> int:
    try:
        capture()
    except ImportError:
        print("Install: pip install playwright && playwright install chromium", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"capture failed: {exc}", file=sys.stderr)
        return 1
    print(f"Saved screenshots to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
