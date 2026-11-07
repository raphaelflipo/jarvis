"""
Registre des outils, contexte PAR TÂCHE (thread-local, pour les tâches parallèles), sauvegardes, verrous.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import config
import security
from security import BLOCKED, NORMAL, RISKY, SAFE

MAX_OUT = 8000


@dataclass
class Tool:
    name: str
    description: str
    params: dict
    required: list
    fn: Callable
    category: str = "read"
    risk: Callable | None = None
    untrusted: bool = False
    summary: Callable | None = None

    def schema(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": {"type": "object", "properties": self.params, "required": self.required}}}


TOOLS: dict[str, Tool] = {}
DEFAULT_LEVEL = {"read": SAFE, "meta": SAFE, "write": NORMAL, "exec": NORMAL, "net": NORMAL,
                 "gui": NORMAL, "browser": NORMAL, "mcp": NORMAL, "send": RISKY, "publish": RISKY}


def tool(name, description, params, required=None, category="read", risk=None, untrusted=False, summary=None):
    def deco(fn):
        TOOLS[name] = Tool(name, description, params, list(params.keys()) if required is None else required,
                           fn, category, risk, untrusted, summary)
        return fn
    return deco


def S(desc: str, **kw) -> dict:
    return {"type": "string", "description": desc, **kw}


def I(desc: str) -> dict:
    return {"type": "integer", "description": desc}


def B(desc: str) -> dict:
    return {"type": "boolean", "description": desc}


# =============================================================== contexte par tâche
class _Ctx(threading.local):
    """Chaque tâche (et sous-tâche) tourne dans son propre thread avec son propre contexte."""

    def __init__(self):
        self.cfg: dict = config.load() if config.CONFIG_FILE.exists() else dict(config.DEFAULTS)
        self.policy = security.Policy()
        self.router = None
        self.backups: Backups | None = None
        self.ui = None
        self.plan: list = []
        self.task_id: str = ""
        self.agent = None
        self.depth: int = 0

    def workspace(self) -> Path:
        return Path(self.cfg.get("workspace", config.HOME / "JarvisWorkspace")).expanduser()

    def info(self, msg: str):
        if self.ui:
            try:
                self.ui.info(msg)
            except Exception:
                pass


Ctx = _Ctx()


def P(path: str | Path) -> Path:
    p = Path(os.path.expandvars(str(path or ""))).expanduser()
    return p if p.is_absolute() else (Ctx.workspace() / p)


def trunc(s: str, n: int = MAX_OUT) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n // 2] + f"\n…[{len(s) - n} caractères coupés]…\n" + s[-n // 2:]


# =============================================================== verrous partagés
_path_locks: dict[str, threading.Lock] = {}
_path_guard = threading.Lock()


def path_lock(p: Path) -> threading.Lock:
    key = str(security.resolve(p))
    with _path_guard:
        return _path_locks.setdefault(key, threading.Lock())


class GuiOwner:
    """Une seule tâche à la fois pilote la souris/le clavier/l'écran."""
    owner: str | None = None
    last: float = 0.0
    lock = threading.Lock()

    @classmethod
    def acquire(cls, task_id: str, wait: float = 120) -> bool:
        t0 = time.time()
        while time.time() - t0 < wait:
            with cls.lock:
                if cls.owner in (None, task_id) or time.time() - cls.last > 90:
                    cls.owner, cls.last = task_id, time.time()
                    return True
            time.sleep(1)
        return False

    @classmethod
    def release(cls, task_id: str):
        with cls.lock:
            if cls.owner == task_id:
                cls.owner = None


