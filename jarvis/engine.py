"""
Moteur d'inférence : Ollama (llama.cpp, par défaut) ou MLX d'Apple (mlx_lm.server), au choix dans les réglages.

MLX : mesuré sur ce MacBook Air M5 avec gpt-oss-20b, 40 jetons/s contre 30 pour llama.cpp, lecture des
instructions 35 % plus rapide. Il tourne en service local (LaunchAgent) sur 127.0.0.1 uniquement.
Ollama reste utilisé pour la vision et la recherche par le sens.
"""
from __future__ import annotations

import os
import plistlib
import subprocess
import time
from pathlib import Path

import config

LABEL = "com.jarvis.mlx"
PORT = 8766
REPO = {"gpt-oss:20b": "mlx-community/gpt-oss-20b-MXFP4-Q8"}


def venv_bin() -> Path:
    return config.JARVIS_DIR / "mlx-venv" / "bin" / "mlx_lm.server"


def model_dir(model: str) -> Path | None:
    repo = REPO.get(model)
    if not repo:
        return None
    snaps = Path.home() / ".cache" / "huggingface" / "hub" / f"models--{repo.replace('/', '--')}" / "snapshots"
    try:
        for d in sorted(snaps.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if any(d.glob("*.safetensors")) and (d / "config.json").exists():
                return d
    except OSError:
        pass
    return None


def available(model: str) -> bool:
    return venv_bin().exists() and model_dir(model) is not None


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _launchctl(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=30)


def start(model: str) -> tuple[bool, str]:
    """Installe et lance le service MLX, attend qu'il réponde."""
    md = model_dir(model)
    if not (venv_bin().exists() and md):
        return False, "MLX non installé pour ce modèle (relance l'installateur)."
    pl = {
        "Label": LABEL,
        "ProgramArguments": [str(venv_bin()), "--model", str(md), "--host", "127.0.0.1", "--port", str(PORT),
                             "--chat-template-args", '{"reasoning_effort":"low"}', "--prompt-cache-size", "6",
                             "--max-tokens", "16384"],          # défaut 512 : trop court pour écrire un fichier
        "RunAtLoad": True, "KeepAlive": True, "ProcessType": "Interactive",
        "StandardOutPath": str(config.LOG_DIR / "mlx-server.log"), "StandardErrorPath": str(config.LOG_DIR / "mlx-server.log"),
        "EnvironmentVariables": {"HF_HUB_OFFLINE": "1", "PATH": "/opt/homebrew/bin:/usr/bin:/bin"},
    }
    p = plist_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(plistlib.dumps(pl))
    uid = os.getuid()
    _launchctl("bootout", f"gui/{uid}", str(p))
    r = _launchctl("bootstrap", f"gui/{uid}", str(p))
    if r.returncode not in (0, 37):           # 37 : déjà chargé
        return False, (r.stderr or "lancement impossible")[:200]
    return wait_ready(90)


def wait_ready(timeout: float = 60) -> tuple[bool, str]:
    import requests
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if requests.get(f"http://127.0.0.1:{PORT}/v1/models", timeout=2).ok:
                return True, f"MLX prêt en {time.time() - t0:.0f} s"
        except requests.RequestException:
            pass
        time.sleep(1)
    return False, "le service MLX ne répond pas (voir ~/.jarvis/logs/mlx-server.log)"


def stop():
    p = plist_path()
    if p.exists():
        _launchctl("bootout", f"gui/{os.getuid()}", str(p))
        p.unlink(missing_ok=True)


def unload_ollama(cfg: dict):
    """Libère la mémoire du même modèle chargé dans Ollama (24 Go ne suffisent pas pour deux copies)."""
    import requests
    try:
        requests.post(f"{cfg['ollama_host']}/api/generate", json={"model": cfg["model"], "keep_alive": 0}, timeout=10)
    except requests.RequestException:
        pass


def mlx_cfg() -> dict:
    return {"url": f"http://127.0.0.1:{PORT}/v1", "model": "default_model"}
