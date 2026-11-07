"""
Navigateur de Jarvis (Playwright + Chromium, gratuit) — un navigateur indépendant par tâche (tâches parallèles),
sessions (cookies) partagées via ~/.jarvis/browser-state.json. Tes navigateurs personnels ne sont jamais touchés.
Tout contenu lu sur une page est marqué « externe » (anti-injection).
"""
from __future__ import annotations

import os
import re
import threading

import config
from registry import B, S, Ctx, tool, trunc
from security import BLOCKED, NORMAL, RISKY, SAFE

_local = threading.local()
_state_lock = threading.Lock()


def _page():
    b = getattr(_local, "b", None)
    if b and not b["page"].is_closed():
        return b["page"]
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=bool(Ctx.cfg.get("browser_headless", True)))
    kw = {"viewport": {"width": 1280, "height": 860}, "locale": "fr-FR", "accept_downloads": False}
    if config.BROWSER_STATE.exists():
        kw["storage_state"] = str(config.BROWSER_STATE)
    ctx = browser.new_context(**kw)
    page = ctx.new_page()
    _local.b = {"pw": pw, "browser": browser, "ctx": ctx, "page": page}
    return page


def close_for_thread():
    b = getattr(_local, "b", None)
    if not b:
        return
    try:
        with _state_lock:
            b["ctx"].storage_state(path=str(config.BROWSER_STATE))
            os.chmod(config.BROWSER_STATE, 0o600)
    except Exception:
        pass
    for k in ("ctx", "browser"):
        try:
            b[k].close()
        except Exception:
            pass
    try:
        b["pw"].stop()
    except Exception:
        pass
    _local.b = None


SNAP_JS = """() => {
  const out = []; let i = 0;
  document.querySelectorAll('[data-jarvis-id]').forEach(e => e.removeAttribute('data-jarvis-id'));
  for (const el of document.querySelectorAll('a,button,input,textarea,select,[role=button],[role=link],[role=tab],[contenteditable=true]')) {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2 || getComputedStyle(el).visibility === 'hidden') continue;
    el.setAttribute('data-jarvis-id', String(++i));
    const label = (el.innerText || el.value || el.getAttribute('aria-label') || el.placeholder || el.name || el.title || '').trim().replace(/\\s+/g,' ').slice(0, 80);
    out.push(`[${i}] <${el.tagName.toLowerCase()}${el.type ? ' type='+el.type : ''}> ${label}`);
    if (i >= 150) break;
  }
  return {title: document.title, url: location.href, text: document.body ? document.body.innerText.slice(0, 24000) : '', els: out};
}"""


def _snapshot(page, limit=9000) -> str:
    d = page.evaluate(SNAP_JS)
    text = re.sub(r"\n\s*\n+", "\n", d["text"])
    return trunc(f"Titre : {d['title']}\nURL : {d['url']}\n\n--- Contenu ---\n{text[:limit]}\n\n--- Éléments interactifs ---\n"
                 + "\n".join(d["els"]), 15000)


def _settle(page, ms=6000):
    try:
        page.wait_for_load_state("networkidle", timeout=ms)
    except Exception:
        pass


def _risk_nav(url):
    if not re.match(r"^(https?|file)://", url):
        return BLOCKED, "schéma d'URL non autorisé"
    if Ctx.policy.tainted and "?" in url and not re.match(r"^https?://(127\.0\.0\.1|localhost)", url):
        return RISKY, "URL avec paramètres après lecture de contenu externe"
    return SAFE, ""


@tool("browser_open", "Ouvre une URL dans le navigateur de Jarvis et renvoie le texte + les éléments cliquables numérotés. "
                      "Parfait pour tester un site local (http://127.0.0.1:PORT).",
      {"url": S("URL")}, category="browser", risk=_risk_nav, untrusted=True)
def browser_open(url: str):
    page = _page()
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    _settle(page)
    return _snapshot(page)


@tool("browser_read", "Relit la page actuelle (texte + éléments numérotés).", {}, [], category="browser", untrusted=True)
def browser_read():
    return _snapshot(_page())


