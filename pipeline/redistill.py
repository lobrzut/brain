"""Re-destyluje krótkie notatki (<MIN_BYTES) na większym modelu.

Idea: 40% naszych notatek to <500B summary z qwen2.5:3b. Distill.py małym modelem
często wyciągnął tylko 1 zdanie. Mamy raw sessions w data/brain-raw/normalized/,
możemy je destylować ponownie używając większego modelu (np. qwen2.5:14b).

Architektura:
  - find_thin_notes() — locate target .md files in vault/distilled/
  - locate_normalized() — find the source session JSON by session_id
  - redistill_one() — call distill.distill_session() + atomic overwrite
  - redistill_batch(n) — batch-mode, used by scheduler

CLI:
  python redistill.py count                # how many thin notes
  python redistill.py one <filename>        # re-distill one specific
  python redistill.py batch 5 [model]       # re-distill N thin notes
"""
from __future__ import annotations
import json, re, sys, time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT       = Path(__file__).resolve().parent.parent
DISTILLED  = ROOT / "data" / "vault" / "distilled"
NORMALIZED = ROOT / "data" / "brain-raw" / "normalized"
STATUS_F   = ROOT / "data" / "redistill-status.json"

DEFAULT_MIN_BYTES = 500
DEFAULT_MODEL     = "qwen2.5:14b"

sys.path.insert(0, str(ROOT / "pipeline"))


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
_SESSION_RE     = re.compile(r"^session:\s*(\S+)", re.MULTILINE)
_SOURCE_RE      = re.compile(r"^source:\s*(\S+)",  re.MULTILINE)


def find_thin_notes(min_bytes: int = DEFAULT_MIN_BYTES,
                    include_stubs: bool = True) -> list[Path]:
    """All .md files that need re-distillation:
       - size < min_bytes (default 500B)
       - OR contains the stub marker (## _Stub_) — means distillation found nothing.

    Returns oldest-first so we tackle the historically-failed ones first."""
    if not DISTILLED.exists():
        return []
    results = []
    for p in DISTILLED.glob("*.md"):
        size = p.stat().st_size
        if size < min_bytes:
            results.append(p)
            continue
        if include_stubs and size < 2000:  # only check small files for stub
            try:
                t = p.read_text(encoding="utf-8", errors="replace")
                if "## _Stub_" in t:
                    results.append(p)
            except Exception:
                pass
    results.sort(key=lambda p: p.stat().st_mtime)
    return results


def _parse_metadata(note_path: Path) -> dict:
    try:
        text = note_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    fm = m.group(1)
    out: dict = {}
    sm = _SESSION_RE.search(fm)
    if sm: out["session"] = sm.group(1)
    src = _SOURCE_RE.search(fm)
    if src: out["source"] = src.group(1)
    return out


def locate_normalized(note_path: Path) -> Path | None:
    """Find the source session JSON for a thin note."""
    meta = _parse_metadata(note_path)
    sess = meta.get("session")
    if not sess:
        return None
    source = meta.get("source") or "claude-ai"
    # Two roots: normalized/inbox/ (claude-ai/grok/chatgpt) and normalized/claude-code/
    candidates = [NORMALIZED / "inbox", NORMALIZED / "claude-code"]
    for root in candidates:
        if not root.exists():
            continue
        # Exact match by session id substring (filenames look like
        # claude_<uuid>.json or <project>_<uuid>.json)
        for p in root.glob("*.json"):
            if sess in p.name or p.stem.endswith(sess):
                return p
    return None


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
def _write_status(**kv) -> None:
    s = {"updated_at": time.time(), **kv}
    STATUS_F.parent.mkdir(parents=True, exist_ok=True)
    STATUS_F.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")


def read_status() -> dict:
    if STATUS_F.exists():
        try: return json.loads(STATUS_F.read_text(encoding="utf-8"))
        except Exception: pass
    return {"state": "idle", "done": 0, "total": 0}


# ---------------------------------------------------------------------------
# Re-distill
# ---------------------------------------------------------------------------
def redistill_one(note_path: Path, model: str = DEFAULT_MODEL) -> dict:
    """Re-distill a single thin note. Atomic overwrite."""
    import importlib, distill
    importlib.reload(distill)

    src = locate_normalized(note_path)
    if src is None:
        return {"ok": False, "file": note_path.name,
                "error": "no normalized source found (session id not in normalized/)"}

    try:
        session = json.loads(src.read_text(encoding="utf-8"))
    except Exception as e:
        return {"ok": False, "file": note_path.name, "error": f"read raw: {e}"}

    old_size = note_path.stat().st_size

    t0 = time.time()
    try:
        distilled = distill.distill_session(session, model)
    except Exception as e:
        return {"ok": False, "file": note_path.name, "error": f"distill: {e}"}
    duration = round(time.time() - t0, 1)

    # write_note returns the path it wrote (overwrites by stable name)
    out = distill.write_note(session, distilled, DISTILLED)
    if out is None:
        return {"ok": False, "file": note_path.name, "error": distilled.get("error", "write_note returned None")}

    new_size = out.stat().st_size
    return {
        "ok": True,
        "file": out.name,
        "model": model,
        "old_size": old_size,
        "new_size": new_size,
        "growth_x": round(new_size / max(1, old_size), 2),
        "duration_sec": duration,
    }


