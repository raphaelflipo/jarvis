"""Outils développeur : patchs multi-fichiers, carte d'un projet, recherche sémantique locale, simulateur iOS."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
import threading
import time
from pathlib import Path

import config
import security
from registry import B, I, P, S, Ctx, backup, path_lock, tool, trunc
from security import BLOCKED, NORMAL, RISKY, SAFE
from tools import SKIP, env, sh

# ====================================================================== apply_patch
PATCH_FILE = re.compile(r"^\+\+\+ (?:b/)?(\S+)", re.M)
PATCH_OLD = re.compile(r"^--- (?:a/)?(\S+)", re.M)


CODEX_HDR = re.compile(r"^\*\*\* (Add|Update|Delete) File: (.+?)\s*$|^\*\*\* Move to: (.+?)\s*$", re.M)


def _rp(root: Path, f: str) -> Path:
    """Chemin d'un fichier de patch. Erreur fréquente des modèles : cwd = « shop » ET chemins « shop/cart.py » →
    on évite de créer un doublon shop/shop/ en reconnaissant le préfixe répété."""
    if f.startswith("/"):
        return Path(f)
    p = (root / f).resolve()
    parts = Path(f).parts
    if not p.exists() and len(parts) > 1 and parts[0] == root.name:
        alt = (root.parent / f).resolve()
        if alt.exists() or alt.parent.exists():
            return alt
    return p


def _is_codex(patch: str) -> bool:
    """Format « *** Begin Patch / *** Update File: » (celui qu'utilisent gpt-oss et les agents d'OpenAI)."""
    return "*** Begin Patch" in patch or bool(re.search(r"^\*\*\* (Add|Update|Delete) File: ", patch, re.M))


def _parse_codex_patch(patch: str) -> list[dict]:
    files, cur, hunk = [], None, None
    for ln in patch.splitlines():
        if ln.startswith("*** Begin Patch") or ln.startswith("*** End of File"):
            continue
        if ln.startswith("*** End Patch"):
            break
        m = re.match(r"^\*\*\* (Add|Update|Delete) File: (.+?)\s*$", ln)
        if m:
            kind, path = m.group(1), m.group(2)
            cur = {"old": "/dev/null" if kind == "Add" else path, "new": "/dev/null" if kind == "Delete" else path, "hunks": []}
            files.append(cur)
            hunk = {"start": 0, "old": [], "new": [], "anchor": ""} if kind == "Add" else None
            if hunk:
                cur["hunks"].append(hunk)
            continue
        m = re.match(r"^\*\*\* Move to: (.+?)\s*$", ln)
        if m and cur is not None:
            cur["new"] = m.group(1)
            continue
        if cur is None:
            continue
        if ln.startswith("@@"):
            hunk = {"start": 0, "old": [], "new": [], "anchor": ln[2:].strip()}
            cur["hunks"].append(hunk)
            continue
        if hunk is None:                       # lignes avant le premier @@ : nouveau bloc implicite
            hunk = {"start": 0, "old": [], "new": [], "anchor": ""}
            cur["hunks"].append(hunk)
        tag, body = (ln[:1], ln[1:]) if ln else (" ", "")
        if tag == "+":
            hunk["new"].append(body)
        elif tag == "-":
            hunk["old"].append(body)
        else:
            body = body if tag == " " else ln
            hunk["old"].append(body)
            hunk["new"].append(body)
    return [f for f in files if f["hunks"] or f["new"] == "/dev/null"]


def _patch_files(patch: str, root: Path) -> list[Path]:
    files = []
    if _is_codex(patch):
        for m in CODEX_HDR.finditer(patch):
            f = (m.group(2) or m.group(3) or "").strip()
            if f:
                p = _rp(root, f)
                if p not in files:
                    files.append(p)
        return files
    for m in PATCH_FILE.finditer(patch):
        f = m.group(1)
        if f != "/dev/null":
            files.append(_rp(root, f))
    for m in PATCH_OLD.finditer(patch):
        f = m.group(1)
        if f != "/dev/null":
            p = _rp(root, f)
            if p not in files:
                files.append(p)
    return files


def _parse_patch(patch: str) -> list[dict]:
    """Découpe un unified diff en fichiers et blocs (tolérant aux défauts typiques des modèles IA)."""
    files, cur, hunk = [], None, None
    lines = patch.splitlines()
    for idx, ln in enumerate(lines):
        nxt = lines[idx + 1] if idx + 1 < len(lines) else ""
        if ln.startswith("--- ") and nxt.startswith("+++ "):        # en-tête de fichier
            old = ln[4:].split("\t")[0].strip()
            cur = {"old": old[2:] if old.startswith("a/") else old, "new": None, "hunks": [], "in_hunk": False}
            files.append(cur)
            hunk = None
            continue
        if ln.startswith("+++ ") and cur is not None and cur["new"] is None:
            new = ln[4:].split("\t")[0].strip()
            cur["new"] = new[2:] if new.startswith("b/") else new
            continue
        if ln.startswith("@@") and cur is not None:
            m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)", ln)
            hunk = {"start": int(m.group(1)) if m else 0, "old": [], "new": []}
            cur["hunks"].append(hunk)
            cur["in_hunk"] = True
            continue
        if hunk is None:
            continue
        if ln.startswith("\\"):
            continue
        tag, body = (ln[:1], ln[1:]) if ln else (" ", "")
        if tag == " ":
            hunk["old"].append(body)
            hunk["new"].append(body)
        elif tag == "-":
            hunk["old"].append(body)
        elif tag == "+":
            hunk["new"].append(body)
        else:                                   # ligne de contexte sans espace initial (fréquent)
            hunk["old"].append(ln)
            hunk["new"].append(ln)
    return files


def _find_block(lines: list[str], block: list[str], start: int, hint: int) -> int:
    if not block:
        return min(max(hint - 1, 0), len(lines))
    for norm in (lambda x: x, lambda x: x.rstrip(), lambda x: " ".join(x.split())):
        nb = [norm(b) for b in block]
        cands = [i for i in range(start, len(lines) - len(block) + 1) if [norm(x) for x in lines[i:i + len(block)]] == nb]
        if not cands:
            cands = [i for i in range(0, len(lines) - len(block) + 1) if [norm(x) for x in lines[i:i + len(block)]] == nb]
        if cands:
            return min(cands, key=lambda i: abs(i - (hint - 1)))
    return -1


def _nearest(lines: list[str], block: list[str], span: int = 12) -> str:
    """Passage du fichier qui ressemble le plus au bloc introuvable : le modèle corrige sans deviner le code."""
    import difflib
    keys = [b.strip() for b in block if b.strip()][:3]
    if not keys or not lines:
        return "(fichier vide)"
    best, score = 0, 0.0
    for idx, ln in enumerate(lines):
        s = max(difflib.SequenceMatcher(None, k, ln.strip()).ratio() for k in keys)
        if s > score:
            best, score = idx, s
    a, b = max(0, best - span // 2), min(len(lines), best + span)
    return "\n".join(f"{k + 1}: {lines[k]}" for k in range(a, b))


def _fuzzy_apply(patch: str, root: Path) -> str:
    """Application tolérante : retrouve chaque bloc par son contenu (numéros de ligne approximatifs acceptés)."""
    return _apply_parsed(_parse_codex_patch(patch) if _is_codex(patch) else _parse_patch(patch), root)


def _apply_parsed(parsed: list[dict], root: Path) -> str:
    plan = []
    for f in parsed:
        target = f["new"] if f["new"] and f["new"] != "/dev/null" else f["old"]
        path = _rp(root, target)
        if f["new"] == "/dev/null":
            return f"[erreur] suppression de fichier par patch non prise en charge ({target}) : utilise run_shell"
        if f["old"] == "/dev/null" or not path.exists():
            text = "\n".join(l for h in f["hunks"] for l in h["new"]) + "\n"
            plan.append((path, text))
            continue
        original = path.read_text()
        lines = original.splitlines()
        pos = 0
        for n, h in enumerate(f["hunks"], 1):
            if h.get("anchor"):                  # « @@ def main(): » : on cherche à partir de cette ligne
                a = next((k for k in range(len(lines)) if lines[k].strip() == h["anchor"].strip()), -1)
                if a >= 0:
                    pos = max(pos, a)
                    h["start"] = a + 1
            i = _find_block(lines, h["old"], pos, h["start"])
            if i < 0:
                preview = "\n".join(h["old"][:4])
                return (f"[erreur] bloc {n} introuvable dans {target} :\n{preview}\n"
                        f"Voici le passage RÉEL le plus proche (copie-le exactement dans ton patch) :\n{_nearest(lines, h['old'])}")
            lines[i:i + len(h["old"])] = h["new"]
            pos = i + len(h["new"])
        plan.append((path, "\n".join(lines) + ("\n" if original.endswith("\n") or not original else "")))
    if not plan:
        return "[erreur] aucun fichier dans le patch"
    for path, text in plan:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return f"Patch appliqué en mode tolérant ({len(plan)} fichier(s)) : " + ", ".join(str(p) for p, _ in plan[:8])


def _risk_patch(patch, cwd="", **k):
    root = P(cwd) if cwd else Ctx.workspace()
    files = _patch_files(patch, root)
    if not files:
        return BLOCKED, "aucun fichier dans le patch (formats acceptés : unified diff --- a/x / +++ b/x, ou *** Update File: x)"
    worst, why = SAFE, ""
    for f in files:
        lvl, w = security.path_level(f, True, Ctx.workspace())
        if lvl > worst:
            worst, why = lvl, f"{f.name} : {w}"
    return max(worst, NORMAL), why


@tool("apply_patch",
      "Applique un patch (unified diff comme `git diff`, ou format « *** Begin Patch / *** Update File: ») : idéal pour "
      "plusieurs modifications dans un ou plusieurs fichiers. Chemins relatifs à cwd. Les fichiers sont sauvegardés avant.",
      {"patch": S("Patch unified diff complet"), "cwd": S("Dossier racine du projet")}, ["patch"],
      category="write", risk=_risk_patch,
      summary=lambda patch, cwd="": f"patch sur {len(_patch_files(patch, P(cwd) if cwd else Ctx.workspace()))} fichier(s) dans {cwd or 'workspace'}")
def apply_patch(patch: str, cwd: str = ""):
    root = P(cwd) if cwd else Ctx.workspace()
    if not patch.endswith("\n"):
        patch += "\n"
    files = _patch_files(patch, root)
    locks = [path_lock(f) for f in files]
    for lk in locks:
        lk.acquire()
    try:
        for f in files:
            backup(f)
        if _is_codex(patch):
            return _fuzzy_apply(patch, root).replace("en mode tolérant", "(format *** Begin Patch)")
        tries = [["git", "apply", "--whitespace=nowarn", "--recount", "-"],
                 ["git", "apply", "--whitespace=nowarn", "--recount", "-p0", "-"],
                 ["patch", "-p1", "--forward", "--batch"], ["patch", "-p0", "--forward", "--batch"]]
        errors = []
        for argv in tries:
            chk = argv[:2] + ["--check"] + argv[2:] if argv[0] == "git" else argv[:1] + ["--dry-run"] + argv[1:]
            r = subprocess.run(chk, input=patch, cwd=str(root), capture_output=True, text=True, env=env())
            if r.returncode != 0 or "Skipped patch" in (r.stdout + r.stderr):
                errors.append((r.stdout + r.stderr).strip()[:400])
                continue
            r = subprocess.run(argv, input=patch, cwd=str(root), capture_output=True, text=True, env=env())
            if r.returncode == 0 and "Skipped patch" not in (r.stdout + r.stderr):
                return f"Patch appliqué ({len(files)} fichier(s)) : " + ", ".join(str(f) for f in files[:8])
            errors.append((r.stdout + r.stderr).strip()[:400])
        res = _fuzzy_apply(patch, root)
        if not res.startswith("[erreur]"):
            return res
        return res + "\n(git apply : " + " | ".join(e.splitlines()[0] for e in errors[:2] if e) + ")"
    finally:
        for lk in locks:
            lk.release()


# ====================================================================== code_map
SYM = {
    ".py": r"^\s*(?:async\s+)?(def|class)\s+([A-Za-z_]\w*)",
    ".swift": r"^\s*(?:public |private |internal |open |fileprivate |final |@\w+ )*(func|class|struct|enum|protocol|extension|actor)\s+([A-Za-z_]\w*)",
    ".js": r"^\s*(?:export\s+)?(?:default\s+)?(function|class|const|let)\s+([A-Za-z_$][\w$]*)",
    ".ts": r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?(function|class|interface|type|const|enum)\s+([A-Za-z_$][\w$]*)",
    ".cpp": r"^\s*(class|struct|namespace|enum)\s+([A-Za-z_]\w*)|^[\w:<>,\s*&]+?\s+([A-Za-z_][\w:]*)\s*\([^;]*\)\s*(?:const)?\s*\{?$",
    ".go": r"^\s*(func|type)\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)",
    ".rs": r"^\s*(?:pub(?:\(\w+\))?\s+)?(fn|struct|enum|trait|impl|mod)\s+([A-Za-z_]\w*)",
    ".kt": r"^\s*(?:\w+\s+)*(fun|class|object|interface)\s+([A-Za-z_]\w*)",
    ".java": r"^\s*(?:public|private|protected)?\s*(?:static\s+)?(class|interface|enum|record)\s+([A-Za-z_]\w*)",
    ".qml": r"^\s*(function|property\s+\w+|signal|id:)\s*([A-Za-z_]\w*)",
}
for ext, base in ((".jsx", ".js"), (".mjs", ".js"), (".tsx", ".ts"), (".hpp", ".cpp"), (".h", ".cpp"), (".cc", ".cpp"),
                  (".c", ".cpp"), (".m", ".cpp"), (".mm", ".cpp")):
    SYM[ext] = SYM[base]


def _iter_files(root: Path, exts: set | None = None, limit: int = 4000):
    n = 0
    stack = [root]
    while stack and n < limit:
        d = stack.pop()
        try:
            entries = sorted(d.iterdir())
        except (PermissionError, FileNotFoundError):
            continue
        for e in entries:
            if e.name in SKIP or e.name.startswith(".") and e.name not in (".github",):
                continue
            ext = e.suffix.lower()
            if e.is_dir() and exts is not None and ext in exts:      # document Pages/Keynote/Numbers (paquet)
                n += 1
                yield e
            elif e.is_dir():
                stack.append(e)
            elif e.is_file() and (exts is None or ext in exts) and \
                    e.stat().st_size < (40_000_000 if ext in DOC_EXT else 400_000):
                n += 1
                yield e


@tool("code_map", "Carte d'un projet : arborescence des fichiers source avec leurs classes/fonctions principales "
                  "et numéros de ligne. À utiliser en premier sur un projet inconnu ou volumineux.",
      {"path": S("Dossier du projet"), "max_files": I("Nb max de fichiers (défaut 150)")}, ["path"])
def code_map(path: str, max_files: int = 150):
    root = P(path)
    if not root.is_dir():
        return f"[erreur] dossier introuvable : {root}"
    out, count = [], 0
    for f in _iter_files(root, set(SYM)):
        if count >= (max_files or 150):
            out.append("… (limite atteinte : précise un sous-dossier)")
            break
        pat = re.compile(SYM[f.suffix.lower()])
        syms = []
        try:
            for i, ln in enumerate(f.read_text(errors="replace").splitlines(), 1):
                m = pat.match(ln)
                if m:
                    g = [x for x in m.groups() if x]
                    if g:
                        syms.append(f"{g[-1]}:{i}")
                if len(syms) >= 25:
                    syms.append("…")
                    break
        except OSError:
            continue
        rel = f.relative_to(root)
        out.append(f"{rel}  ({sum(1 for _ in open(f, errors='replace'))} l.)" + (f"\n    {', '.join(syms)}" if syms else ""))
        count += 1
    others = {}
    for f in _iter_files(root, None, 3000):
        if f.suffix.lower() not in SYM:
            others[f.suffix.lower() or f.name] = others.get(f.suffix.lower() or f.name, 0) + 1
    tail = ", ".join(f"{k}×{v}" for k, v in sorted(others.items(), key=lambda kv: -kv[1])[:15])
    return trunc(f"Projet {root} — {count} fichiers source\n" + "\n".join(out) + (f"\nAutres fichiers : {tail}" if tail else ""), 14000)


# ====================================================================== recherche sémantique
TEXT_EXT = set(SYM) | {".md", ".txt", ".html", ".css", ".scss", ".json", ".yaml", ".yml", ".toml", ".sh", ".sql",
                       ".gradle", ".xml", ".plist", ".rb", ".php", ".vue", ".svelte", ".dart", ".cmake", ".pro", ".ini"}
DOC_EXT = {".pdf", ".docx", ".pptx", ".xlsx", ".rtf", ".odt", ".doc", ".pages", ".key", ".numbers"}
_index_locks: dict[str, threading.Lock] = {}


def _doc_text(f: Path) -> str:
    """Texte d'un document (PDF, Word, PowerPoint, Excel, Pages…) pour l'index par le sens."""
    try:
        if f.stat().st_size > 40_000_000:
            return ""
        import files
        return (files.extract(f) or "")[:300_000]
    except Exception:
        return ""


def _db(root: Path) -> sqlite3.Connection:
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha1(str(root).encode()).hexdigest()[:16]
    con = sqlite3.connect(config.INDEX_DIR / f"{h}.sqlite", timeout=30)
    con.execute("CREATE TABLE IF NOT EXISTS chunks (path TEXT, mtime REAL, start INT, end INT, text TEXT, vec BLOB)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_path ON chunks(path)")
    return con


def _chunks(text: str, size: int = 50, overlap: int = 10):
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        seg = lines[i:i + size]
        if any(s.strip() for s in seg):
            yield i + 1, i + len(seg), "\n".join(seg)
        i += size - overlap


def index_folder(root: Path, progress=None) -> tuple[int, int]:
    import numpy as np
    lock = _index_locks.setdefault(str(root), threading.Lock())
    with lock:
        con = _db(root)
        known = {p: m for p, m in con.execute("SELECT path, MAX(mtime) FROM chunks GROUP BY path")}
        seen, todo = set(), []
        for f in _iter_files(root, TEXT_EXT | DOC_EXT, 3000):
            sp = str(f)
            seen.add(sp)
            mt = f.stat().st_mtime
            if known.get(sp) != mt:
                todo.append((f, mt))
        for gone in set(known) - seen:
            con.execute("DELETE FROM chunks WHERE path=?", (gone,))
        added = 0
        batch: list[tuple] = []

        def flush():
            nonlocal added
            if not batch:
                return
            vecs = Ctx.router.embed([f"search_document: {b[4][:2000]}" for b in batch])
            for b, v in zip(batch, vecs):
                con.execute("INSERT INTO chunks VALUES (?,?,?,?,?,?)", (*b[:5], np.asarray(v, dtype=np.float32).tobytes()))
            added += len(batch)
            batch.clear()
            if progress:
                progress(added)

        for f, mt in todo:
            con.execute("DELETE FROM chunks WHERE path=?", (str(f),))
            if f.suffix.lower() in DOC_EXT or (f.is_dir() and f.suffix.lower() in (".pages", ".key", ".numbers")):
                text = _doc_text(f)
            else:
                try:
                    text = f.read_text(errors="replace")
                except OSError:
                    continue
            rel = str(f.relative_to(root))
            for s, e, chunk in _chunks(text):
                batch.append((str(f), mt, s, e, f"{rel}\n{chunk}"))
                if len(batch) >= 32:
                    flush()
        flush()
        con.commit()
        total = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        con.close()
        return added, total


@tool("semantic_search",
      "Recherche par le SENS dans un projet ou un dossier de documents (modèle d'embeddings local). Ex : "
      "« où est gérée l'authentification Firebase ? ». L'index est construit puis mis à jour automatiquement.",
      {"query": S("Question / description de ce que tu cherches"), "path": S("Dossier"), "top_k": I("Résultats (défaut 8)")},
      ["query", "path"])
def semantic_search(query: str, path: str, top_k: int = 8):
    import numpy as np
    root = P(path)
    if not root.is_dir():
        return f"[erreur] dossier introuvable : {root}"
    if security.path_level(root, False, Ctx.workspace())[0] == BLOCKED:
        return "[erreur] dossier protégé"
    t0 = time.time()
    try:
        added, total = index_folder(root, progress=lambda n: Ctx.info(f"Indexation : {n} extraits…") if n % 320 == 0 else None)
    except Exception as e:
        return f"[erreur] indexation impossible ({e}). Le modèle d'embeddings est-il installé ? `ollama pull {Ctx.cfg.get('embed_model')}`"
    hits = search_index([root], query, top_k or 8)
    if not hits:
        return "Aucun fichier indexable dans ce dossier."
    out = [f"(index : {total} extraits, {added} mis à jour, {time.time() - t0:.1f}s)"]
    for score, pth, s, e, body in hits:
        out.append(f"── {Path(pth).relative_to(root)} l.{s}-{e}  (score {score:.2f})\n{body[:900]}")
    return trunc("\n".join(out), 14000)


def search_index(roots: list[Path], query: str, top_k: int = 8) -> list[tuple]:
    """Meilleurs extraits (score, chemin, début, fin, texte) dans les index déjà construits de ces dossiers."""
    import numpy as np
    rows = []
    for root in roots:
        try:
            con = _db(root)
            rows += con.execute("SELECT path, start, end, text, vec FROM chunks").fetchall()
            con.close()
        except sqlite3.Error:
            pass
    if not rows:
        return []
    q = np.asarray(Ctx.router.embed([f"search_query: {query}"])[0], dtype=np.float32)
    q /= (np.linalg.norm(q) + 1e-9)
    mat = np.stack([np.frombuffer(r[4], dtype=np.float32) for r in rows])
    mat /= (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9)
    scores = mat @ q
    out, seen_files = [], {}
    for i in np.argsort(-scores):
        pth, s, e, text, _ = rows[i]
        if seen_files.get(pth, 0) >= 2:            # variété : au plus 2 extraits par fichier
            continue
        seen_files[pth] = seen_files.get(pth, 0) + 1
        body = text.split("\n", 1)[1] if "\n" in text else text
        out.append((float(scores[i]), pth, s, e, body))
        if len(out) >= top_k:
            break
    return out


# ====================================================================== simulateur iOS
@tool("run_on_simulator",
      "Compile une app iOS (projet Xcode) pour le simulateur, l'installe, la lance et décrit l'écran (modèle vision). "
      "Permet de vérifier visuellement le résultat.",
      {"path": S("Dossier du projet Xcode"), "scheme": S("Schéma"), "device": S("Nom du simulateur (défaut : iPhone le plus récent)"),
       "question": S("Ce qu'il faut vérifier à l'écran")}, ["path"], category="shell",
      risk=lambda **k: (NORMAL, ""))
def run_on_simulator(path: str, scheme: str = "", device: str = "", question: str = "Décris l'écran de l'app."):
    root = P(path)
    ws, proj = list(root.glob("*.xcworkspace")), list(root.glob("*.xcodeproj"))
    if not (ws or proj):
        return "[erreur] pas de projet Xcode ici"
    flag = f'-workspace "{ws[0]}"' if ws else f'-project "{proj[0]}"'
    if not scheme:
        m = re.search(r'"schemes"\s*:\s*\[\s*"([^"]+)"', sh(f"xcodebuild {flag} -list -json", root, 180))
        if not m:
            return "[erreur] schéma introuvable"
        scheme = m.group(1)
    devs = json.loads(subprocess.run(["xcrun", "simctl", "list", "devices", "available", "-j"], capture_output=True,
                                     text=True, env=env()).stdout or "{}").get("devices", {})
    cands = [(rt, d) for rt, ds in devs.items() if "iOS" in rt for d in ds]
    if not cands:
        return "[erreur] aucun simulateur iOS installé (Xcode › Settings › Components)"
    pick = next(((rt, d) for rt, d in cands if device and device.lower() in d["name"].lower()), None) or \
        sorted([c for c in cands if "iPhone" in c[1]["name"]] or cands, key=lambda c: c[0])[-1]
    udid, name = pick[1]["udid"], pick[1]["name"]
    out = sh(f"set -o pipefail; xcodebuild {flag} -scheme '{scheme}' -destination 'id={udid}' -derivedDataPath build/jarvis-sim "
             f"build 2>&1 | grep -E 'error:|BUILD' | tail -40", root, 3600)
    if "BUILD SUCCEEDED" not in out:
        return f"[erreur] compilation échouée :\n{out}"
    apps = sorted((root / "build/jarvis-sim/Build/Products").glob("*-iphonesimulator/*.app"))
    if not apps:
        return "[erreur] .app introuvable après compilation"
    app = apps[-1]
    bundle = subprocess.run(["/usr/libexec/PlistBuddy", "-c", "Print :CFBundleIdentifier", str(app / "Info.plist")],
                            capture_output=True, text=True).stdout.strip()
    for cmd in (["xcrun", "simctl", "boot", udid], ["open", "-a", "Simulator"], ["xcrun", "simctl", "bootstatus", udid, "-b"],
                ["xcrun", "simctl", "install", udid, str(app)], ["xcrun", "simctl", "launch", udid, bundle]):
        subprocess.run(cmd, capture_output=True, text=True, env=env(), timeout=300)
    time.sleep(4)
    shot = config.SCREENS_DIR / f"sim_{int(time.time())}.png"
    subprocess.run(["xcrun", "simctl", "io", udid, "screenshot", str(shot)], capture_output=True, env=env())
    res = f"App {bundle} lancée sur {name}. Capture : {shot}"
    vb = Ctx.router.vision_backend if Ctx.router else None
    if vb and shot.exists():
        res += "\n" + vb.vision(question or "Décris l'écran de l'app, les éléments visibles et les éventuels problèmes d'affichage.", str(shot))
    return res
