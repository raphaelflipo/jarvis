"""
Calendrier, Rappels et Notes du Mac — 100 % local.

Calendrier et Rappels passent par jarvis-agenda (EventKit, dans Jarvis.app) : rapide, et les événements répétés
(cours chaque semaine…) sont bien vus. Notes passe par AppleScript. macOS demande l'accès une seule fois, au nom de
« Jarvis ».
"""
from __future__ import annotations

import datetime
import json
import re
import shutil
import subprocess
from pathlib import Path

import config
from registry import I, S, tool

HELPER_PATHS = (Path("/Applications/Jarvis.app/Contents/MacOS/jarvis-agenda"),
                Path.home() / "Applications" / "Jarvis.app" / "Contents" / "MacOS" / "jarvis-agenda")
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def helper() -> Path | None:
    for p in HELPER_PATHS + (config.JARVIS_DIR / "bin" / "jarvis-agenda",):
        if p.exists():
            return p
    return None


def _run(*args, timeout=150) -> dict | list:
    exe = helper()
    if not exe:
        return {"error": "Outil Calendrier/Rappels absent : relance l'installateur de Jarvis (il le compile sur ton Mac)."}
    try:
        r = subprocess.run([str(exe), *[str(a) for a in args]], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"error": "Pas de réponse de macOS. Dans Jarvis : Réglages › Général › Calendrier et Rappels › « Autoriser », "
                         "puis clique sur « Autoriser » dans la fenêtre de macOS."}
    try:
        return json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {"error": (r.stderr or "aucune réponse")[:300]}
    except ValueError:
        return {"error": (r.stdout or r.stderr)[:300]}


def status() -> dict:
    """Autorisations macOS (sans rien demander) : autorise | refuse | pas_demande | absent."""
    if not helper():
        return {"calendar": "absent", "reminders": "absent"}
    res = _run("status", timeout=10)
    return res if isinstance(res, dict) and "calendar" in res else {"calendar": "absent", "reminders": "absent"}


def norm_date(text: str, end_of_day=False) -> str:
    """« 2026-11-07 14:00 », « 2026-11-07T14:00 », « 07/11/2026 14h30 » ou « 2026-11-07 » → forme ISO locale."""
    t = (text or "").strip()
    if not t:
        return ""
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})(?:[ T](\d{1,2})[h:](\d{2})?)?", t)
    if m:
        d, mo, y, hh, mm = m.groups()
        t = f"{y}-{int(mo):02d}-{int(d):02d}" + (f"T{int(hh):02d}:{int(mm or 0):02d}" if hh else "")
    t = re.sub(r"(\d{1,2})h(\d{2})?$", lambda x: f"{int(x.group(1)):02d}:{x.group(2) or '00'}", t).replace(" ", "T")
    t = re.sub(r"T(\d):", r"T0\1:", t)            # « 9:05 » → « 09:05 »
    try:
        if len(t) == 10:
            datetime.date.fromisoformat(t)
            return t
        return datetime.datetime.fromisoformat(t).strftime("%Y-%m-%dT%H:%M:%S")
    except ValueError:
        raise ValueError(f"date illisible : « {text} » (attendu : AAAA-MM-JJ HH:MM)")


def _when(s: str) -> str:
    if not s:
        return ""
    try:
        d = datetime.datetime.fromisoformat(s)
    except ValueError:
        return s
    return f"{JOURS[d.weekday()]} {d.day:02d}/{d.month:02d}" + ("" if (d.hour, d.minute) == (0, 0) else f" {d.hour:02d}h{d.minute:02d}")


def _err(res) -> str | None:
    return res.get("error") if isinstance(res, dict) and res.get("error") else None


@tool("agenda_events", "Événements du Calendrier du Mac (tous les calendriers, répétitions comprises) à partir d'une date. "
      "Pour « qu'est-ce que j'ai demain / cette semaine ».",
      {"days": I("Nombre de jours (défaut 7, max 62)"), "from_date": S("Début AAAA-MM-JJ (défaut : aujourd'hui)")}, [],
      untrusted=True)        # une invitation reçue peut contenir n'importe quel texte
def agenda_events(days: int = 7, from_date: str = ""):
    start = datetime.date.fromisoformat(norm_date(from_date)[:10]) if from_date else datetime.date.today()
    days = max(1, min(int(days or 7), 62))
    res = _run("events", start.isoformat(), (start + datetime.timedelta(days=days)).isoformat())
    if _err(res):
        return _err(res)
    if not res:
        return f"Aucun événement du {start.strftime('%d/%m')} au {(start + datetime.timedelta(days=days - 1)).strftime('%d/%m')}."
    lines = []
    for e in res:
        when = _when(e["start"]) if not e.get("all_day") else f"{_when(e['start'][:10])} (journée)"
        end = "" if e.get("all_day") else f" → {e['end'][11:16].replace(':', 'h')}"
        lines.append(f"• {when}{end} — {e['title']}" + (f" ({e['location']})" if e.get("location") else "")
                     + f" [{e['calendar']}]")
    return "\n".join(lines)


