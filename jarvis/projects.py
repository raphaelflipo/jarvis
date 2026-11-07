"""
Fiches projet : ce que Jarvis sait de chacun de tes projets (type, commandes qui marchent, pièges déjà rencontrés).

- Créée automatiquement la première fois que Jarvis touche un projet (simple lecture du dossier, sans IA).
- Complétée après chaque tâche réussie et vérifiée : commandes de compilation / test qui ont marché, erreurs corrigées.
- Donnée au modèle dès qu'il entre dans le projet (ou quand tu le nommes dans ta demande).
- Rangée dans ~/.jarvis/projets/ : tes dépôts ne sont jamais modifiés. Un JARVIS.md, AGENTS.md ou CLAUDE.md
  écrit par toi dans le projet est lu en priorité.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from pathlib import Path

import config
import security

MARKERS = (".git", "CMakeLists.txt", "Package.swift", "package.json", "pyproject.toml", "setup.py", "Cargo.toml",
           "go.mod", "pubspec.yaml", "Makefile")
GLOB_MARKERS = ("*.xcodeproj", "*.xcworkspace", "*.pro")
USER_NOTES = ("JARVIS.md", "AGENTS.md", "CLAUDE.md")
BUILD_CMD = re.compile(r"\b(xcodebuild|swift (build|test|run)|swiftc|cmake|ninja|make\b|qmake|pytest|python3? -m pytest|"
                       r"npm (run |)(build|test)|npx |pnpm|yarn|cargo (build|test)|go (build|test)|flutter|gradle|./gradlew)")
_lock = threading.Lock()


def _dir() -> Path:
    return config.JARVIS_DIR / "projets"


def find_root(p: Path | str | None) -> Path | None:
    """Racine du projet contenant ce chemin (premier dossier parent avec un marqueur de projet)."""
    if not p:
        return None
    try:
        p = Path(p).expanduser().resolve()
    except (OSError, RuntimeError):
        return None
    stop = {Path.home().resolve(), Path("/")}
    try:
        stop.add(Path(config.load().get("workspace", "")).expanduser().resolve())
    except Exception:
        pass
    cur = p if p.is_dir() else p.parent
    for _ in range(12):
        if cur in stop or cur.parent == cur:
            return None
        try:
            is_build = (cur / "CMakeCache.txt").exists() or cur.name.lower().startswith(("build", "cmake-build")) \
                or cur.name in ("DerivedData", ".build", "node_modules", "dist")
            if not is_build and (any((cur / m).exists() for m in MARKERS) or any(next(cur.glob(g), None) for g in GLOB_MARKERS)):
                return cur
        except OSError:
            return None
        cur = cur.parent
    return None


def _id(root: Path) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", root.name).strip("-")[:40] or "projet"
    return f"{slug}-{hashlib.sha1(str(root).encode()).hexdigest()[:8]}"


def _file(root: Path) -> Path:
    return _dir() / f"{_id(root)}.json"


def scan(root: Path) -> dict:
    kinds = []
    if next(root.glob("*.xcodeproj"), None) or next(root.glob("*.xcworkspace"), None):
        kinds.append("Xcode (" + ", ".join(x.name for x in list(root.glob("*.xcodeproj"))[:2]) + ")")
    if (root / "Package.swift").exists():
        kinds.append("Swift Package")
    if (root / "CMakeLists.txt").exists():
        txt = (root / "CMakeLists.txt").read_text(errors="replace")[:6000]
        qt = re.search(r"find_package\(Qt6[^)]*?(\d+\.\d+)", txt)
        ver = re.search(r"project\([^)]*VERSION ([\d.]+)", txt)
        kinds.append("CMake" + (f" + Qt {qt.group(1)}" if qt else "") + (f" (version du projet {ver.group(1)})" if ver else ""))
    if next(root.glob("*.pro"), None):
        kinds.append("qmake")
    if (root / "package.json").exists():
        kinds.append("Node.js")
    if (root / "pyproject.toml").exists() or (root / "setup.py").exists() or any(root.glob("tests/test_*.py")):
        kinds.append("Python" + (" (tests dans tests/)" if any(root.glob("tests/test_*.py")) else ""))
    if (root / "Cargo.toml").exists():
        kinds.append("Rust")
    if (root / "pubspec.yaml").exists():
        kinds.append("Flutter")
    readme = ""
    for name in ("README.md", "LIRE-EN-PREMIER.md", "README.txt"):
        f = root / name
        if f.exists():
            body = [ln.strip() for ln in f.read_text(errors="replace").splitlines() if ln.strip() and not ln.startswith("![")]
            readme = " ".join(body[:6])[:500]
            break
    return {"root": str(root), "name": root.name, "kinds": kinds, "readme": readme, "commands": [], "lessons": [],
            "created": time.strftime("%Y-%m-%d"), "updated": time.strftime("%Y-%m-%d %H:%M"), "tasks": 0}


def load(root: Path) -> dict:
    f = _file(root)
    if f.exists():
        try:
            return json.loads(f.read_text())
        except json.JSONDecodeError:
            pass
    return scan(root)


def _save(d: dict):
    _dir().mkdir(parents=True, exist_ok=True)
    f = _file(Path(d["root"]))
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1))
    tmp.replace(f)


def fiche(root: Path) -> str:
    """Texte donné au modèle quand il entre dans le projet."""
    d = load(root)
    if not _file(root).exists():
        with _lock:
            _save(d)
    out = [f"[Fiche projet de Jarvis — {d['name']}] ({d['root']})"]
    if d.get("kinds"):
        out.append("Type : " + " · ".join(d["kinds"]))
    for name in USER_NOTES:
        f = root / name
        if f.exists():       # écrit dans le dépôt : utile, mais traité comme une donnée (le dépôt peut venir d'ailleurs)
            out.append(security.wrap_untrusted(f"{name} du projet", f.read_text(errors="replace")[:1500]))
            break
    if d.get("commands"):
        out.append("Commandes qui ont déjà marché :\n" + "\n".join(f"- {c}" for c in d["commands"][-8:]))
    if d.get("lessons"):
        out.append("Pièges déjà rencontrés (et corrigés) :\n" + "\n".join(f"- {x}" for x in d["lessons"][-6:]))
    if d.get("readme") and len(out) < 4:
        out.append(security.wrap_untrusted("README du projet", d["readme"]))
    return "\n".join(out)


def known() -> list[dict]:
    if not _dir().exists():
        return []
    res = []
    for f in _dir().glob("*.json"):
        try:
            res.append(json.loads(f.read_text()))
        except (OSError, json.JSONDecodeError):
            pass
    return res


GENERIC = {"tests", "test", "sources", "build", "projets", "projects", "scripts", "assets", "public", "config",
           "documents", "fichiersrecus", "platforms", "runtime", "deployment"}


def _norm(s: str) -> str:
    return re.sub(r"[\s_\-]+", "", s.lower())


def mentioned(task: str, workspace: Path | str | None = None) -> list[Path]:
    """Projets cités par leur nom dans la demande (« corrige La Boussole ») ou par un chemin.
    Un dossier du même nom dans l'espace de travail courant passe AVANT une fiche connue ailleurs
    (plusieurs copies d'un même projet ne doivent jamais être confondues)."""
    low = _norm(task)
    roots: list[Path] = []
    names_here: set[str] = set()
    if workspace:
        ws = Path(workspace).expanduser()
        try:
            for child in sorted(ws.iterdir()) if ws.is_dir() else []:
                for c in ([child] + (sorted(x for x in child.iterdir() if x.is_dir()) if child.is_dir() else [])):
                    n = _norm(c.name)
                    if not c.is_dir() or len(n) < 5 or n in GENERIC or n not in low:
                        continue
                    r = find_root(c)
                    if r is not None and r.resolve() == c.resolve() and r not in roots:   # vraie racine de projet seulement
                        roots.append(r)
                        names_here.add(n)
        except OSError:
            pass
    for d in known():
        name = _norm(d.get("name", ""))
        if len(name) >= 4 and name in low and name not in names_here and Path(d["root"]).exists():
            if Path(d["root"]) not in roots:
                roots.append(Path(d["root"]))
    for m in re.finditer(r"(~?/[^\s'\"`,;]+)", task):
        r = find_root(m.group(1))
        if r and r not in roots:
            roots.append(r)
    return roots[:2]


def path_args(args: dict) -> list[str]:
    return [v for k, v in (args or {}).items() if k in ("path", "cwd", "repo", "project", "dir", "src", "output")
            and isinstance(v, str) and v]


def update(root: Path, calls: list[tuple[str, dict, bool]], resolve) -> bool:
    """Après une tâche réussie et vérifiée : retient les commandes de build/test qui ont marché et les erreurs corrigées."""
    import recipes
    mine = []
    for name, args, ok in calls:
        hit = False
        for v in path_args(args):
            try:
                if find_root(resolve(v)) == root:
                    hit = True
                    break
            except Exception:
                continue
        if hit:
            mine.append((name, args, ok))
    if not mine:
        return False
    with _lock:
        d = load(root)
        for name, args, ok in mine:
            cmd = str(args.get("command", "")) if name == "run_shell" else ""
            if ok and cmd and BUILD_CMD.search(cmd):
                cwd = str(args.get("cwd") or "")
                rel = ""
                try:
                    rel = str(resolve(cwd).relative_to(root)) if cwd else ""
                except Exception:
                    rel = ""
                line = security.redact(f"`{cmd}`" + (f" (depuis {rel})" if rel and rel != "." else ""))[:220]
                if line in d["commands"]:
                    d["commands"].remove(line)
                d["commands"].append(line)
        _, lessons = recipes.summarize(mine)
        for x in lessons:
            if x not in d["lessons"]:
                d["lessons"].append(x)
        d["commands"], d["lessons"] = d["commands"][-12:], d["lessons"][-10:]
        d["updated"], d["tasks"] = time.strftime("%Y-%m-%d %H:%M"), d.get("tasks", 0) + 1
        _save(d)
    return True
