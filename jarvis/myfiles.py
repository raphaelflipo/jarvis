"""
Recherche dans TES fichiers par le sens : Documents, Bureau, iCloud Drive (PDF, Word, PowerPoint, Excel, Pages, notes…).
« Retrouve le cours où on parle du mix marketing. » L'index est construit sur le Mac par le modèle d'embeddings local
(rien ne quitte le Mac), d'abord à l'activation puis toutes les 30 min sur secteur, seulement pour les fichiers modifiés.
Désactivé par défaut : c'est toi qui l'actives (macOS demande alors l'accès à ces dossiers, une fois).
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import config
from registry import Ctx, I, S, tool

HOME = Path.home()
_running = threading.Lock()


def folders(cfg: dict) -> list[Path]:
    mf = cfg.get("my_files") or {}
    if mf.get("folders"):
        return [Path(f).expanduser() for f in mf["folders"]]
    out = [HOME / "Documents", HOME / "Desktop"]
    icloud = HOME / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
    if icloud.is_dir():
        out.append(icloud)
    return out


def state_file() -> Path:
    return config.INDEX_DIR / "mes-fichiers.json"


def state() -> dict:
    try:
        return json.loads(state_file().read_text())
    except (OSError, ValueError):
        return {}


def index_all(cfg: dict, progress=None) -> dict:
    """Met l'index à jour (fichiers nouveaux ou modifiés seulement). Un seul passage à la fois."""
    if not _running.acquire(blocking=False):
        return state()
    try:
        from devtools import index_folder
        from llm import Router
        Ctx.cfg = Ctx.cfg or cfg
        Ctx.router = Ctx.router or Router(cfg)
        st = {"folders": {}, "running": True, "started": time.time()}
        config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
        state_file().write_text(json.dumps(st))
        for root in folders(cfg):
            if not root.is_dir():
                continue
            try:
                added, total = index_folder(root, progress=progress)
                st["folders"][str(root)] = {"extraits": total, "ajoutes": added}
            except Exception as e:
                st["folders"][str(root)] = {"erreur": str(e)[:200]}
            state_file().write_text(json.dumps(st))
        st.update(running=False, done=time.time())
        state_file().write_text(json.dumps(st))
        return st
    finally:
        _running.release()


def watch(cfg_getter, stopped=None):
    """Fil de fond du hub : réindexe toutes les 30 min, seulement sur secteur."""
    first = True
    stopped = stopped or threading.Event()
    while not stopped.is_set():
        cfg = cfg_getter()
        if (cfg.get("my_files") or {}).get("enabled"):
            try:
                import diagnostics
                on_ac = not diagnostics.power_state().get("battery")      # « battery » = sur batterie
            except Exception:
                on_ac = True
            if first or on_ac:
                index_all(cfg)
                first = False
        stopped.wait(1800)


@tool("search_my_files",
      "Cherche par le SENS dans les fichiers de l'utilisateur (Documents, Bureau, iCloud Drive : PDF, Word, PowerPoint, "
      "Excel, Pages, notes…). Ex : « le cours sur le mix marketing », « le devis du camp ». Renvoie les extraits les plus "
      "proches avec le chemin du fichier.",
      {"query": S("Ce que tu cherches, en langage naturel"), "top_k": I("Nombre de résultats (défaut 8)")},
      ["query"], category="read", untrusted=True)
def search_my_files(query: str, top_k: int = 8):
    cfg = Ctx.cfg or config.load()
    if not (cfg.get("my_files") or {}).get("enabled"):
        return ("La recherche dans tes fichiers n'est pas activée : Réglages › Mémoire › « Recherche dans mes fichiers ». "
                "En attendant, utilise search_files (par nom) dans le dossier voulu.")
    from devtools import search_index
    roots = [r for r in folders(cfg) if r.is_dir()]
    hits = search_index(roots, query, max(1, min(int(top_k or 8), 20)))
    st = state()
    if not hits:
        return ("Index encore vide : la première indexation est en cours (quelques minutes)." if st.get("running")
                else "Rien trouvé dans l'index de tes fichiers.")
    lines = []
    for score, pth, s, e, body in hits:
        lines.append(f"── {pth}  (pertinence {score:.2f})\n{body[:700]}")
    if st.get("running"):
        lines.insert(0, "(indexation encore en cours : d'autres fichiers peuvent apparaître plus tard)")
    return "\n".join(lines)
