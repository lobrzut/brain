---
name: dedupe-vault
description: Uruchamia skan duplikatów w vault i podsumowuje kandydatów
model: qwen2.5:3b
outputs:
  save_to: vault/digests/{date}_dedupe_report.md
---

Wyobraź sobie że uruchomiłeś skan duplikatów w vault. Wynik z dedupe.py (cosine na mean
embedding + Jaccard 5-gram word shingles + title similarity) dostępny pod adresem
http://127.0.0.1:7860/api/vault/dedupe/candidates.

Napisz krótki przewodnik (po polsku, maks 8 linijek):
- powiedz userowi żeby wszedł w BRAIN → KNOWLEDGE LIFECYCLE → SCAN
- wyjaśnij że MERGE archiwizuje starszą wersję, NOT DUPE zapamiętuje że to nie duplikat
- gdyby chciał zrobić to z linii komend: `python pipeline/dedupe.py scan`

Bez owijania w bawełnę.
