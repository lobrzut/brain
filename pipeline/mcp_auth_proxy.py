"""Brain MCP auth proxy.

Sits in front of the supergateway (MCP SSE/streamable-http) and enforces a
Bearer-token check before forwarding. Lets external clients (Claude Code,
Cursor, Antigravity, claude-desktop) reach brain MCP only with a valid token.

Layout:
    Internet/LAN ──Bearer──> mcp_auth_proxy (0.0.0.0:7862)
                                      │
                                      ▼ reverse-proxy
                              supergateway (127.0.0.1:7863)
                                      │ stdio
                                      ▼
                          brain-rag / brain-vault / brain-library

Tokens are read from data/mcp-tokens.json on every request (no restart needed
to add/revoke a token). Format:
    [
      {"name": "claude-code-laptop",  "token": "btk_...", "created": "..."},
      {"name": "cursor-desktop",      "token": "btk_...", "created": "..."}
    ]

Env:
    BRAIN_MCP_UPSTREAM   — defaults to http://127.0.0.1:7863
    BRAIN_MCP_BIND       — defaults to 0.0.0.0:7862
    BRAIN_DATA_DIR       — defaults to <repo>/data
    BRAIN_MCP_ALLOW_LOCAL — "1" to skip auth for localhost requests (default 0)
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("BRAIN_DATA_DIR") or (ROOT / "data"))
TOKENS_FILE = DATA_DIR / "mcp-tokens.json"
UPSTREAM = os.environ.get("BRAIN_MCP_UPSTREAM", "http://127.0.0.1:7863").rstrip("/")
ALLOW_LOCAL = os.environ.get("BRAIN_MCP_ALLOW_LOCAL", "0") == "1"

# Tiny in-memory cache: re-read tokens file at most every 2s.
_tokens_cache: dict[str, object] = {"mtime": 0.0, "checked_at": 0.0, "set": set()}


def _load_tokens() -> set[str]:
    """Return the current set of valid bearer tokens. Cheap: cached, refreshed
    on file mtime change or every 2s."""
    now = time.monotonic()
    if now - _tokens_cache["checked_at"] < 2.0:
        return _tokens_cache["set"]  # type: ignore[return-value]
    _tokens_cache["checked_at"] = now
    try:
        st = TOKENS_FILE.stat()
    except OSError:
        _tokens_cache["set"] = set()
        return set()
    if st.st_mtime == _tokens_cache["mtime"]:
        return _tokens_cache["set"]  # type: ignore[return-value]
    try:
        data = json.loads(TOKENS_FILE.read_text(encoding="utf-8-sig"))
        valid = {str(e["token"]) for e in data if isinstance(e, dict) and e.get("token")}
    except Exception:
        valid = set()
    _tokens_cache["mtime"] = st.st_mtime
    _tokens_cache["set"] = valid
    return valid


def _is_localhost(req: Request) -> bool:
    host = (req.client.host if req.client else "") or ""
    return host in ("127.0.0.1", "::1", "localhost")


def _authorized(req: Request) -> bool:
    if ALLOW_LOCAL and _is_localhost(req):
        return True
    auth = req.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return False
    token = auth.split(" ", 1)[1].strip()
    return token in _load_tokens()


app = FastAPI(title="brain-mcp-auth-proxy", openapi_url=None, docs_url=None, redoc_url=None)

# Single shared async client — connection pooling matters for SSE.
_client: httpx.AsyncClient | None = None


@app.on_event("startup")
async def _startup() -> None:
    global _client
    # No total timeout — SSE streams stay open. Per-read timeout 5min keeps
    # dead connections from accumulating.
    _client = httpx.AsyncClient(
        timeout=httpx.Timeout(None, connect=10.0, read=300.0),
        follow_redirects=False,
    )


@app.on_event("shutdown")
async def _shutdown() -> None:
    if _client is not None:
        await _client.aclose()


# Headers we never forward — hop-by-hop or set by httpx itself.
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
}


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "upstream": UPSTREAM, "tokens": len(_load_tokens())}


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def proxy(path: str, request: Request) -> Response:
    if not _authorized(request):
        # WWW-Authenticate hint helps debugging in IDEs.
        return JSONResponse(
            {"error": "unauthorized", "hint": "set Authorization: Bearer <token> header"},
            status_code=401,
            headers={"WWW-Authenticate": 'Bearer realm="brain-mcp"'},
        )

    if _client is None:
        raise HTTPException(503, "proxy not ready")

    # Build upstream URL preserving query string.
    qs = request.url.query
    upstream_url = f"{UPSTREAM}/{path}" + (f"?{qs}" if qs else "")

    fwd_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP and k.lower() != "authorization"
    }

    body_iter = request.stream()

    # httpx stream() returns an async context manager; we manually open it to
    # let StreamingResponse drain it lazily.
    req = _client.build_request(
        request.method,
        upstream_url,
        headers=fwd_headers,
        content=body_iter,
    )
    upstream_resp = await _client.send(req, stream=True)

    resp_headers = {
        k: v for k, v in upstream_resp.headers.items()
        if k.lower() not in _HOP_BY_HOP
    }

    async def _body_iter():
        try:
            async for chunk in upstream_resp.aiter_raw():
                yield chunk
        finally:
            await upstream_resp.aclose()

    return StreamingResponse(
        _body_iter(),
        status_code=upstream_resp.status_code,
        headers=resp_headers,
        media_type=upstream_resp.headers.get("content-type"),
    )


if __name__ == "__main__":
    import uvicorn
    bind = os.environ.get("BRAIN_MCP_BIND", "0.0.0.0:7862")
    host, _, port = bind.partition(":")
    uvicorn.run(app, host=host or "0.0.0.0", port=int(port or "7862"), log_level="info")
