"""
« Dis Siri, Jarvis » : envoie une demande au Jarvis déjà ouvert (via son API locale) et renvoie une réponse courte à lire.

- Le jeton est lu dans ~/.jarvis (jamais copié dans le Raccourci, qui peut être synchronisé par iCloud).
- La tâche apparaît dans l'app comme les autres ; les demandes d'accord s'y affichent (et sur ton téléphone si ntfy).
- Tâche longue : réponse « c'est parti » au bout de quelques secondes, puis notification à la fin.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import plistlib
from pathlib import Path

import config

BASE = "http://127.0.0.1:{port}"


def _spoken(text: str, limit: int = 700) -> str:
    """Réponse lisible à voix haute : sans Markdown, ni blocs de code, ni chemins à rallonge."""
    t = re.sub(r"```.*?```", " (code dans l'app) ", text, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"[*_#>|]+", "", t)
    t = re.sub(r"/Users/[^/\s]+/", "~/", t)
    t = re.sub(r"\n{2,}", "\n", t).strip()
    return t if len(t) <= limit else t[:limit].rsplit(" ", 1)[0] + "… (suite dans l'app)"


def _ensure_server(port: int) -> bool:
    import requests
    url = BASE.format(port=port) + "/healthz"
    for i in range(40):
        try:
            if requests.get(url, timeout=1).ok:
                return True
        except requests.RequestException:
            pass
        if i == 0:
            subprocess.run(["open", "-g", "-a", "Jarvis"], capture_output=True)    # ouvre l'app en arrière-plan
        time.sleep(0.5)
    return False


def ask(text: str, wait: float = 25.0, port: int | None = None) -> str:
    import requests
    cfg = config.load()
    port = port or int((cfg.get("server") or {}).get("port", 8765))
    text = text.strip()
    if not text:
        return "Je n'ai rien entendu. Redis ta demande."
    if not _ensure_server(port):
        return "Jarvis ne répond pas. Ouvre l'app Jarvis puis réessaie."
    tok = config.TOKEN_FILE.read_text().strip()
    h = {"x-jarvis-token": tok}
    base = BASE.format(port=port)
    sid = requests.post(f"{base}/api/session", headers=h, timeout=10).json()["sid"]
    state = {"task": None, "final": None, "confirm": False}
    done = threading.Event()

    def listen():
        try:
            with requests.get(f"{base}/api/events", params={"sid": sid}, headers=h, stream=True, timeout=(5, 60)) as r:
                for line in r.iter_lines(decode_unicode=True):
                    if done.is_set():
                        break
                    if not line or not line.startswith("data: "):
                        continue
                    m = json.loads(line[6:])
                    if m.get("type") == "created" and state["task"] is None:
                        state["task"] = m["task"]["id"]
                    elif m.get("type") == "event" and m.get("task_id") == state["task"]:
                        ev = m.get("ev", {})
                        if ev.get("type") == "final":
                            state["final"] = ev.get("text", "")
                            done.set()
                        elif ev.get("type") == "confirm":
                            state["confirm"] = True
        except Exception:
            pass

    th = threading.Thread(target=listen, daemon=True)
    th.start()
    time.sleep(0.3)
    requests.post(f"{base}/api/cmd", params={"sid": sid}, headers=h, json={"type": "new", "text": text}, timeout=10)
    done.wait(wait)
    done.set()
    if state["final"] is not None:
        return _spoken(state["final"])
    if state["confirm"]:
        return "J'ai besoin de ton accord pour continuer : regarde l'app Jarvis."
    return "C'est parti. Je te préviens dès que c'est terminé."


def main(argv: list[str]):
    wait = 25.0
    if "--wait" in argv:
        i = argv.index("--wait")
        wait = float(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    text = " ".join(argv) if argv else sys.stdin.read()
    print(ask(text, wait))


# ---------------------------------------------------------------------- Raccourci Siri
def _attach(uuid: str, name: str) -> dict:
    return {"Value": {"OutputUUID": uuid, "Type": "ActionOutput", "OutputName": name}, "WFSerializationType": "WFTextTokenAttachment"}


def _token_string(uuid: str, name: str) -> dict:
    return {"Value": {"string": "￼", "attachmentsByRange": {"{0, 1}": {"OutputUUID": uuid, "Type": "ActionOutput",
                                                                           "OutputName": name}}},
            "WFSerializationType": "WFTextTokenString"}


def build_shortcut(out_dir: Path) -> tuple[Path | None, str]:
    """Crée « Jarvis.shortcut » (Demander → Jarvis → Afficher le résultat), le signe, et renvoie son chemin."""
    jarvis_bin = Path.home() / ".local" / "bin" / "jarvis"
    ask_id, sh_id = "6F1C2E1A-0A11-4C5B-9E1D-1A2B3C4D5E01", "6F1C2E1A-0A11-4C5B-9E1D-1A2B3C4D5E02"
    wf = {
        "WFWorkflowMinimumClientVersion": 900, "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowClientVersion": "2607.0.3",
        "WFWorkflowIcon": {"WFWorkflowIconStartColor": 4292093695, "WFWorkflowIconGlyphNumber": 59511},
        "WFWorkflowTypes": ["MenuBar", "QuickActions"], "WFWorkflowImportQuestions": [],
        "WFWorkflowInputContentItemClasses": ["WFStringContentItem"], "WFWorkflowHasShortcutInputVariables": False,
        "WFWorkflowActions": [
            {"WFWorkflowActionIdentifier": "is.workflow.actions.ask",
             "WFWorkflowActionParameters": {"UUID": ask_id, "WFAskActionPrompt": "Que veux-tu demander à Jarvis ?",
                                            "WFInputType": "Text"}},
            {"WFWorkflowActionIdentifier": "is.workflow.actions.runshellscript",
             "WFWorkflowActionParameters": {"UUID": sh_id, "Shell": "/bin/zsh", "InputMode": "to stdin",
                                            "Script": f"'{jarvis_bin}' siri --stdin",
                                            "Input": _attach(ask_id, "Texte fourni")}},
            {"WFWorkflowActionIdentifier": "is.workflow.actions.showresult",
             "WFWorkflowActionParameters": {"Text": _token_string(sh_id, "Résultat du script shell")}},
        ],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / "Jarvis-non-signe.shortcut"
    signed = out_dir / "Jarvis.shortcut"
    raw.write_bytes(plistlib.dumps(wf, fmt=plistlib.FMT_BINARY))
    r = subprocess.run(["shortcuts", "sign", "--mode", "anyone", "--input", str(raw), "--output", str(signed)],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0 or not signed.exists():
        return None, (r.stderr or r.stdout).strip()[:300]
    return signed, ""


# ---------------------------------------------------------------------- Raccourcis pour l'iPhone
def _text(s: str) -> dict:
    return {"Value": {"string": s, "attachmentsByRange": {}}, "WFSerializationType": "WFTextTokenString"}


def _dict_field(items: list[tuple[str, dict]]) -> dict:
    return {"Value": {"WFDictionaryFieldValueItems": [
        {"WFItemType": 0, "WFKey": _text(k), "WFValue": v} for k, v in items]},
        "WFSerializationType": "WFDictionaryFieldValue"}


def _post(uuid: str, url: str, key: str, body: dict | None = None, file_from: dict | None = None) -> dict:
    p = {"UUID": uuid, "WFURL": url, "WFHTTPMethod": "POST", "ShowHeaders": True,
         "WFHTTPHeaders": _dict_field([("X-Jarvis-Token", _text(key))])}
    if file_from is not None:
        p.update(WFHTTPBodyType="File", WFRequestVariable=file_from)
    else:
        p.update(WFHTTPBodyType="JSON", WFJSONValues=_dict_field(list((body or {}).items())))
    return {"WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl", "WFWorkflowActionParameters": p}


def _get(uuid: str, key: str, src: str) -> dict:
    return {"WFWorkflowActionIdentifier": "is.workflow.actions.getvalueforkey",
            "WFWorkflowActionParameters": {"UUID": uuid, "WFDictionaryKey": key, "WFInput": _attach(src, "Contenu de l'URL")}}


def ios_workflows(base_url: str, key: str) -> dict[str, dict]:
    """Deux raccourcis iPhone qui parlent à Jarvis sur le Mac (via Tailscale, en HTTPS) avec une clé LIMITÉE :
    « Jarvis » (Siri, bouton Action) et « Envoyer à Jarvis » (bouton Partager : photo, PDF, lien…)."""
    base = base_url.rstrip("/")
    common = {"WFWorkflowMinimumClientVersion": 900, "WFWorkflowMinimumClientVersionString": "900",
              "WFWorkflowClientVersion": "2607.0.3", "WFWorkflowImportQuestions": [], "WFWorkflowHasShortcutInputVariables": False}
    u = [f"6F1C2E1A-0A11-4C5B-9E1D-1A2B3C4D5F{i:02d}" for i in range(20)]
    ask = {**common,
           "WFWorkflowIcon": {"WFWorkflowIconStartColor": 4292093695, "WFWorkflowIconGlyphNumber": 59511},
           "WFWorkflowTypes": ["Watch"], "WFWorkflowInputContentItemClasses": ["WFStringContentItem"],
           "WFWorkflowActions": [
               {"WFWorkflowActionIdentifier": "is.workflow.actions.ask",
                "WFWorkflowActionParameters": {"UUID": u[0], "WFAskActionPrompt": "Que veux-tu demander à Jarvis ?",
                                               "WFInputType": "Text"}},
               _post(u[1], f"{base}/api/ask", key, {"text": _token_string(u[0], "Texte fourni")}),
               _get(u[2], "answer", u[1]),
               {"WFWorkflowActionIdentifier": "is.workflow.actions.showresult",
                "WFWorkflowActionParameters": {"Text": _token_string(u[2], "Valeur du dictionnaire")}}]}
    share = {**common,
             "WFWorkflowIcon": {"WFWorkflowIconStartColor": 4292093695, "WFWorkflowIconGlyphNumber": 59446},
             "WFWorkflowTypes": ["ActionExtension"],
             "WFWorkflowInputContentItemClasses": ["WFImageContentItem", "WFPDFContentItem", "WFGenericFileContentItem",
                                                   "WFURLContentItem", "WFStringContentItem", "WFRichTextContentItem"],
             "WFWorkflowActions": [
                 _post(u[5], f"{base}/api/upload?name=partage", key,
                       file_from={"Value": {"Type": "ExtensionInput"}, "WFSerializationType": "WFTextTokenAttachment"}),
                 _get(u[6], "path", u[5]),
                 {"WFWorkflowActionIdentifier": "is.workflow.actions.ask",
                  "WFWorkflowActionParameters": {"UUID": u[7], "WFAskActionPrompt": "Que dois-je en faire ?", "WFInputType": "Text",
                                                 "WFAskActionDefaultAnswer": "Résume ou décris ce que je t'envoie."}},
                 _post(u[8], f"{base}/api/ask", key, {"text": _token_string(u[7], "Texte fourni"),
                                                      "file": _token_string(u[6], "Valeur du dictionnaire")}),
                 _get(u[9], "answer", u[8]),
                 {"WFWorkflowActionIdentifier": "is.workflow.actions.showresult",
                  "WFWorkflowActionParameters": {"Text": _token_string(u[9], "Valeur du dictionnaire")}}]}
    return {"Jarvis": ask, "Envoyer à Jarvis": share}


def build_ios_shortcuts(out_dir: Path, base_url: str, key: str) -> tuple[list[Path], str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    done, errs = [], []
    for name, wf in ios_workflows(base_url, key).items():
        raw = out_dir / f"{name}-non-signe.shortcut"
        signed = out_dir / f"{name}.shortcut"
        raw.write_bytes(plistlib.dumps(wf, fmt=plistlib.FMT_BINARY))
        r = subprocess.run(["shortcuts", "sign", "--mode", "anyone", "--input", str(raw), "--output", str(signed)],
                           capture_output=True, text=True, timeout=120)
        raw.unlink(missing_ok=True)                # la version non signée contient la clé : on ne la garde pas
        if r.returncode == 0 and signed.exists():
            os.chmod(signed, 0o600)
            done.append(signed)
        else:
            errs.append((r.stderr or r.stdout).strip()[:200])
    return done, " · ".join(errs)
