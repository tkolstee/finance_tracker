"""
JWT authentication helpers for Finance Tracker.

Tokens are issued as HttpOnly cookies (ft_token) on login and accepted from
either the cookie or an Authorization: Bearer <token> header.

Call init_secret(data_dir) once at startup (before handling any requests) to
load or generate a persistent signing key stored in DATA_DIR/secret.key.
This survives both server restarts and gunicorn's master→worker fork.

The key can still be overridden via the FINANCE_TRACKER_SECRET env var.
"""
import os, time, secrets as _secrets_mod
from functools import wraps

import jwt
from flask import request, jsonify, g

_SECRET: str = ""   # set by init_secret() before first request
_TTL:    int = int(os.environ.get("FINANCE_TRACKER_TOKEN_TTL", 86400 * 7))  # 7 days
_COOKIE: str = "ft_token"


# ── startup initialisation ────────────────────────────────────────────────────

def init_secret(data_dir: str) -> None:
    """Load or generate a stable JWT signing key.

    Priority:
      1. FINANCE_TRACKER_SECRET env var (explicit override)
      2. DATA_DIR/secret.key file        (persisted across restarts)
      3. Generate a new random key and save it to DATA_DIR/secret.key
    """
    global _SECRET

    env_val = os.environ.get("FINANCE_TRACKER_SECRET", "").strip()
    if env_val:
        _SECRET = env_val
        return

    secret_path = os.path.join(data_dir, "secret.key")
    if os.path.exists(secret_path):
        _SECRET = open(secret_path).read().strip()
    else:
        _SECRET = _secrets_mod.token_hex(32)
        os.makedirs(data_dir, exist_ok=True)
        with open(secret_path, "w") as fh:
            fh.write(_SECRET)


def _get_secret() -> str:
    if not _SECRET:
        raise RuntimeError("auth.init_secret() was never called — check startup code")
    return _SECRET


# ── token creation / parsing ──────────────────────────────────────────────────

def generate_token(user_id: int, username: str, is_admin: bool) -> str:
    now = int(time.time())
    payload = {
        "sub":      str(user_id),
        "username": username,
        "is_admin": bool(is_admin),
        "iat":      now,
        "exp":      now + _TTL,
    }
    return jwt.encode(payload, _get_secret(), algorithm="HS256")


def decode_token(token: str) -> dict | None:
    """Return the decoded payload, or None if invalid / expired."""
    try:
        return jwt.decode(token, _get_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


# ── internal helpers ──────────────────────────────────────────────────────────

def _extract_token() -> str | None:
    token = request.cookies.get(_COOKIE)
    if token:
        return token
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


def _set_g(payload: dict) -> None:
    g.user_id  = int(payload["sub"])
    g.username = payload["username"]
    g.is_admin = payload["is_admin"]


# ── decorators ────────────────────────────────────────────────────────────────

def require_auth(f):
    """Require a valid JWT. Sets g.user_id, g.username, g.is_admin."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token   = _extract_token()
        payload = decode_token(token) if token else None
        if not payload:
            return jsonify({"error": "Not authenticated"}), 401
        _set_g(payload)
        return f(*args, **kwargs)
    return decorated


def require_admin(f):
    """Require a valid JWT with is_admin=True."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token   = _extract_token()
        payload = decode_token(token) if token else None
        if not payload:
            return jsonify({"error": "Not authenticated"}), 401
        if not payload.get("is_admin"):
            return jsonify({"error": "Admin access required"}), 403
        _set_g(payload)
        return f(*args, **kwargs)
    return decorated


# ── cookie helpers ────────────────────────────────────────────────────────────

def cookie_kwargs(token: str) -> dict:
    """Keyword arguments for flask Response.set_cookie() to issue a session cookie."""
    return dict(
        key      = _COOKIE,
        value    = token,
        max_age  = _TTL,
        httponly = True,
        samesite = "Strict",
        path     = "/",
    )


def clear_cookie_kwargs() -> dict:
    """Keyword arguments to clear the session cookie."""
    return dict(
        key      = _COOKIE,
        value    = "",
        max_age  = 0,
        httponly = True,
        samesite = "Strict",
        path     = "/",
    )
