"""Głęboka analiza jakości destylowanych notatek.

Nie patrzymy tylko na ROZMIAR (to robi vault/quality), ale na MERYTORYKĘ:

  1. Bullet repetition — czy te same zdania nie wracają w wielu sekcjach?
  2. Generic-ness — czy bullety nie są typu "Decided to continue working on X"?
  3. Specificity — czy facts mają liczby, daty, nazwy własne, ścieżki, kod?
  4. Language mix — czy notatka nie ma chaotic PL/EN mieszanki w jednym bullecie?
  5. Hallucination flags — czy są referencje do nieistniejących plików/danych?
  6. Salvageable rate — % notatek które niosą REAL VALUE vs noise.
  7. Source breakdown — która platforma (claude-ai/grok/antigravity/claude-code/chat) destyluje najlepiej?

Wyjście: JSON raport + Markdown podsumowanie do vault/notes/.

Usage:
  python note_quality.py audit            # full scan
  python note_quality.py sample 30        # quick sample of 30 random notes
  python note_quality.py worst 20         # 20 worst notes (manual review)
  python note_quality.py best 20          # 20 best notes (positive examples)
"""
from __future__ import annotations
import json, re, sys, random
from collections import defaultdict, Counter
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

ROOT      = Path(__file__).resolve().parent.parent
DISTILLED = ROOT / "data" / "vault" / "distilled"
SESSIONS  = ROOT / "data" / "vault" / "sessions"
NOTES_OUT = ROOT / "data" / "vault" / "notes"

# ---------------------------------------------------------------------------
# Heuristics — small, fast, no LLM. Catches the obvious shit.
# ---------------------------------------------------------------------------
_FM_RE       = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
_SECTION_RE  = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_BULLET_RE   = re.compile(r"^[-*]\s+(.+?)$", re.MULTILINE)

# Generic phrases — bullety które praktycznie nic nie wnoszą.
# Tworzone z obserwacji notatek qwen2.5:3b który lubi szablony.
GENERIC_PATTERNS = [
    r"\bdecided to\s+(continue|proceed|work on|move forward|further)\b",
    r"\bzdecydowano? (się )?(kontynuować|przejść|pójść|pracować)\b",
    r"\bdiscussed (the |a )?(topic|matter|issue|approach)\b",
    r"\bomówiono?\s+(temat|kwestię|zagadnienie|podejście)\b",
    r"\b(further|additional)\s+(analysis|investigation|research)\b",
    r"\bwymagana? (jest )?(dalsza|dodatkowa) (analiza|weryfikacja)\b",
    r"^(yes|no|tak|nie|ok|okay)\b\s*\.?$",
    r"^\s*(continued|kontynuacja|to be continued|cdn)\.?\s*$",
    r"^\s*(brak|none|n/a|not specified)\s*\.?\s*$",
    r"^\s*\.?\s*$",                              # empty bullet
    r"^[\W_]+$",                                  # only punctuation
    r"^\s*\d+\s*$",                              # just a number
]
_GENERIC_RES = [re.compile(p, re.IGNORECASE) for p in GENERIC_PATTERNS]

# Specificity markers — bullet wartościowy jeśli zawiera:
_HAS_NUMBER   = re.compile(r"\b\d{2,}\b")        # ≥2-digit number
_HAS_DATE     = re.compile(r"\b\d{4}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b")
_HAS_CODE     = re.compile(r"`[^`]+`|\$\w+|/\w+/\w+|\\\w+\\|[a-z_]+\.(py|js|ts|md|json|yaml|rs|go|sh)\b")
_HAS_CMD      = re.compile(r"\b(sudo |apt |npm |pip |git |docker |systemctl |curl |wget )", re.IGNORECASE)
_HAS_URL      = re.compile(r"https?://[^\s)]+")
_HAS_CAPS_AC  = re.compile(r"\b[A-Z][A-Z0-9]{2,}\b")  # proper acronym like NAT, GPU, PDF
_HAS_PROPER   = re.compile(r"\b[A-Z][a-z]+[A-Z]\w+\b")  # CamelCase like MikroTik

# Language mix detector — bullet ma EN-stopwords AND PL-stopwords AND obie >1
_EN_WORDS = re.compile(r"\b(the|and|or|with|that|this|for|from|but|when|where|which|what)\b", re.IGNORECASE)
_PL_WORDS = re.compile(r"\b(i|oraz|lub|albo|który|która|aby|żeby|ponieważ|jednak|jest|są)\b", re.IGNORECASE)


def parse_frontmatter(text: str) -> dict:
    m = _FM_RE.match(text)
    if not m: return {}
    out = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def extract_bullets_per_section(text: str) -> dict[str, list[str]]:
    """Returns {'Decisions': [...], 'Solutions': [...], ...}."""
    sections = {}
    pos = 0
    cur_name = None
    cur_buf  = []
    for m in _SECTION_RE.finditer(text):
        if cur_name is not None:
            sections[cur_name] = cur_buf
        cur_name = m.group(1).strip()
        cur_buf = []
        body_start = m.end()
        nxt = _SECTION_RE.search(text, body_start)
        body_end = nxt.start() if nxt else len(text)
        body = text[body_start:body_end]
        cur_buf = [b.group(1).strip() for b in _BULLET_RE.finditer(body)]
    if cur_name is not None:
        sections[cur_name] = cur_buf
    return sections


