"""Outils locaux : shell (bac à sable), fichiers, macOS, interface graphique, compilation, Git/GitHub/Firebase, web."""
from __future__ import annotations

import datetime
import functools
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

import config
import sandbox
import security
from registry import B, I, P, S, Ctx, GuiOwner, backup, path_lock, tool, trunc
from security import BLOCKED, NORMAL, RISKY, SAFE

HOME = config.HOME
BG: dict[str, subprocess.Popen] = {}
_bg_lock = threading.Lock()
NET_ERR = re.compile(r"(Could not resolve host|ENOTFOUND|EAI_AGAIN|getaddrinfo|nodename nor servname|Network is unreachable|"
                     r"Temporary failure in name resolution|Failed to establish a new connection|connect ECONNREFUSED [^1])", re.I)


def env() -> dict:
    e = os.environ.copy()
    e["PATH"] = f"/opt/homebrew/bin:/opt/homebrew/sbin:{HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    dev = Path(Ctx.cfg.get("dev_venv") or config.DEFAULTS["dev_venv"]).expanduser()
    if (dev / "bin" / "python").exists():        # python, pip, pytest de l'agent en priorité
        e["PATH"] = f"{dev / 'bin'}:" + e["PATH"]
        e["VIRTUAL_ENV"] = str(dev)
    e.pop("PYTHONHOME", None)
    e["GIT_TERMINAL_PROMPT"] = "0"
    e.setdefault("LANG", "fr_FR.UTF-8")
    e["NO_COLOR"] = "1"
    e["CI"] = e.get("CI", "1")            # outils non interactifs
    return e


def _ws() -> Path:
    return Ctx.workspace()


def _shell_argv(cmd: str) -> list[str]:
    return ["/bin/zsh", "-c", cmd] if Path("/bin/zsh").exists() else ["/bin/sh", "-c", cmd]


def not_found(p: Path) -> str:
    """Fichier introuvable : on montre ce qui existe à côté (et le nom le plus proche) pour que le modèle se corrige."""
    import difflib
    msg = f"[erreur] introuvable : {p}"
    d = p.parent
    while not d.exists() and d != d.parent:
        d = d.parent
    try:
        names = sorted(x.name + ("/" if x.is_dir() else "") for x in d.iterdir() if not x.name.startswith("."))
    except OSError:
        return msg
    close = difflib.get_close_matches(p.name, names, n=2, cutoff=0.4)
    msg += f"\nContenu de {d} : {', '.join(names[:40]) or '(vide)'}"
    if close:
        msg += f"\nNom le plus proche : {close[0]} — utilise le nom EXACT du fichier."
    return msg


def sh(cmd: str, cwd: Path | None = None, timeout: int | None = None, sandboxed: bool = True,
       network: bool | None = None) -> str:
    """Exécute une commande. Par défaut dans le bac à sable ; réseau coupé si la tâche est contaminée."""
    cwd = cwd or _ws()
    timeout = timeout or Ctx.cfg.get("tool_timeout", 900)
    tainted = Ctx.policy.tainted
    net = (not tainted) if network is None else network
    argv = _shell_argv(cmd)
    boxed = False
    if sandboxed:
        argv, boxed = sandbox.wrap(argv, cwd, Ctx.cfg, network=net, tainted=tainted)
    try:
        r = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, env=env(),
                           stdin=subprocess.DEVNULL)
        out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if (r.stderr or "").strip() else "")
        res = f"[code retour {r.returncode}]\n{out.strip()}"
        if boxed and r.returncode != 0:
            if "Operation not permitted" in out or "deny(" in out or "sandbox" in out.lower():
                res += sandbox.SANDBOX_HINT
            if not net and NET_ERR.search(out):
                res += sandbox.NETWORK_HINT
        return trunc(res) + (_failure_hint(out, cwd) if r.returncode != 0 else "")
    except subprocess.TimeoutExpired:
        return f"[erreur] délai dépassé ({timeout}s). Pour un serveur ou une tâche très longue, utilise start_background."
    except FileNotFoundError as e:
        return f"[erreur] dossier ou programme introuvable : {e}"


_NOT_FOUND = re.compile(r"file or directory not found|No such file or directory|can't open file|not found: ", re.I)
_IMPORT_ERR = re.compile(r"ModuleNotFoundError|ImportError|is not a package|No module named", re.I)


