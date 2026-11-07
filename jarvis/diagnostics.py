"""Diagnostic complet de l'installation (utilisé par `jarvis doctor` et l'écran Réglages › Diagnostic)."""
from __future__ import annotations

import json
import platform
import shutil
import subprocess
from pathlib import Path

import config


def _run(cmd: str, timeout=20) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return False, "délai dépassé"


def power_state() -> dict:
    """Source d'alimentation du Mac. Sur batterie, macOS bride le GPU : le modèle local va nettement moins vite."""
    try:
        out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return {"known": False}
    import re
    m = re.search(r"(\d+)%", out)
    low = False
    try:
        low = "lowpowermode         1" in subprocess.run(["pmset", "-g"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        pass
    return {"known": bool(out), "battery": "Battery Power" in out, "percent": int(m.group(1)) if m else None,
            "low_power": low, "thermal": thermal_state()}


def thermal_state() -> int | None:
    """État thermique officiel de macOS : 0 normal · 1 tiède · 2 chaud (macOS bride la puce) · 3 critique."""
    try:
        import Foundation
        return int(Foundation.NSProcessInfo.processInfo().thermalState())
    except Exception:
        return None


def tailscale_ip() -> str | None:
    for exe in ("tailscale", "/Applications/Tailscale.app/Contents/MacOS/Tailscale"):
        try:
            r = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip().splitlines()[0]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


def tailscale_exe() -> str | None:
    for exe in ("/opt/homebrew/bin/tailscale", "/usr/local/bin/tailscale", "/Applications/Tailscale.app/Contents/MacOS/Tailscale"):
        if Path(exe).exists():
            return exe
    return shutil.which("tailscale")


def tailscale_url() -> str | None:
    exe = tailscale_exe()
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=6)
        dns = json.loads(r.stdout).get("Self", {}).get("DNSName", "").rstrip(".")
        return f"https://{dns}/" if dns else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def tailscale_state() -> str:
    """État de Tailscale : Running, Stopped (arrêté depuis la barre des menus), NeedsLogin, Starting…
    Vide si l'app ne répond pas (pas lancée)."""
    exe = tailscale_exe()
    if not exe:
        return ""
    try:
        r = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=6)
        return json.loads(r.stdout).get("BackendState", "") or ""
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return ""


def tailscale_devices() -> list[dict]:
    """Autres appareils de ton réseau Tailscale (pour savoir si l'iPhone y est déjà)."""
    exe = tailscale_exe()
    if not exe:
        return []
    try:
        r = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=6)
        peers = (json.loads(r.stdout).get("Peer") or {}).values()
        return [{"name": p.get("HostName", ""), "os": p.get("OS", ""), "online": bool(p.get("Online"))} for p in peers]
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


def realtime_check(port: int) -> tuple[str, str, str]:
    """Teste le serveur de Jarvis et la poignée de main WebSocket (sinon : flux HTTP de secours)."""
    import base64
    import os
    import socket
    try:
        import requests
        if not requests.get(f"http://127.0.0.1:{port}/healthz", timeout=2).ok:
            raise OSError
    except Exception:
        return "warn", "Serveur Jarvis arrêté (normal si l'app est fermée)", "Ouvre l'app Jarvis"
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=3) as s:
            key = base64.b64encode(os.urandom(16)).decode()
            s.sendall((f"GET /ws HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                       f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\nOrigin: http://127.0.0.1:{port}\r\n\r\n").encode())
            first = s.recv(256).decode(errors="replace").splitlines()[0] if True else ""
        if " 101 " in first + " ":
            return "ok", "Connexion temps réel (WebSocket)", ""
        return "warn", f"WebSocket indisponible ({first[:40]}) — flux HTTP de secours utilisé", \
               "~/.jarvis/venv/bin/pip install -U 'uvicorn[standard]' wsproto"
    except OSError as e:
        return "warn", f"WebSocket : {e}", "Consulte ~/.jarvis/logs/server.log"