# =============================================================== sauvegardes
class Backups:
    """Sauvegarde chaque fichier avant modification ; « annuler » restaure toute la tâche (sous-tâches comprises)."""

    def __init__(self, task_id: str):
        self.task_id = task_id
        self.dir = config.BACKUP_DIR / task_id
        self.manifest: list[dict] = []
        self.seen: set[str] = set()
        self.lock = threading.Lock()
        mf = self.dir / "manifest.json"
        if mf.exists():                      # reprise d'une conversation : on conserve l'historique d'annulation
            try:
                self.manifest = json.loads(mf.read_text())
                self.seen = {e["path"] for e in self.manifest}
            except (OSError, json.JSONDecodeError):
                pass

    def before_write(self, path: Path):
        key = str(path.resolve()) if path.exists() else str(path.absolute())
        with self.lock:
            if key in self.seen:
                return
            self.seen.add(key)
            entry = {"path": key, "backup": None}
            if path.is_file():
                self.dir.mkdir(parents=True, exist_ok=True)
                dest = self.dir / f"{len(self.manifest):04d}_{path.name}"
                shutil.copy2(path, dest)
                entry["backup"] = str(dest)
            elif path.exists():
                return
            self.manifest.append(entry)
            self.dir.mkdir(parents=True, exist_ok=True)
            (self.dir / "manifest.json").write_text(json.dumps(self.manifest, indent=1, ensure_ascii=False))

    @staticmethod
    def for_task(task_id: str) -> Path | None:
        d = config.BACKUP_DIR / task_id
        return d if (d / "manifest.json").exists() else None

    @staticmethod
    def list_tasks() -> list[Path]:
        if not config.BACKUP_DIR.exists():
            return []
        dirs = [d for d in config.BACKUP_DIR.iterdir() if (d / "manifest.json").exists()]
        return sorted(dirs, key=lambda d: (d / "manifest.json").stat().st_mtime, reverse=True)

    @staticmethod
    def undo(task_dir: Path) -> str:
        man = json.loads((task_dir / "manifest.json").read_text())
        trash = Path.home() / ".Trash"
        trash.mkdir(exist_ok=True)
        done = []
        for e in reversed(man):
            p = Path(e["path"])
            if e["backup"]:
                p.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(e["backup"], p)
                done.append(f"restauré : {p}")
            elif p.exists():
                dest = trash / f"{p.name}.jarvis-{int(time.time())}"
                shutil.move(str(p), dest)
                done.append(f"mis à la Corbeille (créé par Jarvis) : {p}")
        shutil.rmtree(task_dir, ignore_errors=True)
        return "\n".join(done) or "Rien à annuler."

    @staticmethod
    def prune(keep: int = 60):
        for d in Backups.list_tasks()[keep:]:
            shutil.rmtree(d, ignore_errors=True)


def backup(path: Path):
    if Ctx.backups:
        Ctx.backups.before_write(path)


# =============================================================== exécution
def _validate(t: Tool, args: Any) -> tuple[dict, str | None]:
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError:
            return {}, "arguments JSON invalides"
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return {}, "les arguments doivent être un objet JSON"
    missing = [r for r in t.required if r not in args or args[r] in (None, "")]
    if missing:
        return args, f"argument(s) obligatoire(s) manquant(s) : {', '.join(missing)}"
    clean = {}
    for k, v in args.items():
        spec = t.params.get(k)
        if spec is None or v is None:
            continue
        typ = spec.get("type")
        try:
            if typ == "integer" and not isinstance(v, int):
                v = int(float(v))
            elif typ == "number" and not isinstance(v, (int, float)):
                v = float(v)
            elif typ == "boolean" and not isinstance(v, bool):
                v = str(v).lower() in ("true", "1", "oui", "yes")
            elif typ == "array" and isinstance(v, str):
                v = json.loads(v) if v.strip().startswith("[") else [x.strip() for x in v.split(",") if x.strip()]
            elif typ == "object" and isinstance(v, str):
                v = json.loads(v)
            elif typ == "string" and not isinstance(v, str):
                v = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
        except (ValueError, TypeError, json.JSONDecodeError):
            return args, f"type invalide pour « {k} » (attendu {typ})"
        if "enum" in spec and v not in spec["enum"]:
            return args, f"« {k} » doit valoir : {', '.join(map(str, spec['enum']))}"
        clean[k] = v
    return clean, None


