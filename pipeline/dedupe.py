"""Vault dedup — find near-duplicate markdown notes.

Two-stage verification to avoid topic-level false positives:
  1. Cosine similarity over MEAN embedding of all chunks per file
  2. Jaccard overlap on 5-gram word shingles (text-level confirmation)

A pair is a real candidate only if BOTH thresholds pass.

CLI:
  python dedupe.py scan       -> writes data/dedup-candidates.json
  python dedupe.py merge A B  -> archives loser (older), keeps winner
"""
from __future__ import annotations
import json, re, struct, sqlite3, sys
from pathlib import Path

import numpy as np
import sqlite_vec

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT      = Path(__file__).resolve().parent.parent
VAULT     = ROOT / "data" / "vault" / "distilled"
DB        = ROOT / "data" / "vectordb" / "library.db"
OUT       = ROOT / "data" / "dedup-candidates.json"
DISMISSED = ROOT / "data" / "dedup-dismissed.json"
ARCHIVE   = ROOT / "data" / "vault" / "_archive"


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------
def _mean_embedding_per_file() -> dict[str, np.ndarray]:
    """Return {filename: mean of all chunk embeddings (np.float32, L2-normalised)}"""
    con = sqlite3.connect(DB)
    con.enable_load_extension(True)
    sqlite_vec.load(con)
    cur = con.cursor()
    cur.execute("""
      SELECT c.pdf_name, v.embedding
      FROM chunks c JOIN chunks_vec v ON v.rowid = c.id
      WHERE c.pdf_name LIKE '%.md'
    """)
    bag: dict[str, list[np.ndarray]] = {}
    for name, blob in cur.fetchall():
        vec = np.frombuffer(blob, dtype=np.float32)
        bag.setdefault(name, []).append(vec)
    con.close()

    out: dict[str, np.ndarray] = {}
    for n, vs in bag.items():
        m = np.mean(vs, axis=0)
        nrm = np.linalg.norm(m)
        out[n] = m / nrm if nrm else m
    return out


_WORD = re.compile(r"\w+", re.UNICODE)

def _shingles(text: str, n: int = 5) -> set[str]:
    """5-gram word shingles for Jaccard. Lowercased, unicode-aware."""
    words = _WORD.findall(text.lower())
    if len(words) < n:
        return set(words)
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def _jaccard(a: str, b: str, n: int = 5) -> float:
    sa, sb = _shingles(a, n), _shingles(b, n)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


_DATE_RE  = re.compile(r"^(\d{4}-\d{2}-\d{2})_([a-z-]+)_(.+?)(_[0-9a-f]{8})?\.md$")

def _title_words(filename: str) -> set[str]:
    """Extract topic words from filename (drop date, source, hash, common boilerplate)."""
    m = _DATE_RE.match(filename)
    title = m.group(3) if m else filename.rsplit(".", 1)[0]
    words = {w for w in _WORD.findall(title.lower())
             if len(w) >= 3 and w not in {"the", "and", "for", "with", "code", "new", "conversation"}}
    return words


