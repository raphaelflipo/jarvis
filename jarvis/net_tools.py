"""Outils réseau : SSH vers tes machines, requêtes HTTP/API, diagnostic, notifications téléphone (ntfy)."""
from __future__ import annotations

import json
import re
import socket
import subprocess
import time

import requests

import security
from registry import I, P, S, Ctx, tool, trunc
from security import BLOCKED, NORMAL, RISKY, SAFE
from tools import env, sh

HOST_RE = re.compile(r"^[A-Za-z0-9._-]+(@[A-Za-z0-9._:-]+)?$")


def _trusted(host: str) -> bool:
    return host in (Ctx.cfg.get("ssh_trusted_hosts") or [])


def _risk_ssh(host, command, **k):
    if not HOST_RE.match(host):
        return BLOCKED, "nom d'hôte invalide"
    lvl, why = security.shell_level(command)
    if lvl == BLOCKED:
        return lvl, why
    if not _trusted(host):
        return RISKY, f"première connexion à {host} dans cette session"
    return max(lvl, NORMAL), why


@tool("ssh_run",
      "Exécute une commande sur une autre machine via SSH (clés de ~/.ssh, hôtes de ~/.ssh/config). "
      "Ex : host='pi@192.168.1.30' ou un alias, command='uptime'.",
      {"host": S("user@hôte ou alias SSH"), "command": S("Commande distante"), "timeout": I("Secondes")},
      ["host", "command"], category="net", risk=_risk_ssh,
      summary=lambda host, command, **k: f"[ssh {host}] $ {command}")
def ssh_run(host: str, command: str, timeout: int = 120):
    import shlex
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                        "-o", "StrictHostKeyChecking=accept-new", host, command],
                       capture_output=True, text=True, timeout=timeout or 120, env=env(), stdin=subprocess.DEVNULL)
    # hôte approuvé pour le reste de la session
    trusted = Ctx.cfg.setdefault("ssh_trusted_hosts", [])
    if r.returncode != 255 and host not in trusted:
        trusted.append(host)
    out = (r.stdout + ("\n[stderr]\n" + r.stderr if r.stderr.strip() else "")).strip()
    if r.returncode == 255:
        out += ("\n→ Connexion SSH impossible. Vérifie l'hôte, et que ta clé est installée : "
                f"`ssh-copy-id {shlex.quote(host)}` (à faire toi-même une fois).")
    return trunc(f"[code retour {r.returncode}]\n{out}")


@tool("ssh_copy", "Copie un fichier/dossier vers ou depuis une machine distante (scp). "
                  "Distant = 'hôte:chemin'. Ex : src='site/', dst='pi@192.168.1.30:/var/www/'.",
      {"src": S("Source"), "dst": S("Destination")}, category="net",
      risk=lambda src, dst: (BLOCKED, "clé privée") if ".ssh/id_" in src else (RISKY, "transfert réseau"),
      summary=lambda src, dst: f"scp {src} → {dst}")