def _failure_hint(out: str, cwd: Path) -> str:
    """Après un échec : rappelle où la commande a tourné et oriente vers la cause la plus fréquente (chemin, import)."""
    hint = f"\n[aide] commande lancée dans : {cwd}"
    if _NOT_FOUND.search(out):
        try:
            names = sorted(p.name + ("/" if p.is_dir() else "") for p in Path(cwd).iterdir() if not p.name.startswith("."))
            hint += f"\n[aide] chemins relatifs à ce dossier, qui contient : {', '.join(names[:30]) or '(vide)'}"
        except OSError:
            pass
    if _IMPORT_ERR.search(out) and "pytest" in out.lower():
        hint += ("\n[aide] import en échec : un test placé à côté de son module l'importe par le NOM DU FICHIER "
                 "(`from calc import moyenne` pour calc.py), puis `python -m pytest -q` depuis ce dossier.")
    return hint


# ====================================================================== SHELL
def _risk_shell(command, cwd="", timeout=0, network=False):
    lvl, why = security.shell_level(command)
    if lvl in (SAFE, BLOCKED):
        return lvl, why
    if Ctx.policy.tainted:
        boxed = Ctx.cfg.get("sandbox", True) and sandbox.available()
        if network or not boxed:
            return RISKY, (why + " — " if why else "") + "après lecture de contenu externe" + (" avec Internet" if network else " sans bac à sable")
    return lvl, why


@tool("run_shell",
      "Exécute une commande zsh dans le bac à sable (npm, python, swift, cmake, tests…). L'écriture est limitée à "
      "l'espace de travail, aux dossiers projets et au dossier courant. Pour git push/gh/firebase/ssh, utilise les "
      "outils dédiés. Un serveur qui ne s'arrête pas → start_background.",
      {"command": S("Commande complète"), "cwd": S("Dossier (défaut : espace de travail)"),
       "timeout": I("Délai max (s)"), "network": B("Forcer l'accès Internet (seulement si nécessaire)")}, ["command"],
      category="shell", risk=_risk_shell, summary=lambda command, **k: f"$ {command}")
def run_shell(command: str, cwd: str = "", timeout: int = 0, network: bool = False):
    return sh(command, P(cwd) if cwd else None, timeout or None, network=True if network else None)


def _bg_key(name: str) -> str:
    return f"{Ctx.task_id or 'cli'}:{name}"


def _bg_log(name: str) -> Path:
    return config.LOG_DIR / f"bg-{re.sub(r'[^A-Za-z0-9_-]', '_', _bg_key(name))}.log"


@tool("start_background", "Lance une commande longue en arrière-plan dans le bac à sable (serveur de dev…).",
      {"command": S("Commande"), "name": S("Nom court"), "cwd": S("Dossier"), "network": B("Accès Internet")},
      ["command", "name"], category="shell", risk=lambda command, name="", cwd="", network=False: _risk_shell(command, network=network),
      summary=lambda command, name, **k: f"[fond : {name}] $ {command}")
def start_background(command: str, name: str, cwd: str = "", network: bool = False):
    stop_background(name)
    log = _bg_log(name)
    log.parent.mkdir(parents=True, exist_ok=True)
    wd = P(cwd) if cwd else _ws()
    tainted = Ctx.policy.tainted
    argv, _ = sandbox.wrap(_shell_argv(command), wd, Ctx.cfg, network=bool(network) or not tainted, tainted=tainted)
    proc = subprocess.Popen(argv, cwd=str(wd), stdout=open(log, "w"), stderr=subprocess.STDOUT, env=env(),
                            start_new_session=True, stdin=subprocess.DEVNULL)
    with _bg_lock:
        BG[_bg_key(name)] = proc
    time.sleep(3)
    head = log.read_text(errors="replace")[-1500:] if log.exists() else ""
    state = "en cours" if proc.poll() is None else f"terminé (code {proc.returncode})"
    return f"Processus « {name} » PID {proc.pid} — {state}.\n{head}"


@tool("stop_background", "Arrête un processus lancé avec start_background.", {"name": S("Nom")},
      category="shell", risk=lambda name: (SAFE, ""))
