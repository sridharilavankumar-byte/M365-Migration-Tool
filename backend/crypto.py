"""
Symmetric encryption for sensitive values at rest (client secrets).

Encrypted values are stored with a `enc:v1:` prefix so we can detect legacy
plaintext during the transition period.
"""
from __future__ import annotations

import os
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("crypto")

PREFIX = "enc:v1:"

_fernet: Optional[Fernet] = None


def _get_fernet() -> Optional[Fernet]:
    global _fernet
    if _fernet is not None:
        return _fernet
    key = os.environ.get("CONN_ENCRYPTION_KEY")
    if not key:
        return None
    try:
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
        return _fernet
    except Exception as e:
        logger.error(f"Invalid CONN_ENCRYPTION_KEY: {e}")
        return None


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a plaintext string. Returns 'enc:v1:<token>'.
    If encryption is not configured, returns the plaintext unchanged (dev fallback).
    Empty input returns empty string.
    """
    if not plaintext:
        return ""
    if plaintext.startswith(PREFIX):
        # Already encrypted
        return plaintext
    f = _get_fernet()
    if not f:
        logger.warning("CONN_ENCRYPTION_KEY not set — storing secret in plaintext")
        return plaintext
    token = f.encrypt(plaintext.encode("utf-8")).decode("utf-8")
    return f"{PREFIX}{token}"


def decrypt_secret(stored: str) -> str:
    """Decrypt a stored value. Non-prefixed (legacy plaintext) is returned as-is."""
    if not stored:
        return ""
    if not stored.startswith(PREFIX):
        # Legacy plaintext — pass through so old records still work
        return stored
    f = _get_fernet()
    if not f:
        raise RuntimeError(
            "Encountered encrypted value but CONN_ENCRYPTION_KEY is not configured. "
            "Set the same key that was used to encrypt these values."
        )
    token = stored[len(PREFIX):]
    try:
        return f.decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        raise RuntimeError("Failed to decrypt secret — key mismatch or corrupted value")


def is_encrypted(stored: str) -> bool:
    return bool(stored) and stored.startswith(PREFIX)


def encrypt_tenant_config(cfg: dict) -> dict:
    """Return a copy of a tenant config dict with client_secret encrypted."""
    if not cfg:
        return cfg
    out = dict(cfg)
    secret = out.get("client_secret") or ""
    if secret and not is_encrypted(secret):
        out["client_secret"] = encrypt_secret(secret)
    return out


def decrypt_tenant_config(cfg: dict) -> dict:
    """Return a copy of a tenant config dict with client_secret decrypted
    (usable by MSAL). If the stored value is already plaintext (legacy),
    returns as-is."""
    if not cfg:
        return cfg
    out = dict(cfg)
    if out.get("client_secret"):
        out["client_secret"] = decrypt_secret(out["client_secret"])
    return out
