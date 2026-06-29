"""RAG over data/library/ — PDF chunker + embedder + sqlite-vec index.

Usage:
  python rag.py index               # (re)index all PDFs in data/library/
  python rag.py search "query…"     # semantic search, prints top-k chunks
  python rag.py status              # how many chunks, which PDFs indexed
  python rag.py clear               # drop the index
"""
from __future__ import annotations
import argparse, json, os, shutil, sqlite3, struct, sys, tempfile, time, zipfile
from pathlib import Path
import requests

# Force UTF-8 stdout/stderr — Windows cp1252 crashes on Polish chars like 'ł' in filenames
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import fitz  # PyMuPDF
except ImportError:
    print("ERROR: pymupdf not installed. pip install pymupdf", file=sys.stderr); sys.exit(1)
try:
    import sqlite_vec
except ImportError:
    print("ERROR: sqlite-vec not installed. pip install sqlite-vec", file=sys.stderr); sys.exit(1)

# Optional extras — degrade gracefully if missing
try: from ebooklib import epub  # type: ignore
except ImportError: epub = None
try: from docx import Document as DocxDocument  # type: ignore
except ImportError: DocxDocument = None
try: from bs4 import BeautifulSoup  # type: ignore
except ImportError: BeautifulSoup = None
try: import py7zr  # type: ignore
except ImportError: py7zr = None
try: import mobi as mobi_lib  # type: ignore
except ImportError: mobi_lib = None

ROOT = Path(__file__).resolve().parent.parent
from paths import data_root  # noqa: E402
_DATA = data_root()
LIBRARY = _DATA / "library"
VAULT   = _DATA / "vault"
VECTORDB = _DATA / "vectordb"
INDEX_DB = VECTORDB / "library.db"
STATUS_FILE = _DATA / "rag-status.json"

def _resolve_ollama_url() -> str:
    env = os.environ.get("OLLAMA_HOST")
    if env:
        return env if env.startswith("http") else f"http://{env}"
    opt = Path(__file__).resolve().parent.parent / "data" / "options.json"
    if opt.exists():
        try:
            d = json.loads(opt.read_text(encoding="utf-8"))
            u = (d.get("ollama_url") or "").strip()
            if u:
                return u if u.startswith("http") else f"http://{u}"
        except Exception:
            pass
    return "http://127.0.0.1:11434"


OLLAMA_URL  = _resolve_ollama_url()
OLLAMA_HOST = OLLAMA_URL.replace("http://", "").replace("https://", "")
EMBED_MODEL = os.environ.get("BRAIN_EMBED_MODEL", "nomic-embed-text")
EMBED_DIMS = 768  # nomic-embed-text / nomic-embed-text-v1.5 — same dim either backend

# Embedding backend: "fastembed" (default, in-process ONNX, no GPU/Ollama needed)
# or "ollama" (HTTP call to a running Ollama, e.g. to match an existing GPU setup).
EMBED_BACKEND = os.environ.get("BRAIN_EMBED_BACKEND", "fastembed").strip().lower()
_FASTEMBED_MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"
_fastembed_model = None  # lazy-loaded singleton (first call pays the ~530MB model load)


def _get_fastembed_model():
    global _fastembed_model
    if _fastembed_model is None:
        from fastembed import TextEmbedding
        _fastembed_model = TextEmbedding(_FASTEMBED_MODEL_NAME)
    return _fastembed_model

CHUNK_CHAR  = 1800
CHUNK_OVERLAP = 200


# ---------------------------------------------------------------------------
def write_status(state: dict) -> None:
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = time.time()
    STATUS_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def read_status() -> dict:
    if STATUS_FILE.exists():
        try: return json.loads(STATUS_FILE.read_text(encoding="utf-8-sig"))
        except Exception: pass
    return {"state": "idle"}


