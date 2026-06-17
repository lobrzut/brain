---
name: cv-update
description: Porównuje aktualne CV z nowymi projektami w vault, sugeruje co dodać
model: qwen2.5:14b
inputs:
  query: "cv praca informatyk projekt umiejętności"
context:
  - rag: "{query}"
  - vault_filter: "cv"
outputs:
  save_to: vault/digests/{date}_cv_update.md
---

Pomagasz userowi zaktualizować CV. Otrzymałeś:

## RAG hits (notatki o CV/pracy/projektach)
{context.rag}

## Vault notes z "cv" w nazwie
{context.vault_filter}

Zadanie: stwórz raport po polsku z 4 sekcjami:

1. **Co user ma w aktualnym CV** (cytuj plik źródłowy)
2. **Nowe projekty / umiejętności w vault których w CV NIE ma** — z konkretnymi przykładami
3. **Rekomendacje konkretnych bulletów do dodania** — gotowe, w formacie:
   - `[Nazwa projektu]` — co zrobił, jakich technologii użył, jaki measurable outcome
4. **Brutal honest** — co w CV jest filler ("Office, MS Project") vs co ma faktyczną wartość

Nie wymyślaj projektów. Jeśli vault nie ma materiału do bulleta — pomiń.
