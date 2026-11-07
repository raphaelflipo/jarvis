"""
Banc d'essai de Jarvis : de vraies tâches, vérifiées automatiquement, pour mesurer la fiabilité d'un modèle.
  jarvis bench                   (modèle actuel)
  jarvis bench --model qwen3:14b
  jarvis bench --only Présentation,Parallèle   (seulement certaines tâches)
  jarvis bench --timeout 900                   (limite par tâche, en secondes)
  jarvis bench --renfort --only bug              (mesure le renfort en ligne, s'il est configuré)
  jarvis bench --learn                         (autorise la mémoire de recettes : mesure « avec expérience »)
  jarvis bench --projets / --projets-seuls     (ajoute des tâches sur TES projets, décrits dans ~/.jarvis/bench_projects.json)
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import config


def _prep_bug(ws: Path):
    (ws / "calc").mkdir(parents=True, exist_ok=True)
    (ws / "calc" / "calc.py").write_text("def moyenne(xs):\n    return sum(xs) / len(xs) + 1\n")
    (ws / "calc" / "test_calc.py").write_text("from calc import moyenne\n\ndef test_moyenne():\n    assert moyenne([2, 4]) == 3\n")


def _pytest(d: Path) -> bool:
    r = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=str(d), capture_output=True, text=True)
    return r.returncode == 0


def _xlsx_has_formula(p: Path) -> bool:
    if not p.exists():
        return False
    import openpyxl
    wb = openpyxl.load_workbook(str(p))
    return any(isinstance(c.value, str) and c.value.startswith("=") for ws in wb.worksheets for r in ws.iter_rows() for c in r)


def _pptx_slides(p: Path) -> int:
    if not p.exists():
        return 0
    from pptx import Presentation
    return len(Presentation(str(p)).slides)


def _prep_refactor(ws: Path):
    d = ws / "shop"
    d.mkdir(parents=True, exist_ok=True)
    (d / "pricing.py").write_text("def calc_total(prices, vat=0.2):\n    return round(sum(prices) * (1 + vat), 2)\n")
    (d / "cart.py").write_text("from pricing import calc_total\n\n\nclass Cart:\n    def __init__(self):\n        self.items = []\n\n"
                               "    def add(self, price):\n        self.items.append(price)\n\n"
                               "    def total(self):\n        return calc_total(self.items)\n")
    (d / "test_shop.py").write_text("from cart import Cart\nfrom pricing import calc_total\n\n\ndef test_total():\n"
                                    "    c = Cart()\n    c.add(10)\n    c.add(5)\n    assert c.total() == 18.0\n\n\n"
                                    "def test_calc():\n    assert calc_total([100], vat=0) == 100\n")


def _check_refactor(ws: Path) -> bool:
    d = ws / "shop"
    src = "".join(p.read_text() for p in d.glob("*.py"))
    return "calc_total" not in src and "def compute_total" in (d / "pricing.py").read_text() and _pytest(d)


SALES = [("Clavier", 3, 49.5), ("Souris", 10, 19.0), ("Écran", 2, 189.0), ("Clavier", 2, 49.5), ("Câble", 25, 4.0),
         ("Souris", 4, 19.0), ("Écran", 1, 189.0), ("Casque", 3, 79.0)]


def _prep_sales(ws: Path):
    lines = ["produit;quantite;prix_unitaire"] + [f"{p};{q};{str(u).replace('.', ',')}" for p, q, u in SALES]
    (ws / "ventes.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _num_variants(x: float) -> set[str]:
    i = int(round(x))
    return {f"{x:.2f}", f"{x:.2f}".replace(".", ","), str(i), f"{i:,}".replace(",", " "), f"{i:,}".replace(",", "\u202f"),
            f"{i:,}".replace(",", "\u00a0"), f"{x:,.2f}".replace(",", " ").replace(".", ","), f"{x:.1f}", f"{x:.1f}".replace(".", ",")}


def _check_sales(ws: Path) -> bool:
    p = ws / "rapport.md"
    if not p.exists():
        return False
    txt = p.read_text(errors="replace")
    totals: dict[str, float] = {}
    for prod, q, u in SALES:
        totals[prod] = totals.get(prod, 0) + q * u
    order = sorted(totals, key=lambda k: -totals[k])
    pos = []
    for prod in order:
        line = next((ln for ln in txt.splitlines() if prod.lower() in ln.lower() and any(ch.isdigit() for ch in ln)), "")
        if not line or not any(v in line for v in _num_variants(totals[prod])):
            return False
        pos.append(txt.lower().find(line.lower()))
    return pos == sorted(pos)


def _swift_ok(ws: Path) -> bool:
    exe = ws / "somme"
    if not exe.exists():
        return False
    try:
        return "5050" in subprocess.run([str(exe)], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return False


TASKS = [
    ("Script Python", "Crée hello.py qui affiche exactement « Bonjour Jarvis », puis exécute-le pour vérifier.",
     None, lambda ws: (ws / "hello.py").exists() and "Bonjour Jarvis" in subprocess.run(
         [sys.executable, str(ws / "hello.py")], capture_output=True, text=True).stdout),
    ("Tableur", "Crée budget.xlsx avec 5 dépenses mensuelles (poste, montant) et une ligne Total calculée par formule.",
     None, lambda ws: _xlsx_has_formula(ws / "budget.xlsx")),
    ("Site web", "Crée un site statique dans le dossier site/ : index.html (titre « Test Jarvis ») et style.css relié.",
     None, lambda ws: (ws / "site/index.html").exists() and "Test Jarvis" in (ws / "site/index.html").read_text()
     and "style.css" in (ws / "site/index.html").read_text() and (ws / "site/style.css").exists()),
    ("Code + tests", "Dans le dossier fib/, écris fib.py avec une fonction fib(n) (fib(0)=0, fib(1)=1) et test_fib.py "
     "(pytest, au moins 3 tests). Lance les tests et fais-les passer.",
     None, lambda ws: (ws / "fib/fib.py").exists() and _pytest(ws / "fib")),
    ("Correction de bug", "Le test du dossier calc/ échoue. Trouve et corrige le bug dans calc.py, puis vérifie avec pytest.",
     _prep_bug, lambda ws: _pytest(ws / "calc")),
    ("Présentation", "Crée recyclage.pptx : une présentation de 4 diapositives de contenu sur le recyclage (dont un graphique).",
     None, lambda ws: _pptx_slides(ws / "recyclage.pptx") >= 5),
    ("Parallèle", "Utilise run_parallel pour faire en même temps deux sous-tâches : créer a.txt contenant « A » et créer "
     "b.txt contenant « B ».", None,
     lambda ws: (ws / "a.txt").exists() and (ws / "b.txt").exists()),
    ("Refactorisation", "Dans le projet shop/, renomme la fonction calc_total en compute_total PARTOUT (définition, appels, "
     "imports, tests), puis vérifie que les tests passent.", _prep_refactor, _check_refactor),
    ("Analyse de données", "Analyse ventes.csv (séparateur ;) : calcule le chiffre d'affaires total par produit "
     "(quantité × prix unitaire) et écris rapport.md avec un tableau produit / total, trié du plus grand au plus petit.",
     _prep_sales, _check_sales),
    ("Swift compilé", "Écris somme.swift qui affiche la somme des entiers de 1 à 100, compile-le avec swiftc en un exécutable "
     "nommé somme dans le dossier courant, puis exécute-le pour vérifier.", None, _swift_ok),
]


def _project_tasks() -> list:
    """Tâches sur TES projets (copiés à chaque essai, jamais modifiés) : ~/.jarvis/bench_projects.json."""
    f = config.JARVIS_DIR / "bench_projects.json"
    if not f.exists():
        return []
    try:
        items = json.loads(f.read_text())
    except json.JSONDecodeError:
        return []
    out = []
    for it in items:
        src = Path(it["source"]).expanduser()
        if not src.exists():
            continue
        dest = it.get("as", src.name)

        def prep(ws, src=src, dest=dest, it=it):
            shutil.copytree(src, ws / dest, symlinks=True,
                            ignore=shutil.ignore_patterns("build", "build-*", "DerivedData", ".build", "node_modules", "__pycache__"))
            for ch in it.get("prepare", []):          # ex. bug volontaire à faire trouver
                f = ws / dest / ch["file"]
                txt = f.read_text()
                if ch["old"] not in txt:
                    raise RuntimeError(f"préparation impossible : texte introuvable dans {ch['file']}")
                f.write_text(txt.replace(ch["old"], ch["new"], 1))

        def check(ws, it=it, dest=dest):
            root = ws / dest
            ck = it.get("check", {})
            for rel, needle in (ck.get("must_contain") or {}).items():
                p = root / rel
                if not p.exists() or needle not in p.read_text(errors="replace"):
                    return False
            for rel, needle in (ck.get("must_not_contain") or {}).items():
                p = root / rel
                if p.exists() and needle in p.read_text(errors="replace"):
                    return False
            g = ck.get("grep_any")
            if g:
                files = [p for p in (root / g.get("dir", ".")).rglob(g.get("glob", "*")) if p.is_file()]
                if not any(any(pat in p.read_text(errors="replace") for pat in g["patterns"]) for p in files):
                    return False
            kind = ck.get("type")
            if kind == "ctest":
                bd = root / ck.get("build_dir", "build")
                if not (bd / "CMakeCache.txt").exists():
                    r = subprocess.run(["cmake", "-S", str(root), "-B", str(bd), "-G", "Ninja", "-DBUILD_TESTING=ON",
                                        "-DCMAKE_BUILD_TYPE=Debug"], capture_output=True, text=True, timeout=900)
                    if r.returncode != 0:
                        return False
                r = subprocess.run(["cmake", "--build", str(bd)], capture_output=True, text=True, timeout=1800)
                if r.returncode != 0:
                    return False
                r = subprocess.run(["ctest", "--test-dir", str(bd), "--output-on-failure"], capture_output=True, text=True, timeout=900)
                return r.returncode == 0 and "tests passed" in r.stdout
            if kind == "pytest":
                r = subprocess.run([sys.executable, "-m", "pytest", "-q", ck.get("dir", ".")], cwd=str(root),
                                   capture_output=True, text=True, timeout=600)
                return r.returncode == 0
            if kind == "xcodebuild":
                sel = ["-scheme", ck["scheme"]] if ck.get("scheme") else ["-target", ck["target"]]
                r = subprocess.run(["xcodebuild", "-project", ck["project"], *sel, "-configuration", "Debug",
                                    "-derivedDataPath", str(ws / ".dd-check"), "build", "CODE_SIGNING_ALLOWED=NO", "-quiet"],
                                   cwd=str(root), capture_output=True, text=True, timeout=900)
                return r.returncode == 0
            if kind == "exists":
                return any(root.glob(ck["glob"]))
            return True
        out.append((it["name"], it["prompt"], prep, check))
    return out


def main(cfg: dict):
    args = sys.argv[2:]
    if "--model" in args:
        cfg["model"] = args[args.index("--model") + 1]
    if "--engine" in args:                         # ex. --engine mlx (le service MLX doit tourner)
        cfg["engine"] = args[args.index("--engine") + 1]
    only = [s.strip().lower() for s in args[args.index("--only") + 1].split(",")] if "--only" in args else None
    limit = int(args[args.index("--timeout") + 1]) if "--timeout" in args else 1200
    root = Path(cfg["workspace"]).expanduser() / f"_bench_{time.strftime('%Y%m%d-%H%M%S')}"
    root.mkdir(parents=True)
    (root / ".jarvis-bench").write_text("copies de test du banc d'essai de Jarvis (supprimées à la fin)\n")
    import signal
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(143))      # arrêt demandé (contrôle automatique) : on range
    config.TASKS_DIR = root / ".taches"           # isolé : les tâches du banc d'essai n'apparaissent jamais dans l'app
    config.TASKS_DIR.mkdir()
    config.MEMORY_FILE = root / ".memoire.md"     # ce que le modèle « retient » pendant les essais n'atterrit pas dans ta mémoire
    import projects
    projects._dir = lambda: root / ".projets"     # fiches projet du banc d'essai : à part, jamais mêlées aux tiennes
    print(f"Banc d'essai Jarvis — modèle {cfg['model']}{' (MLX)' if cfg.get('engine') == 'mlx' else ''} — dossier {root}\n", flush=True)
    results = []
    tasks = TASKS + (_project_tasks() if "--projets" in args else [])
    if "--projets-seuls" in args:
        tasks = _project_tasks()
    try:
        _loop(tasks, only, root, cfg, args, limit, results)
    finally:
        if "--keep" not in args:
            shutil.rmtree(root, ignore_errors=True)
    score = sum(r["réussi"] for r in results)
    print(f"\nScore : {score}/{len(results)}  · durée totale {sum(r['secondes'] for r in results)} s")
    out = config.JARVIS_DIR / "bench.jsonl"
    with open(out, "a") as f:
        f.write(json.dumps({"date": time.strftime("%Y-%m-%d %H:%M"), "model": cfg["model"], "score": score,
                            "total": len(results), "details": results, "auto": "--nightly" in args},
                           ensure_ascii=False) + "\n")
    print(f"Historique : {out}")


def _loop(tasks, only, root, cfg, args, limit, results):
    from tasks import TaskManager
    for name, prompt, prep, check in tasks:
        if only and not any(o in name.lower() for o in only):
            continue
        ws = root / re.sub(r"[^\w.-]+", "_", name.replace("+", "et")).strip("_")
        ws.mkdir()
        if prep:
            prep(ws)
        c = {**cfg, "workspace": str(ws), "max_parallel_tasks": 2, "recipes": "--learn" in args, "no_gui": True}
        if "--renfort" in args:
            c["cloud"] = {**(cfg.get("cloud") or {}), "mode": "auto"}
        mgr = TaskManager(c, headless=True)
        t0 = time.time()
        t = mgr.create(prompt, boost="--renfort" in args)      # --renfort : tout passe par le modèle en ligne
        while t.thread and t.thread.is_alive() and time.time() - t0 < limit:
            t.thread.join(0.5)
        timed_out = bool(t.thread and t.thread.is_alive())
        if timed_out:
            mgr.stop(t.id)
            mgr.wait(t.id)
        dt = time.time() - t0
        try:
            ok = bool(check(ws))
        except Exception:
            ok = False
        steps = sum(1 for e in t.events if e["type"] == "tool")
        results.append({"tâche": name, "réussi": ok, "secondes": round(dt), "outils": steps, "délai_dépassé": timed_out})
        print(f"{'✔' if ok else '✖'} {name:<20} {dt:6.0f} s  · {steps} actions{'  (délai dépassé)' if timed_out else ''}",
              flush=True)
        mgr.delete(t.id)