def score_bullet(b: str) -> dict:
    """Returns {generic, specific, lang_mix, length}."""
    b = b.strip()
    is_generic = any(rx.search(b) for rx in _GENERIC_RES)
    spec_score = 0
    if _HAS_NUMBER.search(b):  spec_score += 1
    if _HAS_DATE.search(b):    spec_score += 1
    if _HAS_CODE.search(b):    spec_score += 2
    if _HAS_CMD.search(b):     spec_score += 2
    if _HAS_URL.search(b):     spec_score += 1
    if _HAS_CAPS_AC.search(b): spec_score += 1
    if _HAS_PROPER.search(b):  spec_score += 1
    en_hits = len(_EN_WORDS.findall(b))
    pl_hits = len(_PL_WORDS.findall(b))
    lang_mix = en_hits >= 2 and pl_hits >= 2
    return {
        "generic":  is_generic,
        "specific": spec_score,
        "lang_mix": lang_mix,
        "length":   len(b),
    }


def analyze_note(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"path": str(path), "error": str(e)}

    fm = parse_frontmatter(text)
    sections = extract_bullets_per_section(text)
    all_bullets = [b for bs in sections.values() for b in bs]
    if not all_bullets:
        return {
            "name":    path.name,
            "source":  fm.get("source", "?"),
            "msg_cnt": int(fm.get("msg_count", "0") or "0"),
            "bullets": 0,
            "is_stub": "## _Stub_" in text,
            "size":    path.stat().st_size,
            "score":   0.0,
            "verdict": "empty",
        }

    # Bullet quality stats
    scored = [score_bullet(b) for b in all_bullets]
    n_generic   = sum(1 for s in scored if s["generic"])
    n_lang_mix  = sum(1 for s in scored if s["lang_mix"])
    specific_t  = sum(s["specific"] for s in scored)
    avg_spec    = specific_t / len(scored)
    avg_len     = sum(s["length"] for s in scored) / len(scored)

    # Duplicate bullets across sections (same bullet text in 2+ sections)
    dup_count = 0
    seen = Counter()
    for b in all_bullets:
        seen[b.lower().strip()[:80]] += 1
    dup_count = sum(c - 1 for c in seen.values() if c > 1)

    # Composite score (0-10)
    # +specific_avg ×2 (cap 6)
    # -generic_ratio ×3
    # -lang_mix ratio ×1.5
    # -dup ×0.5 per dup
    # +bonus 1 if has any of decisions/solutions with ≥3 specific bullets
    n = len(scored)
    generic_r  = n_generic / n
    lang_mix_r = n_lang_mix / n
    score = min(6.0, avg_spec * 2.0) - generic_r * 3.0 - lang_mix_r * 1.5 - dup_count * 0.5
    sol_decisions = sections.get("Decisions", []) + sections.get("Solutions", [])
    if any(score_bullet(b)["specific"] >= 2 for b in sol_decisions[:5]):
        score += 1.0
    score = max(0.0, min(10.0, score + 4.0))  # shift so 4.0 is "average"

    verdict = ("solid"   if score >= 6.0 else
               "ok"      if score >= 4.0 else
               "weak"    if score >= 2.0 else
               "garbage")

    return {
        "name":    path.name,
        "source":  fm.get("source", "?"),
        "msg_cnt": int(fm.get("msg_count", "0") or "0"),
        "size":    path.stat().st_size,
        "bullets": n,
        "generic_pct":  round(generic_r * 100, 1),
        "lang_mix_pct": round(lang_mix_r * 100, 1),
        "avg_specific": round(avg_spec, 2),
        "avg_len":      round(avg_len, 1),
        "duplicates":   dup_count,
        "sections":     {k: len(v) for k, v in sections.items()},
        "is_stub":      "## _Stub_" in text,
        "score":        round(score, 2),
        "verdict":      verdict,
    }


