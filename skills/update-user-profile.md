---
name: update-user-profile
description: "Analizuje ostatnie 40 sesji i aktualizuje vault/USER.md — profil użytkownika dla wszystkich agentów (jak Hermes USER.md)"
model: qwen2.5:14b
output_file: vault/USER.md
---

# ZADANIE: Zaktualizuj profil użytkownika

Przeanalizuj poniższe streszczenia sesji i zaktualizuj profil użytkownika.

## AKTUALNY PROFIL (vault/USER.md):
{{ user_profile }}

## OSTATNIE SESJE (ostatnie 40):
{{ recent_sessions }}

## INSTRUKCJA:
Wygeneruj zaktualizowany vault/USER.md w formacie §-delimitowanym.
Sekcje: PROFIL | TECH | KOMUNIKACJA | ZAROBEK
Maksimum 2200 znaków łącznie. Pisz zwięźle — każdy wpis max 1-2 zdania.

ZASADY:
- Zachowaj istniejące wpisy jeśli nadal aktualne
- Dodaj nowe fakty odkryte w sesjach (nowe narzędzia, decyzje, preferencje)
- Usuń wpisy które stały się nieaktualne
- NIE dodawaj trywialnych/oczywistych faktów
- NIE dodawaj danych sesji-specyficznych (konkretne pliki, jednorazowe błędy)
- Zapisuj: trwałe preferencje, nowe tech stack, korekty założeń, styl komunikacji

FORMAT WYJŚCIA — tylko taki, nic więcej:
§ PROFIL
[profil osoby]

§ TECH
[stack techniczny]

§ KOMUNIKACJA
[styl i preferencje komunikacji]

§ ZAROBEK
[ograniczenia i kierunek zarobkowy]