@tool("agenda_add_event", "Ajoute un événement au Calendrier du Mac. Dates « AAAA-MM-JJ HH:MM » (ou « AAAA-MM-JJ » pour "
      "toute la journée) ; fin par défaut : 1 h après.",
      {"title": S("Titre"), "start": S("Début"), "end": S("Fin (facultatif)"), "calendar": S("Nom du calendrier (facultatif)"),
       "location": S("Lieu (facultatif)"), "notes": S("Notes (facultatif)")}, ["title", "start"], category="write")
def agenda_add_event(title: str, start: str, end: str = "", calendar: str = "", location: str = "", notes: str = ""):
    res = _run("add-event", title.strip()[:200], norm_date(start), norm_date(end) if end else "", calendar, location[:200], notes[:2000])
    if _err(res):
        return _err(res)
    return f"Événement ajouté : « {res['title']} », {_when(res['start'])} → {res['end'][11:16].replace(':', 'h')} [{res['calendar']}]."


@tool("reminders_list", "Rappels du Mac (à faire, triés par échéance).", {"include_done": {"type": "boolean",
      "description": "Inclure les rappels terminés"}}, [], untrusted=True)
def reminders_list(include_done: bool = False):
    res = _run("reminders", "all" if include_done else "todo")
    if _err(res):
        return _err(res)
    if not res:
        return "Aucun rappel à faire."
    return "\n".join(f"• {'✓ ' if r.get('done') else ''}{r['title']}" + (f" — {_when(r['due'])}" if r.get("due") else "")
                     + f" [{r['list']}]" for r in res[:150])


@tool("reminder_add", "Ajoute un rappel (app Rappels du Mac, synchronisé avec l'iPhone par iCloud). Échéance « AAAA-MM-JJ HH:MM » "
      "(avec alerte) ou « AAAA-MM-JJ ».",
      {"title": S("Texte du rappel"), "due": S("Échéance (facultatif)"), "list_name": S("Liste (facultatif)")}, ["title"],
      category="write")
def reminder_add(title: str, due: str = "", list_name: str = ""):
    res = _run("add-reminder", title.strip()[:300], norm_date(due) if due else "", list_name)
    if _err(res):
        return _err(res)
    return f"Rappel ajouté : « {res['title']} »" + (f", {_when(norm_date(due))}" if due else "") + f" [{res['list']}]."


def _osa(script: str, *args, timeout=60) -> tuple[bool, str]:
    if not shutil.which("osascript"):
        return False, "AppleScript indisponible."
    r = subprocess.run(["osascript", "-e", script, *args], capture_output=True, text=True, timeout=timeout)
    return r.returncode == 0, (r.stdout if r.returncode == 0 else r.stderr).strip()


def _html(text: str) -> str:
    esc = (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return "<br>".join(esc.splitlines())


@tool("note_create", "Crée une note dans l'app Notes du Mac (synchronisée avec l'iPhone par iCloud).",
      {"title": S("Titre"), "body": S("Contenu (texte, retours à la ligne permis)"), "folder": S("Dossier (facultatif)")},
      ["title", "body"], category="write")
def note_create(title: str, body: str, folder: str = ""):
    script = '''on run argv
  set t to item 1 of argv
  set b to item 2 of argv
  set f to item 3 of argv
  tell application "Notes"
    if f is "" then
      set n to make new note with properties {name:t, body:b}
    else
      if not (exists folder f) then make new folder with properties {name:f}
      set n to make new note at folder f with properties {name:t, body:b}
    end if
    return name of n
  end tell
end run'''
    ok, out = _osa(script, title.strip()[:200], f"<h1>{_html(title.strip()[:200])}</h1>{_html(body[:20000])}", folder.strip()[:100])
    return f"Note créée : « {out} »" + (f" dans « {folder} »." if folder else ".") if ok else f"Notes : {out[:300]}"


@tool("notes_search", "Cherche dans les notes de l'app Notes (titre et contenu) et renvoie les extraits.",
      {"query": S("Mot ou expression"), "max_results": I("≤ 20")}, ["query"], untrusted=True)
def notes_search(query: str, max_results: int = 8):
    script = '''on run argv
  set q to item 1 of argv
  set n to (item 2 of argv) as integer
  set out to ""
  tell application "Notes"
    set found to (every note whose name contains q or plaintext contains q)
    set k to 0
    repeat with x in found
      set k to k + 1
      if k > n then exit repeat
      set p to plaintext of x
      if (length of p) > 400 then set p to text 1 thru 400 of p
      set out to out & "• " & (name of x) & " — " & (modification date of x as string) & linefeed & p & linefeed & "---" & linefeed
    end repeat
  end tell
  return out
end run'''
    ok, out = _osa(script, query.strip()[:100], str(max(1, min(int(max_results or 8), 20))), timeout=90)
    if not ok:
        return f"Notes : {out[:300]}"
    return out or f"Aucune note ne contient « {query} »."
