"""
Vérification de bout en bout de Jarvis sur le Mac (lancée par « Mettre à jour Jarvis.command »).
Teste : serveur, WebSocket, flux HTTP de secours, envoi de fichier, OCR macOS, lecture des formats,
et une vraie tâche exécutée par le modèle local (lecture d'une pièce jointe).
"""
import json
import warnings
warnings.filterwarnings("ignore")
import sys
import time
import urllib.request
from pathlib import Path

HOME = Path.home()
sys.path.insert(0, str(HOME / ".jarvis" / "app"))
import config  # noqa: E402

PORT = int(config.load()["server"]["port"])
BASE = f"http://127.0.0.1:{PORT}"
TOKEN = config.TOKEN_FILE.read_text().strip()
results = []


def ok(label, cond, detail=""):
    results.append(bool(cond))
    print(("  ✔ " if cond else "  ✖ ") + label + (f"  — {detail}" if detail and not cond else ""), flush=True)


def http(method, path, data=None, headers=None, timeout=10):
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"X-Jarvis-Token": TOKEN, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


print("\n[1] Serveur")
try:
    st, body = http("GET", "/healthz")
    ok("serveur Jarvis en ligne", st == 200, body[:80])
except Exception as e:
    ok("serveur Jarvis en ligne", False, str(e))
    sys.exit(1)

print("\n[2] Connexion temps réel (WebSocket, comme l'app)")
ws = None
try:
    from websockets.sync.client import connect
    ws = connect(f"ws://127.0.0.1:{PORT}/ws", origin=f"http://127.0.0.1:{PORT}", open_timeout=8)
    ws.send(json.dumps({"type": "auth", "token": TOKEN}))
    hello = json.loads(ws.recv(timeout=8))
    ok("WebSocket connecté et authentifié", hello.get("type") == "hello", str(hello)[:120])
except Exception as e:
    ok("WebSocket connecté et authentifié", False, f"{type(e).__name__}: {e}")
    ws = None

print("\n[3] Flux HTTP de secours")
try:
    st, body = http("POST", "/api/session")
    sid = json.loads(body)["sid"]
    req = urllib.request.Request(f"{BASE}/api/events?sid={sid}", headers={"X-Jarvis-Token": TOKEN})
    with urllib.request.urlopen(req, timeout=8) as r:
        got = b""
        t0 = time.time()
        while b"hello" not in got and time.time() - t0 < 8:
            got += r.read1(4096) if hasattr(r, "read1") else r.read(256)
    ok("session HTTP + flux d'événements", b"hello" in got)
except Exception as e:
    ok("session HTTP + flux d'événements", False, str(e))

print("\n[4] Envoi de fichier")
up = None
try:
    st, body = http("POST", "/api/upload?name=test-jarvis.txt", data="Le mot secret est PELOUSE.".encode(),
                    headers={"Content-Type": "application/octet-stream"})
    up = json.loads(body)
    ok("téléversement dans « Fichiers reçus »", st == 200 and Path(up["path"]).exists(), str(up))
except Exception as e:
    ok("téléversement dans « Fichiers reçus »", False, str(e))

print("\n[5] Lecture des formats et OCR macOS")
try:
    import files
    from PIL import Image, ImageDraw, ImageFont
    tmp = Path(config.JARVIS_DIR) / "screens" / "ocr-test.png"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (900, 220), "white")
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 90)
    except Exception:
        font = ImageFont.load_default(size=90)
    ImageDraw.Draw(img).text((40, 50), "JARVIS 2026", fill="black", font=font)
    img.save(tmp)
    txt = files.ocr(tmp)
    ok("OCR intégré de macOS (Vision)", "JARVIS" in txt.upper(), repr(txt[:60]))
    pdf = tmp.with_suffix(".pdf")
    img.save(pdf, "PDF")
    out = files.extract(pdf)
    ok("PDF scanné lu par OCR", "JARVIS" in out.upper(), out[:80])
    ql = files.ql_preview(tmp)
    ok("aperçu Quick Look disponible (.pxd, .psd, Keynote…)", ql is not None and ql.exists())
except Exception as e:
    ok("lecture des formats", False, f"{type(e).__name__}: {e}")

print("\n[6] Vraie tâche avec le modèle local (pièce jointe)")
if ws and up:
    try:
        ws.send(json.dumps({"type": "new", "files": [{"path": up["path"]}],
                            "text": "Lis la pièce jointe et réponds uniquement par le mot secret qu'elle contient, en majuscules."}))
        task_id, final, t0, tools_used = None, None, time.time(), []
        while time.time() - t0 < 420 and final is None:
            m = json.loads(ws.recv(timeout=420))
            if m.get("type") == "created":
                task_id = m["task"]["id"]
                print(f"    tâche créée : {task_id}", flush=True)
            elif m.get("type") == "confirm" and m.get("task_id") == task_id:
                ws.send(json.dumps({"type": "confirm", "task_id": task_id, "cid": m["cid"], "answer": "no"}))
            elif m.get("type") == "event" and m.get("task_id") == task_id:
                ev = m["ev"]
                if ev["type"] == "tool":
                    tools_used.append(ev["name"])
                    print(f"    🔧 {ev['name']}", flush=True)
                elif ev["type"] == "final":
                    final = ev["text"]
        dt = time.time() - t0
        ok(f"réponse du modèle en {dt:.0f} s", final is not None, "pas de réponse")
        ok("le modèle a utilisé un outil pour lire le fichier", any(t in ("read_file", "analyze_file") for t in tools_used), str(tools_used))
        ok("réponse correcte (PELOUSE)", final is not None and "PELOUSE" in final.upper(), (final or "")[:200])
        if task_id:
            ws.send(json.dumps({"type": "delete", "task_id": task_id}))
    except Exception as e:
        ok("vraie tâche", False, f"{type(e).__name__}: {e}")
else:
    ok("vraie tâche", False, "WebSocket ou envoi de fichier indisponible")

if ws:
    ws.close()
n_ok = sum(results)
print(f"\nVérification de bout en bout : {n_ok}/{len(results)} réussies")
(Path(config.JARVIS_DIR) / "logs" / "verification.txt").write_text(f"{n_ok}/{len(results)}\n")
sys.exit(0 if n_ok == len(results) else 1)