def redistill_batch(n: int = 5,
                    model: str = DEFAULT_MODEL,
                    min_bytes: int = DEFAULT_MIN_BYTES,
                    progress_cb=None,
                    stop_check=None) -> dict:
    """Process up to N thin notes. Returns summary.

    stop_check: callable returning True if processing should abort. Checked
    between notes (each note is atomic — we don't kill the model mid-call)."""
    thin = find_thin_notes(min_bytes)
    total_thin = len(thin)
    targets = thin[:n]

    _write_status(state="running", done=0, total=len(targets),
                  total_thin=total_thin, model=model)

    done, errors, grew, sum_old, sum_new = 0, 0, 0, 0, 0
    results = []
    stopped = False
    consecutive_errs = 0   # bail if N in a row → catches credit-balance, network down, model gone
    last_err_msg = ""
    BAIL_AFTER = 3
    for i, p in enumerate(targets):
        if stop_check and stop_check():
            stopped = True
            break
        r = redistill_one(p, model)
        results.append(r)
        if r.get("ok"):
            done += 1
            consecutive_errs = 0
            sum_old += r["old_size"]
            sum_new += r["new_size"]
            if r["new_size"] > r["old_size"] * 1.3:
                grew += 1
        else:
            errors += 1
            consecutive_errs += 1
            err_msg = str(r.get("error", ""))
            last_err_msg = err_msg
            # Hard-stop on classic infra errors (no point grinding through)
            if any(x in err_msg for x in ["API", "ollama returned", "Max retries",
                                           "Connection", "Timeout", "billing",
                                           "credit", "401", "403", "429"]):
                _write_status(state="error", error=err_msg, done=done, total=len(targets),
                              total_thin=total_thin, model=model)
                return {"done": done, "errors": errors, "grew": grew,
                        "total_remaining": total_thin - done,
                        "bytes_before": sum_old, "bytes_after": sum_new,
                        "stopped": True, "results": results, "error": err_msg}
            # Soft-stop if 3 errors in a row even if message doesn't match known patterns
            if consecutive_errs >= BAIL_AFTER:
                _write_status(state="error",
                              error=f"Bail after {BAIL_AFTER} consecutive errors. Last: {err_msg[:200]}",
                              done=done, total=len(targets),
                              total_thin=total_thin, model=model)
                return {"done": done, "errors": errors, "grew": grew,
                        "total_remaining": total_thin - done,
                        "bytes_before": sum_old, "bytes_after": sum_new,
                        "stopped": True, "results": results,
                        "error": f"Bail po {BAIL_AFTER} bledach z rzedu: {err_msg[:160]}"}

        _write_status(state="running", done=done + errors, total=len(targets),
                      total_thin=total_thin, model=model,
                      last_file=p.name, errors=errors, grew=grew,
                      last_err=last_err_msg[:200] if errors else "")
        if progress_cb:
            progress_cb(i + 1, len(targets), r)

    _write_status(state="stopped" if stopped else "idle",
                  done=done, total=len(targets),
                  total_thin=total_thin - done, model=model,
                  errors=errors, grew=grew,
                  bytes_before=sum_old, bytes_after=sum_new,
                  finished_at=time.time())
    return {"done": done, "errors": errors, "grew": grew,
            "total_remaining": total_thin - done,
            "bytes_before": sum_old, "bytes_after": sum_new,
            "stopped": stopped,
            "results": results}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: redistill.py count | one <file.md> | batch <N> [model]")
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "count":
        for thresh in (300, 500, 800, 1000):
            n = len(find_thin_notes(thresh))
            print(f"  < {thresh} B: {n} notes")
    elif cmd == "one" and len(sys.argv) >= 3:
        p = DISTILLED / sys.argv[2]
        if not p.exists():
            print(f"not found: {p}"); sys.exit(2)
        print(json.dumps(redistill_one(p), indent=2, ensure_ascii=False))
    elif cmd == "batch" and len(sys.argv) >= 3:
        n = int(sys.argv[2])
        model = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_MODEL
        r = redistill_batch(n, model,
            progress_cb=lambda i, n, r: print(f"  [{i}/{n}] {r.get('file','?')} "
                                              f"{r.get('old_size','?')} → {r.get('new_size','?')} B"
                                              if r.get('ok')
                                              else f"  [{i}/{n}] ERR {r.get('error')}"))
        print(json.dumps({k: v for k, v in r.items() if k != "results"},
                         indent=2, ensure_ascii=False))
    else:
        print("bad args"); sys.exit(2)
