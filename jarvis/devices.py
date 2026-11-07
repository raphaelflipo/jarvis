"""
Appareils associés (iPhone…) : chacun a SA clé, révocable depuis le Mac. Le jeton principal ne quitte jamais le Mac.

Portées :
  • « full » : l'app Jarvis sur l'iPhone (mêmes droits qu'une connexion à distance : pas de réglages sensibles) ;
  • « ask »  : raccourci Siri / bouton Action / Partager — poser une question, envoyer un fichier, lancer une tâche.
Seule l'empreinte SHA-256 de chaque clé est enregistrée.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time

import config

_lock = threading.Lock()
SCOPES = ("full", "ask")


def _file():
    return config.JARVIS_DIR / "devices.json"


def _load() -> list[dict]:
    try:
        return json.loads(_file().read_text())
    except (OSError, ValueError):
        return []


def _save(items: list[dict]):
    f = _file()
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1))
    os.chmod(tmp, 0o600)
    tmp.replace(f)


def _h(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create(name: str, scope: str = "full") -> tuple[str, str]:
    """Nouvelle clé (renvoyée UNE fois). Les associations jamais utilisées depuis plus d'une heure sont retirées."""
    scope = scope if scope in SCOPES else "ask"
    key = "jv_" + secrets.token_urlsafe(32)
    did = secrets.token_hex(4)
    with _lock:
        items = [d for d in _load() if d.get("last_seen") or time.time() - d.get("created", 0) < 3600]
        items.append({"id": did, "name": (name or "iPhone").strip()[:40], "scope": scope, "hash": _h(key),
                      "created": time.time(), "last_seen": None})
        _save(items)
    return did, key


def verify(key) -> dict | None:
    if not isinstance(key, str) or not key.startswith("jv_"):
        return None
    hk = _h(key)
    for d in _load():
        if hmac.compare_digest(d.get("hash", ""), hk):
            return d
    return None


def touch(did: str):
    with _lock:
        items = _load()
        for d in items:
            if d["id"] == did and (not d.get("last_seen") or time.time() - d["last_seen"] > 60):
                d["last_seen"] = time.time()
                _save(items)
                break


def revoke(did: str) -> bool:
    with _lock:
        items = _load()
        keep = [d for d in items if d["id"] != did]
        if len(keep) == len(items):
            return False
        _save(keep)
    return True


def public() -> list[dict]:
    return [{k: d.get(k) for k in ("id", "name", "scope", "created", "last_seen")} for d in _load()]
