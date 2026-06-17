"""Brain skills — reusable LLM-powered workflows stored as markdown.

Each skill file = `brain/skills/<name>.md` with YAML front-matter:

  ---
  name: trading-digest
  description: Aggregate recent trading notes into actionable summary
  model: qwen2.5:14b              # which Ollama model to use
  inputs:                          # what the user can pass in (optional)
    days: int = 7
    query: str = "trading setup"
  context:                         # how to gather context BEFORE the LLM call
    - rag: "{query}"               # call rag.search with formatted query
    - vault_recent: 20             # last N notes from vault/distilled/
    - vault_tag: "#trading"        # filter by tag (if frontmatter present)
  outputs:
    save_to: vault/digests/{date}_trading.md   # save LLM output here
  ---

  System prompt here — instructions for the LLM. Can use `{input.X}`
  placeholders + `{context.rag}`, `{context.vault_recent}`, etc.

CLI:
  python skills.py list
  python skills.py run trading-digest --days 7
"""
from __future__ import annotations
import json, re, sys, time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT      = Path(__file__).resolve().parent.parent
SKILLS    = ROOT / "skills"
VAULT     = ROOT / "data" / "vault"
DISTILLED = VAULT / "distilled"
DIGESTS   = VAULT / "digests"
OLLAMA    = "http://127.0.0.1:11434"

DEFAULT_MODEL = "qwen2.5:14b"
DEFAULT_TIMEOUT = 600  # 10 min per skill — they can be long

# Stop infrastructure — module-level event flag; STOP API sets it,
# run_skill() checks between chunks while streaming from Ollama.
import threading as _threading
_stop_event = _threading.Event()
_current_skill: dict = {"name": None, "started_at": 0.0}


def request_stop_skill() -> dict:
    """Signal the running skill to abort ASAP. Stream stops on next chunk."""
    if not _current_skill.get("name"):
        return {"ok": False, "error": "no skill running"}
    _stop_event.set()
    return {"ok": True, "stopping": _current_skill["name"]}


def current_skill_status() -> dict:
    """For UI: what's running right now."""
    return {
        "name":          _current_skill.get("name"),
        "started_at":    _current_skill.get("started_at"),
        "stop_requested": _stop_event.is_set(),
    }


# ---------------------------------------------------------------------------
# Skill parser
# ---------------------------------------------------------------------------
_FM = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def _parse_yaml_lite(text: str) -> dict:
    """Tiny YAML subset: key: value (str/int/bool), lists, nested dicts via indent.

    No external dependency — keeps brain portable.
    Supports:
      key: value
      key:
        - item1
        - item2
      key:
        sub: val
    """
    out: dict[str, Any] = {}
    stack: list[tuple[int, dict | list]] = [(0, out)]
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        indent = len(raw) - len(raw.lstrip())
        # Pop stack to current indent
        while stack and stack[-1][0] > indent:
            stack.pop()
        parent = stack[-1][1]
        line = raw.lstrip()
        if line.startswith("- "):
            item = _parse_value(line[2:].strip())
            if isinstance(parent, list):
                parent.append(item)
            elif isinstance(parent, dict):
                # Shouldn't happen if YAML well-formed; ignore
                pass
            i += 1
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if not val:
                # Block scalar — peek next line indent
                next_indent = None
                for j in range(i + 1, len(lines)):
                    if lines[j].strip():
                        next_indent = len(lines[j]) - len(lines[j].lstrip())
                        next_line = lines[j].lstrip()
                        break
                else:
                    next_indent = indent
                    next_line = ""
                if next_indent is not None and next_line.startswith("- "):
                    new = []
                else:
                    new = {}
                if isinstance(parent, dict):
                    parent[key] = new
                stack.append((next_indent or indent + 2, new))
            else:
                if isinstance(parent, dict):
                    parent[key] = _parse_value(val)
        i += 1
    return out


def _parse_value(v: str) -> Any:
    v = v.strip()
    if v.lower() in ("true", "yes"): return True
    if v.lower() in ("false", "no"): return False
    if v.lower() in ("null", "none", ""): return None
    if v.startswith('"') and v.endswith('"'): return v[1:-1]
    if v.startswith("'") and v.endswith("'"): return v[1:-1]
    try:
        if "." in v: return float(v)
        return int(v)
    except ValueError:
        return v


def parse_skill(text: str) -> dict:
    m = _FM.match(text)
    if not m:
        return {"meta": {}, "prompt": text.strip()}
    meta = _parse_yaml_lite(m.group(1))
    prompt = m.group(2).strip()
    return {"meta": meta, "prompt": prompt}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def list_skills() -> list[dict]:
    if not SKILLS.exists():
        return []
    out = []
    for p in sorted(SKILLS.glob("*.md")):
        try:
            s = parse_skill(p.read_text(encoding="utf-8"))
            meta = s.get("meta") or {}
            out.append({
                "file":        p.name,
                "name":        meta.get("name", p.stem),
                "description": meta.get("description", ""),
                "model":       meta.get("model", DEFAULT_MODEL),
                "inputs":      meta.get("inputs") or {},
                "outputs":     meta.get("outputs") or {},
            })
        except Exception as e:
            out.append({"file": p.name, "name": p.stem, "error": str(e)})
    return out


