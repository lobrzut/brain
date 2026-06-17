"""Code indexer — RAG over user's source code projects.

Decisions:
  - Separate sqlite-vec DB (data/codedb/code.db) — don't pollute library/vault index.
  - Watched paths configured in data/code-watches.json (added via dashboard).
  - No watchdog/tree-sitter dependency (heavy). Instead:
      * Line-based chunker (60 lines per chunk, 10 overlap) — language-agnostic.
      * Regex-based symbol extractor (def/function/class) for the common langs.
      * Manual SCAN triggered from UI or CLI; user re-runs after edits.
  - Skip binaries, vendor dirs (node_modules, .venv, __pycache__, .git, build, dist).
  - Use same nomic-embed-text via Ollama as library index — consistent retrieval.

CLI:
  python codeindex.py status                # show watched paths + counts
  python codeindex.py add <path>            # add path to watch list
  python codeindex.py remove <path>         # remove path
  python codeindex.py scan [path]           # index all watched, or specific path
  python codeindex.py search "query"        # semantic search
"""
from __future__ import annotations
import json, re, sqlite3, struct, sys, time
from pathlib import Path
from typing import Iterator

import requests
import sqlite_vec

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT       = Path(__file__).resolve().parent.parent
CODE_DB    = ROOT / "data" / "codedb" / "code.db"
WATCHES    = ROOT / "data" / "code-watches.json"
STATUS_F   = ROOT / "data" / "code-status.json"
OLLAMA     = "http://127.0.0.1:11434"
EMBED_MODEL = "nomic-embed-text"
EMBED_DIM  = 768

# What we index
CODE_EXT = {
    # languages
    ".py", ".pyi",
    ".js", ".jsx", ".mjs", ".cjs",
    ".ts", ".tsx",
    ".lua", ".pine",        # TradingView Pine Script
    ".rs",
    ".go",
    ".sh", ".bash", ".zsh",
    ".ps1", ".psm1",
    ".rsc",                 # MikroTik RouterOS scripts
    ".java", ".kt", ".scala",
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp",
    ".cs",
    ".rb",
    ".php",
    ".swift",
    ".sql",
    # config / docs that often have meaningful code-adjacent context
    ".md", ".yaml", ".yml", ".toml", ".json", ".ini", ".cfg",
    ".html", ".css", ".scss",
    ".dockerfile", ".env.example",
}

# Skip these dirs entirely
SKIP_DIRS = {
    "node_modules", ".venv", "venv", "env", "__pycache__",
    ".git", ".hg", ".svn", ".idea", ".vscode",
    "build", "dist", "target", "out", "bin", "obj",
    ".next", ".nuxt", ".cache", ".pytest_cache", ".mypy_cache",
    ".tox", ".eggs", "site-packages",
    "ollama-models", "vault", "vectordb", "codedb", "brain-raw",
    # Specifically skip our own brain dirs to avoid re-indexing ourselves
}

# Limits
MAX_FILE_BYTES   = 256 * 1024     # 256 KB per file — skip massive generated files
CHUNK_LINES      = 60
CHUNK_OVERLAP    = 10
MAX_CHUNK_CHARS  = 4000


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------
def _open_db() -> sqlite3.Connection:
    CODE_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(CODE_DB)
    con.enable_load_extension(True)
    sqlite_vec.load(con)
    cur = con.cursor()
    cur.execute("""
      CREATE TABLE IF NOT EXISTS files (
        id        INTEGER PRIMARY KEY,
        watch     TEXT NOT NULL,
        rel_path  TEXT NOT NULL,
        abs_path  TEXT NOT NULL,
        lang      TEXT,
        size      INTEGER,
        mtime     REAL,
        symbols   TEXT,
        UNIQUE(abs_path)
      )
    """)
    cur.execute("""
      CREATE TABLE IF NOT EXISTS chunks (
        id          INTEGER PRIMARY KEY,
        file_id     INTEGER NOT NULL,
        line_start  INTEGER,
        line_end    INTEGER,
        text        TEXT NOT NULL,
        FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
      )
    """)
    cur.execute(f"""
      CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(
        embedding float[{EMBED_DIM}]
      )
    """)
    con.commit()
    return con


