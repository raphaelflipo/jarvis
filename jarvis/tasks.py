"""
Gestionnaire de tâches parallèles de Jarvis.
  • plusieurs tâches en même temps (limite configurable selon la RAM), file d'attente au-delà ;
  • chaque tâche a son agent, son thread, son contexte, ses sauvegardes, ses confirmations ;
  • persistance (reprise des conversations), anti-veille pendant le travail, notifications, voix.
"""
from __future__ import annotations

import json
import re
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

import config
import security
from attach import attachments_block
from core import Agent
from registry import Backups

EPHEMERAL = {"delta", "step"}


class Limiter:
    """Nombre maximal de tâches simultanées, modifiable à chaud."""

    def __init__(self, n: int):
        self.limit, self.active = max(1, n), 0
        self.cond = threading.Condition()

    def acquire(self):
        with self.cond:
            while self.active >= self.limit:
                self.cond.wait()
            self.active += 1

    def release(self):
        with self.cond:
            self.active = max(0, self.active - 1)
            self.cond.notify_all()

    def set_limit(self, n: int):
        with self.cond:
            self.limit = max(1, n)
            self.cond.notify_all()


class TaskUI:
    """Interface d'une tâche : enregistre l'historique et diffuse en direct."""

    def __init__(self, task: "Task"):
        self.t = task

    def _e(self, ev: dict, store=True):
        self.t.push(ev, store)

    def info(self, msg): self._e({"type": "info", "text": msg})
    def step(self, n, backend): self._e({"type": "step", "n": n, "backend": backend}, False)
    def delta(self, kind, text): self._e({"type": "delta", "kind": kind, "text": text}, False)
    def assistant(self, text): self._e({"type": "assistant", "text": text})

    def tool_start(self, cid, name, args):
        self._e({"type": "tool", "id": cid, "name": name,
                 "args": security.redact(json.dumps(args, ensure_ascii=False))[:2000], "state": "running"})

    def tool_end(self, cid, name, res):
        self.t.update_tool(cid, {"state": "ok" if res["ok"] else ("denied" if res.get("denied") else "error"),
                                 "output": res["output"][:4000]})

    def plan(self, steps):
        self.t.plan = steps
        self._e({"type": "plan", "steps": steps})

    def sub(self, sub_id, data):
        cur = self.t.subs.setdefault(sub_id, {"id": sub_id})
        cur.update(data)
        self._e({"type": "sub", "sub": dict(cur)}, False)
        self.t.dirty = True


