# BRAIN — jak się podłączyć

Praktyczny przewodnik. Wszystko zakłada że `start.ps1` jest uruchomiony.

---

## 1. URL-e które trzeba znać

| Co | URL | Notatka |
|---|---|---|
| Dashboard | `http://127.0.0.1:7860` | UI w przeglądarce |
| Ollama API | `http://127.0.0.1:11434` | Lokalny LLM |
| Status JSON | `http://127.0.0.1:7860/api/status` | Wszystko żywcem |
| API proxy | `http://127.0.0.1:7860/proxy/<provider>/...` | Patrz sekcja 4 |
| Vault | `<brain>/data/vault/` | Markdown notes |
| Library | `<brain>/data/library/` | Wrzuć tu PDF/ebook |
| MCP config | `<brain>/pipeline/mcp-servers.json` | |
| API keys | `<brain>/data/api-keys.json` | Plaintext, backup ostrożnie |
| Backups | `<brain>/data/backups/` | ZIP-y |

Provider IDs w proxy: `anthropic` · `openai` · `google` · `xai` · `deepseek` · `openrouter`

---

## 2. Czat z lokalnym modelem (najprostsze)

Otwórz Dashboard, kliknij **fioletową ikonę gradient bottom-right** (chat).
Wybierz model z dropdownu (Twoje pobrane: `qwen2.5:14b` / `qwen2.5-coder:14b` / `qwen2.5:3b`).
Enter wysyła, Shift+Enter nowa linia. Streaming live z Ollamy.

Z poziomu CLI/kodu:
```bash
curl http://127.0.0.1:11434/api/generate -d '{
  "model": "qwen2.5-coder:14b",
  "prompt": "Write a Python one-liner that flattens a list of lists.",
  "stream": false
}'
```

---

## 3. Podłączenie zewnętrznego asystenta IDE do lokalnego LLM

### Cursor / Continue.dev / Cline
Wszystkie te narzędzia akceptują **OpenAI-compatible endpoint**. Ollama oferuje go pod `http://127.0.0.1:11434/v1`.

**Cursor**: Settings → Models → Add custom OpenAI-compatible:
```
Base URL : http://127.0.0.1:11434/v1
API Key  : ollama   (dowolny string, Ollama nie sprawdza)
Model    : qwen2.5-coder:14b
```

**Continue.dev** (`~/.continue/config.json`):
```json
{
  "models": [
    {
      "title": "Local qwen-coder",
      "provider": "openai",
      "apiBase": "http://127.0.0.1:11434/v1",
      "apiKey": "ollama",
      "model": "qwen2.5-coder:14b"
    }
  ]
}
```

**Cline** (VS Code, settings): "API Provider" → OpenAI Compatible → ten sam URL.

---

## 4. Lokalny proxy do chmurowych API — jedna kopia klucza

Zamiast wpisywać klucz `ANTHROPIC_API_KEY` w *każdym* narzędziu, ustaw klucz **raz** w OPTIONS dashboardu i wskaż narzędzia na lokalny proxy. Dashboard wstrzyknie klucz lokalnie.

**URL pattern**: `http://127.0.0.1:7860/proxy/<provider>/<rest-of-path>`

Provider URL → proxy URL:
| Provider | Oryginalny URL | Proxy URL |
|---|---|---|
| Anthropic | `https://api.anthropic.com/v1/messages` | `http://127.0.0.1:7860/proxy/anthropic/v1/messages` |
| OpenAI | `https://api.openai.com/v1/chat/completions` | `http://127.0.0.1:7860/proxy/openai/v1/chat/completions` |
| Gemini | `https://generativelanguage.googleapis.com/v1beta/models/...` | `http://127.0.0.1:7860/proxy/google/v1beta/models/...` |
| Grok | `https://api.x.ai/v1/chat/completions` | `http://127.0.0.1:7860/proxy/xai/v1/chat/completions` |
| DeepSeek | `https://api.deepseek.com/v1/chat/completions` | `http://127.0.0.1:7860/proxy/deepseek/v1/chat/completions` |
| OpenRouter | `https://openrouter.ai/api/v1/chat/completions` | `http://127.0.0.1:7860/proxy/openrouter/api/v1/chat/completions` |

**Klient nie musi (i nie powinien) wysyłać klucza** — dashboard go nadkłada.

### Test curl
```bash
# zamiast hitować api.anthropic.com z prawdziwym kluczem:
curl http://127.0.0.1:7860/proxy/anthropic/v1/messages \
  -H 'content-type: application/json' \
  -H 'anthropic-version: 2023-06-01' \
  -d '{
    "model": "claude-sonnet-4-5",
    "max_tokens": 1024,
    "messages": [{"role":"user","content":"hi"}]
  }'
```

