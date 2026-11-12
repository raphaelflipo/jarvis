"""
Hub de Jarvis : sessions des interfaces connectées (WebSocket OU flux HTTP de secours), authentification,
diffusion des événements des tâches, traitement des commandes, pièces jointes, réglages.
Indépendant de FastAPI pour être testable et réutilisable.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import re
import secrets
import select
import subprocess
import threading
import sys
import time
import traceback
from datetime import date
from pathlib import Path

import config
import diagnostics
import agenda
import devices
import engine
import myfiles
import nightly
import push
import projects
import recipes
import security
import voice
from attach import KIND_LABEL, attachments_block, human_size, kind_of  # noqa: F401
from llm import (KEY_FORMATS, PROVIDERS, AppleBackend, LLMError, OpenAICompatBackend, cloud_key, exhausted_today,
                 fallback_chain, key_account, looks_like_key, pick_model, rank_models)
from tasks import TaskManager

SETTABLE = {"model", "vision_model", "autonomy", "max_parallel_tasks", "max_subtasks", "verify", "think", "sandbox",
            "project_dirs", "voice", "ntfy", "browser_headless", "remote_ollama_host", "remote_model", "prefer_remote",
            "workspace", "num_ctx", "native_glass", "cloud", "recipes", "project_notes", "thermal_guard", "hotkey", "nightly",
            "apple", "my_files"}
LOCAL_ONLY = {"sandbox", "remote_ollama_host", "workspace", "cloud", "hotkey", "nightly", "apple", "my_files"}
UPLOAD_DIRNAME = "Fichiers reçus"
MAX_UPLOAD = 4 * 1024**3   # 4 Go par fichier


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)

def get_token() -> str:
    if config.TOKEN_FILE.exists():
        t = config.TOKEN_FILE.read_text().strip()
        if t:
            return t
    config.ensure_dirs()
    tok = secrets.token_urlsafe(32)
    config.TOKEN_FILE.write_text(tok)
    os.chmod(config.TOKEN_FILE, 0o600)
    return tok


def safe_project_dir(p: str) -> str | None:
    path = security.resolve(p)
    if not path.is_dir() or not security.under(path, config.HOME) or path == config.HOME:
        return None
    rel = path.relative_to(config.HOME).parts
    if rel[0].startswith(".") or rel[0] == "Library":
        return None
    return str(path)


def uploads_root(cfg: dict) -> Path:
    return Path(cfg.get("workspace", config.HOME / "JarvisWorkspace")).expanduser() / UPLOAD_DIRNAME


def safe_filename(name: str) -> str:
    base = Path(str(name).replace("\\", "/")).name.strip()
    base = re.sub(r"[^\w.\-()+,'& ]+", "_", base, flags=re.UNICODE).strip(" .")
    if not base:
        base = "fichier"
    stem, ext = os.path.splitext(base)
    return (stem[:110] or "fichier") + ext[:12]


def new_upload_path(cfg: dict, name: str) -> Path:
    d = uploads_root(cfg) / date.today().isoformat()
    d.mkdir(parents=True, exist_ok=True)
    fn = safe_filename(name)
    p = d / fn
    stem, ext = os.path.splitext(fn)
    i = 2
    while p.exists():
        p = d / f"{stem} ({i}){ext}"
        i += 1
    return p


def public_settings(cfg: dict) -> dict:
    import sandbox
    from llm import OllamaBackend
    try:
        models = OllamaBackend(cfg["ollama_host"], "", "", None).models()
    except Exception:
        models = []
    n = cfg.get("ntfy") or {}
    return {
        "model": cfg["model"], "vision_model": cfg.get("vision_model", ""), "models": models,
        "autonomy": cfg.get("autonomy"), "max_parallel_tasks": cfg.get("max_parallel_tasks"),
        "max_subtasks": cfg.get("max_subtasks"), "verify": cfg.get("verify"), "think": cfg.get("think"),
        "sandbox": cfg.get("sandbox"), "sandbox_available": sandbox.available(), "project_dirs": cfg.get("project_dirs", []),
        "workspace": cfg.get("workspace"), "voice": cfg.get("voice"),
        "ntfy": {"enabled": n.get("enabled"), "topic": n.get("topic", "")},
        "browser_headless": cfg.get("browser_headless"), "remote_ollama_host": cfg.get("remote_ollama_host", ""),
        "remote_model": cfg.get("remote_model", ""), "prefer_remote": cfg.get("prefer_remote", False),
        "num_ctx": cfg.get("num_ctx"), "native_glass": cfg.get("native_glass", True),
        "remote_url": diagnostics.tailscale_url(), "remote_serving": serve_active(cfg), "version": config.VERSION,
        "tailscale_devices": diagnostics.tailscale_devices(),
        "uploads": str(uploads_root(cfg)),
        "cloud": _cloud_public(cfg),
        "recipes": cfg.get("recipes", True), "recipes_count": recipes.count(),
        "project_notes": cfg.get("project_notes", True), "projects_count": len(projects.known()),
        "thermal_guard": cfg.get("thermal_guard", True), "hotkey": cfg.get("hotkey", "alt+space"),
        "nightly": cfg.get("nightly", True), "nightly_last": nightly.load_state(),
        "whisper": voice.available(),
        "voices": voice.voices() if sys.platform == "darwin" else [],
        "devices": devices.public(),
        "my_files": {"enabled": bool((cfg.get("my_files") or {}).get("enabled")), "state": myfiles.state(),
                     "folders": [str(f) for f in myfiles.folders(cfg)]},
        "apple": {"enabled": bool((cfg.get("apple") or {}).get("enabled")),
                  "installed": sys.platform == "darwin" and AppleBackend.installed()},
        "push": {"available": push.available(), "key": push.public_key() if push.available() else "",
                 "count": len(push.subs())},
        "agenda": agenda.status() if sys.platform == "darwin" else {},
        "engine": cfg.get("engine", "ollama"), "mlx_available": engine.available(cfg.get("model", "")),
        "cloud_providers": {k: {"label": p["label"], "note": p["note"], "key_url": p["key_url"]} for k, p in PROVIDERS.items()},
    }


def _cloud_public(cfg: dict) -> dict:
    c = cfg.get("cloud") or {}
    prov = c.get("provider", "gemini")
    r = c.get("relay") or {}
    rp = r.get("provider", "")
    return {"enabled": bool(c.get("enabled")), "provider": prov, "model": c.get("model", ""), "mode": c.get("mode", "ask"),
            "models": c.get("models", []), "has_key": bool(cloud_key(prov)) if prov in PROVIDERS else False,
            "exhausted": exhausted_today() if c.get("enabled") else [],     # quotas gratuits du jour épuisés
            "relay": {"enabled": bool(r.get("enabled")), "provider": rp, "model": r.get("model", ""),
                      "has_key": bool(cloud_key(rp)) if rp in PROVIDERS else False} if rp else None}


def serve_active(cfg: dict) -> bool:
    exe = diagnostics.tailscale_exe()
    if not exe:
        return False
    try:
        r = subprocess.run([exe, "serve", "status"], capture_output=True, text=True, timeout=6)
        return str(cfg["server"]["port"]) in r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False


def qr_svg(text: str) -> str:
    """QR code (SVG) du lien de connexion : se scanne avec l'appareil photo de l'iPhone. Affiché sur le Mac seulement."""
    try:
        import qrcode
        import qrcode.image.svg
        img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=2)
        return img.to_string(encoding="unicode")
    except Exception as e:
        return f"<p>QR code indisponible ({str(e)[:80]}). Utilise « Copier le lien de connexion ».</p>"


_SERVE_WAIT: dict = {}


def _await_serve(p: subprocess.Popen, on_done, limit: float = 900):
    """Tailscale attend que tu cliques sur « Enable » puis termine tout seul la configuration : on le laisse faire
    (15 min au plus) et on prévient l'app dès que l'accès distant est actif."""
    try:
        p.wait(timeout=limit)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, 15)              # tout le groupe : /usr/local/bin/tailscale est un script qui lance l'app
        except OSError:
            p.kill()
    finally:
        _SERVE_WAIT.pop("p", None)
    if on_done:
        ok = serve_active(config.load())
        on_done(f"Accès distant activé : {diagnostics.tailscale_url()}" if ok else
                "Accès distant : autorisation « Serve » non reçue. Reclique sur « Activer l'accès distant » pour réessayer.", ok)


def _ts_wait(states: tuple, timeout: float) -> str:
    t0, st = time.time(), diagnostics.tailscale_state()
    while st not in states and time.time() - t0 < timeout:
        time.sleep(1)
        st = diagnostics.tailscale_state()
    return st


def _ts_message(out: str) -> str:
    """Messages de Tailscale (en anglais) traduits en consignes claires."""
    low = (out or "").lower()
    if "stopped" in low:
        return ("Tailscale est arrêté : clique sur son icône dans la barre des menus, puis sur « Connect », "
                "et réessaie.")
    if "needslogin" in low or "logged out" in low or "log in" in low:
        return "Tailscale te demande de te reconnecter : clique sur son icône dans la barre des menus, puis « Log in »."
    if "failed to connect" in low or "is tailscale running" in low:
        return "Tailscale n'est pas lancé : ouvre l'app Tailscale (Applications), puis réessaie."
    return f"Tailscale : {(out or 'pas de réponse').strip()[:300]}"


def ensure_tailscale(exe: str) -> str:
    """Remet Tailscale en route si besoin (tu as demandé l'accès distant, qui en dépend). Renvoie "" si c'est bon."""
    st = diagnostics.tailscale_state()
    if st == "Running":
        return ""
    if st in ("", "NoState"):                 # app pas lancée (après un redémarrage du Mac, par ex.)
        subprocess.run(["open", "-g", "-a", "Tailscale"], capture_output=True)
        st = _ts_wait(("Running", "Stopped", "NeedsLogin", "NeedsMachineAuth"), 20)
    if st == "Stopped":                       # coupé depuis la barre des menus : on le reconnecte, réglages inchangés
        r = subprocess.run([exe, "up"], capture_output=True, text=True, timeout=30)
        st = _ts_wait(("Running", "NeedsLogin"), 15)
        if st != "Running" and r.returncode != 0:
            security.audit({"type": "tailscale_up", "ok": False, "out": (r.stderr or r.stdout)[:200]})
    if st == "Running":
        security.audit({"type": "tailscale_up", "ok": True})
        return ""
    subprocess.run(["open", "-a", "Tailscale"], capture_output=True)
    return _ts_message(st or "failed to connect")


def _start_serve(exe: str, port: str) -> tuple[subprocess.Popen, str]:
    p = subprocess.Popen([exe, "serve", "--bg", port], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         start_new_session=True)
    out, t0, fd = "", time.time(), p.stdout.fileno()
    while time.time() - t0 < 10:              # lecture sans bloquer : Tailscale peut attendre longtemps
        r, _, _ = select.select([fd], [], [], 0.5)
        if not r:
            if p.poll() is not None:
                break
            continue
        chunk = os.read(fd, 4096)
        if not chunk:
            p.wait(timeout=5)
            break
        out += chunk.decode("utf-8", "replace")
        if re.search(r"https://login\.tailscale\.com/\S+\s", out):
            break
    return p, out


def set_remote(enable: bool, on_done=None) -> str:
    exe = diagnostics.tailscale_exe()
    if not exe:
        return "Tailscale n'est pas installé (gratuit : brew install --cask tailscale, puis connecte-toi)."
    port = str(config.load()["server"]["port"])
    if not enable:
        r = subprocess.run([exe, "serve", "reset"], capture_output=True, text=True, timeout=20)
        return "Accès distant désactivé." if r.returncode == 0 else _ts_message(r.stderr or r.stdout)
    err = ensure_tailscale(exe)
    if err:
        return err
    # Première fois : Tailscale demande d'autoriser « Serve » (HTTPS) sur ton réseau et attend indéfiniment.
    # On repère ce cas, on ouvre la page d'autorisation pour toi, et on ne bloque pas Jarvis.
    if _SERVE_WAIT.get("p") and _SERVE_WAIT["p"].poll() is None:
        return "Jarvis attend toujours ton clic sur « Enable » dans la page Tailscale (ouverte dans ton navigateur)."
    for attempt in range(4):
        p, out = _start_serve(exe, port)
        # Juste après une reconnexion, le serveur de Tailscale répond parfois « 500 … serverNoiseKey » : passager
        if p.poll() is not None and ("serverNoiseKey" in out or "500 Internal Server Error" in out) and attempt < 3:
            time.sleep(3)
            continue
        break
    m = re.search(r"https://login\.tailscale\.com/\S+", out or "")
    if m and "not enabled" in (out or ""):
        subprocess.run(["open", m.group(0)], capture_output=True)
        _SERVE_WAIT["p"] = p
        threading.Thread(target=_await_serve, args=(p, on_done), daemon=True).start()
        return ("Une seule fois : clique sur « Enable » dans la page Tailscale qui vient de s'ouvrir. "
                "Jarvis active ensuite l'accès distant tout seul et te prévient.")
    if p.poll() is None:
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, 15)
            except OSError:
                p.kill()
    if p.returncode not in (0, None) or not serve_active(config.load()):
        return _ts_message(out)
    return f"Accès distant activé : {diagnostics.tailscale_url()}"


# ====================================================================== sessions
class Session:
    def __init__(self, hub: "Hub", kind: str, ip: str, remote: bool, ws=None):
        self.hub, self.kind, self.ip, self.remote, self.ws = hub, kind, ip, remote, ws
        self.device: dict = {}                    # appareil associé (clé révocable), vide pour le jeton du Mac
        self.id = secrets.token_urlsafe(18)
        self.queue: asyncio.Queue | None = asyncio.Queue(maxsize=5000) if kind == "http" else None
        self.last_seen = time.time()
        self.attached = kind == "ws"

    async def send(self, data: str):
        try:
            if self.ws is not None:
                await self.ws.send_text(data)
            elif self.queue is not None:
                if self.queue.full():
                    self.queue.get_nowait()
                self.queue.put_nowait(data)
        except Exception as e:
            if str(e):
                log(f"[session {self.kind}] envoi impossible : {e}")
            self.hub.sessions.pop(self.id, None)

    async def reply(self, obj: dict):
        await self.send(json.dumps(obj, ensure_ascii=False, default=str))


class Hub:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.stopped = threading.Event()
        self.token = get_token()
        self.sessions: dict[str, Session] = {}
        self.loop: asyncio.AbstractEventLoop | None = None
        self.fails: dict[str, list[float]] = {}
        self.downloads: dict[str, tuple] = {}     # liens de téléchargement à usage unique (raccourcis iPhone)
        self.manager = TaskManager(cfg, broadcast=self.broadcast)
        self.manager.warmup()
        self.power = diagnostics.power_state()
        self.manager.set_thermal(self.power.get("thermal"))
        self.power_thread = threading.Thread(target=self._watch_power, daemon=True, name="jarvis-power")
        self.power_thread.start()
        threading.Thread(target=self._ensure_nightly, daemon=True, name="jarvis-nightly").start()
        threading.Thread(target=self._warmup, daemon=True, name="jarvis-warmup").start()
        threading.Thread(target=myfiles.watch, args=(lambda: self.cfg, self.stopped), daemon=True, name="jarvis-myfiles").start()

    def _warmup(self):
        """Préchauffage : le modèle lit tout de suite les instructions de base et les outils du noyau, gardés en
        mémoire. La première vraie demande démarre alors en quelques secondes au lieu d'une minute."""
        if self.stopped.wait(3):
            return
        try:
            import registry
            from core import Agent
            a = Agent(self.cfg, ui=None)
            msgs = [a._system()] + a._context() + [{"role": "user", "content": "Réponds juste : ok"}]
            a.router.chat(msgs, tools=registry.schemas_for(set()), options={"num_predict": 1, "temperature": 0})
            log("[préchauffage] modèle prêt")
        except Exception as e:
            log(f"[préchauffage] {e}")

    def _ensure_nightly(self):
        """Contrôle automatique (banc d'essai quand le Mac est branché et inutilisé) : service installé si activé."""
        try:
            if sys.platform == "darwin" and self.cfg.get("nightly", False) and not nightly.installed():
                nightly.install()
        except Exception as e:
            log(f"[contrôle automatique] {e}")

    # ---------------------------------------------------------------- authentification
    def locked(self, ip: str) -> bool:
        recent = [t for t in self.fails.get(ip, []) if time.time() - t < 600]
        self.fails[ip] = recent
        return len(recent) >= 5

    def who(self, tok, ip: str) -> dict | None:
        """Jeton principal du Mac, ou clé d'un appareil associé (iPhone…), révocable. None sinon."""
        if self.locked(ip):
            return None
        if isinstance(tok, str) and tok and hmac.compare_digest(tok.encode(), self.token.encode()):
            return {"kind": "master", "scope": "full"}
        d = devices.verify(tok)
        if d:
            devices.touch(d["id"])
            return {"kind": "device", "scope": d["scope"], "id": d["id"], "name": d["name"]}
        self.fails.setdefault(ip, []).append(time.time())
        security.audit({"type": "auth_fail", "ip": ip})
        log(f"[auth] jeton refusé depuis {ip}")
        return None

    def check(self, tok, ip: str) -> bool:
        w = self.who(tok, ip)
        return bool(w) and w["scope"] == "full"

    # ---------------------------------------------------------------- diffusion (appelée depuis les threads des tâches)
    def _watch_power(self):
        """Prévient l'interface quand le Mac passe sur batterie (modèle plus lent) ou revient sur secteur."""
        while not self.stopped.wait(20):
            p = diagnostics.power_state()
            self.manager.set_thermal(p.get("thermal"))
            if p != self.power:
                if (p.get("thermal") or 0) != (self.power.get("thermal") or 0):
                    security.audit({"type": "thermal", "level": p.get("thermal"), "parallel": self.manager.effective_parallel()})
                self.power = p
                self.broadcast({"type": "power", "power": {**p, "parallel": self.manager.effective_parallel()}})

    def stop(self):
        self.stopped.set()
        self.loop = None
        if threading.current_thread() is not self.power_thread:
            self.power_thread.join(timeout=2)

    def broadcast(self, msg: dict):
        loop = self.loop
        if self.stopped.is_set() or not loop or loop.is_closed() or not loop.is_running() or not self.sessions:
            return
        data = json.dumps(msg, ensure_ascii=False, default=str)
        for s in list(self.sessions.values()):
            if s.attached:
                coroutine = s.send(data)
                try:
                    asyncio.run_coroutine_threadsafe(coroutine, loop)
                except RuntimeError:
                    coroutine.close()

    # ---------------------------------------------------------------- sessions
    async def open(self, kind: str, ip: str, remote: bool, ws=None) -> Session:
        s = Session(self, kind, ip, remote, ws)
        self.sessions[s.id] = s
        security.audit({"type": "ui_login", "ip": ip, "remote": remote, "transport": kind})
        log(f"[ui] connexion {kind} depuis {ip}{' (distant)' if remote else ''}")
        return s

    def close(self, s: Session):
        self.sessions.pop(s.id, None)

    def reap(self):
        """Supprime les sessions HTTP abandonnées."""
        for s in list(self.sessions.values()):
            if s.kind == "http" and not s.attached and time.time() - s.last_seen > 90:
                self.sessions.pop(s.id, None)

    def hello(self, s: Session) -> dict:
        m = self.manager
        return {"type": "hello", "version": config.VERSION, "remote": s.remote, "transport": s.kind, "sid": s.id,
                "tasks": m.list(), "model": self.cfg["model"], "autonomy": self.cfg.get("autonomy"), "power": self.power,
                "pending": [{"task_id": t.id, "title": t.title, "cid": k, **{kk: vv for kk, vv in v.items() if kk != "event"}}
                            for t in list(m.tasks.values()) for k, v in list(t.pending.items())]}

    # ---------------------------------------------------------------- pièces jointes
    def validate_files(self, files) -> list[dict]:
        root = security.resolve(uploads_root(self.cfg))
        out = []
        for f in files or []:
            p = security.resolve(f.get("path", "") if isinstance(f, dict) else str(f))
            if security.under(p, root) and p.is_file():
                out.append({"path": str(p), "name": p.name, "size": p.stat().st_size, "kind": kind_of(p.name)})
        return out[:30]

    # ---------------------------------------------------------------- commandes
    async def handle(self, s: Session, msg: dict):
        loop = asyncio.get_running_loop()
        t = msg.get("type")
        tid = msg.get("task_id", "")
        m = self.manager
        try:
            if t in ("new", "send"):
                files = self.validate_files(msg.get("files"))
                text = str(msg.get("text", "")).strip()[:30000]
                if not text and not files:
                    return
                if not text:
                    text = "Voici " + ("ce fichier." if len(files) == 1 else "ces fichiers.") + " Analyse-les et dis-moi ce qu'ils contiennent."
                boost = bool(msg.get("boost"))
                if t == "new":
                    task = await loop.run_in_executor(None, lambda: m.create(text, files=files, boost=boost))
                    await s.reply({"type": "created", "task": task.meta()})
                else:
                    err = m.send(tid, text, files=files, boost=boost)
                    if err:
                        await s.reply({"type": "toast", "text": err})
            elif t == "open":
                task = m.tasks.get(tid)
                if task:
                    await s.reply({"type": "snapshot", **task.snapshot()})
            elif t == "list":
                await s.reply({"type": "tasks", "tasks": m.list()})
            elif t == "stop":
                m.stop(tid)
            elif t == "confirm":
                m.answer(tid, msg.get("cid", ""), msg.get("answer", "no"))
            elif t == "undo":
                res = await loop.run_in_executor(None, m.undo, tid)
                await s.reply({"type": "toast", "text": res[:400]})
            elif t == "delete":
                m.delete(tid)
            elif t == "rename":
                m.rename(tid, str(msg.get("title", "")))
            elif t == "settings_get":
                await s.reply({"type": "settings", "settings": await loop.run_in_executor(None, public_settings, self.cfg)})
            elif t == "settings_set":
                res = self.apply_settings(msg.get("changes") or {}, s.remote)
                await s.reply({"type": "toast", "text": res})
                await s.reply({"type": "settings", "settings": await loop.run_in_executor(None, public_settings, self.cfg)})
            elif t == "diagnostics":
                await s.reply({"type": "diagnostics", "checks": await loop.run_in_executor(None, diagnostics.checks, self.cfg)})
            elif t == "remote" and not s.remote:
                def remote_done(text, ok, hub=self):
                    hub.broadcast({"type": "toast", "text": text})
                    hub.broadcast({"type": "settings", "settings": public_settings(hub.cfg)})
                res = await loop.run_in_executor(None, set_remote, bool(msg.get("enable")), remote_done)
                await s.reply({"type": "toast", "text": res})
                await s.reply({"type": "settings", "settings": await loop.run_in_executor(None, public_settings, self.cfg)})
            elif t == "remote_qr" and not s.remote:
                url = diagnostics.tailscale_url()
                if not url:
                    await s.reply({"type": "toast", "text": "Tailscale n'est pas connecté sur ce Mac."})
                else:                                 # clé propre à l'appareil : le jeton du Mac ne sort jamais
                    _, key = devices.create(str(msg.get("name") or "iPhone"), "full")
                    security.audit({"type": "device_pair", "scope": "full"})
                    svg = await loop.run_in_executor(None, qr_svg, f"{url}#t={key}")
                    await s.reply({"type": "remote_qr", "svg": svg, "url": url})
            elif t == "device_revoke" and not s.remote:
                did = str(msg.get("id", ""))
                if devices.revoke(did):
                    push.unsubscribe_device(did)
                    security.audit({"type": "device_revoke", "id": did})
                    for other in list(self.sessions.values()):     # déconnecte tout de suite l'appareil retiré
                        if other.device.get("id") == did:
                            await other.reply({"type": "auth_failed", "locked": False})
                            self.close(other)
                await s.reply({"type": "toast", "text": "Appareil retiré : sa clé ne marche plus."})
                await s.reply({"type": "settings", "settings": await loop.run_in_executor(None, public_settings, self.cfg)})
            elif t == "push_subscribe":
                err = push.subscribe(msg.get("sub") or {}, s.device.get("id") or ("mac" if not s.remote else "appareil"))
                if not err:
                    security.audit({"type": "push_subscribe", "device": s.device.get("name", "")})
                    sent = await loop.run_in_executor(None, lambda: push.send_all(
                        "Jarvis", "Les notifications fonctionnent ✅", "/", "test", False, diagnostics.tailscale_url() or ""))
                    err = "" if sent else "Abonné, mais la notification d'essai n'est pas passée (réessaie dans un moment)."
                await s.reply({"type": "toast", "text": err or "Notifications activées sur cet appareil ✅"})
            elif t == "ios_shortcuts":
                url = diagnostics.tailscale_url()
                if not url:
                    await s.reply({"type": "toast", "text": "L'accès à distance (Tailscale) doit être actif."})
                else:
                    name = (s.device.get("name") or "iPhone") + " · raccourcis"
                    did, key = devices.create(name, "ask")
                    out = config.JARVIS_DIR / "push" / f"raccourcis-{did}"
                    import siri
                    files, err = await loop.run_in_executor(None, siri.build_ios_shortcuts, out, url, key)
                    links = []
                    for f in files:
                        code = secrets.token_urlsafe(24)
                        self.downloads[code] = (f, f.name, time.time() + 600)
                        links.append({"name": f.stem, "url": f"/api/dl?c={code}"})
                    if not links:
                        devices.revoke(did)
                    security.audit({"type": "ios_shortcuts", "ok": bool(links)})
                    await s.reply({"type": "ios_shortcuts", "links": links, "error": err})
            elif t == "ntfy_setup":
                cfg2 = config.load()
                n = cfg2.get("ntfy") or {}
                if not n.get("topic"):
                    n["topic"] = "jarvis-" + secrets.token_hex(10)
                n["enabled"], n["server"] = True, n.get("server", "https://ntfy.sh")
                cfg2["ntfy"] = n
                config.save(cfg2)
                self.cfg = cfg2
                m.apply_settings(cfg2)
                from net_tools import send_ntfy
                await loop.run_in_executor(None, send_ntfy, n, "Jarvis", "Les notifications fonctionnent ✅")
                await s.reply({"type": "settings", "settings": await loop.run_in_executor(None, public_settings, cfg2)})
            elif t == "cloud_setup" and not s.remote:
                res = await loop.run_in_executor(None, self.cloud_setup, msg)
                await s.reply({"type": "cloud_result", **res})
                await s.reply({"type": "settings", "settings": await loop.run_in_executor(None, public_settings, self.cfg)})
            elif t == "voice_test" and not s.remote:
                v = self.cfg.get("voice") or {}
                await loop.run_in_executor(None, voice.speak, voice.PHRASE, str(msg.get("voice") or v.get("voice", "")),
                                           int(v.get("rate", 190)))
            elif t == "voice_settings" and not s.remote:       # télécharger une voix « Premium » (gratuite, Apple)
                subprocess.run(["open", "x-apple.systempreferences:com.apple.Accessibility-Settings.extension?SpokenContent"],
                               capture_output=True, timeout=10)
                voice.voices(refresh=True)
            elif t == "apple_setup" and not s.remote:
                subprocess.run(["open", "-a", "Shortcuts"], capture_output=True, timeout=10)
                await s.reply({"type": "toast", "text": "Dans Raccourcis : ＋ nouveau raccourci, nomme-le exactement « Jarvis · modèle Apple », "
                               "ajoute l'action « Utiliser un modèle », choisis « Cloud Pro » (ou « Cloud »), mets « Entrée du raccourci » "
                               "comme demande, puis l'action « Arrêter et produire » avec la réponse. Reviens ici et touche « Tester »."})
            elif t == "apple_test" and not s.remote:
                def _try():
                    try:
                        out = AppleBackend().chat([{"role": "user", "content": "Réponds seulement par le mot : prêt"}])
                        return f"Modèle d'Apple : « {out['content'][:60]} » ✅"
                    except LLMError as e:
                        return f"Modèle d'Apple indisponible : {e}"
                await s.reply({"type": "toast", "text": await loop.run_in_executor(None, _try)})
                await s.reply({"type": "settings", "settings": await loop.run_in_executor(None, public_settings, self.cfg)})
            elif t == "cloud_relay_off" and not s.remote:
                cfg2 = config.load()
                c = dict(cfg2.get("cloud") or {})
                if c.pop("relay", None) is not None:
                    cfg2["cloud"] = c
                    config.save(cfg2)
                    self.cfg = cfg2
                    m.apply_settings(cfg2)
                    security.audit({"type": "cloud_relay_off"})
                await s.reply({"type": "toast", "text": "Relais retiré (la clé reste dans le Trousseau)."})
                await s.reply({"type": "settings", "settings": await loop.run_in_executor(None, public_settings, self.cfg)})
            elif t == "open_url" and not s.remote:
                url = str(msg.get("url", ""))
                allowed = {p["key_url"] for p in PROVIDERS.values() if p.get("key_url")}
                if url in allowed:
                    subprocess.run(["open", url], timeout=10)
            elif t == "engine_set" and not s.remote:
                res = await loop.run_in_executor(None, self.set_engine, str(msg.get("engine", "ollama")))
                await s.reply({"type": "toast", "text": res})
                await s.reply({"type": "settings", "settings": await loop.run_in_executor(None, public_settings, self.cfg)})
            elif t == "transcribe":
                ok = self.validate_files([str(msg.get("path", ""))])
                if not ok:
                    await s.reply({"type": "transcript", "text": "", "error": "Enregistrement introuvable."})
                else:
                    res = await loop.run_in_executor(None, voice.transcribe, Path(ok[0]["path"]), self.cfg.get("voice_lang", "fr"))
                    security.audit({"type": "dictation", "chars": len(res.get("text", "")), "error": res.get("error", "")[:80]})
                    await s.reply({"type": "transcript", **res})
            elif t == "recipes_clear" and not s.remote:
                recipes.clear()
                security.audit({"type": "recipes_cleared"})
                await s.reply({"type": "toast", "text": "Méthodes apprises oubliées."})
                await s.reply({"type": "settings", "settings": await loop.run_in_executor(None, public_settings, self.cfg)})
            elif t == "memory_get":
                await s.reply({"type": "memory", "text": config.MEMORY_FILE.read_text() if config.MEMORY_FILE.exists() else ""})
            elif t == "memory_set" and not s.remote:
                config.MEMORY_FILE.write_text(str(msg.get("text", ""))[:20000])
                await s.reply({"type": "toast", "text": "Mémoire enregistrée."})
            elif t == "ping":
                await s.reply({"type": "pong"})
        except Exception as e:
            log(f"[commande {t}] erreur : {e}\n{traceback.format_exc()}")
            await s.reply({"type": "toast", "text": f"Erreur interne ({t}) : {e}"})

    def set_engine(self, eng: str) -> str:
        """Ollama (llama.cpp) ou MLX d'Apple pour le modèle principal."""
        cfg2 = config.load()
        if eng == "mlx":
            if not engine.available(cfg2["model"]):
                return f"MLX n'est pas installé pour {cfg2['model']}."
            engine.unload_ollama(cfg2)
            ok, why = engine.start(cfg2["model"])
            if not ok:
                return f"MLX indisponible : {why}. Jarvis reste sur Ollama."
            cfg2.update(engine="mlx", mlx=engine.mlx_cfg())
            msg = f"Moteur MLX actif ({why}) : environ 30 % plus rapide."
        else:
            engine.stop()
            cfg2["engine"] = "ollama"
            msg = "Moteur Ollama actif."
        config.save(cfg2)
        self.cfg = cfg2
        self.manager.apply_settings(cfg2)
        security.audit({"type": "engine", "engine": cfg2["engine"]})
        return msg

    def cloud_setup(self, msg: dict) -> dict:
        """Enregistre la clé du renfort dans le Trousseau, liste les modèles, choisit le meilleur et fait un essai réel."""
        prov = str(msg.get("provider", "gemini"))
        relay = bool(msg.get("relay"))
        if prov not in PROVIDERS:
            return {"ok": False, "text": "Fournisseur inconnu."}
        if relay and prov == (config.load().get("cloud") or {}).get("provider"):
            return {"ok": False, "relay": True, "text": "Le relais doit être un autre service que le renfort principal."}
        key = str(msg.get("key", "")).strip()
        from_clip = False
        if msg.get("from_clipboard"):                  # lu sur le Mac : la clé ne transite jamais par l'interface
            try:
                clip = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                clip = ""
            if not looks_like_key(prov, clip):
                hint = KEY_FORMATS.get(prov, ("", ""))[1]
                return {"ok": False, "text": "Le presse-papiers ne contient pas de clé " + PROVIDERS[prov]["label"].split(" (")[0]
                        + (f" ({hint})" if hint else "") + ". Copie la clé sur la page du service, puis réessaie."}
            key, from_clip = clip, True
        if key:
            if len(key) > 400 or not re.fullmatch(r"[A-Za-z0-9_\-.:]+", key):
                return {"ok": False, "text": "Clé invalide (caractères inattendus)."}
            if not security.keychain_set(key_account(prov), key):
                return {"ok": False, "text": "Impossible d'enregistrer la clé dans le Trousseau."}
            if from_clip:                             # hygiène : la clé, désormais au Trousseau, ne traîne pas dans le presse-papiers
                try:
                    subprocess.run(["pbcopy"], input="", text=True, timeout=5)
                except (OSError, subprocess.SubprocessError):
                    pass
        key = key or cloud_key(prov)
        if not key:
            return {"ok": False, "text": "Colle d'abord ta clé gratuite."}
        cfg2 = config.load()
        c = dict(cfg2.get("cloud") or {})
        prev = (c.get("relay") or {}) if relay else c
        base = PROVIDERS[prov]["base_url"] or str(msg.get("base_url", prev.get("base_url", ""))).strip()
        if prov == "custom" and not re.match(r"^(https://[A-Za-z0-9.\-:/]+|http://(127\.0\.0\.1|localhost)(:\d+)?(/[A-Za-z0-9.\-/]*)?)$", base):
            return {"ok": False, "text": "Adresse invalide (https://… attendu, ou http://127.0.0.1 pour un serveur local)."}
        b = OpenAICompatBackend(base, "", key, prov)
        try:
            ids = b.models()
        except Exception as e:
            return {"ok": False, "text": f"Le service refuse la clé ou est injoignable : {security.redact(str(e))[:200]}"}
        wanted = str(msg.get("model", "")).strip()
        clean = [i.split("/", 1)[1] if i.startswith("models/") else i for i in ids]
        ranked = rank_models(prov, ids)
        if wanted in clean:
            ranked = [wanted] + [m for m in ranked if m != wanted]
        if not ranked:
            return {"ok": False, "text": "Aucun modèle disponible avec cette clé."}
        t0, r, model, errs = time.time(), None, "", []
        for cand in ranked[:6]:                 # le plus récent peut être saturé (503) : on essaie le suivant
            b.model, b.name = cand, f"renfort · {cand}"
            try:
                r = b.chat([{"role": "user", "content": "Réponds uniquement : OK"}], None, {"temperature": 0, "num_predict": 16})
                model = cand
                break
            except Exception as e:
                errs.append(f"{cand} : {security.redact(str(e))[:90]}")
        if not model:
            return {"ok": False, "relay": relay, "models": clean,
                    "text": "Aucun modèle n'a répondu (" + " · ".join(errs[:3]) + "). Réessaie dans quelques minutes."}
        conf = dict(enabled=True, provider=prov, base_url=base if prov == "custom" else "", model=model,
                    fallbacks=fallback_chain(prov, ids, model),   # chaque modèle a son propre quota gratuit du jour
                    models=sorted(x for x in clean if not re.search(PROVIDERS[prov].get("avoid") or "^$", x, re.I))[:80])
        if relay:
            c["relay"] = conf
        else:
            c.update(conf, mode=c.get("mode") if c.get("mode") in ("ask", "auto") else "ask")
            if (c.get("relay") or {}).get("provider") == prov:
                c.pop("relay", None)              # même service que le relais : le relais n'a plus d'intérêt
        cfg2["cloud"] = c
        config.save(cfg2)
        self.cfg = cfg2
        self.manager.apply_settings(cfg2)
        security.audit({"type": "cloud_setup", "provider": prov, "model": model, "relay": relay})
        what = "Relais prêt" if relay else "Renfort prêt"
        return {"ok": True, "relay": relay, "model": model,
                "text": f"{what} : {model} a répondu en {time.time() - t0:.1f} s."
                        + (" Clé rangée dans le Trousseau, presse-papiers vidé." if from_clip else "")}

    def apply_settings(self, changes: dict, remote: bool) -> str:
        cfg2 = config.load()
        applied = []
        for k, v in changes.items():
            if k not in SETTABLE or (remote and k in LOCAL_ONLY):
                continue
            try:
                if k == "autonomy" and (v not in ("prudent", "autonome", "total") or (v == "total" and remote)):
                    continue
                if k in ("max_parallel_tasks", "max_subtasks"):
                    v = max(1, min(int(v), 8))
                if k == "num_ctx":
                    v = max(4096, min(int(v), 131072))
                if k == "project_dirs":
                    v = sorted({d for d in (safe_project_dir(x) for x in (v or [])) if d})
                if k == "sandbox" and v is False:
                    security.audit({"type": "sandbox_disabled"})
                if k == "ntfy" and isinstance(v, dict):
                    v = {**(cfg2.get("ntfy") or {}), "enabled": bool(v.get("enabled"))}
                if k == "voice" and isinstance(v, dict):
                    v = {**(cfg2.get("voice") or {}), **{kk: vv for kk, vv in v.items() if kk in ("enabled", "voice", "rate")}}
                if k == "cloud":
                    if not isinstance(v, dict):
                        continue
                    cur = dict(cfg2.get("cloud") or {})
                    if v.get("mode") in ("off", "ask", "auto"):
                        cur["mode"] = v["mode"]
                    if isinstance(v.get("model"), str) and v["model"] in (cur.get("models") or []):
                        cur["model"] = v["model"]
                        cur["fallbacks"] = [m for m in cur.get("fallbacks", []) if m != v["model"]]
                    if "enabled" in v:
                        cur["enabled"] = bool(v["enabled"]) and bool(cur.get("model"))
                    v = cur
                if k == "hotkey" and v not in ("alt+space", "cmd+shift+j", "off"):
                    continue
                if k == "my_files":
                    v = {**(cfg2.get("my_files") or {}), "enabled": bool((v or {}).get("enabled"))}
                    if v["enabled"]:                      # première indexation tout de suite (macOS demande l'accès)
                        threading.Thread(target=myfiles.index_all, args=({**cfg2, "my_files": v},), daemon=True,
                                         name="jarvis-index").start()
                if k == "apple":
                    v = {**(cfg2.get("apple") or {}), "enabled": bool((v or {}).get("enabled"))}
                if k == "nightly":
                    v = bool(v)
                    try:
                        nightly.install() if v else nightly.uninstall()
                    except Exception as e:
                        log(f"[contrôle automatique] {e}")
                if k == "remote_ollama_host" and v and not re.match(r"^https?://[A-Za-z0-9.\-:\[\]]+$", str(v)):
                    continue
            except (TypeError, ValueError):
                continue
            cfg2[k] = v
            applied.append(k)
        config.save(cfg2)
        self.cfg = cfg2
        self.manager.apply_settings(cfg2)
        security.audit({"type": "settings", "changed": applied, "remote": remote})
        return "Réglages enregistrés." if applied else "Aucun changement autorisé."
