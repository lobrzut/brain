#!/usr/bin/env bash
# Brain — Linux server edition installer
set -euo pipefail

LINUX_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${BRAIN_DIR:-$(cd "$LINUX_DIR/.." && pwd)}"
DATA_DIR="${BRAIN_DATA:-/var/lib/brain}"
VENV_DIR="${BRAIN_VENV:-$REPO_ROOT/.venv}"
MODEL="${BRAIN_MODEL:-qwen2.5:14b}"
DASH_PORT="${BRAIN_DASHBOARD_PORT:-7860}"
MCP_PORT="${BRAIN_MCP_PORT:-7862}"
OLLAMA_PORT="${BRAIN_OLLAMA_PORT:-11434}"
BIND="${BRAIN_BIND:-0.0.0.0}"
LANG_FILE="${REPO_ROOT}/locale.env"

# shellcheck source=locale.sh
source "$LINUX_DIR/locale.sh"

log() { echo "==> $*"; }
warn() { echo "!! $*" >&2; }

require_debian() {
  if [[ ! -f /etc/debian_version ]]; then
    warn "$(L warn_non_debian)"
  fi
}

install_packages() {
  log "$(L install_packages)"
  apt-get update -qq
  apt-get install -y -qq \
    ca-certificates curl git jq \
    python3 python3-pip python3-venv \
    systemd
  if ! command -v node >/dev/null 2>&1; then
    apt-get install -y -qq nodejs npm || true
  fi
}

setup_data_dirs() {
  log "$(L install_data)"
  mkdir -p "$DATA_DIR"/{vault,library,backups,logs}
  install -d -m 755 "$DATA_DIR/vault" "$DATA_DIR/library"

  if [[ ! -f "$DATA_DIR/api-keys.json" && -f "$REPO_ROOT/data/api-keys.example.json" ]]; then
    cp "$REPO_ROOT/data/api-keys.example.json" "$DATA_DIR/api-keys.json"
  fi
  if [[ ! -f "$DATA_DIR/vault/USER.md" && -f "$REPO_ROOT/data/vault/USER.example.md" ]]; then
    cp "$REPO_ROOT/data/vault/USER.example.md" "$DATA_DIR/vault/USER.md"
  fi
}

setup_venv() {
  log "$(L install_venv)"
  python3 -m venv "$VENV_DIR"
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  pip install --upgrade pip -q
  pip install -r "$REPO_ROOT/requirements.txt" -q
}

install_ollama() {
  if command -v ollama >/dev/null 2>&1; then
    log "$(L install_ollama_skip)"
    return
  fi
  log "$(L install_ollama)"
  curl -fsSL https://ollama.com/install.sh | sh
}

write_config() {
  log "$(L install_config)"
  cat >"$REPO_ROOT/config.json" <<EOF
{
  "version": "0.5.0",
  "edition": "linux",
  "root": "$REPO_ROOT",
  "data_dir": "$DATA_DIR",
  "bind_host": "$BIND",
  "ollama_port": $OLLAMA_PORT,
  "dashboard_port": $DASH_PORT,
  "mcp_gateway_port": $MCP_PORT,
  "default_model": "$MODEL",
  "gpu": { "Vendor": "auto", "Name": "Linux", "VramMB": 0, "Cuda": false, "HipSdk": false, "HipPath": null }
}
EOF
}

write_mcp_gateway_config() {
  local tpl="$LINUX_DIR/mcp-multi-server.json.template"
  local out="$LINUX_DIR/mcp-multi-server.json"
  local py="$VENV_DIR/bin/python"
  sed -e "s|@VAULT@|$DATA_DIR/vault|g" \
      -e "s|@LIBRARY@|$DATA_DIR/library|g" \
      -e "s|@PYTHON@|$py|g" \
      -e "s|@MCP_RAG@|$REPO_ROOT/dashboard/mcp_rag.py|g" \
      "$tpl" >"$out"
}

install_systemd() {
  log "$(L install_systemd)"
  local svc_user="${BRAIN_USER:-brain}"
  if ! id "$svc_user" &>/dev/null; then
    useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin "$svc_user" || true
  fi
  chown -R "$svc_user:$svc_user" "$DATA_DIR" 2>/dev/null || true

  sed -e "s|@REPO@|$REPO_ROOT|g" \
      -e "s|@DATA@|$DATA_DIR|g" \
      -e "s|@VENV@|$VENV_DIR|g" \
      -e "s|@BIND@|$BIND|g" \
      -e "s|@DASH_PORT@|$DASH_PORT|g" \
      -e "s|@MCP_PORT@|$MCP_PORT|g" \
      -e "s|@USER@|$svc_user|g" \
      -e "s|@OLLAMA_PORT@|$OLLAMA_PORT|g" \
      "$LINUX_DIR/systemd/brain-dashboard.service.template" \
      >"/etc/systemd/system/brain-dashboard.service"

  sed -e "s|@REPO@|$REPO_ROOT|g" \
      -e "s|@MCP_PORT@|$MCP_PORT|g" \
      -e "s|@USER@|$svc_user|g" \
      "$LINUX_DIR/systemd/brain-mcp-gateway.service.template" \
      >"/etc/systemd/system/brain-mcp-gateway.service"

  systemctl daemon-reload
  systemctl enable brain-dashboard.service brain-mcp-gateway.service
  systemctl restart brain-dashboard.service brain-mcp-gateway.service
}

pull_models() {
  log "$(L install_models) $MODEL"
  OLLAMA_HOST="127.0.0.1:$OLLAMA_PORT" ollama pull "$MODEL" || warn "ollama pull failed — run manually"
  OLLAMA_HOST="127.0.0.1:$OLLAMA_PORT" ollama pull nomic-embed-text || true
}

main() {
  require_debian
  log "$(L install_title)"
  log "Repo: $REPO_ROOT"
  log "Data: $DATA_DIR"

  install_packages
  setup_data_dirs
  setup_venv
  install_ollama
  write_config
  write_mcp_gateway_config
  install_systemd
  pull_models

  echo ""
  echo "$(L install_done)"
  echo "  Dashboard:  http://$(hostname -I | awk '{print $1}'):$DASH_PORT"
  echo "  MCP gateway: http://$(hostname -I | awk '{print $1}'):$MCP_PORT"
  echo "  Cursor mcp.json example: linux/docs/cursor-mcp-remote.json"
  echo ""
}

main "$@"