def call(name: str, raw_args: Any) -> dict:
    """Exécute un outil : validation → évaluation du risque → politique → exécution → marquage → audit."""
    t0 = time.time()
    t = TOOLS.get(name)
    if not t:
        close = [n for n in TOOLS if name.split("_")[0] in n][:6]
        return {"ok": False, "output": f"[erreur] outil inconnu « {name} ». Proches : {', '.join(close) or '—'}"}
    if t.category == "gui" and (Ctx.cfg or {}).get("no_gui"):
        return {"ok": True, "output": "(mode sans écran : ouverture d'application ignorée, continue sans)"}
    args, err = _validate(t, raw_args)
    if err:
        return {"ok": False, "output": f"[erreur] {err}. Paramètres attendus : {json.dumps(t.params, ensure_ascii=False)[:700]}"}
    level, detail = DEFAULT_LEVEL.get(t.category, NORMAL), ""
    if t.risk:
        try:
            level, detail = t.risk(**args)
        except Exception as e:
            level, detail = RISKY, f"évaluation du risque impossible ({e})"
    try:
        summary = t.summary(**args) if t.summary else f"{name} {json.dumps(args, ensure_ascii=False)[:300]}"
    except Exception:
        summary = f"{name} {json.dumps(args, ensure_ascii=False)[:300]}"
    d = Ctx.policy.decide(name, t.category, level, summary, detail)
    if not d.allowed:
        return {"ok": False, "denied": True, "output": f"[refusé] {d.reason}. Ne réessaie pas la même action : "
                                                        f"propose une alternative ou explique à l'utilisateur."}
    try:
        out = t.fn(**args)
        out = "" if out is None else str(out)
        ok = not out.lstrip().startswith("[erreur") and not re.match(r"\s*\[code retour [1-9]", out)
    except TypeError as e:
        out, ok = f"[erreur arguments] {e}", False
    except Exception as e:
        out, ok = f"[erreur] {type(e).__name__}: {e}", False
    out = security.redact(trunc(out))
    if t.untrusted and ok:
        Ctx.policy.taint(name)
        out = security.wrap_untrusted(name, out)
    security.audit({"type": "tool", "task": Ctx.task_id, "tool": name, "ok": ok, "ms": int((time.time() - t0) * 1000),
                    "args": security.redact(json.dumps(args, ensure_ascii=False)[:400]), "out": out[:300]})
    return {"ok": ok, "output": out}


def schemas(exclude: set | None = None) -> list[dict]:
    return [t.schema() for n, t in TOOLS.items() if not exclude or n not in exclude]


# =============================================================== outils utiles seulement
# Le modèle relit la description de chaque outil à chaque étape : avec ~60 outils, c'est les trois quarts de ce qu'il
# lit. On n'envoie que le noyau + les familles utiles à la demande ; `more_tools` (ou l'appel direct d'un outil
# connu) ajoute une famille en cours de route.
CORE = {"run_shell", "read_file", "write_file", "edit_file", "list_dir", "search_files", "apply_patch", "update_plan",
        "remember", "notify", "web_search", "fetch_url", "analyze_file", "run_parallel", "more_tools"}