def _embed(text: str) -> list[float] | None:
    try:
        r = requests.post(f"{OLLAMA}/api/embeddings", json={
            "model": EMBED_MODEL, "prompt": text[:8000],
        }, timeout=60)
        r.raise_for_status()
        return r.json().get("embedding")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Symbol extraction (regex, language-aware)
# ---------------------------------------------------------------------------
_SYMBOL_PATTERNS = {
    ".py":  [r"^\s*(?:async\s+)?def\s+(\w+)", r"^\s*class\s+(\w+)"],
    ".js":  [r"function\s+(\w+)", r"class\s+(\w+)", r"const\s+(\w+)\s*=\s*(?:async\s+)?\("],
    ".ts":  [r"function\s+(\w+)", r"class\s+(\w+)", r"interface\s+(\w+)",
             r"export\s+(?:async\s+)?function\s+(\w+)"],
    ".tsx": [r"function\s+(\w+)", r"class\s+(\w+)", r"const\s+(\w+)\s*=\s*(?:async\s+)?\("],
    ".jsx": [r"function\s+(\w+)", r"class\s+(\w+)"],
    ".rs":  [r"fn\s+(\w+)", r"struct\s+(\w+)", r"enum\s+(\w+)", r"trait\s+(\w+)"],
    ".go":  [r"func\s+(?:\([^)]+\)\s+)?(\w+)", r"type\s+(\w+)\s+(?:struct|interface)"],
    ".java":[r"(?:public|private|protected)?\s*(?:static)?\s*(?:\w+\s+)*(\w+)\s*\("],
    ".c":   [r"^\s*(?:static\s+)?(?:\w+\s+\*?)+(\w+)\s*\(", r"^\s*struct\s+(\w+)\s*\{"],
    ".cpp": [r"^\s*(?:static\s+)?(?:\w+::)?(?:\w+\s+\*?)+(\w+)\s*\(", r"^\s*class\s+(\w+)"],
    ".pine":[r"\/\/@function\s+(\w+)", r"^(\w+)\s*\([^)]*\)\s*=>"],
    ".rsc": [r"^/(\S+)"],          # RouterOS section markers
    ".sh":  [r"^(?:function\s+)?(\w+)\s*\(\)"],
    ".ps1": [r"^\s*function\s+([\w-]+)"],
}


def _extract_symbols(text: str, ext: str) -> list[str]:
    patterns = _SYMBOL_PATTERNS.get(ext, [])
    if not patterns:
        return []
    found: list[str] = []
    for line in text.splitlines():
        for pat in patterns:
            for m in re.finditer(pat, line):
                sym = m.group(1)
                if sym and sym not in found and not sym.startswith("_"):
                    found.append(sym)
    return found[:50]   # cap to avoid bloat


# ---------------------------------------------------------------------------
# File walker
# ---------------------------------------------------------------------------
def _iter_code_files(root: Path) -> Iterator[Path]:
    """Walk root yielding code files, skipping vendor/build dirs."""
    if not root.exists():
        return
    if root.is_file():
        if root.suffix.lower() in CODE_EXT:
            yield root
        return
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        # Skip if any parent dir is in SKIP_DIRS
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() not in CODE_EXT:
            # Special-case Dockerfile etc.
            if p.name.lower() not in {"dockerfile", "makefile", ".env.example"}:
                continue
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        yield p


def _chunk_lines(text: str) -> list[tuple[int, int, str]]:
    """Split text by lines into overlapping chunks. Returns (line_start, line_end, text)."""
    lines = text.splitlines()
    out: list[tuple[int, int, str]] = []
    i = 0
    n = len(lines)
    if n == 0:
        return out
    while i < n:
        end = min(i + CHUNK_LINES, n)
        block = "\n".join(lines[i:end])[:MAX_CHUNK_CHARS]
        out.append((i + 1, end, block))
        if end >= n:
            break
        i += max(1, CHUNK_LINES - CHUNK_OVERLAP)
    return out