def ssh_copy(src: str, dst: str):
    def loc(x):
        return x if ":" in x and not x.startswith("/") else str(P(x))
    r = subprocess.run(["scp", "-r", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", loc(src), loc(dst)],
                       capture_output=True, text=True, timeout=1800, env=env())
    return trunc(f"[code retour {r.returncode}] {(r.stdout + r.stderr).strip() or 'Copie terminée'}")


# ---------------------------------------------------------------- HTTP / API
def _resolve_secrets(obj):
    """Remplace {{keychain:nom}} par le secret du Trousseau — le modèle ne voit jamais la valeur."""
    if isinstance(obj, str):
        def rep(m):
            v = security.keychain_get(m.group(1))
            if v is None:
                raise ValueError(f"secret « {m.group(1)} » absent du Trousseau (jarvis secret set {m.group(1)})")
            return v
        return re.sub(r"\{\{keychain:([A-Za-z0-9_.-]+)\}\}", rep, obj)
    if isinstance(obj, dict):
        return {k: _resolve_secrets(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_secrets(v) for v in obj]
    return obj


def _risk_http(method, url, **k):
    if not url.startswith(("http://", "https://")):
        return BLOCKED, "seuls http(s) sont autorisés"
    m = (method or "GET").upper()
    if m in ("GET", "HEAD"):
        if Ctx.policy.tainted and ("?" in url or len(url) > 160):
            return RISKY, "requête avec paramètres après lecture de contenu externe"
        return SAFE, ""
    return RISKY, f"requête {m} (modifie un service distant)"


@tool("http_request",
      "Requête HTTP/API (REST, webhooks, appareils du réseau local, API Firebase…). Pour un secret, écris "
      "{{keychain:nom}} dans les headers : il est injecté depuis le Trousseau sans jamais t'être montré.",
      {"method": S("GET|POST|PUT|PATCH|DELETE|HEAD", enum=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]),
       "url": S("URL"), "headers": {"type": "object", "description": "En-têtes"},
       "json_body": {"type": "object", "description": "Corps JSON"}, "body": S("Corps texte brut")},
      ["method", "url"], category="net", risk=_risk_http, untrusted=True,
      summary=lambda method, url, **k: f"HTTP {method} {url}")
def http_request(method: str, url: str, headers: dict | None = None, json_body: dict | None = None, body: str = ""):
    h = _resolve_secrets(headers or {})
    h.setdefault("User-Agent", "Jarvis/3")
    r = requests.request(method.upper(), url, headers=h, json=json_body if json_body else None,
                         data=body.encode() if body and not json_body else None, timeout=40)
    ctype = r.headers.get("content-type", "")
    text = r.text
    if "json" in ctype:
        try:
            text = json.dumps(r.json(), ensure_ascii=False, indent=1)
        except ValueError:
            pass
    return trunc(f"HTTP {r.status_code} {r.reason} ({ctype})\n{text}", 15000)


# ---------------------------------------------------------------- diagnostic
@tool("net_check", "Teste la joignabilité d'une machine/service : ping et connexion TCP à un port.",
      {"host": S("Hôte ou IP"), "port": I("Port TCP (facultatif)")}, ["host"], category="read")
def net_check(host: str, port: int = 0):
    if not re.fullmatch(r"[A-Za-z0-9._:-]+", host):
        return "[erreur] hôte invalide"
    out = [sh(f"ping -c 2 -W 2000 {host} 2>&1 | tail -3", timeout=15, sandboxed=False)]
    if port:
        t0 = time.time()
        try:
            with socket.create_connection((host, int(port)), timeout=5):
                out.append(f"Port {port} : OUVERT ({(time.time() - t0) * 1000:.0f} ms)")
        except OSError as e:
            out.append(f"Port {port} : FERMÉ ou filtré ({e})")
    return "\n".join(out)


@tool("network_info", "Infos réseau du Mac : IP locale, Wi-Fi, IP Tailscale et machines du tailnet.", {}, [], category="read")
def network_info():
    parts = [sh("echo IP locale : $(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1)", timeout=10, sandboxed=False),
             sh("networksetup -getairportnetwork en0 2>/dev/null", timeout=10, sandboxed=False),
             sh("command -v tailscale >/dev/null && tailscale status 2>&1 | head -20 || "
                "echo 'Tailscale non installé (gratuit : brew install --cask tailscale)'", timeout=15, sandboxed=False)]
    return "\n".join(parts)


# ---------------------------------------------------------------- notifications téléphone
@tool("notify_phone", "Envoie une notification sur ton téléphone via ntfy (gratuit, sur ton sujet privé).",
      {"title": S("Titre"), "message": S("Message"), "priority": S("low|default|high", enum=["low", "default", "high"])},
      ["title", "message"], category="send", risk=lambda **k: (NORMAL, ""))
def notify_phone(title: str, message: str, priority: str = "default"):
    n = Ctx.cfg.get("ntfy") or {}
    if not n.get("enabled") or not n.get("topic"):
        return "[erreur] ntfy non configuré (lance `jarvis setup-phone` ou Réglages › Notifications)."
    return send_ntfy(n, title, message, priority)


def send_ntfy(n: dict, title: str, message: str, priority: str = "default") -> str:
    try:
        r = requests.post(f"{n.get('server', 'https://ntfy.sh').rstrip('/')}/{n['topic']}",
                          data=security.redact(message)[:3500].encode(),
                          headers={"Title": title[:120].encode("ascii", "ignore").decode() or "Jarvis",
                                   "Priority": {"low": "2", "high": "4"}.get(priority, "3"), "Tags": "robot"},
                          timeout=15)
        return "Notification envoyée." if r.ok else f"[erreur] ntfy HTTP {r.status_code}"
    except requests.RequestException as e:
        return f"[erreur] ntfy : {e}"
