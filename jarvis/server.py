"""
Serveur de Jarvis : interface « liquid glass », temps réel, pièces jointes.

Deux transports, l'interface choisit automatiquement :
  • WebSocket (/ws) — le plus rapide ;
  • flux HTTP de secours (/api/session + /api/events + /api/cmd) — fonctionne partout, même si la
    bibliothèque WebSocket fait défaut ou qu'un proxy la bloque.

Sécurité : écoute uniquement sur 127.0.0.1 (accès iPhone via `tailscale serve` en HTTPS) ; jeton de 256 bits,
comparaison en temps constant, verrouillage après 5 échecs ; contrôle d'origine ; CSP stricte ; téléversements
limités au dossier « Fichiers reçus » de l'espace de travail.
"""
# NB : pas de « from __future__ import annotations » ici : FastAPI doit voir les vrais types
# (Request, WebSocket) sinon il les prend pour des paramètres d'URL → erreurs 403/422.

import asyncio
import json
import re
import time
import traceback
from pathlib import Path

import config
import devices
import security
from hub import (MAX_UPLOAD, Hub, get_token, kind_of, log, new_upload_path, public_settings,  # noqa: F401
                 safe_project_dir, set_remote, uploads_root)

_safe_project_dir = safe_project_dir   # compatibilité


