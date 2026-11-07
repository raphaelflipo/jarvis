"""
Application Jarvis : fenêtre native macOS (WebKit via pywebview) avec effet verre (vibrancy).
Le serveur tourne en arrière-plan : fermer la fenêtre n'arrête pas les tâches en cours ;
rouvrir Jarvis les retrouve. Repli automatique sur le navigateur si pywebview n'est pas disponible.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import requests

import config

HERE = Path(__file__).parent


def server_up(port: int) -> bool:
    try:
        return requests.get(f"http://127.0.0.1:{port}/healthz", timeout=1.5).ok
    except requests.RequestException:
        return False


def ensure_server(cfg: dict) -> bool:
    port = int(cfg["server"]["port"])
    if server_up(port):
        return True
    log = open(config.LOG_DIR / "server.log", "a")
    subprocess.Popen([sys.executable, str(HERE / "jarvis.py"), "serve"], stdout=log, stderr=log,
                     stdin=subprocess.DEVNULL, start_new_session=True, cwd=str(HERE))
    for _ in range(80):
        if server_up(port):
            return True
        time.sleep(0.25)
    return False


def main():
    config.ensure_dirs()
    cfg = config.load()
    if not ensure_server(cfg):
        subprocess.run(["osascript", "-e", 'display alert "Jarvis" message "Le serveur ne démarre pas. '
                        'Consulte ~/.jarvis/logs/server.log ou lance « jarvis doctor » dans le Terminal."'])
        return
    from server import get_token
    native = cfg.get("native_glass", True)
    url = f"http://127.0.0.1:{cfg['server']['port']}/?app=1{'&glass=1' if native else ''}#t={get_token()}"
    try:
        import webview
    except Exception:
        webbrowser.open(url)
        return
    win = webview.create_window(
        "Jarvis", url, width=1380, height=900, min_size=(860, 600), background_color="#06110A",
        text_select=True, zoomable=True, vibrancy=bool(native), transparent=bool(native))

    def on_closing():
        return True   # fermer la fenêtre ne coupe pas le serveur (tâches conservées)
    win.events.closing += on_closing
    webview.start(private_mode=False, storage_path=str(config.JARVIS_DIR / "webview"))


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    os.chdir(HERE)
    main()