# ---------------------------------------------------------------------------
# Watch list
# ---------------------------------------------------------------------------
def load_watches() -> list[str]:
    if not WATCHES.exists():
        return []
    try:
        return json.loads(WATCHES.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_watches(paths: list[str]) -> None:
    WATCHES.parent.mkdir(parents=True, exist_ok=True)
    WATCHES.write_text(json.dumps(sorted(set(paths)), indent=2), encoding="utf-8")


def add_watch(path: str) -> dict:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return {"ok": False, "error": f"path does not exist: {p}"}
    paths = load_watches()
    s = str(p)
    if s in paths:
        return {"ok": True, "already": True, "path": s}
    paths.append(s)
    save_watches(paths)
    return {"ok": True, "path": s}


def remove_watch(path: str) -> dict:
    p = str(Path(path).expanduser().resolve())
    paths = [x for x in load_watches() if x != p]
    save_watches(paths)
    return {"ok": True, "path": p}


# ---------------------------------------------------------------------------
# Indexer
# ---------------------------------------------------------------------------
def _write_status(state: str, **kv) -> None:
    s = {"state": state, "updated_at": time.time(), **kv}
    STATUS_F.parent.mkdir(parents=True, exist_ok=True)
    STATUS_F.write_text(json.dumps(s, indent=2), encoding="utf-8")


def scan(specific_path: str | None = None,
         model: str = EMBED_MODEL,
         progress_cb=None) -> dict:
    """Index all watched paths (or one specific). Skips files unchanged since last scan."""
    watches = [specific_path] if specific_path else load_watches()
    if not watches:
        _write_status("idle", message="no watched paths")
        return {"ok": False, "error": "no watched paths — add one first"}

    con = _open_db()
    cur = con.cursor()
    t0 = time.time()
    total_files = 0
    new_files = 0
    new_chunks = 0
    skipped = 0
    errors = 0

    for watch_path in watches:
        watch = Path(watch_path)
        if not watch.exists():
            continue
        files = list(_iter_code_files(watch))
        total_files += len(files)
        for i, f in enumerate(files):
            try:
                stat = f.stat()
                rel = str(f.relative_to(watch)) if f != watch else f.name
                # Check if unchanged
                cur.execute("SELECT id, mtime FROM files WHERE abs_path = ?", (str(f),))
                row = cur.fetchone()
                if row and abs(row[1] - stat.st_mtime) < 1.0 and row[1] >= stat.st_mtime:
                    skipped += 1
                    continue

                text = f.read_text(encoding="utf-8", errors="replace")
                if not text.strip():
                    skipped += 1
                    continue

                ext = f.suffix.lower()
                symbols = _extract_symbols(text, ext)

                # Delete old chunks for this file
                if row:
                    file_id = row[0]
                    cur.execute("SELECT id FROM chunks WHERE file_id = ?", (file_id,))
                    old_ids = [r[0] for r in cur.fetchall()]
                    for cid in old_ids:
                        cur.execute("DELETE FROM chunks_vec WHERE rowid = ?", (cid,))
                    cur.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
                    cur.execute("""UPDATE files SET watch=?, rel_path=?, lang=?,
                                   size=?, mtime=?, symbols=? WHERE id=?""",
                                (watch_path, rel, ext, stat.st_size, stat.st_mtime,
                                 json.dumps(symbols), file_id))
                else:
                    cur.execute("""INSERT INTO files (watch, rel_path, abs_path, lang,
                                   size, mtime, symbols) VALUES (?,?,?,?,?,?,?)""",
                                (watch_path, rel, str(f), ext, stat.st_size,
                                 stat.st_mtime, json.dumps(symbols)))
                    file_id = cur.lastrowid
                    new_files += 1

                # Chunk + embed
                for line_start, line_end, chunk_text in _chunk_lines(text):
                    # Prepend filename + symbols to make matches more discriminative
                    enriched = f"// file: {rel}\n"
                    if symbols:
                        enriched += f"// symbols: {', '.join(symbols[:10])}\n"
                    enriched += chunk_text
                    emb = _embed(enriched)
                    if emb is None:
                        errors += 1
                        continue
                    cur.execute("""INSERT INTO chunks (file_id, line_start, line_end, text)
                                   VALUES (?,?,?,?)""",
                                (file_id, line_start, line_end, chunk_text))
                    chunk_id = cur.lastrowid
                    blob = struct.pack(f"{EMBED_DIM}f", *emb)
                    cur.execute("INSERT INTO chunks_vec(rowid, embedding) VALUES (?,?)",
                                (chunk_id, blob))
                    new_chunks += 1

                if (i + 1) % 10 == 0:
                    con.commit()
                    _write_status("indexing", done=i + 1, total=len(files),
                                  current=rel, new_chunks=new_chunks)
                    if progress_cb:
                        progress_cb(i + 1, len(files), rel)
            except Exception as e:
                errors += 1
                continue
        con.commit()

    con.close()
    duration = round(time.time() - t0, 1)
    result = {
        "ok": True, "total_files": total_files, "new_files": new_files,
        "new_chunks": new_chunks, "skipped": skipped, "errors": errors,
        "duration": duration,
    }
    _write_status("idle", **result)
    return result


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def search(query: str, top_k: int = 10, lang: str | None = None) -> list[dict]:
    if not CODE_DB.exists():
        return []
    emb = _embed(query)
    if emb is None:
        return []
    con = _open_db()
    cur = con.cursor()
    blob = struct.pack(f"{EMBED_DIM}f", *emb)
    where = ""
    params: list = [blob, top_k * 3]
    if lang:
        where = " AND f.lang = ?"
        params.insert(1, lang)
    sql = f"""
      SELECT c.id, c.line_start, c.line_end, c.text, f.rel_path, f.lang, f.symbols,
             v.distance
      FROM chunks_vec v
      JOIN chunks c ON c.id = v.rowid
      JOIN files f  ON f.id = c.file_id
      WHERE v.embedding MATCH ?{where}
      ORDER BY v.distance
      LIMIT ?
    """
    cur.execute(sql, params)
    rows = cur.fetchall()
    out = []
    for row in rows[:top_k]:
        cid, ls, le, text, rel, lang_, sym_json, dist = row
        try:
            syms = json.loads(sym_json or "[]")
        except Exception:
            syms = []
        out.append({
            "file":    rel,
            "lang":    lang_,
            "lines":   f"{ls}-{le}",
            "score":   round(1.0 - float(dist), 4),
            "symbols": syms[:8],
            "text":    text[:600],
        })
    con.close()
    return out


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
def status() -> dict:
    s: dict = {"watches": load_watches(), "files": 0, "chunks": 0, "langs": {}}
    if STATUS_F.exists():
        try:
            s.update(json.loads(STATUS_F.read_text(encoding="utf-8")))
        except Exception:
            pass
    if CODE_DB.exists():
        con = _open_db()
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM files")
        s["files"] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM chunks")
        s["chunks"] = cur.fetchone()[0]
        cur.execute("SELECT lang, COUNT(*) FROM files GROUP BY lang")
        s["langs"] = dict(cur.fetchall())
        con.close()
    s["db_path"] = str(CODE_DB)
    return s


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: codeindex.py status | add <path> | remove <path> | scan [path] | search <query>")
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "status":
        print(json.dumps(status(), indent=2, ensure_ascii=False))
    elif cmd == "add" and len(sys.argv) >= 3:
        print(json.dumps(add_watch(sys.argv[2]), indent=2))
    elif cmd == "remove" and len(sys.argv) >= 3:
        print(json.dumps(remove_watch(sys.argv[2]), indent=2))
    elif cmd == "scan":
        path = sys.argv[2] if len(sys.argv) >= 3 else None
        r = scan(path, progress_cb=lambda i, n, f: print(f"  [{i}/{n}] {f}"))
        print(json.dumps(r, indent=2))
    elif cmd == "search" and len(sys.argv) >= 3:
        q = " ".join(sys.argv[2:])
        for h in search(q):
            print(f"\n## {h['file']} L{h['lines']} ({h['lang']}) score={h['score']}")
            if h['symbols']:
                print(f"   symbols: {', '.join(h['symbols'])}")
            print(h['text'][:300])
    else:
        print("bad args"); sys.exit(2)