def sniff_ext(p: Path) -> str:
    """Extension d'après les premiers octets (fichier partagé depuis l'iPhone sans nom)."""
    try:
        head = p.read_bytes()[:64]
    except OSError:
        return ""
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head.startswith(b"\x89PNG"):
        return ".png"
    if head.startswith(b"%PDF"):
        return ".pdf"
    if head[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftyphevc"):
        return ".heic"
    if head[4:8] == b"ftyp":
        return ".mp4" if b"qt" not in head[8:12] else ".mov"
    if head.startswith(b"GIF8"):
        return ".gif"
    if head.startswith(b"PK\x03\x04"):
        return ".zip"
    try:
        p.read_bytes()[:20000].decode("utf-8")
        return ".txt"                              # texte ou lien partagé depuis Safari
    except UnicodeDecodeError:
        return ""
WEB_DIR = Path(__file__).parent / "web"


def create_app(cfg: dict):
    from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
    from fastapi.staticfiles import StaticFiles
    from contextlib import asynccontextmanager

    hub = Hub(cfg)

    @asynccontextmanager
    async def lifespan(app):
        hub.loop = asyncio.get_running_loop()

        async def reaper():
            while True:
                await asyncio.sleep(30)
                hub.reap()
        task = asyncio.create_task(reaper())
        log(f"Jarvis {config.VERSION} prêt sur http://127.0.0.1:{cfg['server']['port']}")
        yield
        task.cancel()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    def client_ip(headers, host) -> tuple[str, bool]:
        fwd = headers.get("x-forwarded-for", "")
        if host in ("127.0.0.1", "::1") and fwd:
            return fwd.split(",")[0].strip(), True          # via tailscale serve
        return host, host not in ("127.0.0.1", "::1")

    def origin_ok(headers, host) -> bool:
        origin = headers.get("origin", "")
        if not origin:
            return True
        allowed = {headers.get("host", ""), headers.get("x-forwarded-host", "")} - {""}
        ohost = origin.split("://", 1)[-1].split("/")[0]
        proxied = host in ("127.0.0.1", "::1") and bool(headers.get("x-forwarded-for"))
        local_origin = ohost.rsplit(":", 1)[0].strip("[]") in ("127.0.0.1", "localhost", "::1")
        ok = ohost in allowed or (proxied and ohost.endswith(".ts.net")) or origin == "null" or \
            (local_origin and host in ("127.0.0.1", "::1") and not proxied)
        if not ok:
            log(f"[origine] refusée : origin={origin!r} host={headers.get('host')!r} client={host}")
        return ok

    def auth(request: Request, allow_ask: bool = False) -> tuple[bool, str, bool]:
        """Jeton du Mac ou clé d'un appareil associé. Les clés limitées (raccourcis) n'ouvrent que /api/ask et l'envoi
        de fichiers."""
        ip, remote = client_ip(request.headers, request.client.host if request.client else "?")
        tok = request.headers.get("x-jarvis-token") or request.query_params.get("t")
        w = hub.who(tok, ip)
        request.state.who = w or {}
        return bool(w) and (w["scope"] == "full" or allow_ask), ip, remote

    def device_of(tok) -> dict:
        d = devices.verify(tok)
        return {"id": d["id"], "name": d["name"]} if d else {}

    @app.middleware("http")
    async def headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers["Content-Security-Policy"] = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                                                   "connect-src 'self' ws: wss: http://127.0.0.1:* http://localhost:*; "
                                                   "img-src 'self' data: blob:; font-src 'self'; frame-ancestors 'none'; "
                                                   "base-uri 'none'; form-action 'none'")
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        if "cache-control" not in resp.headers:
            resp.headers["Cache-Control"] = "no-store"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(self), geolocation=()"
        return resp

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return (WEB_DIR / "index.html").read_text()

    @app.get("/manifest.webmanifest")
    async def manifest(k: str = ""):
        # Ajout à l'écran d'accueil de l'iPhone : l'icône s'ouvre déjà connectée avec la clé DE CET APPAREIL
        # (jamais le jeton du Mac : seules les clés d'appareil « jv_… » sont acceptées ici).
        start = f"/#t={k}" if re.fullmatch(r"jv_[A-Za-z0-9_-]{30,60}", k or "") and devices.verify(k) else "/"
        return JSONResponse({"name": "Jarvis", "short_name": "Jarvis", "display": "standalone", "start_url": start,
                             "id": "/", "scope": "/", "background_color": "#06110A", "theme_color": "#06110A",
                             "icons": [{"src": "/static/icon.png", "sizes": "512x512", "type": "image/png",
                                        "purpose": "any maskable"}]})

    @app.get("/sw.js")
    async def service_worker():
        return FileResponse(str(WEB_DIR / "sw.js"), media_type="application/javascript",
                            headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})

    @app.get("/healthz")
    async def healthz():
        return {"ok": True, "version": config.VERSION, "sessions": len(hub.sessions)}

    # ---------------------------------------------------------------- transport 1 : WebSocket
    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        host = ws.client.host if ws.client else "?"
        ip, remote = client_ip(ws.headers, host)
        log(f"[ws] demande de connexion (origin={ws.headers.get('origin')!r}, host={ws.headers.get('host')!r})")
        if not origin_ok(ws.headers, host):
            await ws.close(code=4403)
            return
        await ws.accept()
        try:
            first = json.loads(await asyncio.wait_for(ws.receive_text(), timeout=15))
        except Exception:
            await ws.close(code=4401)
            return
        if first.get("type") != "auth" or not hub.check(first.get("token"), ip):
            await ws.send_text(json.dumps({"type": "auth_failed", "locked": hub.locked(ip)}))
            await ws.close(code=4401)
            return
        s = await hub.open("ws", ip, remote, ws=ws)
        s.device = device_of(first.get("token"))
        try:
            await s.reply(hub.hello(s))
            while True:
                msg = json.loads(await ws.receive_text())
                s.last_seen = time.time()
                await hub.handle(s, msg)
        except WebSocketDisconnect:
            pass
        except Exception as e:
            log(f"[ws] erreur : {e}\n{traceback.format_exc()}")
        finally:
            hub.close(s)

    # ---------------------------------------------------------------- transport 2 : flux HTTP (secours)
    @app.post("/api/session")
    async def api_session(request: Request):
        ok, ip, remote = auth(request)
        if not ok:
            return JSONResponse({"type": "auth_failed", "locked": hub.locked(ip)}, status_code=401)
        if not origin_ok(request.headers, request.client.host if request.client else "?"):
            return JSONResponse({"error": "origine refusée"}, status_code=403)
        s = await hub.open("http", ip, remote)
        s.device = device_of(request.headers.get("x-jarvis-token") or request.query_params.get("t"))
        s.attached = False
        await s.reply(hub.hello(s))
        return {"sid": s.id}

    @app.get("/api/events")
    async def api_events(request: Request, sid: str):
        ok, ip, _ = auth(request)
        s = hub.sessions.get(sid)
        if not ok or not s or s.kind != "http":
            return JSONResponse({"error": "session inconnue"}, status_code=401)
        s.attached = True

        async def gen():
            yield ": ok\n\n"
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        data = await asyncio.wait_for(s.queue.get(), timeout=15)
                        yield f"data: {data}\n\n"
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
                    s.last_seen = time.time()
            finally:
                s.attached = False
                s.last_seen = time.time()
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/cmd")
    async def api_cmd(request: Request, sid: str):
        ok, _, _ = auth(request)
        s = hub.sessions.get(sid)
        if not ok or not s:
            return JSONResponse({"error": "session inconnue"}, status_code=401)
        try:
            msg = json.loads(await request.body())
        except ValueError:
            return JSONResponse({"error": "JSON invalide"}, status_code=400)
        s.last_seen = time.time()
        await hub.handle(s, msg)
        return {"ok": True}

    # ---------------------------------------------------------------- pièces jointes
    @app.post("/api/upload")
    async def api_upload(request: Request, name: str):
        ok, ip, _ = auth(request, allow_ask=True)
        if not ok:
            return JSONResponse({"error": "non autorisé"}, status_code=401)
        dest = new_upload_path(hub.cfg, name)
        size = 0
        try:
            with open(dest, "wb") as f:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_UPLOAD:
                        raise ValueError("fichier trop volumineux (4 Go max)")
                    f.write(chunk)
        except Exception as e:
            dest.unlink(missing_ok=True)
            log(f"[upload] {name} : {e}")
            return JSONResponse({"error": str(e)}, status_code=400)
        if not dest.suffix:                       # envoyé depuis le bouton Partager de l'iPhone : type deviné
            ext = sniff_ext(dest)
            if ext:
                named = dest.with_name(dest.name + ext)
                dest.rename(named)
                dest = named
        security.audit({"type": "upload", "name": dest.name, "size": size, "ip": ip})
        return {"path": str(dest), "name": dest.name, "size": size, "kind": kind_of(dest.name)}

    # ---------------------------------------------------------------- raccourcis (Siri, bouton Action, Partager)
    @app.post("/api/ask")
    async def api_ask(request: Request):
        """Question simple → réponse courte, lisible par Siri. Si la tâche dure, elle continue et une notification
        prévient à la fin."""
        ok, ip, remote = auth(request, allow_ask=True)
        if not ok:
            return JSONResponse({"answer": "Clé refusée : réassocie ton iPhone depuis le Mac.", "done": False}, status_code=401)
        try:
            body = json.loads(await request.body() or b"{}")
        except ValueError:
            body = {}
        text = str(body.get("text") or "").strip()[:4000]
        files = hub.validate_files([{"path": str(body["file"])}] if body.get("file") else body.get("files") or [])
        if not text and not files:
            return {"answer": "Je n'ai rien reçu.", "done": True}
        who = getattr(request.state, "who", {}) or {}
        security.audit({"type": "ask", "ip": ip, "device": who.get("name", ""), "files": len(files)})
        t = hub.manager.create(text or "Analyse ce fichier.", files=files)
        wait = max(5.0, min(float(body.get("wait") or 25), 55.0))
        t0 = time.time()
        while time.time() - t0 < wait and t.status in ("idle", "queued", "running"):
            await asyncio.sleep(0.4)
        final = next((e.get("text", "") for e in reversed(t.events) if e.get("type") == "final"), "")
        import siri
        if t.status == "done" and final:
            return {"answer": siri._spoken(final, 600), "done": True, "task_id": t.id}
        if t.status == "waiting":
            return {"answer": "J'ai besoin de ton accord pour continuer : touche la notification ou ouvre Jarvis.",
                    "done": False, "task_id": t.id}
        if t.status in ("error", "stopped"):
            return {"answer": siri._spoken(final or "La tâche n'a pas pu aboutir : regarde dans Jarvis.", 400),
                    "done": True, "task_id": t.id}
        return {"answer": "C'est parti. Je te préviens par une notification dès que c'est terminé.", "done": False,
                "task_id": t.id}

    @app.get("/api/dl")
    async def api_dl(c: str = ""):
        """Lien à usage unique (10 min) pour installer les raccourcis sur l'iPhone."""
        item = hub.downloads.pop(c, None)
        if not item or time.time() > item[2] or not Path(item[0]).exists():
            return JSONResponse({"error": "lien expiré : redemande les raccourcis dans Jarvis"}, status_code=404)
        data = Path(item[0]).read_bytes()
        Path(item[0]).unlink(missing_ok=True)      # contient une clé : on ne le garde pas sur le Mac
        from urllib.parse import quote
        return Response(data, media_type="application/octet-stream",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(item[1])}"})

    @app.get("/api/file")
    async def api_file(request: Request, path: str):
        """Aperçu des fichiers (images, PDF…) de l'espace de travail et des dossiers projets."""
        ok, _, _ = auth(request)
        if not ok:
            return JSONResponse({"error": "non autorisé"}, status_code=401)
        p = security.resolve(path)
        roots = [security.resolve(hub.cfg["workspace"])] + [security.resolve(d) for d in hub.cfg.get("project_dirs", [])]
        if not any(security.under(p, r) for r in roots) or not p.is_file() or \
                security.path_level(p, False, roots[0])[0] == security.BLOCKED:
            return JSONResponse({"error": "interdit"}, status_code=403)
        return FileResponse(str(p), headers={"Cache-Control": "private, max-age=600"})

    @app.get("/api/audit")
    async def api_audit(request: Request):
        ok, _, _ = auth(request)
        if not ok:
            return JSONResponse({"error": "non autorisé"}, status_code=401)
        return security.read_audit(300)

    return app, hub.token, hub.manager


def _ws_impl() -> str:
    """Choisit un moteur WebSocket réellement importable (évite l'échec silencieux d'uvicorn)."""
    try:
        from uvicorn.config import WS_PROTOCOLS
        from uvicorn.importer import import_from_string
    except Exception:
        return "auto"
    for name in ("websockets-sansio", "wsproto", "websockets"):
        if name in WS_PROTOCOLS:
            try:
                import_from_string(WS_PROTOCOLS[name])
                return name
            except Exception as e:
                log(f"[ws] moteur {name} indisponible : {e}")
    log("[ws] AUCUN moteur WebSocket : l'interface utilisera le flux HTTP de secours.")
    return "none"


def serve(cfg: dict):
    import uvicorn
    port = int(cfg["server"]["port"])
    app, _, _ = create_app(cfg)
    ws = _ws_impl()
    log(f"Moteur WebSocket : {ws}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", ws=ws, ws_max_size=4_000_000,
                proxy_headers=False, timeout_keep_alive=30)
