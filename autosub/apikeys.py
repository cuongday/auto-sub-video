"""API keys entered in the web UI. Kept encrypted (Fernet) in MinIO and never sent back to the browser: the UI only
sees the last 4 characters and a SHA-256 fingerprint. A key saved on the web wins over the one in .env."""
import base64
import hashlib
import time
from cryptography.fernet import Fernet, InvalidToken
from . import config
from .storage import get_store, read_json, write_json

KEYS = "secrets/api_keys.json"
# one entry per provider: the web UI lists exactly these. `env` is the config attribute read as the .env fallback.
PROVIDERS = {
    "openai": {"label": "OpenAI", "placeholder": "sk-...", "env": "OPENAI_API_KEY"},
}

def _env(provider: str) -> str | None:
    return getattr(config, PROVIDERS[provider]["env"], None) or None

class KeyStoreError(Exception):
    pass

def _fernet() -> Fernet:
    secret = config.APP_SECRET
    if not secret:
        raise KeyStoreError("Chưa có khoá mã hoá: đặt AUTOSUB_SECRET (hoặc MINIO_ROOT_PASSWORD) trong .env")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("autosub-keys\x1f" + secret).encode()).digest()))

def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]

def _load() -> dict:
    return read_json(get_store(), KEYS, default={})

def save(provider: str, value: str) -> None:
    value = value.strip()
    if provider not in PROVIDERS:
        raise KeyStoreError(f"Không hỗ trợ {provider!r}")
    if len(value) < 20 or any(c.isspace() for c in value):
        raise KeyStoreError("API key không hợp lệ")
    keys = _load()
    keys[provider] = {"enc": _fernet().encrypt(value.encode()).decode(), "last4": value[-4:],
                      "sha256": fingerprint(value), "saved": time.time()}
    write_json(get_store(), KEYS, keys)

def clear(provider: str) -> None:
    keys = _load()
    if keys.pop(provider, None) is not None:
        write_json(get_store(), KEYS, keys)

def _web(provider: str) -> str | None:
    rec = _load().get(provider)
    if not rec:
        return None
    try:
        return _fernet().decrypt(rec["enc"].encode()).decode()
    except (InvalidToken, KeyStoreError):
        return None                        # secret changed since it was saved: the user enters the key again

def get(provider: str) -> str | None:
    """The key to call the provider with: web first, then .env."""
    return _web(provider) or _env(provider)

def info(provider: str) -> dict:
    """What the UI may know about a key: where it comes from and its last 4 characters, never the key."""
    rec = _load().get(provider)
    if rec and _web(provider):
        return {"source": "web", "last4": rec["last4"], "sha256": rec["sha256"], "saved": rec["saved"]}
    env = _env(provider)
    if env:
        return {"source": "env", "last4": env[-4:], "sha256": fingerprint(env), "saved": None}
    return {"source": None, "last4": "", "sha256": "", "saved": None,
            "stale": bool(rec)}             # saved but cannot be decrypted any more

def listing() -> list[dict]:
    meta = lambda p: {"id": p, "label": PROVIDERS[p]["label"], "placeholder": PROVIDERS[p]["placeholder"],  # noqa: E731
                      "env": PROVIDERS[p]["env"]}
    return [{**meta(p), **info(p)} for p in PROVIDERS]
