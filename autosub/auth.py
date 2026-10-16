"""Optional password for the web UI (set AUTOSUB_PASSWORD). Off by default: the app binds to 127.0.0.1.
Needed when AUTOSUB_BIND=0.0.0.0 opens it to the LAN, because the app can browse HOST_ROOT."""
import hashlib
import hmac
import secrets
import time

COOKIE = "autosub_session"
MAX_AGE = 30 * 24 * 3600

def _key(password: str) -> bytes:
    return hashlib.sha256(("autosub\x1f" + password).encode()).digest()

def make_token(password: str) -> str:
    ts = str(int(time.time()))
    nonce = secrets.token_hex(8)
    sig = hmac.new(_key(password), f"{ts}.{nonce}".encode(), hashlib.sha256).hexdigest()
    return f"{ts}.{nonce}.{sig}"

def valid(token: str, password: str) -> bool:
    try:
        ts, nonce, sig = token.split(".")
        if time.time() - int(ts) > MAX_AGE:
            return False
    except ValueError:
        return False
    want = hmac.new(_key(password), f"{ts}.{nonce}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, want)

def check_password(given: str, password: str) -> bool:
    return hmac.compare_digest(given.encode(), password.encode())
