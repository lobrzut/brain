---
name: session-handoff
description: Generuje prompt do wklejenia w INNYM agencie żeby kontynuować od miejsca w którym skończyłeś
model: qwen2.5:7b
inputs:
  next_agent: "claude-desktop"
context:
  - vault_filter: "sessions"
outputs:
  save_to: vault/digests/{date}_handoff_to_{input.next_agent}.md
---

Otrzymałeś listę plików z `vault/sessions/` (zapisanych przez `brain-rag.save_conversation`
z różnych agentów):

{context.vault_filter}

Twoje zadanie:
1. Znajdź **NAJNOWSZĄ** sesję (najwyższa data, najwyższy czas w nazwie pliku)
2. Wyciągnij z niej:
   - Topic
   - Decisions (co ustalono)
   - Solutions (co działa)
   - Open Questions (co jeszcze trzeba sprawdzić)
3. Wygeneruj **gotowy prompt** do wklejenia w agencie `{input.next_agent}` żeby
   kontynuować pracę bez pytania "od czego zaczynamy"

Format outputu (markdown):

```
# Handoff: <topic z najnowszej sesji>

## Skopiuj do `{input.next_agent}`:

> Kontynuuję pracę z poprzedniej sesji w innym agencie. Stan:
>
> **Co już ustaliliśmy:**
> - <decision 1>
> - <decision 2>
>
> **Co działa:**
> - <solution 1 jeśli kod, w bloku kodu>
>
> **Co jeszcze do sprawdzenia:**
> - <open question 1>
>
> Najpierw użyj brain-rag.search_library "<topic>" żeby zobaczyć pełną historię.
> Potem kontynuuj — kolejny krok to: <co najsensowniej zrobić dalej>.

---

**Źródło**: <nazwa pliku najnowszej sesji>
**Data**: <data sesji>
**Wcześniejszy agent**: <source z frontmattera>
```

Reguły:
- Wybierz NAJNOWSZĄ sesję (po dacie/czasie w nazwie pliku) chyba że user dał `topic` filter
- Cytuj pełne treści z Solutions (kod, komendy) — nie skracaj
- Jeśli sesja jest pusta lub trywialna, napisz "Brak sensownej sesji do przekazania"
- Output musi być GOTOWY do skopiowania do agenta, bez dodatkowych komentarzy
