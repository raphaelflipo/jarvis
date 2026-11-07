#!/usr/bin/env python3
"""
JARVIS — agent IA autonome, local, gratuit et sécurisé pour macOS (Apple Silicon).

  jarvis                      ouvre l'application (fenêtre native)
  jarvis "tâche"              exécute une tâche dans le Terminal (affichage en direct)
  jarvis chat                 conversation dans le Terminal
  jarvis serve                serveur seul (utilisé par l'application)
  jarvis doctor               diagnostic complet
  jarvis allow <dossier>      autorise un dossier projet pour le bac à sable
  jarvis remote on|off        accès depuis l'iPhone via Tailscale
  jarvis undo [--list]        annule les modifications de la dernière tâche
  jarvis token [--reset]      jeton de l'interface
  jarvis secret set <nom>     range un secret dans le Trousseau
  jarvis setup-phone          notifications téléphone (ntfy)
  jarvis schedules            tâches planifiées
  jarvis bench                banc d'essai (mesure la fiabilité du modèle)
  jarvis nightly [--force]    contrôle automatique (banc d'essai si le Mac est branché et inutilisé)
Options : --model <nom>  --mode prudent|autonome|total  --headless  --notify
"""
from __future__ import annotations

import argparse
import getpass
import json
import queue
import secrets
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import config  # noqa: E402
import security  # noqa: E402

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.text import Text
    console = Console()
except ImportError:  # pragma: no cover
    console = None

GREEN = "#7CFC00"
SUB = {"app", "chat", "serve", "doctor", "allow", "remote", "undo", "token", "secret", "setup-phone", "schedules",
       "bench", "version", "config", "siri", "raccourci-siri", "nightly"}


def say(msg, style=""):
    if console:
        console.print(Text(str(msg), style=style) if not isinstance(msg, (Panel, Markdown)) else msg)
    else:
        print(msg)