def _gather_context(spec: dict, inputs: dict) -> dict:
    """Run context gatherers declared in skill front-matter."""
    ctx: dict[str, Any] = {}
    items = spec.get("context") or []
    if isinstance(items, dict):
        items = [items]  # tolerate dict form
    if not isinstance(items, list):
        return ctx

    for entry in items:
        if not isinstance(entry, dict):
            continue
        for kind, arg in entry.items():
            if isinstance(arg, str):
                arg = _format(arg, inputs, ctx)
            try:
                if kind == "rag":
                    sys.path.insert(0, str(ROOT / "pipeline"))
                    import importlib
                    rag = importlib.import_module("rag")
                    hits = rag.search(str(arg), 8)
                    ctx["rag"] = "\n\n".join(
                        f"[{h['pdf']} p{h['page']} score={h['score']}]\n{h['text']}"
                        for h in hits
                    )
                elif kind == "vault_recent":
                    n = int(arg) if arg else 10
                    files = sorted(DISTILLED.glob("*.md"),
                                   key=lambda p: p.stat().st_mtime, reverse=True)[:n]
                    ctx["vault_recent"] = "\n\n---\n\n".join(
                        f"# {f.name}\n{f.read_text(encoding='utf-8', errors='replace')[:2000]}"
                        for f in files
                    )
                elif kind == "vault_filter":
                    # Filename substring filter (case-insensitive)
                    needle = str(arg).lower()
                    files = [p for p in DISTILLED.glob("*.md")
                             if needle in p.name.lower()]
                    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                    files = files[:30]
                    ctx["vault_filter"] = "\n\n---\n\n".join(
                        f"# {f.name}\n{f.read_text(encoding='utf-8', errors='replace')[:2000]}"
                        for f in files
                    )
                elif kind == "inbox_count":
                    inbox = ROOT / "data" / "brain-raw" / "inbox"
                    ctx["inbox_count"] = len(list(inbox.glob("*"))) if inbox.exists() else 0
            except Exception as e:
                ctx[f"_{kind}_error"] = str(e)
    return ctx


_PH = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_.]*)\}")

def _format(template: str, inputs: dict, ctx: dict) -> str:
    """Substitute {input.X} / {context.Y} / {date} / {now} placeholders."""
    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key == "date":
            return datetime.now().strftime("%Y-%m-%d")
        if key == "now":
            return datetime.now().strftime("%Y-%m-%d_%H-%M")
        if key.startswith("input."):
            return str(inputs.get(key[6:], ""))
        if key.startswith("context."):
            return str(ctx.get(key[8:], ""))
        # Bare key — try inputs first, then ctx
        if key in inputs: return str(inputs[key])
        if key in ctx:    return str(ctx[key])
        return m.group(0)
    return _PH.sub(sub, template)


def run_skill(name: str, inputs: dict | None = None,
              model_override: str | None = None) -> dict:
    """Execute a skill end-to-end: gather context, call LLM, save output."""
    inputs = inputs or {}
    matches = [p for p in SKILLS.glob("*.md")
               if p.stem == name or p.name == name or p.name == f"{name}.md"]
    if not matches:
        return {"ok": False, "error": f"skill not found: {name}"}
    p = matches[0]
    spec = parse_skill(p.read_text(encoding="utf-8"))
    meta = spec.get("meta") or {}
    model = model_override or meta.get("model") or DEFAULT_MODEL

    # Apply input defaults
    declared_inputs = meta.get("inputs") or {}
    if isinstance(declared_inputs, dict):
        for k, v in declared_inputs.items():
            if k not in inputs and v is not None:
                inputs[k] = v

    # Build context, then format prompt
    t0 = time.time()
    _stop_event.clear()
    _current_skill["name"]       = name
    _current_skill["started_at"] = t0
    try:
        ctx = _gather_context(meta, inputs)
        prompt = _format(spec.get("prompt", ""), inputs, ctx)

        # Call Ollama with STREAMING — lets us abort mid-generation
        output = ""
        stopped = False
        try:
            r = requests.post(f"{OLLAMA}/api/chat", json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": True,
                "options": {"temperature": 0.3, "num_ctx": 16384},
            }, timeout=DEFAULT_TIMEOUT, stream=True)
            r.raise_for_status()
            for line in r.iter_lines(decode_unicode=True):
                if _stop_event.is_set():
                    stopped = True
                    try: r.close()
                    except Exception: pass
                    break
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    delta = (chunk.get("message") or {}).get("content", "")
                    if delta:
                        output += delta
                    if chunk.get("done"):
                        break
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            return {"ok": False, "error": f"LLM call failed: {e}",
                    "duration": round(time.time() - t0, 1)}

        if stopped:
            return {"ok": False, "error": "stopped by user",
                    "skill": name, "model": model,
                    "partial_output": output,
                    "duration": round(time.time() - t0, 1)}
    finally:
        _current_skill["name"]       = None
        _current_skill["started_at"] = 0.0
        _stop_event.clear()

    # Save output if configured
    saved_path = None
    outputs = meta.get("outputs") or {}
    save_to = outputs.get("save_to") if isinstance(outputs, dict) else None
    if save_to:
        path = _format(save_to, inputs, ctx)
        dest = ROOT / "data" / path if not Path(path).is_absolute() else Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(output, encoding="utf-8")
        saved_path = str(dest)

    return {
        "ok":       True,
        "skill":    name,
        "model":    model,
        "duration": round(time.time() - t0, 1),
        "output":   output,
        "saved_to": saved_path,
        "context_keys": list(ctx.keys()),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: skills.py list | run <name> [key=val ...]")
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "list":
        for s in list_skills():
            print(f"  {s['name']:<24} {s.get('description','')[:60]}")
    elif cmd == "run" and len(sys.argv) >= 3:
        name = sys.argv[2]
        kv = {}
        for arg in sys.argv[3:]:
            if "=" in arg:
                k, _, v = arg.partition("=")
                kv[k] = _parse_value(v)
        r = run_skill(name, kv)
        print(json.dumps({k: v for k, v in r.items() if k != "output"},
                          indent=2, ensure_ascii=False))
        if r.get("ok") and r.get("output"):
            print("\n--- OUTPUT ---")
            print(r["output"])
    else:
        print("bad args"); sys.exit(2)
