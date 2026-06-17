#!/usr/bin/env bash
# Brain Linux script i18n — PL/EN via locale.env (LANG=pl|en)
if [[ -n "${BRAIN_LOCALE_LOADED:-}" ]]; then return 0; fi
BRAIN_LOCALE_LOADED=1

_brain_locale() {
  local key="$1"
  local lang="pl"
  if [[ -f "${BRAIN_LOCALE_FILE:-}" ]]; then
  :
  elif [[ -f locale.env ]]; then
    BRAIN_LOCALE_FILE="locale.env"
  fi
  if [[ -f "${BRAIN_LOCALE_FILE:-locale.env}" ]]; then
    local line
    line=$(head -n1 "${BRAIN_LOCALE_FILE:-locale.env}" 2>/dev/null || true)
    if [[ "$line" =~ LANG=(pl|en) ]]; then lang="${BASH_REMATCH[1]}"; fi
  fi
  case "${lang}:${key}" in
    pl:install_title) echo "Brain — instalacja (Linux server)" ;;
    en:install_title) echo "Brain — install (Linux server)" ;;
    pl:install_packages) echo "Instalacja pakietow systemowych..." ;;
    en:install_packages) echo "Installing system packages..." ;;
    pl:install_data) echo "Katalogi danych..." ;;
    en:install_data) echo "Data directories..." ;;
    pl:install_venv) echo "Python venv + pip..." ;;
    en:install_venv) echo "Python venv + pip..." ;;
    pl:install_ollama) echo "Instalacja Ollama..." ;;
    en:install_ollama) echo "Installing Ollama..." ;;
    pl:install_ollama_skip) echo "Ollama juz zainstalowane" ;;
    en:install_ollama_skip) echo "Ollama already installed" ;;
    pl:install_config) echo "Zapis config.json..." ;;
    en:install_config) echo "Writing config.json..." ;;
    pl:install_systemd) echo "Konfiguracja systemd..." ;;
    en:install_systemd) echo "Configuring systemd..." ;;
    pl:install_models) echo "Pobieranie modelu Ollama:" ;;
    en:install_models) echo "Pulling Ollama model:" ;;
    pl:install_done) echo "Gotowe." ;;
    en:install_done) echo "Done." ;;
    pl:warn_non_debian) echo "Testowane na Debian/Ubuntu. Inne dystrybucje moga wymagac recznej konfiguracji." ;;
    en:warn_non_debian) echo "Tested on Debian/Ubuntu. Other distros may need manual setup." ;;
    *) echo "$key" ;;
  esac
}

L() { _brain_locale "$1"; }
