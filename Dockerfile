# Brain — lightweight core image (edge profile)
#
# No Ollama, no GPU, no tray. Vault + sqlite-vec semantic search (fastembed,
# in-process ONNX CPU) + MCP servers + Bearer auth proxy. Runs the same image
# in three roles via docker-compose (dashboard / mcp-gateway / mcp-auth-proxy)
# — mirrors linux/install.sh's three systemd services, just containerized.
#
# Build:  docker build -t brain-core .
# Run:    see docker-compose.yml (this image alone needs CMD overridden per role)
FROM python:3.12-slim

# Node is needed only for @modelcontextprotocol/server-filesystem (the
# brain-vault/brain-library leaf MCP servers) — the actual SSE/HTTP
# multiplexing across all three MCP servers is done by mcp-proxy (PyPI,
# pip-installed below), not a Node-based gateway. This mirrors the real,
# already-running production setup (verified against the live server).
RUN apt-get update -qq && apt-get install -y --no-install-recommends \
      curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @modelcontextprotocol/server-filesystem \
    && apt-get purge -y gnupg && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# pystray/pillow are Windows-tray-only — skip them in the container image.
COPY requirements.txt .
RUN grep -v -E '^(pystray|pillow)' requirements.txt > requirements.core.txt \
    && pip install --no-cache-dir -r requirements.core.txt

COPY dashboard/ dashboard/
COPY pipeline/ pipeline/
COPY skills/ skills/
COPY config.docker.json config.json

# Data lives on a volume (see docker-compose.yml) — never baked into the image.
ENV BRAIN_DATA_DIR=/data
ENV BRAIN_EMBED_BACKEND=fastembed
ENV PYTHONUNBUFFERED=1

# Pre-fetch the fastembed model at build time so the first real request
# (and the first container start in a fresh deploy) isn't a 500MB download
# blocking the request. Safe no-op if it's already cached in a layer.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('nomic-ai/nomic-embed-text-v1.5')"

EXPOSE 7860 7862 7863

# Default role: dashboard. docker-compose overrides `command` for the other
# two roles (mcp-gateway, mcp-auth-proxy) using this same image.
WORKDIR /app/dashboard
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