class Task:
    def __init__(self, manager: "TaskManager", task_id: str, title: str):
        self.m = manager
        self.id = task_id
        self.title = title
        self.status = "idle"          # idle | queued | running | waiting | done | error | stopped
        self.created = self.updated = time.time()
        self.events: list[dict] = []
        self.plan: list = []
        self.subs: dict[str, dict] = {}
        self.pending: dict[str, dict] = {}
        self.messages: list | None = None
        self.agent: Agent | None = None
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.dirty = False
        self.started_at = 0.0
        self.model = ""
        self.deleted = False          # supprimée : plus aucune écriture sur disque
        self.delete_after = False     # suppression demandée pendant l'exécution

    # ---------------------------------------------------------------- événements
    def push(self, ev: dict, store=True):
        ev = {"ts": time.time(), **ev}
        if store:
            with self.lock:
                self.events.append(ev)
                if len(self.events) > 2500:
                    self.events = self.events[-2000:]
            self.dirty = True
        self.updated = time.time()
        self.m.broadcast({"type": "event", "task_id": self.id, "ev": ev})

    def update_tool(self, cid, data):
        with self.lock:
            for ev in reversed(self.events):
                if ev.get("type") == "tool" and ev.get("id") == cid:
                    ev.update(data)
                    break
        self.dirty = True
        self.m.broadcast({"type": "event", "task_id": self.id, "ev": {"type": "tool_end", "id": cid, **data}})

    def set_status(self, s: str):
        self.status = s
        self.updated = time.time()
        self.m.broadcast({"type": "task", "task": self.meta()})

    def meta(self) -> dict:
        return {"id": self.id, "title": self.title, "status": self.status, "created": self.created,
                "updated": self.updated, "pending": len(self.pending), "subs": len(self.subs),
                "can_undo": Backups.for_task(self.id) is not None, "model": self.model}

    def snapshot(self) -> dict:
        with self.lock:
            evs = list(self.events)
        return {"task": self.meta(), "events": evs, "plan": self.plan, "subs": list(self.subs.values()),
                "pending": [{"cid": k, **{kk: vv for kk, vv in v.items() if kk != "event"}} for k, v in self.pending.items()]}

    # ---------------------------------------------------------------- confirmations
    def confirm(self, summary: str, detail: str, level: int) -> str:
        cid = uuid.uuid4().hex[:10]
        ev = threading.Event()
        entry = {"event": ev, "answer": "no", "summary": summary, "detail": detail,
                 "level": security.LEVEL_NAMES.get(level), "can_always": level < security.RISKY}
        self.pending[cid] = entry
        prev = self.status
        self.set_status("waiting")
        self.m.broadcast({"type": "confirm", "task_id": self.id, "title": self.title, "cid": cid,
                          **{k: v for k, v in entry.items() if k != "event"}})
        self.m.notify_confirm(self, summary)
        ev.wait(600)
        ans = self.pending.pop(cid, {}).get("answer", "no")
        self.push({"type": "decision", "summary": summary[:300], "answer": ans})
        self.m.broadcast({"type": "confirm_done", "task_id": self.id, "cid": cid, "answer": ans})
        if self.status == "waiting":
            self.set_status(prev if prev in ("running",) else "running")
        return ans

    def answer(self, cid: str, ans: str):
        p = self.pending.get(cid)
        if p:
            p["answer"] = ans if ans in ("yes", "no", "always") else "no"
            p["event"].set()

    # ---------------------------------------------------------------- persistance
    def path(self) -> Path:
        return config.TASKS_DIR / f"{self.id}.json"

    def save(self):
        if self.deleted:
            return
        msgs = self.agent.messages if self.agent else (self.messages or [])
        data = {"meta": self.meta(), "plan": self.plan, "subs": self.subs, "events": self.events[-2000:],
                "messages": [m for m in msgs[1:]]}
        txt = security.redact(json.dumps(data, ensure_ascii=False, default=str))
        tmp = self.path().with_suffix(".tmp")
        tmp.write_text(txt)
        tmp.replace(self.path())
        self.dirty = False

    @classmethod
    def load(cls, manager, path: Path) -> "Task | None":
        try:
            d = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        m = d.get("meta", {})
        t = cls(manager, m.get("id", path.stem), m.get("title", "Tâche"))
        t.status = m.get("status", "done")
        if t.status in ("running", "queued", "waiting"):
            t.status = "stopped"        # interrompue par un redémarrage
        t.created, t.updated = m.get("created", time.time()), m.get("updated", time.time())
        t.events, t.plan, t.subs = d.get("events", []), d.get("plan", []), d.get("subs", {})
        t.messages = d.get("messages", [])
        t.model = m.get("model", "")
        return t


