---
name: mikrotik-config
description: Wyciąga z vault konfiguracje MikroTik/sieciowe, zbiera w jeden playbook
model: qwen2.5:14b
inputs:
  query: "mikrotik router wireguard vpn vlan config network"
context:
  - rag: "{query}"
  - vault_filter: "mikrotik"
outputs:
  save_to: vault/digests/{date}_mikrotik_playbook.md
---

Stwórz **MikroTik Playbook** z notatek usera.

## Materiał:
### RAG
{context.rag}

### Vault notes z "mikrotik"
{context.vault_filter}

## Format outputu (markdown po polsku):

### 1. Topologia sieci
Co user ma fizycznie podłączone (jeśli wynika z notatek).

### 2. WireGuard / VPN
Konkretne komendy RouterOS które user testował lub wdrożył. Cytuj plik źródłowy.

### 3. VLAN-y i firewall
Reguły jakie są skonfigurowane lub planowane.

### 4. Open issues
Co nie zadziałało, jakie błędy zostały do rozwiązania.

### 5. Komendy do skopiowania
Lista gotowych snippetów `/interface wireguard...`, `/ip firewall...` które user może wkleić do terminalu.

### Reguły:
- Tylko komendy które FAKTYCZNIE pojawiły się w notatkach — nic z głowy
- Cytuj plik: `[[2025-12-15_claude-ai_Tunel_WireGuard_MikroTik.md]]`
- Jeśli sekcja jest pusta → "brak danych"
