"""
Images générées sur le Mac : Z-Image-Turbo (Tongyi, licence Apache 2.0) via mflux, la version MLX optimisée pour
Apple Silicon. Gratuit et hors ligne après le premier téléchargement (environ 6 Go). Environ 5 Go de mémoire
pendant la création, puis tout est libéré.
"""
from __future__ import annotations

import datetime
import os
import random
import re
import subprocess
import time
from pathlib import Path

import config
import security
import registry
from registry import Ctx, I, S, tool

MODEL = "filipstrand/Z-Image-Turbo-mflux-4bit"
BASE = "z-image-turbo"


def exe() -> Path:
    return config.JARVIS_DIR / "image-venv" / "bin" / "mflux-generate-z-image-turbo"


def model_cached() -> bool:
    snaps = Path.home() / ".cache" / "huggingface" / "hub" / f"models--{MODEL.replace('/', '--')}" / "snapshots"
    try:
        return any(any(d.rglob("*.safetensors")) for d in snaps.iterdir())
    except OSError:
        return False


def available() -> bool:
    return exe().exists()


def _size(v, default: int) -> int:
    try:
        v = int(v or default)
    except (TypeError, ValueError):
        v = default
    return max(256, min(1536, v)) // 16 * 16


def fit(width, height) -> tuple[int, int]:
    """Taille acceptée par le modèle (côtés ≤ 1536, multiples de 16) en GARDANT les proportions demandées."""
    try:
        w, h = int(width or 1024), int(height or 1024)
    except (TypeError, ValueError):
        w, h = 1024, 1024
    w, h = max(w, 64), max(h, 64)
    k = min(1.0, 1536 / max(w, h))
    w, h = w * k, h * k
    if min(w, h) < 256:
        k = 256 / min(w, h)
        w, h = w * k, h * k
    return _size(round(w), 1024), _size(round(h), 1024)


def _slug(text: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:50].rstrip("-") or "image"


@tool("generate_image",
      "Crée une image sur le Mac (illustration, photo réaliste, visuel de diapositive, affiche, fond de site, icône simple). "
      "Décris l'image EN ANGLAIS, précisément : sujet, style, couleurs, lumière, cadrage. Le texte écrit dans l'image peut "
      "être imparfait : ajoute plutôt les titres ensuite (diapo, page web). Environ 30 s à 1 min par image. Renvoie le "
      "chemin du PNG, à insérer ensuite dans une présentation, un document ou un site.",
      {"prompt": S("Description de l'image, en anglais"), "width": I("Largeur en pixels (défaut 1024, max 1536)"),
       "height": I("Hauteur en pixels (défaut 1024 ; 16:9 → 1344×768)"), "path": S("Fichier PNG à créer (facultatif)"),
       "seed": I("Graine pour refaire la même image (facultatif)")},
      ["prompt"], category="write")
def generate_image(prompt: str, width: int = 1024, height: int = 1024, path: str = "", seed: int = 0):
    if not available():
        return "Création d'images non installée : relance l'installateur de Jarvis (option « images sur le Mac »)."
    prompt = (prompt or "").strip()
    if len(prompt) < 3:
        return "Décris l'image à créer."
    w, h = fit(width, height)
    seed = int(seed) if seed else random.randint(1, 2**31 - 1)
    if path:
        out = registry.P(path).resolve()       # chemin relatif → dans l'espace de travail de la tâche
        if out.suffix.lower() != ".png":
            out = out.with_suffix(".png")
    else:
        folder = Path(Ctx.cfg.get("workspace") or (Path.home() / "JarvisWorkspace")).expanduser() / "Images"
        out = folder / f"{datetime.date.today().isoformat()}-{_slug(prompt)}-{seed % 10000}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    first = not model_cached()
    if first:
        ui = getattr(Ctx, "ui", None)
        if ui is not None:
            try:
                ui.info("🎨 Premier usage : téléchargement du modèle d'images (environ 6 Go, une seule fois)…")
            except Exception:
                pass
    env = {**os.environ, "PATH": "/opt/homebrew/bin:/usr/bin:/bin"}
    if not first:
        env["HF_HUB_OFFLINE"] = "1"           # rien ne part sur Internet une fois le modèle sur le Mac
    args = [str(exe()), "--model", MODEL, "--base-model", BASE, "--prompt", prompt[:1500], "--steps", "9",
            "--width", str(w), "--height", str(h), "--seed", str(seed), "--output", str(out),
            "--mlx-cache-limit-gb", "6", "--vae-tiling"]
    t0 = time.time()
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=3600 if first else 900, env=env)
    except subprocess.TimeoutExpired:
        return "La création de l'image a pris trop de temps (Mac très chargé ?). Réessaie, ou demande une image plus petite."
    if r.returncode != 0 or not out.exists():
        tail = (r.stderr or r.stdout or "").strip().splitlines()[-3:]
        return "Échec de la création de l'image : " + " / ".join(tail)[:400]
    security.audit({"type": "image", "task": getattr(Ctx, "task_id", ""), "size": f"{w}x{h}", "seconds": round(time.time() - t0)})
    return f"Image créée : {out} ({w}×{h}, {time.time() - t0:.0f} s, graine {seed})."