### W Pythonie z SDK
```python
import anthropic
client = anthropic.Anthropic(
    base_url="http://127.0.0.1:7860/proxy/anthropic",
    api_key="proxied"   # ignored, dashboard injects real key
)
client.messages.create(model="claude-sonnet-4-5", max_tokens=1024,
                       messages=[{"role":"user","content":"hi"}])
```

```python
from openai import OpenAI
client = OpenAI(
    base_url="http://127.0.0.1:7860/proxy/openai/v1",
    api_key="proxied"
)
```

### Co dostaniesz w zamian
- **Liczniki użycia per provider** w zakładce TOOLS → API USAGE (requests/day, errors, bytes).
- **Jedno miejsce do rotacji klucza** — zmieniasz w OPTIONS, wszystkie narzędzia automatycznie korzystają z nowego.
- **Streaming działa** (Server-Sent Events forwardowane chunk-by-chunk).

### Co NIE działa
- **Web UI w przeglądarce** (Claude.ai, ChatGPT.com) — to inne usługi, nie API, nie da się zaproxować.
- **Płatność** — proxy NIC nie cachuje, każdy request to realny request do dostawcy z normalnym kosztem.
- **Auth dashboardu** — nasłuchuje na `127.0.0.1`. Każdy proces na Twojej maszynie może go uderzyć. Akceptowalne dla single-user laptopa, nie dla shared.

---

## 5. Connect MCP server → Twój asystent

MCP (Model Context Protocol) to standardowy sposób udostępniania narzędzi i danych LLM-om.

### A) Dodaj MCP server w dashboardzie

TOOLS → MCP SERVERS → `+ ADD SERVER`. Przykład — filesystem MCP nad vaultem:

| Pole | Wartość |
|---|---|
| ID | `vault-fs` |
| Title | `Brain Vault (filesystem)` |
| Command | `npx` |
| Args (po linii) | `-y`<br>`@modelcontextprotocol/server-filesystem`<br>`<brain>/data/vault` |
| Env | *(puste)* |

SAVE → kliknij START w wierszu. Dot się zazieleni gdy proces żyje. Logs są dostępne przyciskiem LOGS.

### B) Podłącz **Claude Desktop** do tego MCP

Edytuj `%APPDATA%\Claude\claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "brain-vault": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem",
               "C:\\\\path\\\\to\\\\brain\\\\data\\\\vault"]
    }
  }
}
```
Restart Claude Desktop. Vault będzie dostępny jako narzędzie do czytania/edycji notatek.

### C) Podłącz **Claude Code (CLI)** do tego MCP

```bash
claude mcp add brain-vault \
  npx -y @modelcontextprotocol/server-filesystem /path/to/brain/data/vault
```
Sprawdź: `claude mcp list`. W sesji Claude Code automatycznie zaproponuje narzędzia z tego MCP.

### D) Inne ciekawe MCP do dorzucenia
- **`@modelcontextprotocol/server-sqlite`** — dostęp do bazy SQLite
- **`@modelcontextprotocol/server-github`** — operacje GitHub
- **`@modelcontextprotocol/server-puppeteer`** — kontrola przeglądarki
- Custom Python MCP — zobacz `mcp` SDK na PyPI

---

## 6. Pipeline destylacji transkryptów

Co robi: czyta historię Twoich rozmów z Claude Code (i w przyszłości Cursora/ChatGPT/Gemini), wyciąga z każdej sesji decyzje/komendy/fakty/pytania, zapisuje do `data/vault/distilled/*.md`.

### Z dashboardu
BRAIN → TRANSCRIPT DISTILLATION:
1. Patrz panel "sources" — pokazuje wykryte źródła
2. Wybierz `model` (najlepiej `qwen2.5:14b`)
3. Opcjonalnie `limit` (np. 5 — ile najnowszych sesji)
4. **COLLECT** — tylko normalizuje (szybkie, sekundy)
5. **RUN ALL** — collect + destyluj (każda sesja ~1 minuta na qwen 14B)
6. **STOP** — przerywa w trakcie

Progress widoczny live: `done/total`, current session, pasek postępu.

### Z CLI (równolegle, w tle)
```powershell
$env:OLLAMA_HOST = "127.0.0.1:11434"
& "<brain>\bin\python\python.exe" "<brain>\pipeline\distill.py" run --model qwen2.5:14b --limit 10
& "<brain>\bin\python\python.exe" "<brain>\pipeline\distill.py" status
```

