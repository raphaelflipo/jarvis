"""
Profils Seatbelt pour les commandes shell et les compilations.

Les écritures autorisées dépendent de la configuration, du dossier courant
admissible, des caches de compilation et des fichiers temporaires. Le profil
limite aussi les lectures des chemins DENY_READ et, selon la tâche, le réseau.
wrap() indique si un profil a effectivement été appliqué. Les outils Git,
déploiement et SSH utilisent leurs propres règles de confirmation.
"""
from __future__ import annotations

import functools
import shutil
import subprocess
from pathlib import Path

import config
import security

HOME = config.HOME

CACHE_DIRS = [
    "Library/Caches", "Library/Developer", "Library/Logs", "Library/org.swift.swiftpm", "Library/pnpm",
    "Library/Python", "Library/Application Support/Code/User/workspaceStorage",
    ".npm", ".cache", ".cargo", ".rustup", "go", ".gradle", ".m2", ".swiftpm", ".cocoapods", ".pub-cache",
    ".local/share", ".node-gyp", ".yarn", ".bun", ".deno", ".expo", ".pyenv", ".conan2", ".vcpkg",
]
DENY_READ = [
    ".ssh", "Library/Keychains", ".config/gh", ".config/configstore", ".netrc", ".aws", ".gnupg",
    "Library/Cookies", "Library/Safari", "Library/Messages", "Library/Mail",
    "Library/Application Support/Google/Chrome", "Library/Application Support/Firefox",
    "Library/Application Support/BraveSoftware", "Library/Containers/com.apple.mail",
]


def _q(p: Path | str) -> str:
    return '"' + str(p).replace("\\", "\\\\").replace('"', '\\"') + '"'


def eligible_cwd(cwd: Path, cfg: dict | None = None) -> bool:
    """Seuls l'espace de travail et les projets explicitement autorisés sont inscriptibles."""
    cfg = cfg or {}
    roots = [Path(cfg.get("workspace", HOME / "JarvisWorkspace")).expanduser()]
    roots += [Path(d).expanduser() for d in cfg.get("project_dirs", [])]
    c = security.resolve(cwd)
    return any(security.under(c, security.resolve(root)) for root in roots)


def profile(writable: list[Path], network: bool, allow_brew: bool) -> str:
    w = [security.resolve(p) for p in writable if p]
    w += [HOME / d for d in CACHE_DIRS]
    if allow_brew:
        w.append(Path("/opt/homebrew"))
    lines = [
        "(version 1)",
        "(allow default)",
        "(deny file-write*)",
        "(allow file-write*",
        '  (literal "/dev/null") (literal "/dev/zero") (literal "/dev/random") (literal "/dev/urandom")',
        '  (literal "/dev/dtracehelper") (regex #"^/dev/tty") (regex #"^/dev/fd/") (regex #"^/dev/ptmx")',
        '  (subpath "/private/tmp") (subpath "/private/var/folders") (subpath "/private/var/tmp")',
        f'  (regex #"^{_re(HOME)}/Library/Preferences/com\\.apple\\.dt\\.")',
    ]
    lines += [f"  (subpath {_q(p)})" for p in dict.fromkeys(w)]
    lines.append(")")
    deny = [HOME / d for d in DENY_READ] + [config.JARVIS_DIR]
    lines.append("(deny file-read* file-write*")
    lines += [f"  (subpath {_q(p)})" for p in deny]
    lines.append(")")
    if not network:
        lines += [
            "(deny network-outbound)",
            '(allow network-outbound (remote ip "localhost:*") (remote unix-socket))',
            '(deny network-outbound (remote unix-socket (path-literal "/private/var/run/mDNSResponder")))',
        ]
    return "\n".join(lines) + "\n"


def _re(p: Path) -> str:
    import re
    return re.escape(str(p))


@functools.lru_cache(maxsize=1)
def available() -> bool:
    exe = shutil.which("sandbox-exec") or "/usr/bin/sandbox-exec"
    if not Path(exe).exists():
        return False
    try:
        r = subprocess.run([exe, "-p", profile([config.JARVIS_DIR.parent / "JarvisWorkspace"], True, True), "/usr/bin/true"],
                           capture_output=True, timeout=10)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def wrap(argv: list[str], cwd: Path, cfg: dict, network: bool, tainted: bool) -> tuple[list[str], bool]:
    """Renvoie (commande éventuellement enveloppée, sandbox_active)."""
    if not cfg.get("sandbox", True):
        return argv, False
    if not available():
        raise RuntimeError("Bac à sable indisponible : commande refusée. Vérifie les réglages de sécurité.")
    writable = [Path(cfg.get("workspace", HOME / "JarvisWorkspace")).expanduser()]
    writable += [Path(d).expanduser() for d in cfg.get("project_dirs", [])]
    if cfg.get("dev_venv"):
        writable.append(Path(cfg["dev_venv"]).expanduser())
    prof = profile(writable, network=network, allow_brew=not tainted)
    return ["/usr/bin/sandbox-exec", "-p", prof, *argv], True


SANDBOX_HINT = ("\n[bac à sable] Une écriture ou une lecture a été bloquée. Jarvis ne peut écrire que dans l'espace de "
                "travail, les dossiers projets autorisés explicitement autorisés. Pour autoriser un dossier : "
                "Réglages › Dossiers projets (ou `jarvis allow ~/chemin`). Pour git push / gh / firebase / ssh, "
                "utilise les outils dédiés `git`, `github`, `firebase`, `ssh_run`.")
NETWORK_HINT = ("\n[bac à sable] Réseau coupé : cette tâche a lu du contenu externe, les commandes tournent donc sans "
                "Internet (seul localhost / 127.0.0.1 reste joignable). Si Internet est vraiment nécessaire, relance la "
                "commande avec network=true (l'utilisateur devra confirmer).")