def _locate(page, target: str):
    t = target.strip()
    if re.fullmatch(r"\[?\d+\]?", t):
        return page.locator(f'[data-jarvis-id="{t.strip("[]")}"]').first
    if t.startswith(("css=", "#", ".", "//", "xpath=")) or re.match(r"^[a-z]+\[", t):
        return page.locator(t).first
    for role in ("button", "link", "tab", "menuitem"):
        loc = page.get_by_role(role, name=t)
        if loc.count():
            return loc.first
    return page.get_by_text(t, exact=False).first


IRREVERSIBLE = re.compile(r"(payer|paiement|pay\b|acheter|buy|commander|order|checkout|supprimer|delete|envoyer|send|"
                          r"publier|publish|confirm|valider|s'inscrire|sign ?up|transférer|transfer|souscrire|subscribe)", re.I)


@tool("browser_click", "Clique sur un élément : numéro [n] (voir browser_read), texte visible, ou sélecteur CSS.",
      {"target": S("Numéro, texte ou sélecteur")}, category="browser",
      risk=lambda target: (RISKY, "clic potentiellement irréversible (achat, envoi, suppression, publication)")
      if IRREVERSIBLE.search(target) else (NORMAL, ""), untrusted=True)
def browser_click(target: str):
    page = _page()
    loc = _locate(page, target)
    label = ""
    try:
        label = (loc.inner_text(timeout=2000) or "")[:80]
    except Exception:
        pass
    if IRREVERSIBLE.search(label) and not IRREVERSIBLE.search(target):
        return f"[refusé] le bouton visé s'intitule « {label} » (action irréversible) : appelle browser_click avec ce texte exact pour demander confirmation."
    loc.click(timeout=10000)
    _settle(page, 8000)
    return "Cliqué.\n" + _snapshot(page, 5000)


def _risk_type(target, text, **k):
    if re.search(r"(password|mot.de.passe|passcode|card|carte|cvv|cvc|iban|ssn|code.secret)", target, re.I):
        return BLOCKED, "saisie d'identifiants ou de données bancaires : à faire toi-même"
    if Ctx.policy.tainted and len(text) > 200:
        return RISKY, "saisie d'un long texte après lecture de contenu externe"
    return NORMAL, ""


@tool("browser_type", "Remplit un champ (numéro [n], libellé ou sélecteur). submit=true appuie sur Entrée.",
      {"target": S("Champ"), "text": S("Texte"), "submit": B("Valider avec Entrée")},
      ["target", "text"], category="browser", risk=_risk_type,
      summary=lambda target, text, **k: f"saisir « {text[:80]} » dans {target}")
def browser_type(target: str, text: str, submit: bool = False):
    page = _page()
    loc = _locate(page, target)
    if not loc.count():
        loc = page.get_by_label(target).first
    try:
        if (loc.get_attribute("type", timeout=2000) or "").lower() == "password":
            return "[refusé] champ mot de passe : à remplir toi-même."
    except Exception:
        pass
    loc.fill(text, timeout=10000)
    if submit:
        loc.press("Enter")
        _settle(page, 8000)
    return "Saisi." + ("\n" + _snapshot(page, 4000) if submit else "")


@tool("browser_screenshot", "Capture la page et la fait décrire par le modèle vision (rendu d'un site, mise en page).",
      {"question": S("Question"), "full_page": B("Page entière")}, ["question"], category="browser", untrusted=True)
def browser_screenshot(question: str, full_page: bool = False):
    page = _page()
    p = config.SCREENS_DIR / f"browser_{Ctx.task_id or 'cli'}.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(p), full_page=bool(full_page))
    vb = Ctx.router.vision_backend if Ctx.router else None
    if not vb:
        return f"Capture : {p} (pas de modèle vision installé)"
    return vb.vision(question, str(p))


@tool("browser_close", "Ferme le navigateur de cette tâche (sessions conservées).", {}, [], category="meta")
def browser_close():
    close_for_thread()
    return "Navigateur fermé."
