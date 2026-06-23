# BRAIN Client

Mały agent w tray dla **Windows / Linux (Debian) / macOS**.

## Co robi

- Siedzi w **system tray** (zielony / żółty / czerwony status)
- Pokazuje podstawowe info: model BRAIN, uptime, ile agentów ma MCP
- **Otwórz BRAIN** → dashboard w przeglądarce
- **Deploy MCP** → jednym kliknięciem wpina `brain-vault`, `brain-library`, `brain-rag` do:
  - Cursor
  - Claude Desktop
  - Claude Code
  - Antigravity + Antigravity IDE
  - VS Code
  - Windsurf
  - Zed (eksperymentalnie)

## Wymagania

- Python 3.10+
- Dostęp LAN do serwera BRAIN (`:7860` dashboard, `:7862` MCP HTTP)
- Dla trybu HTTP na Claude Desktop: **Node.js/npx** (`mcp-remote`)
- Cursor / VS Code / Windsurf: natywny transport HTTP (bez npx)

## Instalacja

### Windows

```powershell
cd scripts
.\install.ps1
```

### Linux / macOS

```bash
chmod +x scripts/install.sh
./scripts/install.sh
```

## Konfiguracja

`~/.brain/client.json`:

```json
{
  "brain_url": "http://<brain-host>:7860",
  "mcp_url": "http://<brain-host>:7862",
  "transport": "http",
  "auto_deploy_on_start": true,
  "poll_interval_sec": 30
}
```

Transporty:
- **`http`** (domyślny) — MCP po HTTP/SSE na `:7862` (zalecany, bez SSH)
- **`ssh`** — stdio przez SSH (bezpieczniejszy, wymaga klucza)

## CLI

```bash
python -m brain_client tray          # tray (domyślne)
python -m brain_client status --pretty
python -m brain_client deploy
python -m brain_client deploy --agent cursor
python -m brain_client config --set transport http
```

## Build (pojedynczy plik)

```powershell
.\scripts\build-win.ps1      # → dist/brain-client.exe
```

```bash
./scripts/build-linux.sh     # → dist/brain-client
```

## Pobieranie z serwera BRAIN

Po wdrożeniu na VM:

```
http://<brain-host>:7860/client/
```

## Dlaczego to rozwiązuje auto-deploy

Deploy z **dashboardu na serwerze** nie widzi Twojego PC.

**BRAIN Client działa na kliencie** — skanuje lokalne aplikacje i zapisuje `~/.cursor/mcp.json` itd. To jest właściwy model „auto-deploy na nieznanym hoście”: mały agent rejestruje się sam przy pierwszym uruchomieniu.
