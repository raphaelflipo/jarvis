"""
Mémoire de « recettes » : Jarvis retient la méthode des tâches réussies et la ressert quand une demande proche revient.

- Seules les tâches terminées ET vérifiées, sans contenu externe lu (anti-injection), sont retenues.
- On garde la séquence d'actions utiles (pas les lectures ni le plan) et les erreurs corrigées (« leçons »).
- La recherche se fait par le sens (nomic-embed-text, local) avec repli sur les mots communs.
Tout reste dans ~/.jarvis/recipes.jsonl, sur le Mac.
"""
from __future__ import annotations

import json
import math
import re
import threading
import time

import config
import security

MAX_RECIPES = 400
NOISE = {"update_plan", "list_dir", "read_file", "search_files", "code_map", "semantic_search", "read_log", "remember"}
_lock = threading.Lock()


def path():
    return config.JARVIS_DIR / "recipes.jsonl"


def _short(name: str, args: dict) -> str:
    a = args or {}
    if name == "run_shell":
        cwd = str(a.get("cwd") or "").rstrip("/").split("/")[-1]
        s = f"run_shell `{a.get('command', '')}`" + (f" (cwd …/{cwd})" if cwd else "")
    elif name in ("write_file", "edit_file", "create_word", "create_excel", "create_powerpoint", "convert_file", "analyze_file"):
        p = str(a.get("path") or a.get("output") or a.get("src") or "")
        s = f"{name} {p.split('/')[-2] + '/' if p.count('/') else ''}{p.split('/')[-1]}"
        if name == "write_file" and str(a.get("path", "")).endswith(".py"):
            imports = [ln.strip() for ln in str(a.get("content", "")).splitlines() if ln.startswith(("from ", "import "))][:2]
            if imports:
                s += f" [{'; '.join(imports)}]"
    else:
        s = name + " " + json.dumps({k: v for k, v in a.items() if isinstance(v, (str, int, bool)) and len(str(v)) < 60},
                                    ensure_ascii=False)[:100]
    return security.redact(s)[:160]


def summarize(calls: list[tuple[str, dict, bool]]) -> tuple[list[str], list[str]]:
    """calls = [(outil, arguments, réussi)] → (étapes utiles, leçons « échec → correction »)."""
    steps, lessons, failed = [], [], {}
    for name, args, ok in calls:
        if name in NOISE:
            continue
        s = _short(name, args)
        if not ok:
            failed[name] = s
            continue
        if name in failed and len(lessons) < 3:
            lessons.append(f"✗ {failed.pop(name)} → ✓ {s}")
        if steps and steps[-1] == s:
            continue
        steps.append(s)
    return steps[:20], lessons


def _cos(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def _words(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-zà-ÿ0-9]{4,}", t.lower())}


def _jac(a: str, b: str) -> float:
    x, y = _words(a), _words(b)
    return len(x & y) / len(x | y) if x and y else 0.0


def _embed(router, text: str):
    try:
        return router.embed([text[:2000]])[0]
    except Exception:
        return None


def load() -> list[dict]:
    p = path()
    if not p.exists():
        return []
    out = []
    for line in p.read_text(errors="replace").splitlines()[-MAX_RECIPES:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def count() -> int:
    return len(load())


def record(router, task: str, calls: list[tuple[str, dict, bool]], model: str = ""):
    steps, lessons = summarize(calls)
    if not steps:
        return False
    rec = {"ts": time.strftime("%Y-%m-%d %H:%M"), "task": security.redact(task.strip())[:500], "steps": steps,
           "lessons": lessons, "model": model, "emb": _embed(router, task)}
    with _lock:
        items = [r for r in load() if r.get("task") != rec["task"]] + [rec]      # une seule recette par demande identique
        p = path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in items[-MAX_RECIPES:]) + "\n")
        tmp.replace(p)
    return True


def best(router, task: str, min_cos: float = 0.67, min_jac: float = 0.34) -> dict | None:
    """Seuils calibrés sur nomic-embed-text : demandes proches 0,69–0,78 ; sans rapport 0,51–0,60."""
    items = load()
    if not items:
        return None
    emb = _embed(router, task)
    scored = []
    for r in items:
        s = _cos(emb, r.get("emb")) if emb and r.get("emb") else 0.0
        j = _jac(task, r.get("task", ""))
        if s >= min_cos or j >= min_jac:
            scored.append((max(s, j + 0.45), r))
    return max(scored, key=lambda x: x[0])[1] if scored else None


def hint(r: dict) -> str:
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(r["steps"], 1))
    les = ("\nErreurs déjà corrigées :\n" + "\n".join(f"- {x}" for x in r["lessons"])) if r.get("lessons") else ""
    return (f"[Expérience de Jarvis] Une demande proche a déjà réussi : « {r['task'][:200]} ».\nMéthode qui a marché :\n{steps}{les}\n"
            "Inspire-t'en (chemins et noms à adapter) ; ne la recopie pas aveuglément.")


def clear():
    with _lock:
        p = path()
        if p.exists():
            p.write_text("")
