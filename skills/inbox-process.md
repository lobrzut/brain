---
name: inbox-process
description: Sprawdza inbox z eksportami rozmów (ZIP), zwraca status co czeka na destylację
model: qwen2.5:3b
context:
  - inbox_count: 1
outputs:
  save_to: vault/digests/{date}_inbox_status.md
---

Inbox zawiera {context.inbox_count} plików oczekujących na destylację.

Napisz krótki raport (maks 5 linijek po polsku):
- co prawdopodobnie jest w inboxie (na podstawie liczby — duże = pełne eksporty, małe = pojedyncze rozmowy)
- czy warto teraz uruchomić RUN ALL w dashboardzie
- szacowany czas (~30s per session na qwen2.5:3b)

Bez bzdur, konkrety. Jeśli inbox jest pusty, napisz "Inbox pusty — nic do roboty."