class TaskManager:
    def __init__(self, cfg: dict, broadcast: Callable[[dict], None] | None = None, headless: bool = False):
        config.ensure_dirs()
        self.cfg = cfg
        self._broadcast = broadcast
        self.headless = headless
        self.tasks: dict[str, Task] = {}
        self.sem = Limiter(int(cfg.get("max_parallel_tasks", 2)))
        self.thermal = None
        self.lock = threading.Lock()
        self.caffeinate: subprocess.Popen | None = None
        for p in sorted(config.TASKS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)[-300:]:
            t = Task.load(self, p)
            if t:
                t.external = True        # fichier déjà sur disque : s'il disparaît, la tâche sort de la liste
                self.tasks[t.id] = t
        threading.Thread(target=self._autosave, daemon=True).start()

    # ---------------------------------------------------------------- diffusion
    def broadcast(self, msg: dict):
        if self._broadcast:
            try:
                self._broadcast(msg)
            except Exception:
                pass

    def list(self) -> list[dict]:
        for p in config.TASKS_DIR.glob("*.json"):       # tâches créées par la ligne de commande / planifiées
            if p.stem not in self.tasks:
                t = Task.load(self, p)
                if t:
                    t.external = True
                    self.tasks[t.id] = t
        for tid, t in list(self.tasks.items()):          # supprimées depuis l'extérieur : on les retire de la liste
            if getattr(t, "external", False) and not t.thread and not t.path().exists():
                self.tasks.pop(tid, None)
        return sorted((t.meta() for t in self.tasks.values()), key=lambda m: -m["updated"])

    def running(self) -> list[Task]:
        return [t for t in self.tasks.values() if t.status in ("running", "waiting", "queued")]

    # ---------------------------------------------------------------- cycle de vie
    def create(self, text: str, title: str = "", files: list | None = None, boost: bool = False) -> Task:
        tid = f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"
        t = Task(self, tid, title or _quick_title(text if not files or len(text) > 60 else f"{files[0]['name']} — {text}"))
        self.tasks[tid] = t
        self.broadcast({"type": "task", "task": t.meta()})
        self._start(t, text, new=True, files=files, boost=boost)
        return t

    def send(self, task_id: str, text: str, files: list | None = None, boost: bool = False) -> str | None:
        t = self.tasks.get(task_id)
        if not t:
            return "Tâche introuvable."
        if t.status in ("running", "waiting", "queued"):
            return "Cette tâche travaille encore : attends la fin, arrête-la, ou crée une nouvelle tâche."
        self._start(t, text, new=False, files=files, boost=boost)
        return None

    def _start(self, t: Task, text: str, new: bool, files: list | None = None, boost: bool = False):
        ev = {"type": "user", "text": text}
        if boost:
            ev["boost"] = True
        if files:
            ev["files"] = files
        t.push(ev)
        t.set_status("queued")
        agent_text = text + attachments_block(files or [])
        th = threading.Thread(target=self._run, args=(t, agent_text, new, boost), daemon=True, name=f"jarvis-{t.id}")
        t.thread = th
        th.start()

    def _agent_for(self, t: Task) -> Agent:
        if t.agent is None:
            cfg = json.loads(json.dumps(self.cfg))
            a = Agent(cfg, ui=TaskUI(t), confirm=None if self.headless else t.confirm,
                      headless=self.headless, task_id=t.id)
            if t.messages:
                a.messages = [a.messages[0]] + t.messages
            a.plan = list(t.plan or [])
            t.agent = a
        return t.agent

    def _run(self, t: Task, text: str, new: bool, boost: bool = False):
        self.sem.acquire()
        try:
            if t.status == "stopped":
                return
            t.set_status("running")
            t.started_at = time.time()
            self._caffeinate()
            agent = self._agent_for(t)
            agent.force_boost = bool(boost)
            t.model = agent.cfg.get("model", "")
            answer = agent.run(text)
            if new and len(text) > 40:          # titre calculé APRÈS la tâche : le GPU reste dédié au travail
                threading.Thread(target=self._retitle, args=(t, agent, text), daemon=True).start()
            t.push({"type": "final", "text": answer})
            t.set_status("stopped" if agent.stop_event.is_set() else "done")
            self._finished(t, answer)
        except Exception as e:
            t.push({"type": "final", "text": f"[Erreur interne] {type(e).__name__}: {e}"})
            t.set_status("error")
        finally:
            self.sem.release()
            try:
                t.save()
            except OSError:
                pass
            self._caffeinate()
            if t.delete_after:
                self.delete(t.id, from_runner=True)

    def _retitle(self, t: Task, agent: Agent, text: str):
        title = agent.title_for(text)
        if title and not t.deleted:
            t.title = title
            try:
                t.save()
            except OSError:
                pass
            self.broadcast({"type": "task", "task": t.meta()})

    def stop(self, task_id: str):
        t = self.tasks.get(task_id)
        if not t:
            return
        if t.agent:
            t.agent.stop()
        for cid in list(t.pending):
            t.answer(cid, "no")
        if t.status == "queued":
            t.set_status("stopped")

    def answer(self, task_id: str, cid: str, ans: str):
        t = self.tasks.get(task_id)
        if t:
            t.answer(cid, ans)

    def undo(self, task_id: str) -> str:
        t = self.tasks.get(task_id)
        if t and t.status in ("running", "waiting", "queued"):
            return "Impossible pendant que la tâche travaille."
        d = Backups.for_task(task_id)
        res = Backups.undo(d) if d else "Rien à annuler pour cette tâche."
        if t:
            t.push({"type": "info", "text": "↶ " + res})
            t.save()
            self.broadcast({"type": "task", "task": t.meta()})
        return res

    def delete(self, task_id: str, from_runner: bool = False):
        t = self.tasks.get(task_id)
        if not t:
            return
        busy = t.status in ("running", "waiting", "queued") or (t.thread and t.thread.is_alive())
        if busy and not from_runner:
            t.delete_after = True        # on arrête la tâche ; elle sera supprimée dès qu'elle aura rendu la main
            self.stop(task_id)
            return
        import tools
        tools.stop_all_background(task_id)
        t.deleted = True
        self.tasks.pop(task_id, None)
        t.path().unlink(missing_ok=True)
        self.broadcast({"type": "deleted", "task_id": task_id})

    def rename(self, task_id: str, title: str):
        t = self.tasks.get(task_id)
        if t:
            t.title = title.strip()[:80] or t.title
            t.save()
            self.broadcast({"type": "task", "task": t.meta()})

    def effective_parallel(self) -> int:
        """Mac chaud (macOS bride la puce) : une tâche à la fois, pour ne pas tout ralentir ni surchauffer."""
        n = int(self.cfg.get("max_parallel_tasks", 2))
        if self.cfg.get("thermal_guard", True) and (self.thermal or 0) >= 2:
            return 1
        return n

    def set_thermal(self, level):
        if level != self.thermal:
            self.thermal = level
            self.sem.set_limit(self.effective_parallel())

    def apply_settings(self, cfg: dict):
        """Les nouvelles tâches utilisent la nouvelle config ; les tâches en cours gardent la leur."""
        model_changed = (cfg.get("model") != self.cfg.get("model") or cfg.get("think") != self.cfg.get("think")
                         or cfg.get("engine") != self.cfg.get("engine"))
        self.cfg = cfg
        self.sem.set_limit(self.effective_parallel())
        if model_changed and not self.headless:
            self.warmup()
        for t in self.tasks.values():
            if t.status not in ("running", "waiting", "queued") and t.agent is not None:
                t.messages = list(t.agent.messages[1:])   # on garde la conversation…
                t.agent = None                             # …et l'agent est recréé avec la nouvelle config

    def wait(self, task_id: str, poll=0.3):
        t = self.tasks.get(task_id)
        while t and t.thread and t.thread.is_alive():
            t.thread.join(poll)

    # ---------------------------------------------------------------- confort
    def warmup(self):
        """Précharge le modèle et le long prompt de Jarvis dans le cache d'Ollama : la 1re tâche démarre vite."""
        def w():
            try:
                import registry
                a = Agent(json.loads(json.dumps(self.cfg)))
                a.router.chat([a._system(), {"role": "user", "content": "Réponds simplement : prêt."}],
                              tools=registry.schemas(), options={"num_predict": 1})
                security.audit({"type": "warmup", "model": self.cfg.get("model")})
            except Exception as e:
                security.audit({"type": "warmup_failed", "error": str(e)[:200]})
        threading.Thread(target=w, daemon=True, name="jarvis-warmup").start()

    def _autosave(self):
        while True:
            time.sleep(5)
            for t in list(self.tasks.values()):
                if t.dirty and t.status in ("running", "waiting"):
                    try:
                        t.save()
                    except OSError:
                        pass

    def _caffeinate(self):
        busy = bool(self.running())
        with self.lock:
            if busy and (self.caffeinate is None or self.caffeinate.poll() is not None):
                try:
                    self.caffeinate = subprocess.Popen(["caffeinate", "-i", "-m"], stdout=subprocess.DEVNULL,
                                                       stderr=subprocess.DEVNULL)
                except FileNotFoundError:
                    self.caffeinate = None
            elif not busy and self.caffeinate is not None:
                self.caffeinate.terminate()
                self.caffeinate = None

    def _finished(self, t: Task, answer: str):
        dur = time.time() - t.started_at
        short = re.sub(r"[`*#>\[\]_]", "", answer).strip()
        if dur > 25:
            try:
                subprocess.run(["osascript", "-e", f'display notification "{short[:180].replace(chr(34), chr(39))}" '
                                f'with title "Jarvis — {t.title[:60].replace(chr(34), chr(39))}" sound name "Glass"'],
                               capture_output=True, timeout=10)
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass
            n = self.cfg.get("ntfy") or {}
            if n.get("enabled") and n.get("topic"):
                from net_tools import send_ntfy
                send_ntfy(n, f"Jarvis — {t.title}", short[:1500])
            import push                            # iPhone : notification de l'app Jarvis (écran d'accueil)
            push.send_async(f"✅ {t.title[:80]}", short[:500], f"/#task={t.id}", t.id[-24:])
        v = self.cfg.get("voice") or {}
        if v.get("enabled"):
            first = re.split(r"(?<=[.!?])\s", short.replace("\n", " "))[:2]
            phrase = " ".join(first)[:300]
            threading.Thread(target=_say, args=(phrase, v.get("voice", "Thomas"), v.get("rate", 190)), daemon=True).start()

    def notify_confirm(self, t: Task, summary: str):
        import push
        push.send_async(f"✋ Jarvis attend ton accord — {t.title[:60]}", summary[:300], f"/#task={t.id}", t.id[-24:], True)
        n = self.cfg.get("ntfy") or {}
        if n.get("enabled") and n.get("topic"):
            from net_tools import send_ntfy
            threading.Thread(target=send_ntfy, args=(n, f"Jarvis attend ton accord — {t.title}", summary[:300], "high"),
                             daemon=True).start()


def _say(text: str, voice_name: str, rate: int):
    import voice
    voice.speak(text, voice_name, rate)


def _quick_title(text: str) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    return (t[:48] + "…") if len(t) > 50 else t or "Nouvelle tâche"