def stop_background(name: str):
    with _bg_lock:
        p = BG.pop(_bg_key(name), None)
    if not p:
        return f"Aucun processus « {name} »."
    try:
        os.killpg(os.getpgid(p.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    return f"Arrêté : {name}"


def stop_all_background(task_id: str):
    with _bg_lock:
        keys = [k for k in BG if k.startswith(f"{task_id}:")]
        procs = [BG.pop(k) for k in keys]
    for p in procs:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass


@tool("read_log", "Lit la fin du log d'un processus d'arrière-plan.", {"name": S("Nom"), "lines": I("Lignes")}, ["name"])
def read_log(name: str, lines: int = 80):
    log = _bg_log(name)
    if not log.exists():
        return f"[erreur] pas de log pour {name}"
    p = BG.get(_bg_key(name))
    state = "" if not p else (" (en cours)" if p.poll() is None else f" (terminé, code {p.returncode})")
    return f"[{name}{state}]\n" + "\n".join(log.read_text(errors="replace").splitlines()[-int(lines or 80):])


# ====================================================================== FICHIERS
UNTRUSTED_DIRS = [HOME / "Downloads", HOME / "Library" / "Mail", HOME / "Library" / "Containers" / "com.apple.mail"]


def read_any(p: Path) -> str:
    import files
    return files.extract(p)


@tool("read_file", "Lit le CONTENU d'un fichier : texte, code, PDF (OCR auto des scans), Word, Excel (.xlsx/.xls/.csv), "
                   "PowerPoint, images (OCR), e-mails, archives, Keynote/Pages/Numbers, Pixelmator/Photoshop (aperçu + OCR)… "
                   "Option : plage de lignes. Pour l'aspect visuel : analyze_file.",
      {"path": S("Chemin"), "start_line": I("1re ligne"), "end_line": I("Dernière ligne")},
      ["path"], category="read", risk=lambda path, **k: security.path_level(P(path), False, _ws()))
def read_file(path: str, start_line: int = 0, end_line: int = 0):
    p = P(path)
    if not p.exists():
        return not_found(p)
    if p.is_dir():
        return list_dir(str(p))
    text = read_any(p)
    if start_line or end_line:
        lines = text.splitlines()
        s, e = max(1, start_line or 1), min(len(lines), end_line or len(lines))
        text = "\n".join(f"{i}: {lines[i - 1]}" for i in range(s, e + 1))
    import files
    if files.is_untrusted(p):
        Ctx.policy.taint(f"fichier externe {p.name}")
        return security.wrap_untrusted(str(p), trunc(text, 20000))
    return trunc(text, 20000)


def _risk_write(path, **k):
    return security.path_level(P(path), True, _ws())


@tool("write_file", "Crée ou remplace entièrement un fichier. Crée les dossiers. L'ancienne version est sauvegardée.",
      {"path": S("Chemin"), "content": S("Contenu complet")}, category="write", risk=_risk_write,
      summary=lambda path, content: f"écrire {P(path)} ({len(content.splitlines())} lignes)")
def write_file(path: str, content: str):
    p = P(path)
    with path_lock(p):
        backup(p)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return f"Écrit : {p} ({len(content.splitlines())} lignes)"


@tool("edit_file",
      "Remplace un passage EXACT d'un fichier (espaces et indentation compris). Le passage doit être unique : "
      "ajoute du contexte, ou replace_all=true. Pour plusieurs modifications, préfère apply_patch.",
      {"path": S("Chemin"), "old": S("Texte exact à remplacer"), "new": S("Nouveau texte"), "replace_all": B("Tout remplacer")},
      ["path", "old", "new"], category="write", risk=_risk_write, summary=lambda path, **k: f"modifier {P(path)}")
def edit_file(path: str, old: str, new: str, replace_all: bool = False):
    p = P(path)
    if not p.exists():
        return not_found(p)
    with path_lock(p):
        txt = p.read_text()
        n = txt.count(old)
        if n == 0:
            stripped = old.strip()
            if stripped and txt.count(stripped) == 1:          # tolérance : espaces de début/fin
                old, n = stripped, 1
                new = new.strip()
            else:
                # on renvoie directement le contenu actuel : le modèle peut corriger sans étape « read_file » en plus
                lines = txt.splitlines()
                first = stripped.splitlines()[0].strip() if stripped else ""
                center = next((i for i, ln in enumerate(lines) if first and first[:30] in ln), 0)
                a = max(0, center - 40) if len(lines) > 120 else 0
                b = min(len(lines), a + 120)
                view = "\n".join(f"{i + 1}: {lines[i]}" for i in range(a, b))
                more = f"\n… ({len(lines)} lignes au total)" if len(lines) > b - a else ""
                return ("[erreur] passage introuvable : le texte « old » doit être copié EXACTEMENT. Contenu actuel du fichier "
                        f"(lignes {a + 1}-{b}) — refais edit_file avec un passage exact de ce contenu :\n{view}{more}")
        if n > 1 and not replace_all:
            return f"[erreur] passage présent {n} fois : ajoute du contexte ou replace_all=true."
        backup(p)
        p.write_text(txt.replace(old, new) if replace_all else txt.replace(old, new, 1))
    return f"Modifié : {p} ({n if replace_all else 1} remplacement)"


SKIP = {"node_modules", ".git", "venv", ".venv", "__pycache__", "DerivedData", ".build", "Pods", "dist", ".next",
        "build", ".gradle", "target", ".dart_tool", ".idea", ".turbo", ".cache", "coverage"}


@tool("list_dir", "Liste un dossier (2 niveaux, ignore node_modules/.git/build…).", {"path": S("Dossier")}, [])
def list_dir(path: str = ""):
    root = P(path) if path else _ws()
    if not root.exists():
        return f"[erreur] introuvable : {root}"
    out = []
    for item in sorted(root.iterdir()):
        if item.name in SKIP or item.name == ".DS_Store":
            continue
        out.append(("📁 " if item.is_dir() else "📄 ") + item.name)
        if item.is_dir():
            try:
                subs = [s for s in sorted(item.iterdir()) if s.name not in SKIP and s.name != ".DS_Store"]
                out += ["   " + ("📁 " if s.is_dir() else "📄 ") + s.name for s in subs[:25]]
                if len(subs) > 25:
                    out.append(f"   … +{len(subs) - 25}")
            except PermissionError:
                out.append("   (accès refusé)")
    return trunc(f"{root}\n" + "\n".join(out))


@tool("search_files", "Cherche un texte/regex dans les fichiers d'un dossier (ripgrep), ou dans les NOMS de fichiers.",
      {"pattern": S("Texte ou regex"), "path": S("Dossier"), "names_only": B("Chercher dans les noms")}, ["pattern"])
def search_files(pattern: str, path: str = "", names_only: bool = False):
    root = P(path) if path else _ws()
    q, r = shlex.quote(pattern), shlex.quote(str(root))
    if names_only:
        return sh(f"find {r} -iname {shlex.quote('*' + pattern + '*')} -not -path '*/node_modules/*' -not -path '*/.git/*' | head -100",
                  sandboxed=False, timeout=60)
    if shutil.which("rg", path=env()["PATH"]):
        return sh(f"rg -n --max-count 6 --max-columns 220 -S -e {q} {r} | head -160", sandboxed=False, timeout=60)
    return sh(f"grep -rIn --exclude-dir=node_modules --exclude-dir=.git -e {q} {r} | head -160", sandboxed=False, timeout=60)


# ====================================================================== macOS
def _risk_as(script: str):
    if re.search(r"do shell script", script, re.I):
        lvl = security.shell_level(script)[0]
        return (BLOCKED if lvl == BLOCKED else RISKY), "AppleScript lançant une commande shell"
    if re.search(r"\b(delete|empty trash|send|shut down|restart|log out|keystroke|key code|password)\b", script, re.I):
        return RISKY, "AppleScript : envoi / suppression / frappe clavier"
    return NORMAL, ""


@tool("applescript",
      "Exécute un AppleScript pour piloter les apps macOS : Mail, Calendrier, Rappels, Notes, Contacts, Finder, Safari, "
      "Musique, Messages, fenêtres, volume… (à préférer à la souris).",
      {"script": S("Code AppleScript")}, category="exec", risk=_risk_as, summary=lambda script: "AppleScript :\n" + script[:700])
def applescript(script: str):
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=180)
    out = (r.stdout + r.stderr).strip() or "OK"
    if re.search(r'application "(Mail|Messages|Safari|Notes|Google Chrome|Microsoft Outlook)"', script):
        Ctx.policy.taint("contenu d'application (mail/web/notes)")
        return security.wrap_untrusted("applescript", out)
    return out


@tool("open_app", "Ouvre une application, un fichier ou une URL (navigateur par défaut).",
      {"target": S("Nom d'app, chemin ou URL")}, category="gui", risk=lambda target: (NORMAL, ""))
def open_app(target: str):
    if target.startswith(("http://", "https://")):
        cmd = ["open", target]
    elif P(target).exists():
        cmd = ["open", str(P(target))]
    else:
        cmd = ["open", "-a", target]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stderr.strip() or f"Ouvert : {target}"


@tool("open_in_editor", "Ouvre un fichier/dossier/projet dans VS Code (option : ligne) ou Xcode.",
      {"path": S("Chemin"), "editor": S("vscode | xcode", enum=["vscode", "xcode"]), "line": I("Ligne")},
      ["path"], category="gui", risk=lambda **k: (NORMAL, ""))
def open_in_editor(path: str, editor: str = "vscode", line: int = 0):
    p = P(path)
    if editor == "xcode":
        r = subprocess.run(["open", "-a", "Xcode", str(p)], capture_output=True, text=True)
    else:
        code = shutil.which("code", path=env()["PATH"])
        target = f"{p}:{line}" if line else str(p)
        r = subprocess.run([code, "-g", target] if code else ["open", "-a", "Visual Studio Code", str(p)],
                           capture_output=True, text=True)
    return r.stderr.strip() or f"Ouvert dans {editor} : {p}"


@tool("notify", "Affiche une notification macOS.", {"title": S("Titre"), "message": S("Message")}, category="meta")
def notify(title: str, message: str):
    t, m = title.replace('"', "'")[:80], message.replace('"', "'").replace("\n", " ")[:240]
    subprocess.run(["osascript", "-e", f'display notification "{m}" with title "{t}"'], capture_output=True)
    return "Notification affichée"


@tool("clipboard", "Lit ou écrit le presse-papiers.", {"action": S("get | set", enum=["get", "set"]), "text": S("Texte (set)")},
      ["action"], category="gui", risk=lambda action, **k: (NORMAL, ""))
def clipboard(action: str, text: str = ""):
    if action == "set":
        subprocess.run("pbcopy", input=text, text=True)
        return "Copié."
    Ctx.policy.taint("presse-papiers")
    return security.wrap_untrusted("presse-papiers", subprocess.run("pbpaste", capture_output=True, text=True).stdout)


# ====================================================================== ÉCRAN / GUI (une tâche à la fois)
def _need_gui():
    if not GuiOwner.acquire(Ctx.task_id or "cli"):
        raise RuntimeError("l'écran est utilisé par une autre tâche ; réessaie dans un moment ou utilise une autre méthode")


def screenshot() -> Path:
    import pyautogui
    from PIL import Image
    p = config.SCREENS_DIR / f"screen_{datetime.datetime.now():%H%M%S%f}.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["screencapture", "-x", str(p)], check=True)
    w, h = pyautogui.size()
    img = Image.open(p)
    if img.size != (w, h):
        img.resize((w, h)).save(p)
    for old in sorted(config.SCREENS_DIR.glob("screen_*.png"))[:-30]:
        old.unlink(missing_ok=True)
    return p


@tool("look_at_screen",
      "Capture l'écran et le fait décrire par le modèle vision local. Question précise, ex : « où est le bouton Build ? "
      "donne x,y ».", {"question": S("Question sur l'écran")}, category="gui", risk=lambda question: (SAFE, ""))
def look_at_screen(question: str):
    _need_gui()
    try:
        p = screenshot()
    except Exception as e:
        return f"[erreur] capture impossible ({e}) : Réglages › Confidentialité › Enregistrement de l'écran → autorise Jarvis/Terminal."
    vb = Ctx.router.vision_backend if Ctx.router else None
    if not vb:
        return f"Capture : {p}. Pas de modèle vision installé."
    import pyautogui
    w, h = pyautogui.size()
    ans = vb.vision(f"Capture d'écran macOS de {w}x{h} points. {question} "
                    f"Si tu donnes une position, utilise des coordonnées x,y dans ce repère.", str(p))
    Ctx.policy.taint("écran")
    return security.wrap_untrusted("écran", ans)


def _gui():
    _need_gui()
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.15
    return pyautogui


@tool("mouse_click", "Clique à (x,y) en points écran.",
      {"x": I("x"), "y": I("y"), "button": S("left|right", enum=["left", "right"]), "clicks": I("1 ou 2")},
      ["x", "y"], category="gui", summary=lambda x, y, **k: f"clic en ({x},{y})")
def mouse_click(x: int, y: int, button: str = "left", clicks: int = 1):
    g = _gui()
    w, h = g.size()
    if not (0 <= x < w and 0 <= y < h):
        return f"[erreur] coordonnées hors écran ({w}x{h})"
    g.click(x, y, clicks=clicks or 1, button=button or "left", interval=0.1)
    return f"Clic {button or 'left'} x{clicks or 1} en ({x},{y})"


def _risk_type(text):
    if Ctx.policy.tainted and len(text) > 200:
        return RISKY, "saisie d'un long texte après lecture de contenu externe"
    return NORMAL, ""


@tool("type_text", "Tape du texte dans l'app active (accents OK).", {"text": S("Texte")}, category="gui",
      risk=_risk_type, summary=lambda text: f"taper : {text[:160]}")
def type_text(text: str):
    g = _gui()
    old = subprocess.run("pbpaste", capture_output=True, text=True).stdout
    subprocess.run("pbcopy", input=text, text=True)
    g.hotkey("command", "v")
    time.sleep(0.35)
    subprocess.run("pbcopy", input=old, text=True)
    return f"Tapé {len(text)} caractères"


@tool("press_keys", "Touche ou raccourci clavier, ex : [\"command\",\"s\"], [\"enter\"].",
      {"keys": {"type": "array", "items": {"type": "string"}, "description": "Touches"}}, category="gui",
      risk=lambda keys: (RISKY, "raccourci système") if {"command", "q"} <= {k.lower() for k in keys} or
      {"command", "option", "esc"} <= {k.lower() for k in keys} else (NORMAL, ""))
def press_keys(keys: list):
    _gui().hotkey(*[str(k).lower() for k in keys])
    return f"Touches : {'+'.join(keys)}"


# ====================================================================== COMPILATION
def _xcode(root: Path, action: str, scheme: str) -> str:
    ws, proj = list(root.glob("*.xcworkspace")), list(root.glob("*.xcodeproj"))
    flag = f'-workspace "{ws[0]}"' if ws else f'-project "{proj[0]}"'
    if not scheme:
        lst = sh(f"xcodebuild {flag} -list -json", root, 180)
        m = re.search(r'"schemes"\s*:\s*\[\s*"([^"]+)"', lst)
        if not m:
            return "Schéma introuvable :\n" + lst
        scheme = m.group(1)
    sdk = sh(f"xcodebuild {flag} -scheme '{scheme}' -showBuildSettings 2>/dev/null | grep -m1 ' SDKROOT'", root, 180)
    dest = ""
    if "iphoneos" in sdk:
        dest = "-destination 'generic/platform=iOS Simulator'" if action == "build" else \
               "-destination 'platform=iOS Simulator,name=iPhone 17'"
    pretty = "| xcbeautify --quieter --disable-colored-output" if shutil.which("xcbeautify", path=env()["PATH"]) else \
             "| grep -E 'error:|warning: |BUILD|TEST|Test Suite|\\*\\*|failed|passed'"
    cmd = (f"set -o pipefail; xcodebuild {flag} -scheme '{scheme}' {dest} -derivedDataPath build/jarvis "
           f"CODE_SIGNING_ALLOWED=NO {action} 2>&1 {pretty} | tail -150")
    out = sh(cmd, root, 3600)
    return f"[Xcode · schéma {scheme}]\n{out}"


@tool("build_project",
      "Compile ou teste un projet (détection automatique) : Xcode, Swift Package, Node, CMake/Qt, Python, Rust, Go. "
      "Renvoie les erreurs filtrées. Tourne dans le bac à sable.",
      {"path": S("Dossier du projet"), "action": S("build | test", enum=["build", "test"]), "scheme": S("Schéma Xcode")},
      ["path"], category="shell", risk=lambda path, **k: _risk_shell("make", network=False))
def build_project(path: str, action: str = "build", scheme: str = ""):
    root = P(path)
    if not root.exists():
        return f"[erreur] introuvable : {root}"
    action = action or "build"
    if list(root.glob("*.xcworkspace")) or list(root.glob("*.xcodeproj")):
        return _xcode(root, action, scheme)
    if (root / "Package.swift").exists():
        return sh(f"swift {action} 2>&1 | tail -120", root, 3600)
    if (root / "package.json").exists():
        pkg = json.loads((root / "package.json").read_text())
        scripts = pkg.get("scripts", {})
        inst = "" if (root / "node_modules").exists() else "npm install --no-audit --no-fund && "
        script = "test" if action == "test" else ("build" if "build" in scripts else None)
        if not script or script not in scripts:
            return sh(f"{inst}echo 'Dépendances OK — scripts disponibles : {', '.join(scripts) or 'aucun'}'", root, 1800)
        return sh(f"{inst}npm run {script} 2>&1 | tail -120", root, 3600)
    if (root / "CMakeLists.txt").exists():
        prefix = ""
        qt = sorted(Path("/opt/homebrew/opt").glob("qt*")) if Path("/opt/homebrew/opt").exists() else []
        if qt:
            prefix = f"-DCMAKE_PREFIX_PATH={qt[-1]}"
        return sh(f"cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug {prefix} 2>&1 | tail -30 && cmake --build build -j 2>&1 | "
                  f"grep -E 'error|warning|Built target|\\[100%\\]' | tail -100"
                  + (" && ctest --test-dir build --output-on-failure | tail -80" if action == "test" else ""), root, 3600)
    if (root / "Cargo.toml").exists():
        return sh(f"cargo {action} 2>&1 | tail -120", root, 3600)
    if (root / "go.mod").exists():
        return sh(f"go {action} ./... 2>&1 | tail -120", root, 3600)
    if list(root.glob("*.py")) or (root / "pyproject.toml").exists():
        return sh("python3 -m pytest -q 2>&1 | tail -80" if action == "test" else
                  "python3 -m compileall -q . && echo 'Compilation Python OK'", root, 1800)
    if (root / "index.html").exists():
        return "Site statique : pas de compilation. Teste-le avec start_background `python3 -m http.server 8080` puis browser_open."
    return "Type de projet non reconnu."


# ====================================================================== GIT / GITHUB / FIREBASE (hors bac à sable)
@functools.lru_cache(maxsize=1)
def gh_login() -> str:
    try:
        r = subprocess.run(["gh", "api", "user", "--jq", ".login"], capture_output=True, text=True, timeout=15, env=env())
        return r.stdout.strip().lower()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _taint_if_foreign_clone(args: str):
    """Un dépôt cloné qui n'appartient pas à l'utilisateur est du contenu externe (README piégé possible)."""
    m = re.search(r"\bclone\s+(\S+)", args)
    if not m:
        return
    target = m.group(1)
    owner = ""
    mm = re.search(r"github\.com[:/]([^/]+)/", target) or re.match(r"^([A-Za-z0-9_.-]+)/[A-Za-z0-9_.-]+$", target)
    if mm:
        owner = mm.group(1).lower()
    if not owner or owner != gh_login():
        Ctx.policy.taint(f"dépôt externe {target[:60]}")


def _risk_cli(prefix):
    def r(args, **k):
        return security.shell_level(f"{prefix} {args}")
    return r


@tool("git", "Git avec tes identifiants : 'status', 'pull', 'add -A', 'commit -m \"msg\"', 'push', 'checkout -b jarvis/x'…",
      {"args": S("Arguments git"), "repo": S("Dossier du dépôt")}, category="exec", risk=_risk_cli("git"),
      summary=lambda args, repo: f"git {args}   (dans {repo})")
def git(args: str, repo: str):
    out = sh(f"git {args}", P(repo), 900, sandboxed=False)
    _taint_if_foreign_clone(args)
    return out


@tool("github",
      "GitHub CLI (gh, connecté) : 'repo clone user/projet', 'repo create nom --private --source=. --push', "
      "'pr create --fill', 'issue list', 'run list'…",
      {"args": S("Arguments gh"), "cwd": S("Dossier")}, ["args"], category="exec",
      risk=lambda args, **k: (RISKY, "création/publication sur GitHub") if re.search(r"repo create|pr merge|release|gist create", args)
      else security.shell_level(f"gh {args}"), summary=lambda args, **k: f"gh {args}")
def github(args: str, cwd: str = ""):
    out = sh(f"gh {args}", P(cwd) if cwd else None, 900, sandboxed=False)
    _taint_if_foreign_clone(args)
    return out


@tool("firebase", "Firebase CLI (plan Spark gratuit) : 'projects:list', 'deploy --only hosting', 'emulators:start'… "
                  "Ajoute --non-interactive si possible.",
      {"args": S("Arguments"), "cwd": S("Dossier du projet")}, category="exec", risk=_risk_cli("firebase"),
      summary=lambda args, cwd: f"firebase {args}   (dans {cwd})")
def firebase(args: str, cwd: str):
    return sh(f"firebase {args}", P(cwd), 1800, sandboxed=False)


@tool("deploy_website",
      "Publie gratuitement un site statique (dossier avec index.html) sur Firebase Hosting ou GitHub Pages.",
      {"folder": S("Dossier du site (ou dist/)"), "target": S("firebase | github-pages", enum=["firebase", "github-pages"]),
       "project": S("ID projet Firebase OU nom du dépôt GitHub")}, category="publish",
      risk=lambda **k: (RISKY, "publication publique sur Internet"),
      summary=lambda folder, target, project: f"publier {P(folder)} sur {target} ({project})")
def deploy_website(folder: str, target: str, project: str):
    root = P(folder)
    if not (root / "index.html").exists():
        return f"[erreur] pas d'index.html dans {root}"
    if not re.fullmatch(r"[A-Za-z0-9._-]+", project):
        return "[erreur] nom de projet invalide"
    if target == "firebase":
        fj = root / "firebase.json"
        if not fj.exists():
            fj.write_text(json.dumps({"hosting": {"public": ".", "ignore": ["firebase.json", "**/.*", "**/node_modules/**"]}}, indent=2))
        return sh(f"firebase deploy --only hosting --project {project} --non-interactive", root, 1800, sandboxed=False)
    steps = []
    if not (root / ".git").exists():
        steps.append(sh("git init -b main && git add -A && git commit -m 'Site initial'", root, sandboxed=False))
    else:
        steps.append(sh("git add -A && (git diff --cached --quiet || git commit -m 'Mise à jour du site')", root, sandboxed=False))
    if "origin" not in sh("git remote", root, sandboxed=False):
        steps.append(sh(f"gh repo create {project} --public --source=. --push", root, sandboxed=False))
    else:
        steps.append(sh("git push -u origin HEAD", root, sandboxed=False))
    owner = gh_login() or sh("gh api user --jq .login", root, sandboxed=False).splitlines()[-1].strip()
    steps.append(sh(f"gh api -X POST repos/{owner}/{project}/pages -f 'source[branch]=main' -f 'source[path]=/' "
                    f">/dev/null 2>&1 && echo 'GitHub Pages activé' || echo 'GitHub Pages déjà actif'", root, sandboxed=False))
    steps.append(f"URL (1 à 2 min de propagation) : https://{owner}.github.io/{project}/")
    return trunc("\n".join(steps))


# ====================================================================== WEB (lecture)
def _risk_fetch(url, **k):
    if not url.startswith(("http://", "https://")):
        return BLOCKED, "seuls http(s) sont autorisés"
    if Ctx.policy.tainted and ("?" in url or len(url) > 160):
        return RISKY, "URL avec paramètres après lecture de contenu externe (risque de fuite de données)"
    return SAFE, ""


@tool("web_search", "Recherche web gratuite (DuckDuckGo, sans clé).", {"query": S("Requête"), "max_results": I("≤10")},
      ["query"], category="net", risk=lambda **k: (SAFE, ""), untrusted=True)
def web_search(query: str, max_results: int = 6):
    try:
        from ddgs import DDGS
        res = DDGS().text(query, max_results=min(int(max_results or 6), 10))
        return "\n\n".join(f"• {r.get('title')}\n  {r.get('href')}\n  {r.get('body')}" for r in res) or "Aucun résultat"
    except Exception as e:
        return f"[erreur recherche] {e}"


@tool("fetch_url", "Télécharge une page web et renvoie son texte lisible (ou le JSON brut). Utile aussi pour tester "
                   "un serveur local (http://127.0.0.1:PORT).", {"url": S("URL http(s)")}, category="net",
      risk=_risk_fetch, untrusted=True)
def fetch_url(url: str):
    import requests
    from bs4 import BeautifulSoup
    r = requests.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0 (Macintosh) Jarvis/3"})
    ctype = r.headers.get("content-type", "")
    if "json" in ctype or "text/plain" in ctype:
        return trunc(f"[{r.status_code}]\n{r.text}", 15000)
    soup = BeautifulSoup(r.text, "html.parser")
    for t in soup(["script", "style", "nav", "footer", "noscript", "svg"]):
        t.decompose()
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    return trunc(f"[{r.status_code}] {title}\n" + re.sub(r"\n\s*\n+", "\n\n", soup.get_text("\n")), 15000)


# ====================================================================== MÉMOIRE / PLAN
_mem_lock = threading.Lock()


@tool("remember", "Mémorise durablement une info utile sur l'utilisateur ou ses projets (préférences, chemins, noms).",
      {"note": S("Information")}, category="meta",
      risk=lambda note: (RISKY, "mémorisation après lecture de contenu externe") if Ctx.policy.tainted else (SAFE, ""))
def remember(note: str):
    with _mem_lock:
        config.MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(config.MEMORY_FILE, "a") as f:
            f.write(f"- {datetime.date.today()} : {note.strip()[:400]}\n")
    return "Mémorisé."


@tool("update_plan",
      "Définit ou met à jour ton plan. À appeler AU DÉBUT de toute tâche de plus de 2 étapes, puis à chaque étape "
      "terminée. steps = [{step, status: todo|doing|done|failed}].",
      {"steps": {"type": "array", "items": {"type": "object", "properties": {
          "step": {"type": "string"}, "status": {"type": "string", "enum": ["todo", "doing", "done", "failed"]}}},
          "description": "Étapes"}}, category="meta")
def update_plan(steps: list):
    clean = []
    for s in steps:
        if isinstance(s, str):
            s = {"step": s, "status": "todo"}
        st = s.get("status", "todo")
        clean.append({"step": str(s.get("step", ""))[:200], "status": st if st in ("todo", "doing", "done", "failed") else "todo"})
    Ctx.plan = clean
    if Ctx.ui and hasattr(Ctx.ui, "plan"):
        Ctx.ui.plan(clean)
    icons = {"todo": "☐", "doing": "▶", "done": "☑", "failed": "✗"}
    return "Plan :\n" + "\n".join(f"{icons.get(s['status'], '☐')} {s['step']}" for s in clean)