# ---------------------------------------------------------------------------
def _open_db() -> sqlite3.Connection:
    VECTORDB.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(INDEX_DB))
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    db.execute("""CREATE TABLE IF NOT EXISTS chunks (
        id INTEGER PRIMARY KEY,
        pdf_path TEXT NOT NULL,
        pdf_name TEXT NOT NULL,
        page_num INTEGER NOT NULL,
        chunk_idx INTEGER NOT NULL,
        text TEXT NOT NULL,
        char_count INTEGER NOT NULL
    )""")
    db.execute(f"""CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(
        embedding float[{EMBED_DIMS}]
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_chunks_pdf ON chunks(pdf_path)")
    return db


# ---------------------------------------------------------------------------
SUPPORTED_EXT = {".pdf", ".epub", ".mobi", ".azw", ".azw3",
                 ".docx", ".txt", ".md", ".html", ".htm"}
ARCHIVE_EXT   = {".zip", ".7z"}


def _extract_pdf(path: Path) -> list[tuple[int, str]]:
    pages = []
    with fitz.open(str(path)) as doc:
        for i, page in enumerate(doc, 1):
            text = (page.get_text("text") or "").strip()
            if text:
                pages.append((i, text))
    return pages


def _extract_epub(path: Path) -> list[tuple[int, str]]:
    if epub is None or BeautifulSoup is None:
        raise RuntimeError("epub: install ebooklib + beautifulsoup4")
    book = epub.read_epub(str(path))
    pages = []
    chapter_i = 0
    for item in book.get_items():
        # Accept EpubHtml (chapters) — skip nav, cover, etc.
        if isinstance(item, epub.EpubHtml) and not isinstance(item, epub.EpubNav):
            chapter_i += 1
            try:
                soup = BeautifulSoup(item.get_content(), "html.parser")
                text = soup.get_text(" ", strip=True)
            except Exception:
                continue
            if text and len(text) > 20:
                pages.append((chapter_i, text))
    return pages


def _extract_mobi(path: Path) -> list[tuple[int, str]]:
    if mobi_lib is None:
        raise RuntimeError("mobi: install `mobi` package (best-effort for AZW/MOBI)")
    tmpdir, filepath = mobi_lib.extract(str(path))
    try:
        # mobi extracts to a temp dir as HTML/EPUB
        result = Path(filepath)
        if result.suffix.lower() == ".epub":
            return _extract_epub(result)
        # Otherwise, look for HTML files in temp dir
        pages = []
        for i, html_file in enumerate(sorted(Path(tmpdir).rglob("*.html")), 1):
            if BeautifulSoup is None:
                text = html_file.read_text(encoding="utf-8", errors="replace")
            else:
                soup = BeautifulSoup(html_file.read_bytes(), "html.parser")
                text = soup.get_text(" ", strip=True)
            if text and len(text) > 50:
                pages.append((i, text))
        return pages
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _extract_docx(path: Path) -> list[tuple[int, str]]:
    if DocxDocument is None:
        raise RuntimeError("docx: install python-docx")
    doc = DocxDocument(str(path))
    text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    return [(1, text)] if text else []


def _extract_text(path: Path) -> list[tuple[int, str]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    return [(1, text)] if text.strip() else []


def _extract_html(path: Path) -> list[tuple[int, str]]:
    if BeautifulSoup is None:
        return _extract_text(path)
    try:
        soup = BeautifulSoup(path.read_bytes(), "html.parser")
        text = soup.get_text(" ", strip=True)
        return [(1, text)] if text else []
    except Exception:
        return []


EXTRACTORS = {
    ".pdf":  _extract_pdf,
    ".epub": _extract_epub,
    ".mobi": _extract_mobi,
    ".azw":  _extract_mobi,
    ".azw3": _extract_mobi,
    ".docx": _extract_docx,
    ".txt":  _extract_text,
    ".md":   _extract_text,
    ".html": _extract_html,
    ".htm":  _extract_html,
}


def _extract_any(path: Path) -> list[tuple[int, str]]:
    ext = path.suffix.lower()
    fn = EXTRACTORS.get(ext)
    if not fn:
        return []
    return fn(path)


def _extract_archive(archive: Path, dest_dir: Path) -> int:
    """Extract supported archive types. Returns number of files extracted."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    ext = archive.suffix.lower()
    count = 0
    if ext == ".zip":
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest_dir)
            count = len(zf.namelist())
    elif ext == ".7z":
        if py7zr is None:
            raise RuntimeError("7z: install py7zr")
        with py7zr.SevenZipFile(archive) as zf:
            zf.extractall(dest_dir)
            count = len(zf.getnames())
    else:
        return 0
    return count


