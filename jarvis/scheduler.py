"""
Tâches planifiées via launchd (natif macOS, gratuit, survit aux redémarrages).
Les exécutions planifiées tournent en mode SANS SURVEILLANCE : toute action risquée est refusée
automatiquement ; le résultat arrive en notification (Mac + téléphone si ntfy est configuré).
"""
from __future__ import annotations

import json
import os
import plistlib
import re
import subprocess
from pathlib import Path

import config
from registry import I, S, tool
from security import RISKY, SAFE

AGENTS = Path.home() / "Library" / "LaunchAgents"
INDEX = config.JARVIS_DIR / "schedules.json"
PREFIX = "com.jarvis.task."


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9-]", "-", s.lower()).strip("-")[:40] or "tache"


def _load() -> dict:
    return json.loads(INDEX.read_text()) if INDEX.exists() else {}


def _save(d: dict):
    INDEX.write_text(json.dumps(d, indent=2, ensure_ascii=False))


WEEKDAYS = {"dimanche": 0, "lundi": 1, "mardi": 2, "mercredi": 3, "jeudi": 4, "vendredi": 5, "samedi": 6}


@tool("schedule_task",
      "Planifie une tâche récurrente exécutée par Jarvis en arrière-plan (même Terminal fermé). "
      "days = liste parmi lundi…dimanche, ou vide = tous les jours. Ex : chaque jour à 8h05, "
      "'Fais git pull de tous les dépôts de ~/Projets et signale les conflits'.",
      {"name": S("Nom court"), "prompt": S("Instruction complète pour Jarvis"), "hour": I("Heure 0-23"),
       "minute": I("Minute 0-59"), "days": {"type": "array", "items": {"type": "string"}, "description": "Jours"}},
      ["name", "prompt", "hour", "minute"], category="exec",
      risk=lambda **k: (RISKY, "tâche persistante exécutée sans surveillance"),
      summary=lambda name, prompt, hour, minute, days=None: f"planifier « {name} » à {hour:02d}:{minute:02d} "
                                                            f"({', '.join(days) if days else 'tous les jours'}) : {prompt[:200]}")
def schedule_task(name: str, prompt: str, hour: int, minute: int, days: list | None = None):
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return "[erreur] heure invalide"
    slug = _slug(name)
    label = PREFIX + slug
    atlas_bin = str(Path.home() / ".local" / "bin" / "jarvis")
    intervals = []
    for d in days or []:
        wd = WEEKDAYS.get(str(d).lower().strip())
        if wd is None:
            return f"[erreur] jour inconnu : {d}"
        intervals.append({"Weekday": wd, "Hour": hour, "Minute": minute})
    if not intervals:
        intervals = [{"Hour": hour, "Minute": minute}]
    plist = {
        "Label": label,
        "ProgramArguments": [atlas_bin, "--headless", "--notify", prompt],
        "StartCalendarInterval": intervals if len(intervals) > 1 else intervals[0],
        "StandardOutPath": str(config.LOG_DIR / f"task-{slug}.log"),
        "StandardErrorPath": str(config.LOG_DIR / f"task-{slug}.log"),
        "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
        "ProcessType": "Background",
    }
    AGENTS.mkdir(parents=True, exist_ok=True)
    path = AGENTS / f"{label}.plist"
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(path)], capture_output=True)
    with open(path, "wb") as f:
        plistlib.dump(plist, f)
    r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(path)], capture_output=True, text=True)
    if r.returncode != 0:
        return f"[erreur] launchctl : {r.stderr.strip()}"
    idx = _load()
    idx[slug] = {"prompt": prompt, "hour": hour, "minute": minute, "days": days or [], "label": label}
    _save(idx)
    return f"Tâche « {slug} » planifiée à {hour:02d}:{minute:02d} ({', '.join(days) if days else 'tous les jours'})."


@tool("list_scheduled", "Liste les tâches planifiées de Jarvis.", {}, [], category="read")
def list_scheduled():
    idx = _load()
    if not idx:
        return "Aucune tâche planifiée."
    return "\n".join(f"• {k} — {v['hour']:02d}:{v['minute']:02d} {', '.join(v['days']) or 'tous les jours'} : {v['prompt'][:120]}"
                     for k, v in idx.items())


@tool("remove_scheduled", "Supprime une tâche planifiée.", {"name": S("Nom de la tâche")}, category="exec",
      risk=lambda name: (SAFE, ""))
def remove_scheduled(name: str):
    slug = _slug(name)
    idx = _load()
    path = AGENTS / f"{PREFIX}{slug}.plist"
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(path)], capture_output=True)
    path.unlink(missing_ok=True)
    existed = idx.pop(slug, None)
    _save(idx)
    return f"Tâche « {slug} » supprimée." if existed else f"Aucune tâche « {slug} »."
