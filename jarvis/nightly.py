"""
Contrôle automatique : quand ton Mac est branché et que tu ne t'en sers pas, Jarvis repasse son banc d'essai
(tâches types + copies de tes projets) au plus une fois par jour. Il s'arrête dès que tu reviens sur le Mac.
Si le score baisse, tu reçois une notification. Résultat dans Réglages › Diagnostic.

Lancé toutes les 30 min par le service com.jarvis.nightly (priorité basse) ; il ne fait rien la plupart du temps.
"""
from __future__ import annotations

import json
import os
import plistlib
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import config

LABEL = "com.jarvis.nightly"
IDLE_MIN = 20 * 60          # inactif depuis 20 min
RESUME_S = 60               # activité récente : on s'arrête
GAP_H = 20                  # au plus une fois par jour


def state_file() -> Path:
    return config.JARVIS_DIR / "nightly.json"


def load_state() -> dict:
    try:
        return json.loads(state_file().read_text())
    except (OSError, ValueError):
        return {}


def save_state(st: dict):
    state_file().write_text(json.dumps(st, ensure_ascii=False, indent=1))


def idle_seconds() -> float:
    try:
        out = subprocess.run(["ioreg", "-c", "IOHIDSystem", "-d", "4"], capture_output=True, text=True, timeout=10).stdout
        m = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', out)
        return int(m.group(1)) / 1e9 if m else 0.0
    except (OSError, subprocess.SubprocessError):
        return 0.0


def on_ac() -> bool:
    try:
        return "AC Power" in subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return False


def hot() -> bool:
    try:
        import diagnostics
        return (diagnostics.thermal_state() or 0) >= 2     # macOS bride déjà la puce : on remet à plus tard
    except Exception:
        return False


def should_run(st: dict, now: float | None = None, idle: float | None = None, ac: bool | None = None,
               warm: bool | None = None) -> tuple[bool, str]:
    now = time.time() if now is None else now
    if now - float(st.get("last_run_ts", 0)) < GAP_H * 3600:
        return False, "déjà fait aujourd'hui"
    if not (on_ac() if ac is None else ac):
        return False, "sur batterie"
    if (idle_seconds() if idle is None else idle) < IDLE_MIN:
        return False, "Mac utilisé"
    if hot() if warm is None else warm:
        return False, "Mac chaud"
    return True, ""


def notify(title: str, text: str, cfg: dict):
    try:
        subprocess.run(["osascript", "-e", f"display notification {json.dumps(text)} with title {json.dumps(title)}"],
                       capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass
    n = cfg.get("ntfy") or {}
    if n.get("enabled") and n.get("topic"):
        try:
            from net_tools import send_ntfy
            send_ntfy(n, title, text)
        except Exception:
            pass


def last_bench() -> dict:
    try:
        lines = (config.JARVIS_DIR / "bench.jsonl").read_text().strip().splitlines()
        return json.loads(lines[-1]) if lines else {}
    except (OSError, ValueError):
        return {}


def run(force: bool = False) -> str:
    cfg = config.load()
    if cfg.get("nightly", True) is False and not force:
        return "désactivé"
    st = load_state()
    ok, why = (True, "") if force else should_run(st)
    if not ok:
        return why
    st["last_run_ts"] = time.time()
    save_state(st)
    before = last_bench().get("date")
    args = [sys.executable, "-u", str(Path(__file__).with_name("jarvis.py")), "bench", "--timeout", "600", "--nightly"]
    if (config.JARVIS_DIR / "bench_projects.json").exists():
        args.append("--projets")
    log = open(config.LOG_DIR / "nightly.log", "w")
    p = subprocess.Popen(args, cwd=str(Path(__file__).parent), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    t0, stopped = time.time(), ""
    while p.poll() is None:
        time.sleep(15)
        if not force and idle_seconds() < RESUME_S:
            stopped = "tu es revenu sur le Mac"
        elif not force and not on_ac():
            stopped = "Mac débranché"
        if stopped or time.time() - t0 > 3 * 3600:
            stopped = stopped or "trop long"
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except OSError:
                pass
            try:
                p.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
            break
    log.close()
    res = last_bench()
    prev = st.get("score_ratio")
    if stopped or res.get("date") == before:
        st.update(status="interrompu", reason=stopped or "pas de résultat", date=time.strftime("%Y-%m-%d %H:%M"))
        st["last_run_ts"] = 0 if stopped else st["last_run_ts"]      # interrompu : on réessaiera au prochain moment calme
        save_state(st)
        return f"interrompu ({stopped or 'pas de résultat'})"
    score, total = res.get("score", 0), res.get("total", 0)
    ratio = score / total if total else 0
    failed = [d["tâche"] for d in res.get("details", []) if not d.get("réussi")]
    st.update(status="fait", date=res.get("date"), score=score, total=total, score_ratio=ratio, failed=failed,
              minutes=round(sum(d.get("secondes", 0) for d in res.get("details", [])) / 60), previous=prev)
    save_state(st)
    if prev is not None and ratio + 1e-9 < prev:
        notify("Jarvis : contrôle automatique", f"Score en baisse : {score}/{total} (avant : {round(prev * total)}/{total}). "
               f"À revoir : {', '.join(failed[:3])}.", cfg)
    return f"{score}/{total}"


# ------------------------------------------------------------------ service
def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def install():
    py = config.JARVIS_DIR / "venv" / "bin" / "python3"
    pl = {"Label": LABEL, "ProgramArguments": [str(py), str(Path(__file__).with_name("jarvis.py")), "nightly"],
          "StartInterval": 1800, "RunAtLoad": False, "ProcessType": "Background", "LowPriorityIO": True, "Nice": 10,
          "WorkingDirectory": str(Path(__file__).parent),
          "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
          "StandardOutPath": str(config.LOG_DIR / "nightly-service.log"),
          "StandardErrorPath": str(config.LOG_DIR / "nightly-service.log")}
    p = plist_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(plistlib.dumps(pl))
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(p)], capture_output=True, timeout=30)
    subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(p)], capture_output=True, timeout=30)


def uninstall():
    p = plist_path()
    if p.exists():
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(p)], capture_output=True, timeout=30)
        p.unlink(missing_ok=True)


def installed() -> bool:
    return plist_path().exists()