def _chunk_text(text: str, size: int = CHUNK_CHAR, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks. Tries to break at paragraph/sentence boundaries."""
    text = " ".join(text.split())  # collapse whitespace
    if len(text) <= size:
        return [text] if text else []
    chunks = []
    i = 0
    while i < len(text):
        end = min(i + size, len(text))
        # try break at sentence
        if end < len(text):
            for sep in (". ", "; ", "\n", " "):
                cut = text.rfind(sep, i + size // 2, end)
                if cut > 0:
                    end = cut + len(sep)
                    break
        chunks.append(text[i:end].strip())
        if end == len(text): break
        i = end - overlap
    return [c for c in chunks if c]


def _embed_batch(texts: list[str], is_query: bool = False) -> list[list[float]]:
    """Embed texts. Backend selected by BRAIN_EMBED_BACKEND (default: fastembed,
    in-process ONNX CPU, no GPU/Ollama needed). 'ollama' uses /api/embed on a
    running Ollama instead — same model lineage, useful to match an existing
    GPU-backed index (see EMBED_BACKEND docstring at top of file).

    is_query distinguishes search queries from indexed documents — nomic-embed
    models expect a "search_query: " / "search_document: " prefix for best
    retrieval quality. Ollama's nomic-embed-text bakes this into its model
    template already, so we only add it explicitly for the fastembed backend.
    """
    if EMBED_BACKEND == "ollama":
        r = requests.post(
            f"{OLLAMA_URL}/api/embed",
            json={"model": EMBED_MODEL, "input": texts},
            timeout=300,
        )
        if not r.ok:
            raise RuntimeError(f"ollama embed failed: {r.status_code} {r.text[:200]}")
        d = r.json()
        return d.get("embeddings") or d.get("embedding") or []

    prefix = "search_query: " if is_query else "search_document: "
    model = _get_fastembed_model()
    return [v.tolist() for v in model.embed([prefix + t for t in texts])]


def _vec_to_blob(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


# ---------------------------------------------------------------------------
def index_file(db: sqlite3.Connection, path: Path) -> int:
    """Index any supported file (PDF/EPUB/MOBI/DOCX/TXT/MD/HTML).
    Returns number of chunks indexed. Reuses 'page_num' for non-paged formats
    (e.g. EPUB chapter index, DOCX = 1)."""
    rel = str(path)
    # Remove previous chunks (re-index from scratch)
    cur = db.execute("SELECT id FROM chunks WHERE pdf_path = ?", (rel,))
    old_ids = [r[0] for r in cur.fetchall()]
    if old_ids:
        db.executemany("DELETE FROM chunks_vec WHERE rowid = ?", [(i,) for i in old_ids])
        db.execute("DELETE FROM chunks WHERE pdf_path = ?", (rel,))

    try:
        pages = _extract_any(path)
    except Exception as e:
        print(f"  [warn] extract failed for {path.name}: {e}", flush=True)
        return 0

    if not pages: return 0

    all_chunks = []
    for page_num, page_text in pages:
        for ci, chunk in enumerate(_chunk_text(page_text)):
            all_chunks.append((page_num, ci, chunk))

    if not all_chunks: return 0

    BATCH = 32
    total_written = 0
    for i in range(0, len(all_chunks), BATCH):
        batch = all_chunks[i:i+BATCH]
        texts = [c[2] for c in batch]
        embeds = _embed_batch(texts)
        if len(embeds) != len(batch):
            raise RuntimeError(f"embedding count mismatch: got {len(embeds)} for {len(batch)} chunks")
        for (page_num, chunk_idx, chunk_text), emb in zip(batch, embeds):
            cur = db.execute(
                "INSERT INTO chunks (pdf_path, pdf_name, page_num, chunk_idx, text, char_count) VALUES (?, ?, ?, ?, ?, ?)",
                (rel, path.name, page_num, chunk_idx, chunk_text, len(chunk_text)),
            )
            rowid = cur.lastrowid
            db.execute("INSERT INTO chunks_vec (rowid, embedding) VALUES (?, ?)",
                       (rowid, _vec_to_blob(emb)))
            total_written += 1
    db.commit()
    return total_written


# Back-compat alias
index_pdf = index_file


def _expand_archives(library: Path) -> int:
    """Auto-extract ZIP/7Z archives into sibling _extracted/ folder. Returns count extracted."""
    extracted = 0
    for arch in list(library.rglob("*")):
        if not arch.is_file(): continue
        if arch.suffix.lower() not in ARCHIVE_EXT: continue
        # destination: same dir + filename stem
        dest = arch.parent / f"_extracted_{arch.stem}"
        # Skip if already extracted (and archive not newer)
        if dest.exists() and dest.stat().st_mtime >= arch.stat().st_mtime:
            continue
        try:
            n = _extract_archive(arch, dest)
            print(f"  [archive] {arch.name} -> {n} files in {dest.name}", flush=True)
            extracted += 1
        except Exception as e:
            print(f"  [warn] archive {arch.name}: {e}", flush=True)
    return extracted


def _find_indexable(library: Path, vault: Path | None = None) -> list[Path]:
    """Walk library + vault, return all supported files for embedding."""
    out = []
    for p in library.rglob("*"):
        if not p.is_file(): continue
        if p.suffix.lower() in SUPPORTED_EXT:
            out.append(p)
    if vault and vault.exists():
        for p in vault.rglob("*.md"):
            if not p.is_file(): continue
            # Skip the chats/ subfolder (raw chat dumps from chat widget) to avoid double-indexing
            # Distilled notes ARE indexed — they're our extracted knowledge
            out.append(p)
    return sorted(out)


def run_index_all() -> dict:
    if not LIBRARY.exists():
        write_status({"state": "idle", "indexed": 0, "files": 0,
                      "message": "data/library/ does not exist"})
        return {"indexed": 0, "files": 0}

    # Step 1: extract any archives we haven't yet
    extracted = _expand_archives(LIBRARY)
    if extracted:
        print(f"[ok] extracted {extracted} archive(s)", flush=True)

    # Step 2: find indexable files (library + vault markdowns)
    files = _find_indexable(LIBRARY, VAULT)
    if not files:
        write_status({"state": "idle", "indexed": 0, "files": 0,
                      "message": "no indexable files in data/library/ or data/vault/"})
        return {"indexed": 0, "files": 0}

    write_status({"state": "indexing", "total_pdfs": len(files),
                  "done_pdfs": 0, "indexed_chunks": 0,
                  "started_at": time.time(), "model": EMBED_MODEL})

    db = _open_db()
    total_chunks = 0
    for i, f in enumerate(files):
        try:
            write_status({"state": "indexing", "total_pdfs": len(files),
                          "done_pdfs": i, "current": f.name,
                          "indexed_chunks": total_chunks,
                          "model": EMBED_MODEL})
            n = index_file(db, f)
            total_chunks += n
            tag = f.suffix.lower().lstrip(".")
            print(f"[ok] {f.name} ({tag}): {n} chunks", flush=True)
        except Exception as e:
            print(f"[ERR] {f.name}: {e}", flush=True)
    db.close()

    write_status({"state": "idle", "total_pdfs": len(files),
                  "done_pdfs": len(files), "indexed_chunks": total_chunks,
                  "finished_at": time.time(), "model": EMBED_MODEL,
                  "archives_extracted": extracted})
    return {"files": len(files), "indexed": total_chunks, "archives": extracted}


# ---------------------------------------------------------------------------
def search(query: str, top_k: int = 5, source: str = "all") -> list[dict]:
    """Hybrid search: semantic embedding + keyword match boost.

    source filter:
      - 'all'     (default) — search vault notes + library docs together
      - 'vault'   — only .md from vault/distilled/
      - 'library' — only PDF/EPUB/DOCX from library/

    Why hybrid: nomic-embed-text is English-centric. Mixed Polish/English queries
    ("tunel WireGuard MikroTik") get scattered embeddings. Literal keyword
    matches in filename/path/content give a strong signal we must use.
    """
    if not INDEX_DB.exists():
        return []
    db = _open_db()
    try:
        emb = _embed_batch([query], is_query=True)[0]
    except Exception:
        db.close()
        raise

    fetch_n = max(top_k * 3, 12)
    semantic_rows = db.execute("""
        SELECT chunks.id, chunks.pdf_name, chunks.pdf_path, chunks.page_num,
               chunks.chunk_idx, chunks.text, chunks_vec.distance
        FROM chunks_vec
        JOIN chunks ON chunks.id = chunks_vec.rowid
        WHERE chunks_vec.embedding MATCH ? AND k = ?
        ORDER BY chunks_vec.distance
    """, (_vec_to_blob(emb), fetch_n)).fetchall()

    # Source filter — vault = .md only, library = anything else
    def _matches_source(name: str) -> bool:
        if source == "all": return True
        is_md = name.lower().endswith(".md")
        if source == "vault":   return is_md
        if source == "library": return not is_md
        return True

    candidates: dict[int, dict] = {}
    for r in semantic_rows:
        if not _matches_source(r[1]):
            continue
        candidates[r[0]] = {
            "id": r[0], "pdf": r[1], "pdf_path": r[2],
            "page": r[3], "chunk_idx": r[4], "text": r[5],
            "sem_score": round(1 - r[6], 4),
            "kw_name_hits": 0, "kw_text_hits": 0,
        }

    # Tokenize query. Keep tokens >= 2 chars (CV, AI, ML, IP, VM are real keywords).
    # For 2-char tokens, require word-boundary match (avoid 'cv' matching 'discover').
    raw_terms = re_split_terms(query)
    stops = {"the", "and", "for", "with", "this", "that", "but",
             "konfiguracja", "ustawienia", "miedzy", "między", "jak",
             "lub", "albo", "oraz", "albo"}
    terms = [t for t in raw_terms if len(t) >= 2 and t.lower() not in stops][:8]

    def _name_match(name_lc: str, tl: str) -> bool:
        """Word-boundary match for short tokens (2-3 chars), substring for longer."""
        if len(tl) >= 4:
            return tl in name_lc
        # 2-3 char: match only if surrounded by non-letter (separator or start/end)
        import re
        return bool(re.search(rf"(?:^|[^a-z0-9]){re.escape(tl)}(?:[^a-z0-9]|$)", name_lc))

    if terms:
        # Keyword candidates from name + text. Use word-boundary for short terms.
        like_clauses_name = " OR ".join(["LOWER(pdf_name) LIKE ?"] * len(terms))
        like_clauses_text = " OR ".join(["LOWER(text) LIKE ?"] * len(terms))
        # For short terms include separator-flanked pattern for tighter filtering
        like_args = []
        for t in terms:
            tl = t.lower()
            if len(tl) <= 3:
                # SQL LIKE has no regex; use loose match here, refine via _name_match in Python
                like_args.append(f"%{tl}%")
            else:
                like_args.append(f"%{tl}%")
        kw_rows = db.execute(f"""
            SELECT id, pdf_name, pdf_path, page_num, chunk_idx, text
            FROM chunks
            WHERE ({like_clauses_name}) OR ({like_clauses_text})
            LIMIT ?
        """, (*like_args, *like_args, fetch_n * 2)).fetchall()
        for r in kw_rows:
            row_id = r[0]
            if row_id not in candidates:
                candidates[row_id] = {
                    "id": row_id, "pdf": r[1], "pdf_path": r[2],
                    "page": r[3], "chunk_idx": r[4], "text": r[5],
                    "sem_score": 0.0,
                    "kw_name_hits": 0, "kw_text_hits": 0,
                }

    # Score every candidate with strict boundary check (filters substring false positives)
    for c in candidates.values():
        name_lc = (c["pdf"] or "").lower()
        text_lc = (c["text"] or "").lower()
        for t in terms:
            tl = t.lower()
            if _name_match(name_lc, tl): c["kw_name_hits"] += 1
            if _name_match(text_lc, tl): c["kw_text_hits"] += 1

    # Recency + size boost for vault notes only.
    # Rationale: user's knowledge improves over time — a recent thoughtful note
    # is usually more relevant than an old one on the same topic. Larger notes
    # are also typically more substantive than 200-byte stubs.
    import math as _math
    now = time.time()
    for c in candidates.values():
        name_lc = (c["pdf"] or "").lower()
        if not name_lc.endswith(".md"):
            c["recency_boost"] = 0.0
            c["size_boost"]    = 0.0
            continue
        try:
            p = Path(c["pdf_path"])
            st = p.stat()
            age_days = max(0.0, (now - st.st_mtime) / 86400.0)
            size_b = st.st_size
        except Exception:
            c["recency_boost"] = 0.0
            c["size_boost"]    = 0.0
            continue
        # Recency: full boost <30d, linear decay to 0 at 730d (2 years).
        if age_days <= 30:
            rec = 0.25
        elif age_days >= 730:
            rec = 0.0
        else:
            rec = 0.25 * (1.0 - (age_days - 30) / 700.0)
        # Size: log scale, 0 at <500B (stub), max 0.20 at ≥8 KB.
        if size_b < 500:
            sz = -0.10  # actively penalise stubs/tiny notes
        else:
            sz = min(0.20, 0.20 * _math.log2(max(1.0, size_b / 500.0)) / 4.0)
        c["recency_boost"] = round(rec, 4)
        c["size_boost"]    = round(sz, 4)

    # Final score: semantic + keyword + recency/size signals
    for c in candidates.values():
        c["score"] = round(c["sem_score"]
                           + 0.40 * c["kw_name_hits"]
                           + 0.15 * c["kw_text_hits"]
                           + c.get("recency_boost", 0.0)
                           + c.get("size_boost",    0.0), 4)

    db.close()
    ranked = sorted(candidates.values(), key=lambda x: -x["score"])[:top_k]
    return ranked


def re_split_terms(query: str) -> list[str]:
    import re
    # Split on non-word chars, keep unicode letters
    return [w for w in re.split(r"\W+", query, flags=re.UNICODE) if w]


# ---------------------------------------------------------------------------
def status() -> dict:
    s = read_status()
    if INDEX_DB.exists():
        db = _open_db()
        chunks = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        pdfs = db.execute("SELECT COUNT(DISTINCT pdf_path) FROM chunks").fetchone()[0]
        files = [r[0] for r in db.execute("SELECT DISTINCT pdf_name FROM chunks ORDER BY pdf_name").fetchall()]
        db.close()
        s["index_chunks"] = chunks
        s["index_pdfs"] = pdfs
        s["files"] = files[:50]
    else:
        s["index_chunks"] = 0
        s["index_pdfs"] = 0
        s["files"] = []
    s["db_path"] = str(INDEX_DB)
    return s


def clear():
    if INDEX_DB.exists():
        INDEX_DB.unlink()
    if STATUS_FILE.exists():
        STATUS_FILE.unlink()


# ---------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("index", help="(re)index PDFs in data/library/")
    s = sub.add_parser("search", help="semantic search")
    s.add_argument("query")
    s.add_argument("--top-k", type=int, default=5)
    sub.add_parser("status")
    sub.add_parser("clear")
    args = p.parse_args()
    if args.cmd == "index":
        r = run_index_all()
        n = r.get("files", r.get("pdfs", 0))
        print(f"indexed {r['indexed']} chunks across {n} files"
              + (f" (extracted {r['archives']} archives)" if r.get("archives") else ""))
    elif args.cmd == "search":
        for hit in search(args.query, args.top_k):
            print(f"--- {hit['pdf']} p.{hit['page']} (score {hit['score']}) ---")
            print(hit["text"][:600])
            print()
    elif args.cmd == "status":
        print(json.dumps(status(), indent=2, ensure_ascii=False))
    elif args.cmd == "clear":
        clear(); print("cleared.")


if __name__ == "__main__":
    main()
