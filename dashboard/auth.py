"""Dependency-free single-user auth for the Brain dashboard.

stdlib only (hashlib pbkdf2 + hmac-signed token) so it runs identically under
the Windows portable Python and the Linux server venv — no bcrypt / jwt / DB.

Storage (both gitignored, 0600):
  data/auth.json  -> {"username", "salt", "pwd_hash"}
  data/.secret    -> random key used to sign session cookies
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

PBKDF2_ROUNDS = 200_000
TOKEN_TTL = 60 * 60 * 24 * 7  # 7 days
COOKIE_NAME = "brain_session"

# In-memory brute-force guard (per process; single-instance homelab).
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 300.0


class Auth:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.auth_file = self.data_dir / "auth.json"
        self.secret_file = self.data_dir / ".secret"
        self._failures: dict[str, list[float]] = {}

    # ---- secret key (signs cookies) ----
    def _secret(self) -> bytes:
        try:
            if self.secret_file.is_file():
                s = self.secret_file.read_text(encoding="utf-8").strip()
                if len(s) >= 32:
                    return s.encode()
        except OSError:
            pass
        s = secrets.token_hex(32)
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.secret_file.write_text(s, encoding="utf-8")
            if hasattr(os, "chmod"):
                os.chmod(self.secret_file, 0o600)
        except OSError:
            pass
        return s.encode()

    # ---- credential store ----
    def _load(self) -> dict:
        try:
            return json.loads(self.auth_file.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return {}

    def is_configured(self) -> bool:
        d = self._load()
        return bool(d.get("username") and d.get("pwd_hash") and d.get("salt"))

    def username(self) -> str:
        return self._load().get("username", "admin")

    @staticmethod
    def _hash(password: str, salt: str) -> str:
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ROUNDS)
        return dk.hex()

    def set_credentials(self, username: str, password: str) -> None:
        salt = secrets.token_hex(16)
        data = {
            "username": (username or "admin").strip() or "admin",
            "salt": salt,
            "pwd_hash": self._hash(password, salt),
        }
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.auth_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        try:
            if hasattr(os, "chmod"):
                os.chmod(self.auth_file, 0o600)
        except OSError:
            pass

    def verify(self, username: str, password: str) -> bool:
        d = self._load()
        if not (d.get("pwd_hash") and d.get("salt")):
            return False
        if (username or "").strip().lower() != str(d.get("username", "")).lower():
            return False
        return hmac.compare_digest(self._hash(password, d["salt"]), d["pwd_hash"])

    def change_password(self, current: str, new: str) -> bool:
        d = self._load()
        if not self.verify(d.get("username", ""), current):
            return False
        self.set_credentials(d.get("username", "admin"), new)
        return True

    # ---- session token (hmac-signed, stateless) ----
    def issue_token(self, username: str) -> str:
        payload = {"sub": username, "exp": int(time.time()) + TOKEN_TTL}
        raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=")
        sig = hmac.new(self._secret(), raw, hashlib.sha256).hexdigest()
        return raw.decode() + "." + sig

    def verify_token(self, token: str | None) -> str | None:
        if not token or "." not in token:
            return None
        raw, sig = token.rsplit(".", 1)
        expect = hmac.new(self._secret(), raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expect):
            return None
        try:
            payload = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        except Exception:
            return None
        if int(payload.get("exp", 0)) < time.time():
            return None
        return payload.get("sub")

    # ---- brute-force guard ----
    def _prune(self, key: str, now: float) -> list[float]:
        fails = [t for t in self._failures.get(key, []) if now - t < LOGIN_WINDOW_SECONDS]
        if fails:
            self._failures[key] = fails
        else:
            self._failures.pop(key, None)
        return fails

    def lockout_seconds(self, key: str) -> int:
        now = time.monotonic()
        fails = self._prune(key, now)
        if len(fails) >= LOGIN_MAX_ATTEMPTS:
            return max(1, int(LOGIN_WINDOW_SECONDS - (now - fails[0])))
        return 0

    def register_failure(self, key: str) -> None:
        now = time.monotonic()
        fails = self._prune(key, now)
        fails.append(now)
        self._failures[key] = fails

    def reset_attempts(self, key: str) -> None:
        self._failures.pop(key, None)