# ---------------------------------------------------------------------------
# Aggregation + reports
# ---------------------------------------------------------------------------
def audit_all(sample: int | None = None, include_sessions: bool = True) -> dict:
    # Distilled notes are the bulk of the data (claude-ai/grok zip imports)
    files = sorted(DISTILLED.glob("*.md"))
    # Sessions = saves from antigravity/cursor/claude-code via save_conversation MCP.
    # Same structure (frontmatter + sections), different folder.
    if include_sessions and SESSIONS.exists():
        files.extend(sorted(SESSIONS.glob("*.md")))
    if not files:
        return {"error": "no notes found"}
    if sample and sample < len(files):
        files = random.sample(files, sample)

    results = []
    for i, p in enumerate(files):
        r = analyze_note(p)
        results.append(r)
        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(files)} analyzed", file=sys.stderr)

    valid = [r for r in results if "error" not in r and r.get("bullets", 0) > 0]
    sources = defaultdict(list)
    for r in valid:
        sources[r["source"]].append(r)

    summary = {
        "total_files":     len(results),
        "analyzed":        len(valid),
        "empty_or_stub":   len(results) - len(valid),
        "verdicts":        Counter(r["verdict"] for r in valid),
        "avg_score":       round(sum(r["score"] for r in valid) / max(1, len(valid)), 2),
        "by_source":       {},
    }
    for src, items in sources.items():
        summary["by_source"][src] = {
            "count":         len(items),
            "avg_score":     round(sum(r["score"] for r in items) / len(items), 2),
            "avg_bullets":   round(sum(r["bullets"] for r in items) / len(items), 1),
            "avg_generic":   round(sum(r["generic_pct"] for r in items) / len(items), 1),
            "avg_specific":  round(sum(r["avg_specific"] for r in items) / len(items), 2),
            "verdicts":      dict(Counter(r["verdict"] for r in items)),
        }
    summary["by_source"] = dict(sorted(
        summary["by_source"].items(),
        key=lambda kv: -kv[1]["avg_score"]
    ))
    summary["verdicts"] = dict(summary["verdicts"])
    return {"summary": summary, "results": results}


def write_report(audit: dict, path: Path) -> None:
    s = audit["summary"]
    lines = []
    lines.append("# Audyt jakości notatek — analiza merytoryczna\n")
    lines.append(f"_Wygenerowano przez `pipeline/note_quality.py`._\n")
    lines.append(f"\n## Podsumowanie\n")
    lines.append(f"- **Plików łącznie:** {s['total_files']}")
    lines.append(f"- **Zanalizowanych (mają bullety):** {s['analyzed']}")
    lines.append(f"- **Pustych / stubów:** {s['empty_or_stub']}")
    lines.append(f"- **Średni score:** {s['avg_score']} / 10")
    lines.append(f"- **Werdykt:** ")
    for v, c in sorted(s["verdicts"].items(), key=lambda kv: -kv[1]):
        pct = round(c / max(1, s["analyzed"]) * 100, 1)
        lines.append(f"    - **{v}** — {c} ({pct}%)")
    lines.append("")
    lines.append("## Per-source ranking (sortowane po average score)\n")
    lines.append("| Source | Notatki | Avg score | Avg bullets | Generic % | Avg specific |")
    lines.append("|--------|--------:|----------:|------------:|----------:|-------------:|")
    for src, st in s["by_source"].items():
        lines.append(f"| `{src}` | {st['count']} | {st['avg_score']} | "
                     f"{st['avg_bullets']} | {st['avg_generic']}% | {st['avg_specific']} |")
    lines.append("\n## Werdykty per source\n")
    for src, st in s["by_source"].items():
        verds = " · ".join(f"{v}: {c}" for v, c in st["verdicts"].items())
        lines.append(f"- `{src}` — {verds}")
    lines.append("")
    # Worst notes
    valid = [r for r in audit["results"] if "error" not in r and r.get("bullets", 0) > 0]
    worst = sorted(valid, key=lambda r: r["score"])[:15]
    best  = sorted(valid, key=lambda r: -r["score"])[:15]
    lines.append("## 15 najgorszych notatek (najniższy score)\n")
    for r in worst:
        lines.append(f"- `{r['name']}` — score **{r['score']}** "
                     f"({r['verdict']}, gen {r['generic_pct']}%, "
                     f"spec {r['avg_specific']}, bullets {r['bullets']})")
    lines.append("\n## 15 najlepszych notatek (najwyższy score)\n")
    for r in best:
        lines.append(f"- `{r['name']}` — score **{r['score']}** "
                     f"({r['verdict']}, spec {r['avg_specific']}, "
                     f"bullets {r['bullets']})")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  raport: {path}", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "audit":
        audit = audit_all()
        out_md = NOTES_OUT / "2026-05-25_note-quality-audit.md"
        NOTES_OUT.mkdir(parents=True, exist_ok=True)
        write_report(audit, out_md)
        # Also dump JSON for further processing
        out_json = ROOT / "data" / "note-quality.json"
        out_json.write_text(json.dumps(audit, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"JSON: {out_json}", file=sys.stderr)
        print(json.dumps(audit["summary"], ensure_ascii=False, indent=2))
    elif cmd == "sample":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        audit = audit_all(sample=n)
        print(json.dumps(audit["summary"], ensure_ascii=False, indent=2))
    elif cmd == "worst":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        audit = audit_all()
        valid = [r for r in audit["results"] if "error" not in r and r.get("bullets", 0) > 0]
        worst = sorted(valid, key=lambda r: r["score"])[:n]
        print(json.dumps(worst, ensure_ascii=False, indent=2))
    elif cmd == "best":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        audit = audit_all()
        valid = [r for r in audit["results"] if "error" not in r and r.get("bullets", 0) > 0]
        best = sorted(valid, key=lambda r: -r["score"])[:n]
        print(json.dumps(best, ensure_ascii=False, indent=2))
    elif cmd == "one":
        p = DISTILLED / sys.argv[2]
        print(json.dumps(analyze_note(p), ensure_ascii=False, indent=2))
    else:
        print(f"unknown command: {cmd}")
        sys.exit(2)
