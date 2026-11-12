"""Configuration et chemins de Jarvis."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

HOME = Path.home()
JARVIS_DIR = Path(os.environ.get("JARVIS_HOME", HOME / ".jarvis"))
CONFIG_FILE = JARVIS_DIR / "config.json"
MEMORY_FILE = JARVIS_DIR / "memory.md"
AUDIT_FILE = JARVIS_DIR / "audit.jsonl"
TASKS_DIR = JARVIS_DIR / "tasks"
BACKUP_DIR = JARVIS_DIR / "backups"
LOG_DIR = JARVIS_DIR / "logs"
SCREENS_DIR = JARVIS_DIR / "screens"
INDEX_DIR = JARVIS_DIR / "index"
BROWSER_STATE = JARVIS_DIR / "browser-state.json"
TOKEN_FILE = JARVIS_DIR / "server_token"

VERSION = "3.3.0-rc.1"
NAME = "Jarvis"

DEFAULTS: dict = {
    # --- Modèles ------------------------------------------------------------
    "model": "qwen3:8b",
    "vision_model": "",
    "embed_model": "nomic-embed-text",
    "ollama_host": "http://127.0.0.1:11434",
    "remote_ollama_host": "",        # Ollama d'un PC plus puissant (IP Tailscale de préférence)
    "remote_model": "",
    "prefer_remote": False,
    "cloud": {"enabled": False, "provider": "gemini", "base_url": "", "model": "", "mode": "ask", "models": []},  # renfort, désactivé
    "num_ctx": 16384,
    "recipes": True,              # mémoire des méthodes qui ont marché
    "project_notes": True,        # fiche par projet : type, commandes qui marchent, pièges (dans ~/.jarvis/projets)
    "thermal_guard": True,        # Mac chaud : une tâche à la fois
    "engine": "ollama",           # « mlx » : moteur Apple (mlx_lm.server local), plus rapide sur puce M
    "mlx": {"url": "http://127.0.0.1:8766/v1", "model": "default_model"},
    "temperature": 0.2,
    "think": False,                  # réflexion approfondie (qwen3…) : plus juste sur les problèmes durs, ~10× plus lent
    # --- Moteur -------------------------------------------------------------
    "max_steps": 60,
    "max_parallel_tasks": 2,         # tâches simultanées (ajusté selon la RAM par l'installateur)
    "max_subtasks": 3,               # sous-agents lancés par une tâche
    "verify": True,
    "tool_timeout": 900,
    "max_tool_calls_per_task": 200,
    # --- Sécurité -----------------------------------------------------------
    "autonomy": "autonome",          # prudent | autonome | total
    "sandbox": True,                 # bac à sable macOS (Seatbelt) pour le shell et les compilations
    "workspace": str(HOME / "JarvisWorkspace"),
    "dev_venv": str(HOME / "JarvisWorkspace" / ".venv"),   # Python de développement de l'agent (python, pip, pytest)
    "project_dirs": [],              # dossiers projets où le shell peut écrire (en plus de l'espace de travail)
    "ssh_trusted_hosts": [],
    "mcp_auto_allow": [],
    # --- Interface / réseau -------------------------------------------------
    "server": {"host": "127.0.0.1", "port": 8765},
    "voice": {"enabled": False, "voice": "Thomas", "rate": 190},
    "ntfy": {"enabled": False, "server": "https://ntfy.sh", "topic": ""},
    "mcp_servers": {},
    "browser_headless": True,
}

_lock = threading.Lock()


def _merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
    if CONFIG_FILE.exists():
        try:
            cfg = _merge(cfg, json.loads(CONFIG_FILE.read_text()))
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save(cfg: dict):
    with _lock:
        JARVIS_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
        os.chmod(tmp, 0o600)
        tmp.replace(CONFIG_FILE)


def update(**changes) -> dict:
    cfg = load()
    cfg = _merge(cfg, changes)
    save(cfg)
    return cfg


def ensure_dirs():
    for d in (JARVIS_DIR, TASKS_DIR, BACKUP_DIR, LOG_DIR, SCREENS_DIR, INDEX_DIR):
        d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(JARVIS_DIR, 0o700)
    except OSError:
        pass
