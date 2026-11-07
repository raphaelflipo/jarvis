"""
Notifications sur l'iPhone, sans app ni service tiers : le « Web Push » standard (RFC 8030/8291/8292), que l'iPhone
accepte pour une app web ajoutée à l'écran d'accueil. Gratuit : Apple transmet, le contenu est chiffré de bout en
bout (Apple ne peut pas le lire).

Clé du Mac (VAPID) : ~/.jarvis/push/vapid.pem (lisible par toi seul). Abonnements : ~/.jarvis/push/subs.json.
"""
from __future__ import annotations

import base64
import json
import os
import threading
import time
from urllib.parse import urlparse

import config

# Seuls les vrais services de notification sont acceptés (un abonnement ne peut pas faire écrire le Mac ailleurs)
PUSH_HOSTS = ("web.push.apple.com", "fcm.googleapis.com", "updates.push.services.mozilla.com", "notify.windows.com")
_lock = threading.Lock()


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _dir():
    d = config.JARVIS_DIR / "push"
    d.mkdir(parents=True, exist_ok=True)
    return d


def available() -> bool:
    try:
        import cryptography  # noqa: F401
        return True
    except ImportError:
        return False


def _private_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    f = _dir() / "vapid.pem"
    if f.exists():
        return serialization.load_pem_private_key(f.read_bytes(), password=None)
    key = ec.generate_private_key(ec.SECP256R1())
    f.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()))
    os.chmod(f, 0o600)
    return key


def public_key() -> str:
    """Clé publique du Mac à donner au navigateur (applicationServerKey)."""
    from cryptography.hazmat.primitives import serialization
    pub = _private_key().public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return b64u(pub)


def encrypt(payload: bytes, p256dh: str, auth: str, salt: bytes | None = None, server_key=None) -> bytes:
    """Chiffrement « aes128gcm » de RFC 8291 : seul l'appareil abonné peut lire le message."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    ua_public = unb64u(p256dh)
    secret = unb64u(auth)
    as_key = server_key or ec.generate_private_key(ec.SECP256R1())
    as_public = as_key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    shared = as_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public))
    ikm = HKDF(hashes.SHA256(), 32, secret, b"WebPush: info\x00" + ua_public + as_public).derive(shared)
    salt = salt or os.urandom(16)
    cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
    body = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + (4096).to_bytes(4, "big") + bytes([len(as_public)]) + as_public + body


def vapid_auth(endpoint: str, sub: str) -> str:
    """En-tête d'authentification VAPID (RFC 8292) : prouve que la notification vient de TON Mac."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    u = urlparse(endpoint)
    head = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    claims = b64u(json.dumps({"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + 12 * 3600, "sub": sub},
                             separators=(",", ":")).encode())
    signing = f"{head}.{claims}".encode()
    r, s = decode_dss_signature(_private_key().sign(signing, ec.ECDSA(hashes.SHA256())))
    jwt = f"{head}.{claims}.{b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
    return f"vapid t={jwt}, k={public_key()}"


# ------------------------------------------------------------------ abonnements
def _subs_file():
    return _dir() / "subs.json"


def subs() -> list[dict]:
    try:
        return json.loads(_subs_file().read_text())
    except (OSError, ValueError):
        return []


def _save(items: list[dict]):
    f = _subs_file()
    f.write_text(json.dumps(items, indent=1))
    os.chmod(f, 0o600)


def valid_endpoint(url: str) -> bool:
    u = urlparse(url or "")
    host = (u.hostname or "").lower()
    return u.scheme == "https" and any(host == h or host.endswith("." + h) for h in PUSH_HOSTS)


def subscribe(sub: dict, device: str = "") -> str:
    ep = (sub or {}).get("endpoint", "")
    keys = (sub or {}).get("keys") or {}
    if not valid_endpoint(ep) or not keys.get("p256dh") or not keys.get("auth"):
        return "Abonnement refusé (service de notification inconnu)."
    with _lock:
        items = [s for s in subs() if s["endpoint"] != ep]
        items.append({"endpoint": ep, "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]}, "device": device[:40],
                      "created": time.time()})
        _save(items)
    return ""


def unsubscribe_device(device: str):
    with _lock:
        _save([s for s in subs() if s.get("device") != device])


def send_all(title: str, body: str, url: str = "/", tag: str = "", urgent: bool = False, sub_claim: str = "") -> int:
    """Envoie à tous les appareils abonnés ; retire ceux qui ne sont plus valables. Renvoie le nombre d'envois réussis."""
    items = subs()
    if not items or not available():
        return 0
    import requests
    data = json.dumps({"title": title[:120], "body": body[:600], "url": url, "tag": tag}, ensure_ascii=False).encode()
    if not sub_claim:                         # Apple exige une adresse de contact : celle de TON Mac sur Tailscale
        try:
            import diagnostics
            sub_claim = diagnostics.tailscale_url() or ""
        except Exception:
            sub_claim = ""
    claim = sub_claim if sub_claim.startswith("https://") else "mailto:jarvis@localhost.localdomain"
    ok, dead = 0, []
    for s in items:
        try:
            r = requests.post(s["endpoint"], data=encrypt(data, s["keys"]["p256dh"], s["keys"]["auth"]), timeout=15,
                              headers={"Authorization": vapid_auth(s["endpoint"], claim), "Content-Encoding": "aes128gcm",
                                       "Content-Type": "application/octet-stream", "TTL": "86400",
                                       "Urgency": "high" if urgent else "normal", **({"Topic": tag[:32]} if tag else {})})
            if r.status_code in (404, 410):
                dead.append(s["endpoint"])
            elif r.status_code < 300:
                ok += 1
        except Exception:
            pass
    if dead:
        with _lock:
            _save([s for s in subs() if s["endpoint"] not in dead])
    return ok


def send_async(*a, **k):
    if subs():
        threading.Thread(target=send_all, args=a, kwargs=k, daemon=True, name="jarvis-push").start()