### Jak to działa pod spodem
- Wczytuje `~/.claude/projects/*/*.jsonl`
- Filtruje śmieci (tylko `user`/`assistant`, pomija `queue-operation` itp.)
- Tnie transkrypt na chunki po ~7KB (powyżej 14B model ignoruje schemat JSON)
- Każdy chunk → Ollama z prompt-em system-role + delimitery + few-shot
- Deduplikacja wyników z chunków
- Output: `2026-MM-DD_<source>_<project>_<sid>.md` z YAML frontmatter

### Wynik
Pierwsza notatka pojawi się w `data/vault/distilled/` po uruchomieniu destylacji.
Otwórz w Obsidianie albo czytaj jako markdown.

---

## 7. Backup

TOOLS → BACKUP → `CREATE BACKUP`.

Zawartość ZIP:
- ✓ `vault/` (wszystkie notatki + destylowane)
- ✓ `dashboard/` (kod backendu/frontendu)
- ✓ `pipeline/` (distill.py, mcp-servers.json)
- ✓ `start.ps1`, `stop.ps1`, `config.json`, `README.md`, `CONNECT.md`
- ✗ `bin/` (Ollama + Python — pobierze się przy `brain-setup.ps1`)
- ✗ `data/ollama-models/` (~20 GB)
- ✗ `data/brain-raw/` (znormalizowane transkrypty, regenerowalne)
- ✗ `logs/`, `__pycache__`
- ✗ `data/api-keys.json` (chyba że zaznaczysz "include keys")
- ✗ `data/api-usage.json`

Typowy rozmiar: 40 KB - kilka MB. Restore: rozpakuj do nowego katalogu, uruchom `brain-setup.ps1 -Root <ten katalog>` (postawi Ollama+Python, vault zostanie nietknięty).

---

## 8. System tray

Przy starcie `start.ps1` pojawia się **ikona w tray-u** (bottom-right Windows). Prawym przyciskiem:
- **Open Dashboard** (też domyślne, lewy podwójny klik)
- **Open Vault Folder** — explorer w `data/vault/`
- **Open Brain Folder** — explorer w roocie
- **Restart Ollama** — kill + relaunch (przy zacięciu)
- **Stop All** — odpala `stop.ps1`, kończy wszystko
- **Quit tray only** — zamyka samą ikonę, dashboard/Ollama lecą dalej

Tooltip pokazuje status: `Brain · ollama OK · dash OK`.

---

## 9. Sync między komputerami

Strategia: **dwa katalogi w `brain/data/`**:
- `vault/` — Twoja wiedza (sync via Git lub Syncthing)
- `ollama-models/` — NIE syncuj (regenerowane przez `ollama pull`)

Plus `pipeline/mcp-servers.json` i `data/api-keys.json` syncuj jeśli chcesz tę samą konfigurację wszędzie.

`.gitignore` przykład w `brain/`:
```
bin/
data/ollama-models/
data/brain-raw/
data/backups/
data/api-keys.json
data/api-usage.json
logs/
__pycache__/
```

---

## 10. Troubleshooting

| Objaw | Diagnostyka |
|---|---|
| Dashboard nie odpowiada | `logs\dashboard.err.log` — szukaj traceback |
| Ollama na CPU mimo GPU | `logs\ollama.err.log` — szukaj `library=Vulkan`. Jeśli brak, sprawdź czy `OLLAMA_VULKAN=1` jest ustawione |
| Tray nie pokazuje się | `Get-Process pythonw` — czy proces żyje. Brak → uruchom ręcznie: `bin\python\pythonw.exe dashboard\tray.py` |
| Proxy 401 | Klucz nieustawiony — OPTIONS → włącz provider + wpisz klucz |
| Distillation pusty wynik | Zobacz sekcję "Jak to działa" — chunki muszą być <7KB, prompt v0.3 ma chunkowanie |
| MCP server "stopped" mimo START | LOGS → `mcp-<id>` — typowo brakuje `npx` w PATH lub błąd w `args` |

Wszystkie logi: TOOLS → LOGS (dropdown wybiera plik, auto-refresh co 3s).

---

## 11. Co dalej

Nieskończone, ale w kolejności pewności wartości:
1. Wlej parę PDF-ów fizyki do `data/library/` — RAG over PDF jeszcze nie zaimplementowany, ale przygotuj dane
2. Uruchom destylację swoich starych sesji Claude Code (`RUN ALL` w BRAIN)
3. Dodaj MCP server filesystem → podłącz Claude Desktop → daj mu czytać destylowane notatki
4. Zacznij ustawiać klucze cloud-API w OPTIONS i puszczać requesty przez `/proxy/...` — w tydzień zobaczysz w USAGE którego dostawcy realnie używasz