# =================================================================== exécution dans le Terminal
class TermRunner:
    """Affiche en direct les événements d'une tâche et pose les confirmations au clavier."""

    def __init__(self):
        self.q: queue.Queue = queue.Queue()
        self.streaming = False

    def broadcast(self, msg):
        self.q.put(msg)

    def pump(self, manager, task_id):
        t = manager.tasks[task_id]
        while True:
            try:
                msg = self.q.get(timeout=0.3)
            except queue.Empty:
                if not (t.thread and t.thread.is_alive()) and self.q.empty():
                    break
                continue
            except KeyboardInterrupt:
                say("\n⏹ Arrêt demandé…", "yellow")
                manager.stop(task_id)
                continue
            if msg.get("task_id") not in (None, task_id):
                continue
            self.show(msg, manager)

    def _end_stream(self):
        if self.streaming:
            print()
            self.streaming = False

    def show(self, msg, manager):
        typ = msg["type"]
        if typ == "confirm":
            self._end_stream()
            body = Text(msg["summary"])
            if msg.get("detail"):
                body.append("\n\n" + msg["detail"], style="yellow")
            say(Panel(body, title=f"⚠ Confirmation ({msg.get('level')})", border_style="yellow"))
            hint = "o = oui · n = non" + (" · t = toujours pour cette tâche" if msg.get("can_always") else "")
            try:
                a = input(f"Autoriser ? ({hint}) › ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                a = "n"
            manager.answer(msg["task_id"], msg["cid"], {"o": "yes", "oui": "yes", "y": "yes", "t": "always"}.get(a, "no"))
            return
        if typ != "event":
            return
        ev = msg["ev"]
        k = ev["type"]
        if k == "delta":
            if ev["kind"] == "content":
                if not self.streaming:
                    self.streaming = True
                sys.stdout.write(ev["text"])
                sys.stdout.flush()
            return
        self._end_stream()
        if k == "tool":
            t = Text()
            t.append(f"🔧 {ev['name']} ", style=f"bold {GREEN}")
            t.append(ev.get("args", "")[:220], style="dim")
            say(t)
        elif k == "tool_end":
            out = ev.get("output", "")
            say(Panel(Text(out[:700] + (" …" if len(out) > 700 else "")),
                      border_style="green" if ev.get("state") == "ok" else "red", padding=(0, 1)))
        elif k == "plan":
            icons = {"todo": "☐", "doing": "▶", "done": "☑", "failed": "✗"}
            say(Panel("\n".join(f"{icons.get(s['status'], '☐')} {s['step']}" for s in ev["steps"]),
                      title="Plan", border_style=GREEN))
        elif k == "sub":
            s = ev["sub"]
            say(f"  ⫸ [{s.get('title')}] {s.get('status', '')} {s.get('last', '')}", "cyan")
        elif k == "info":
            say(ev["text"], "dim")
        elif k == "final":
            say(Panel(Markdown(ev["text"] or "(terminé)"), title="Jarvis", border_style=GREEN))


def run_terminal(cfg, text, headless=False, notify=False):
    from tasks import TaskManager
    runner = TermRunner()
    mgr = TaskManager(cfg, broadcast=runner.broadcast, headless=headless)
    t = mgr.create(text)
    runner.pump(mgr, t.id)
    mgr.wait(t.id)
    last = next((e["text"] for e in reversed(t.events) if e["type"] == "final"), "")
    if notify or headless:
        import tools
        tools.notify("Jarvis", (last or "Tâche terminée")[:200])
        n = cfg.get("ntfy") or {}
        if n.get("enabled") and n.get("topic"):
            from net_tools import send_ntfy
            send_ntfy(n, f"Jarvis — {t.title}", last or "(terminé)")
    return last


def chat(cfg):
    from tasks import TaskManager
    runner = TermRunner()
    mgr = TaskManager(cfg, broadcast=runner.broadcast)
    say(Panel(f"[bold]JARVIS {config.VERSION}[/] · modèle {cfg['model']} · autonomie {cfg['autonomy']}\n"
              f"Ctrl+C arrête une tâche · Ctrl+D quitte · tu peux aussi ouvrir l'app : `jarvis`", border_style=GREEN))
    tid = None
    while True:
        try:
            text = input("\nToi › ").strip()
        except (EOFError, KeyboardInterrupt):
            say("\nÀ bientôt.")
            return
        if not text:
            continue
        if text in ("/quitter", "/quit", "/exit"):
            return
        if text == "/reset":
            tid = None
            say("Nouvelle conversation.")
            continue
        if tid is None:
            tid = mgr.create(text).id
        else:
            err = mgr.send(tid, text)
            if err:
                say(err, "yellow")
                continue
        runner.pump(mgr, tid)
        mgr.wait(tid)


# =================================================================== sous-commandes
def undo_cmd(argv):
    from registry import Backups
    tasks = Backups.list_tasks()
    if not tasks:
        say("Rien à annuler.")
        return
    if "--list" in argv:
        for t in tasks[:15]:
            man = json.loads((t / "manifest.json").read_text())
            say(f"• {t.name} — {len(man)} fichier(s) : " + ", ".join(Path(m['path']).name for m in man[:5]))
        return
    man = json.loads((tasks[0] / "manifest.json").read_text())
    say(f"Dernière tâche ({tasks[0].name}) — {len(man)} fichier(s) :")
    for m in man:
        say(f"  {'restaurer' if m['backup'] else 'mettre à la Corbeille'} : {m['path']}")
    if input("Annuler ces modifications ? [o/N] ").strip().lower() in ("o", "oui", "y"):
        say(Backups.undo(tasks[0]))


def doctor(cfg):
    import diagnostics
    say(Panel(f"Diagnostic Jarvis {config.VERSION}", border_style=GREEN))
    bad = 0
    for c in diagnostics.checks(cfg):
        icon = {"ok": "[green]✔[/]", "warn": "[yellow]•[/]", "fail": "[red]✖[/]"}[c["status"]]
        line = f"{icon} {c['label']}"
        if c["status"] != "ok" and c.get("fix"):
            line += f"\n    [dim]→ {c['fix']}[/]"
        console.print(line) if console else print(line)
        bad += c["status"] == "fail"
    say("\nTout est prêt." if not bad else "\nCorrige les points en rouge.", "bold green" if not bad else "yellow")


def setup_phone(cfg):
    n = cfg.get("ntfy") or {}
    if not n.get("topic"):
        n = {"enabled": True, "server": "https://ntfy.sh", "topic": "jarvis-" + secrets.token_hex(10)}
    n["enabled"] = True
    config.update(ntfy=n)
    say(Panel(f"1. Installe l'app gratuite « ntfy » sur ton téléphone.\n2. « + » → abonne-toi au sujet :\n\n   {n['topic']}\n\n"
              f"Ce nom est secret. Jarvis t'y enverra la fin des tâches et ses demandes d'accord.",
              title="Notifications téléphone", border_style=GREEN))
    from net_tools import send_ntfy
    say(send_ntfy(n, "Jarvis", "Les notifications fonctionnent ✅"))


def main():
    argv = sys.argv[1:]
    config.ensure_dirs()
    cfg = config.load()
    if not argv:
        import app
        app.main()
        return
    if argv[0] in SUB:
        sub, rest = argv[0], argv[1:]
        if sub == "app":
            import app
            app.main()
        elif sub == "chat":
            chat(cfg)
        elif sub == "serve":
            from server import serve
            import mcp_client
            if cfg.get("mcp_servers"):
                mcp_client.load_all(cfg)
            serve(cfg)
        elif sub == "doctor":
            doctor(cfg)
        elif sub == "allow":
            from server import _safe_project_dir
            if not rest:
                say("Usage : jarvis allow ~/Projets/MonProjet")
                return
            d = _safe_project_dir(rest[0])
            if not d:
                say("Dossier refusé (inexistant, hors de ton dossier personnel, ou sensible).", "red")
                return
            dirs = list(dict.fromkeys(cfg.get("project_dirs", []) + [d]))
            config.update(project_dirs=dirs)
            say(f"Dossier projet autorisé : {d}", "green")
        elif sub == "remote":
            from server import set_remote
            say(set_remote(bool(rest) and rest[0] in ("on", "oui", "activer")))
        elif sub == "undo":
            undo_cmd(rest)
        elif sub == "token":
            from server import get_token
            if "--reset" in rest:
                config.TOKEN_FILE.unlink(missing_ok=True)
                say("Jeton régénéré : redémarre Jarvis (Quitter puis rouvrir).")
            say(f"Jeton : {get_token()}")
        elif sub == "secret":
            if len(rest) >= 2 and rest[0] == "set":
                val = getpass.getpass(f"Valeur pour « {rest[1]} » (masquée) : ")
                ok = security.keychain_set(rest[1], val)
                say("Rangé dans le Trousseau ✅" if ok else "Échec", "green" if ok else "red")
                say(f"Utilisation : {{{{keychain:{rest[1]}}}}} dans les en-têtes de http_request.")
            else:
                say("Usage : jarvis secret set <nom>")
        elif sub == "setup-phone":
            setup_phone(cfg)
        elif sub == "schedules":
            import scheduler
            say(scheduler.list_scheduled())
        elif sub == "bench":
            import bench
            bench.main(cfg)
        elif sub == "nightly":
            import nightly
            say(f"Contrôle automatique : {nightly.run(force='--force' in sys.argv)}")
        elif sub == "siri":
            import siri
            siri.main([x for x in rest if x != "--stdin"])     # sans texte : lu sur l'entrée standard (Raccourci)
        elif sub == "raccourci-siri":
            import siri
            p, err = siri.build_shortcut(config.JARVIS_DIR / "siri")
            if p:
                subprocess.run(["open", str(p)])
                say(f"Raccourci prêt : {p}\nClique sur « Ajouter le raccourci », puis dis « Dis Siri, Jarvis ».", "green")
            else:
                say(f"Signature du raccourci impossible : {err}", "red")
        elif sub == "config":
            subprocess.run(["open", "-t", str(config.CONFIG_FILE)])
        elif sub == "version":
            say(f"Jarvis {config.VERSION}")
        return
    ap = argparse.ArgumentParser(prog="jarvis")
    ap.add_argument("task", nargs="+")
    ap.add_argument("--model")
    ap.add_argument("--mode", choices=["prudent", "autonome", "total"])
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--notify", action="store_true")
    a = ap.parse_args(argv)
    if a.model:
        cfg["model"] = a.model
    if a.mode:
        cfg["autonomy"] = a.mode
    import mcp_client
    if cfg.get("mcp_servers"):
        mcp_client.load_all(cfg, log=lambda m: say(m, "dim"))
    run_terminal(cfg, " ".join(a.task), headless=a.headless, notify=a.notify)


if __name__ == "__main__":
    main()