def checks(cfg: dict) -> list[dict]:
    out: list[dict] = []

    def add(status, label, fix=""):
        out.append({"status": status, "label": label, "fix": fix})   # ok | warn | fail

    add("ok" if platform.machine() == "arm64" else "fail", f"Mac Apple Silicon (macOS {platform.mac_ver()[0] or '?'})")
    free = shutil.disk_usage(Path.home()).free // 2**30
    add("ok" if free > 15 else "warn", f"Espace disque libre : {free} Go", "Libère de l'espace (les modèles font 5 à 20 Go).")

    from llm import OllamaBackend, model_ctx
    b = OllamaBackend(cfg["ollama_host"], cfg["model"], "local", None)
    up = b.available()
    add("ok" if up else "fail", "Moteur IA Ollama actif", "launchctl kickstart -k gui/$(id -u)/com.jarvis.ollama")
    if up:
        names = b.models()
        has = lambda m: m and (m in names or f"{m}:latest" in names)
        add("ok" if has(cfg["model"]) else "fail", f"Modèle principal : {cfg['model']}", f"ollama pull {cfg['model']}")
        add("ok" if has(cfg.get("vision_model")) else "warn",
            f"Modèle vision : {cfg.get('vision_model') or 'aucun'}", "Réglages › Modèles, ou ollama pull gemma4:e4b")
        add("ok" if has(cfg.get("embed_model")) else "warn", f"Recherche sémantique : {cfg.get('embed_model')}",
            f"ollama pull {cfg.get('embed_model')}")
        try:
            res = b.chat([{"role": "user", "content": "Quelle heure est-il ? Utilise l'outil."}],
                         [{"type": "function", "function": {"name": "get_time", "description": "Donne l'heure",
                                                            "parameters": {"type": "object", "properties": {}}}}],
                         {"num_ctx": model_ctx(cfg, cfg["model"]), "temperature": 0})   # même contexte : pas de rechargement
            add("ok" if res["tool_calls"] else "fail", "Le modèle sait utiliser des outils",
                "Choisis un modèle compatible (qwen3, qwen3-coder, gemma4…)")
        except Exception as e:
            add("fail", f"Test du modèle : {str(e)[:120]}")
    if cfg.get("remote_ollama_host"):
        ok = OllamaBackend(cfg["remote_ollama_host"], "", "", None).available()
        add("ok" if ok else "warn", f"Ollama réseau : {cfg['remote_ollama_host']}", "Sur l'autre machine : OLLAMA_HOST=0.0.0.0 ollama serve")
    port = int(cfg.get("server", {}).get("port", 8765))
    st, lab, fix = realtime_check(port)
    add(st, lab, fix)
    import sandbox
    add("ok" if sandbox.available() and cfg.get("sandbox", True) else "warn",
        "Bac à sable macOS actif" if sandbox.available() else "Bac à sable indisponible",
        "Réglages › Sécurité › Bac à sable")
    ok, _ = _run("osascript -e 'tell application \"System Events\" to get name of first process'")
    add("ok" if ok else "warn", "Autorisation Accessibilité / Automatisation",
        "Réglages Système › Confidentialité et sécurité › Accessibilité → active Jarvis")
    add("ok" if Path("/Applications/Xcode.app").exists() else "warn", "Xcode installé", "App Store → Xcode (gratuit)")
    add("ok" if shutil.which("code") or Path("/opt/homebrew/bin/code").exists() else "warn", "VS Code (commande code)",
        "brew install --cask visual-studio-code")
    ok, _ = _run("PATH=/opt/homebrew/bin:$PATH gh auth status")
    add("ok" if ok else "warn", "GitHub connecté", "Terminal : gh auth login --web")
    ok, o = _run("git config --global user.email")
    add("ok" if ok and "@" in o else "warn", "Identité Git configurée", "git config --global user.email ton@mail")
    ok, o = _run("PATH=/opt/homebrew/bin:$PATH firebase login:list", 30)
    add("ok" if ok and "@" in o else "warn", "Firebase connecté", "Terminal : firebase login")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            exe = Path(p.chromium.executable_path)
        add("ok" if exe.exists() else "warn", "Navigateur intégré (Chromium)", "~/.jarvis/venv/bin/python -m playwright install chromium")
    except Exception as e:
        add("warn", f"Navigateur intégré : {str(e)[:80]}", "~/.jarvis/venv/bin/python -m playwright install chromium")
    url = tailscale_url()
    add("ok" if url else "warn", f"Accès à distance : {url or 'Tailscale non connecté'}", "Réglages › Accès à distance")
    n = cfg.get("ntfy") or {}
    add("ok" if n.get("enabled") else "warn", "Notifications téléphone (ntfy)", "Réglages › Notifications")
    add("ok" if cfg.get("autonomy") != "total" else "warn", f"Autonomie : {cfg.get('autonomy')}", "Le mode total est déconseillé au quotidien")
    perm = oct(config.JARVIS_DIR.stat().st_mode)[-3:] if config.JARVIS_DIR.exists() else "?"
    add("ok" if perm == "700" else "warn", f"Dossier privé ~/.jarvis ({perm})", "chmod 700 ~/.jarvis")
    return out