GROUPS = {
    "dev": {"build_project", "git", "github", "firebase", "code_map", "semantic_search", "run_on_simulator",
            "start_background", "stop_background", "read_log", "open_in_editor", "deploy_website"},
    "office": {"create_word", "create_powerpoint", "create_excel", "edit_office", "convert_file", "generate_image"},
    "web": {"browser_open", "browser_read", "browser_click", "browser_type", "browser_screenshot", "browser_close",
            "http_request", "deep_research"},
    "mac": {"applescript", "open_app", "clipboard", "look_at_screen", "mouse_click", "type_text", "press_keys",
            "agenda_events", "agenda_add_event", "reminders_list", "reminder_add", "note_create", "notes_search",
            "search_my_files"},
    "reseau": {"ssh_run", "ssh_copy", "net_check", "network_info", "notify_phone", "http_request"},
    "planif": {"schedule_task", "list_scheduled", "remove_scheduled"},
}
_KW = {
    "dev": r"\b(code|coder|projet|compil\w*|build|bug\w*|tests?|git|github|commit|pull request|firebase|xcode|swift|python|"
           r"c\+\+|qt|qml|cmake|appli\w*|app|site|web ?app|html|css|javascript|js|typescript|react|d[ée]ploi\w*|deploy\w*|"
           r"script|fonction|erreur|crash\w*|simulateur|ios|android|api|serveur local|npm|pip|d[ée]p[ôo]t|repo|branche|"
           r"programm\w*|d[ée]bogu\w*|refactor\w*|log|logs)\b|\.(py|js|ts|swift|cpp|h|java|kt|go|rs)\b",
    "office": r"\b(word|docx?|powerpoint|pptx?|pr[ée]sentation|diapo\w*|slides?|excel|xlsx|tableur|tableau|feuille de calcul|"
              r"rapport|compte rendu|cv|lettre|courrier|pdf|convert\w*|image|illustration|affiche|flyer|logo|dessin|visuel|"
              r"graphique|exposé|dossier|fiche|brochure|invitation|menu)\b",
    "web": r"\b(navigateur|connecte-toi|connexion|formulaire|clique|cliquer|page web|site web|onglet|browser|recherche "
           r"approfondie|compar\w*|actualit\w*|derni[èe]res? nouvelles|sources|http|url|r[ée]serv\w*)\b|https?://|🔎",
    "mac": r"\b(calendrier|agenda|rendez-vous|rdv|demain|cette semaine|semaine prochaine|rappel\w*|rappelle|notes?|finder|"
           r"mail|e-mail|musique|music|ouvre|lance l'app|application|[ée]cran|souris|presse-papiers?|applescript|r[ée]glages|"
           r"raccourcis?|safari|photos|retrouve|mes (fichiers|documents|cours|dossiers|notes|pdf)|o[uù] (est|sont|ai-je)|"
           r"cherche dans mes)\b",
    "reseau": r"\b(ssh|serveur|r[ée]seau|wi-?fi|ping|adresse ip|ip|routeur|port|t[ée]l[ée]phone|iphone|notifi\w*)\b",
    "planif": r"\b(chaque (jour|matin|soir|semaine|lundi|mois)|tous les|toutes les|planifi\w*|programme\w*|r[ée]guli[èe]rement|"
              r"quotidien\w*|hebdo\w*)\b",
}


def group_of(name: str) -> str | None:
    return next((g for g, names in GROUPS.items() if name in names), None)


def groups_for(text: str) -> set:
    """Familles d'outils utiles d'après la demande (et les noms d'outils qu'elle cite)."""
    low = (text or "").lower()
    out = {g for g, rx in _KW.items() if re.search(rx, low, re.I)}
    out |= {g for n in re.findall(r"\b[a-z]+_[a-z_]+\b", low) if (g := group_of(n))}
    return out


def schemas_for(groups: set, exclude: set | None = None) -> list[dict]:
    """Le noyau D'ABORD, toujours dans le même ordre : ce début commun reste en mémoire du modèle d'une tâche à
    l'autre (préchauffé au lancement), seules les familles ajoutées sont à lire."""
    extra = set()
    for g in sorted(groups or ()):
        extra |= GROUPS.get(g, set())
    ok = lambda n: not exclude or n not in exclude                       # noqa: E731
    core = [TOOLS[n].schema() for n in TOOLS if n in CORE and ok(n)]
    rest = [t.schema() for n, t in TOOLS.items()                        # outils MCP ajoutés par toi : toujours là
            if n not in CORE and (n in extra or n.startswith("mcp__")) and ok(n)]
    return core + rest


def now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