def _title_jaccard(a: str, b: str) -> float:
    ta, tb = _title_words(a), _title_words(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _load_dismissed() -> set[tuple[str, str]]:
    if not DISMISSED.exists():
        return set()
    try:
        raw = json.loads(DISMISSED.read_text(encoding="utf-8"))
        return {tuple(sorted(p)) for p in raw}
    except Exception:
        return set()


def _save_dismissed(pairs: set[tuple[str, str]]) -> None:
    DISMISSED.parent.mkdir(parents=True, exist_ok=True)
    DISMISSED.write_text(
        json.dumps([list(p) for p in sorted(pairs)], indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def scan(cosine_thresh: float = 0.90,
         jaccard_thresh: float = 0.15,
         title_thresh: float = 0.40,
         max_candidates: int = 500) -> dict:
    """Full scan. Writes JSON to disk + returns it.

    A pair qualifies when:
      cosine(mean_emb)        >= cosine_thresh   (cheap pre-filter)
      AND ( jaccard(text 5-gram) >= jaccard_thresh
            OR jaccard(title words) >= title_thresh )

    Defaults calibrated for our vault (small distilled summaries: 300-500B):
      cosine  0.90 — pre-filter
      jaccard 0.15 — text overlap (low because distillates are short + paraphrased)
      title   0.40 — strong topic overlap in filename (catches near-dupes
                     even when text was differently phrased)
    """
    means = _mean_embedding_per_file()
    if len(means) < 2:
        result = {"pairs": [], "scanned": len(means), "cosine_thresh": cosine_thresh,
                  "jaccard_thresh": jaccard_thresh}
        OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        return result

    names = sorted(means.keys())
    M = np.stack([means[n] for n in names]).astype(np.float32)
    sim = M @ M.T
    np.fill_diagonal(sim, 0.0)

    # Pre-filter pairs by cosine, sort desc, cap at max_candidates*3 (cheap)
    iu = np.triu_indices(len(names), k=1)
    pairs = [(float(sim[i, j]), int(i), int(j))
             for i, j in zip(iu[0], iu[1]) if sim[i, j] >= cosine_thresh]
    pairs.sort(reverse=True)
    pairs = pairs[: max_candidates * 3]

    dismissed = _load_dismissed()
    results = []
    text_cache: dict[str, str] = {}

    for cos, i, j in pairs:
        a, b = names[i], names[j]
        key = tuple(sorted([a, b]))
        if key in dismissed:
            continue
        pa, pb = VAULT / a, VAULT / b
        if not (pa.exists() and pb.exists()):
            continue
        try:
            ta = text_cache.setdefault(a, pa.read_text(encoding="utf-8", errors="replace"))
            tb = text_cache.setdefault(b, pb.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        jac   = _jaccard(ta, tb)
        tjac  = _title_jaccard(a, b)
        if jac < jaccard_thresh and tjac < title_thresh:
            continue
        # Combined score: cosine + text overlap + title overlap, weighted
        score = 0.40 * cos + 0.35 * jac + 0.25 * tjac
        results.append({
            "a": a, "b": b,
            "cosine":   round(cos, 4),
            "jaccard":  round(jac, 4),
            "title_jac": round(tjac, 4),
            "score":    round(score, 4),
            "size_a":   pa.stat().st_size,
            "size_b":   pb.stat().st_size,
            "preview_a": ta[:500].replace("\n", " "),
            "preview_b": tb[:500].replace("\n", " "),
        })
        if len(results) >= max_candidates * 2:
            break

    # Sort by combined score and cap
    results.sort(key=lambda p: -p["score"])
    results = results[:max_candidates]

    out = {
        "pairs": results,
        "scanned": len(names),
        "cosine_thresh":  cosine_thresh,
        "jaccard_thresh": jaccard_thresh,
        "title_thresh":   title_thresh,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def load_candidates() -> dict:
    if OUT.exists():
        try:
            return json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"pairs": [], "scanned": 0, "cosine_thresh": None, "jaccard_thresh": None}


def merge(a: str, b: str, strategy: str = "newer") -> dict:
    """Archive the loser, keep the winner.
       strategy = 'newer' (by YYYY-MM-DD prefix) | 'longer' (by size).
       Loser is moved to data/vault/_archive/.
    """
    pa = VAULT / a
    pb = VAULT / b
    if not pa.exists() or not pb.exists():
        return {"ok": False, "error": "file missing"}

    if strategy == "longer":
        winner = pa if pa.stat().st_size >= pb.stat().st_size else pb
    else:
        da = re.match(r"(\d{4}-\d{2}-\d{2})", a)
        db = re.match(r"(\d{4}-\d{2}-\d{2})", b)
        sa = da.group(1) if da else ""
        sb = db.group(1) if db else ""
        winner = pa if sa >= sb else pb
    loser = pb if winner == pa else pa

    ARCHIVE.mkdir(parents=True, exist_ok=True)
    dest = ARCHIVE / loser.name
    if dest.exists():
        dest = ARCHIVE / f"{loser.stem}__{int(loser.stat().st_mtime)}{loser.suffix}"
    loser.rename(dest)

    # Drop from candidates JSON so UI refresh removes the pair
    cands = load_candidates()
    cands["pairs"] = [p for p in cands.get("pairs", [])
                      if not ({p["a"], p["b"]} == {a, b})]
    OUT.write_text(json.dumps(cands, indent=2, ensure_ascii=False), encoding="utf-8")

    return {"ok": True, "kept": winner.name, "archived": str(dest)}


def dismiss(a: str, b: str) -> dict:
    pair = tuple(sorted([a, b]))
    dis = _load_dismissed()
    dis.add(pair)
    _save_dismissed(dis)

    cands = load_candidates()
    cands["pairs"] = [p for p in cands.get("pairs", [])
                      if not ({p["a"], p["b"]} == {a, b})]
    OUT.write_text(json.dumps(cands, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: dedupe.py scan | merge A B | dismiss A B")
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "scan":
        r = scan()
        print(f"Scanned {r['scanned']} files, {len(r['pairs'])} dedup candidates")
        for p in r["pairs"][:5]:
            print(f"  cos={p['cosine']} jac={p['jaccard']}")
            print(f"    {p['a']}")
            print(f"    {p['b']}")
    elif cmd == "merge" and len(sys.argv) >= 4:
        print(merge(sys.argv[2], sys.argv[3]))
    elif cmd == "dismiss" and len(sys.argv) >= 4:
        print(dismiss(sys.argv[2], sys.argv[3]))
    else:
        print("bad args"); sys.exit(2)
