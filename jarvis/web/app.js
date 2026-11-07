/* ==========================================================================
   JARVIS — interface temps réel (tâches parallèles, streaming, confirmations)
   ========================================================================== */
"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
function copyText(t) {
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(t);
  return new Promise((ok) => { const a = document.createElement("textarea"); a.value = t; a.style.position = "fixed"; a.style.opacity = "0";
    document.body.appendChild(a); a.select(); try { document.execCommand("copy"); } catch (_) {} a.remove(); ok(); });
}
function h(tag, cls, html) { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }

const ACTIVE = new Set(["running", "waiting", "queued"]);
const STATUS_TXT = { running: "En cours", queued: "En file d'attente", waiting: "Attend ton accord", done: "Terminé", error: "Erreur", stopped: "Arrêtée", idle: "Prête" };
const TOOL_UI = {
  run_shell: ["⌘", "Commande"], start_background: ["▶", "Processus en fond"], stop_background: ["■", "Arrêt processus"], read_log: ["≣", "Journal du processus"],
  read_file: ["📄", "Lecture"], write_file: ["✎", "Écriture"], edit_file: ["✎", "Modification"], apply_patch: ["±", "Patch"],
  list_dir: ["📁", "Dossier"], search_files: ["⌕", "Recherche"], code_map: ["🗺", "Carte du projet"], semantic_search: ["✦", "Recherche par le sens"],
  build_project: ["⚙", "Compilation"], run_on_simulator: ["📱", "Simulateur iOS"], git: ["⎇", "Git"], github: ["⎇", "GitHub"],
  firebase: ["🔥", "Firebase"], deploy_website: ["🚀", "Publication du site"], web_search: ["🌐", "Recherche web"], fetch_url: ["↓", "Page web"],
  browser_open: ["🧭", "Navigateur"], browser_read: ["🧭", "Lecture de page"], browser_click: ["🧭", "Clic web"], browser_type: ["🧭", "Saisie web"],
  browser_screenshot: ["🧭", "Aperçu de page"], browser_close: ["🧭", "Navigateur fermé"], applescript: ["✳", "Automatisation macOS"],
  open_app: ["↗", "Ouverture"], open_in_editor: ["</>", "Éditeur"], notify: ["🔔", "Notification"], clipboard: ["⎘", "Presse-papiers"],
  look_at_screen: ["👁", "Écran"], mouse_click: ["🖱", "Clic"], type_text: ["⌨", "Saisie"], press_keys: ["⌨", "Raccourci"],
  create_word: ["W", "Document Word"], create_powerpoint: ["P", "Présentation"], create_excel: ["X", "Classeur Excel"], edit_office: ["✎", "Retouche Office"],
  ssh_run: ["⇄", "SSH"], ssh_copy: ["⇄", "Transfert SSH"], http_request: ["⇅", "Requête HTTP"], net_check: ["◎", "Test réseau"],
  network_info: ["◎", "Réseau"], notify_phone: ["📲", "Notification téléphone"], schedule_task: ["⏰", "Planification"],
  list_scheduled: ["⏰", "Tâches planifiées"], remove_scheduled: ["⏰", "Suppression planification"], remember: ["🧠", "Mémoire"],
  run_parallel: ["⫸", "Sous-tâches en parallèle"], analyze_file: ["👁", "Analyse visuelle"], convert_file: ["⇆", "Conversion"],
  code_map: ["🗺", "Carte du projet"], deep_research: ["🔎", "Recherche approfondie"],
  agenda_events: ["📅", "Calendrier"], agenda_add_event: ["📅", "Ajout au calendrier"], reminders_list: ["☑️", "Rappels"],
  reminder_add: ["☑️", "Nouveau rappel"], note_create: ["🗒", "Nouvelle note"], notes_search: ["🗒", "Recherche dans Notes"],
  generate_image: ["🎨", "Création d'image"],
};
const SUGGEST = [
  ["🌐", "Créer un site", "Site vitrine responsive, testé puis publié", "Crée un site vitrine moderne et responsive pour "],
  ["🛠", "Réparer un projet", "Compile, corrige les erreurs, lance les tests", "Ouvre mon projet ~/ , compile-le, corrige les erreurs et lance les tests"],
  ["📊", "Présentation", "Diapos soignées avec graphiques", "Fais une présentation de 10 diapositives sur "],
  ["📈", "Tableur", "Formules, mise en forme, graphiques", "Crée un tableur Excel pour suivre "],
  ["🔎", "Recherche approfondie", "Plusieurs sources lues, rapport sourcé", "@research"],
  ["🖥", "Mon Mac", "Fichiers, apps, rappels, réseau", "Range mon dossier Téléchargements par type de fichier"],
];

const S = {
  ws: null, token: "", connected: false, remote: false, tasks: new Map(), current: null,
  view: null, pending: new Map(), settings: null, stream: null, typing: null, search: "", tab: "general", backoff: 800,
  att: [], submitWhenReady: false,
};

/* état du transport (WebSocket ou flux HTTP de secours) */
const T = { mode: "ws", sid: null, wsFails: 0, abort: null, gen: 0, helloTimer: null };
try { localStorage.removeItem("jarvisTransport"); } catch (_) {}   // le WebSocket est retenté à chaque ouverture

/* ------------------------------------------------------------------ démarrage */
(function init() {
  const q = new URLSearchParams(location.search);
  if (q.get("app")) document.body.classList.add("app");
  if (q.get("glass")) document.body.classList.add("glass-native");
  const tk = location.hash.match(/task=([\w-]+)/);           // ouverture depuis une notification
  if (tk) { S.current = tk[1]; history.replaceState(null, "", location.pathname + location.search); }
  const m = location.hash.match(/(?:^#|&)t=([^&]+)/);
  if (m) {
    S.token = decodeURIComponent(m[1]);
    try { localStorage.setItem("jarvisToken", S.token); } catch (_) {}
    history.replaceState(null, "", location.pathname + location.search);
  } else {
    try { S.token = localStorage.getItem("jarvisToken") || ""; } catch (_) {}
  }
  const hr = new Date().getHours();
  $("#greet").textContent = hr < 5 ? "Bonne nuit." : hr < 12 ? "Bonjour." : hr < 18 ? "Bon après-midi." : "Bonsoir.";
  const sg = $("#suggest");
  SUGGEST.forEach(([ic, t, d, p]) => {
    const c = h("button", "card-s glass", `<div class="ic">${ic}</div><b>${esc(t)}</b><small>${esc(d)}</small>`);
    c.type = "button";
    c.onclick = () => {
      const i = $("#input");
      if (p === "@research") { setResearch(true); i.focus(); return; }
      i.value = p; i.focus(); i.setSelectionRange(p.length, p.length); grow();
    };
    sg.appendChild(c);
  });
  bindUI();
  showHome();
  connect();
})();

/* ------------------------------------------------------------------ connexion
   1) WebSocket (rapide) ; 2) si échec, flux HTTP de secours (SSE via fetch) — choisi automatiquement. */

function connect() {
  if (!S.token) { $("#login").hidden = false; setTimeout(() => $("#tokenInput").focus(), 50); return; }
  T.gen++;
  if (T.mode === "http") { connectHTTP(T.gen); return; }
  let ws;
  try { ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws"); }
  catch (_) { wsFailed(); return; }
  S.ws = ws;
  let gotHello = false;
  clearTimeout(T.helloTimer);
  T.helloTimer = setTimeout(() => { if (!gotHello) { try { ws.close(); } catch (_) {} } }, 6000);
  ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token: S.token }));
  ws.onmessage = (e) => {
    let m; try { m = JSON.parse(e.data); } catch (_) { return; }
    if (m.type === "hello") { gotHello = true; T.wsFails = 0; clearTimeout(T.helloTimer); }
    try { handle(m); } catch (err) { console.error(err); }
  };
  ws.onclose = (e) => {
    clearTimeout(T.helloTimer);
    if (S.ws === ws) S.ws = null;
    setConn(false);
    if (e.code === 4401 || e.code === 4403) { if (e.code === 4403) wsFailed(); return; }
    if (!gotHello) { wsFailed(); return; }
    retry();
  };
}
function wsFailed() {
  T.wsFails++;
  if (T.wsFails >= 2) {                       // le WebSocket ne passe pas : flux HTTP pour cette session
    T.mode = "http";
    setTimeout(() => { if (T.mode === "http") { T.wsFails = 0; T.mode = "ws"; T.gen++; if (T.abort) T.abort.abort(); connect(); } }, 300000);
  }
  retry();
}
function retry() { setTimeout(connect, S.backoff); S.backoff = Math.min(S.backoff * 1.6, 8000); }

async function connectHTTP(gen) {
  const H = { "X-Jarvis-Token": S.token };
  let sid;
  try {
    const r = await fetch("/api/session", { method: "POST", headers: H });
    if (r.status === 401) { handle(await r.json()); return; }
    if (!r.ok) throw new Error("HTTP " + r.status);
    sid = (await r.json()).sid;
  } catch (e) { setConn(false); retry(); return; }
  T.sid = sid;
  const ctrl = new AbortController(); T.abort = ctrl;
  try {
    const r = await fetch(`/api/events?sid=${encodeURIComponent(sid)}`, { headers: H, signal: ctrl.signal, cache: "no-store" });
    if (!r.ok || !r.body) throw new Error("flux " + r.status);
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf = "";
    while (gen === T.gen) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        const data = chunk.split("\n").filter((l) => l.startsWith("data: ")).map((l) => l.slice(6)).join("\n");
        if (data) { try { handle(JSON.parse(data)); } catch (err) { console.error(err); } }
      }
    }
  } catch (e) { /* coupure : on se reconnecte */ }
  if (gen !== T.gen) return;
  T.sid = null; setConn(false);
  // si le flux HTTP échoue alors que le WebSocket n'a pas été essayé récemment, on retente le WebSocket
  if (T.wsFails < 2) { T.mode = "ws"; }
  retry();
}

function send(obj) {
  if (T.mode === "ws" && S.ws && S.ws.readyState === 1) { S.ws.send(JSON.stringify(obj)); return true; }
  if (T.mode === "http" && T.sid) {
    fetch(`/api/cmd?sid=${encodeURIComponent(T.sid)}`, { method: "POST", headers: { "X-Jarvis-Token": S.token, "Content-Type": "application/json" }, body: JSON.stringify(obj) })
      .then((r) => { if (r.status === 401) { T.sid = null; T.gen++; connect(); } })
      .catch(() => toast("Commande non transmise — reconnexion…"));
    return true;
  }
  toast("Pas encore connecté au Mac — nouvelle tentative…");
  return false;
}
function setConn(on) {
  S.connected = on;
  const c = $("#conn"); c.classList.toggle("on", on);
  c.querySelector("span").textContent = on ? (S.remote ? "Connecté à distance" : "Connecté") + (T.mode === "http" ? " · mode compatible" : "") : "Reconnexion…";
}

function handle(m) {
  switch (m.type) {
    case "auth_failed":
      try { localStorage.removeItem("jarvisToken"); } catch (_) {}
      S.token = ""; $("#login").hidden = false;
      $("#loginErr").textContent = m.locked ? "Trop d'essais : réessaie dans 10 minutes." : "Jeton invalide.";
      break;
    case "hello":
      S.backoff = 800; S.remote = m.remote; setConn(true); $("#login").hidden = true; pinManifest();
      S.tasks = new Map(m.tasks.map((t) => [t.id, t]));
      S.pending = new Map((m.pending || []).map((p) => [p.cid, p]));
      $("#modelChip").textContent = m.model;
      S.power = m.power || null;
      renderSidebar(); renderToasts();
      if (S.current && S.tasks.has(S.current)) openTask(S.current); else if (S.current) showHome();
      send({ type: "settings_get" });
      break;
    case "tasks": S.tasks = new Map(m.tasks.map((t) => [t.id, t])); renderSidebar(); break;
    case "power": {
      const was = S.power && S.power.battery;
      S.power = m.power; renderStatusRow();
      const wasHot = S.powerHot; S.powerHot = (m.power.thermal || 0) >= 2;
      if (S.powerHot && !wasHot) toast("Le Mac chauffe : macOS ralentit la puce. Jarvis passe à une tâche à la fois le temps qu'il refroidisse.");
      else if (!S.powerHot && wasHot) toast("Le Mac a refroidi : retour à la vitesse normale.");
      if (m.power.battery && !was) toast("Mac sur batterie : macOS ralentit le modèle (environ 40 %). Branche-le pour les grosses tâches.");
      else if (!m.power.battery && was) toast("Mac sur secteur : pleine vitesse.");
      break;
    }
    case "task": {
      S.tasks.set(m.task.id, m.task); renderSidebar();
      if (m.task.id === S.current) renderTop();
      break;
    }
    case "created": S.tasks.set(m.task.id, m.task); renderSidebar(); openTask(m.task.id); break;
    case "deleted": S.tasks.delete(m.task_id); renderSidebar(); if (S.current === m.task_id) showHome(); break;
    case "snapshot": if (m.task.id === S.current) { S.view = m; renderThread(); } break;
    case "event": onEvent(m.task_id, m.ev); break;
    case "confirm": S.pending.set(m.cid, m); renderToasts(); if (m.task_id === S.current) renderInlineConfirms(); break;
    case "confirm_done": S.pending.delete(m.cid); renderToasts(); $$(`[data-cid="${m.cid}"]`).forEach((n) => n.remove()); break;
    case "settings": S.settings = m.settings; $("#modelChip").textContent = m.settings.model; renderStatusRow(); renderTop(); if (!$("#settings").hidden) renderSettings(); break;
    case "transcript": if (S.onTranscript) S.onTranscript(m); break;
    case "ios_shortcuts": {
      const box = $("#iosLinks");
      if (!m.links || !m.links.length) { toast("Raccourcis non créés : " + (m.error || "erreur inconnue")); renderSettings(); break; }
      if (box) {
        box.innerHTML = "";
        m.links.forEach((l) => { const a = h("a", "btn-primary", `⬇︎ ${esc(l.name)}`); a.href = l.url; a.target = "_blank"; a.rel = "noopener"; box.appendChild(a); });
      }
      toast("Touche chaque raccourci puis « Ajouter le raccourci ». Liens valables 10 minutes, une seule fois.");
      break;
    }
    case "remote_qr": {
      const ov = h("div", "qr-overlay");
      ov.innerHTML = `<div class="qr-card"><div class="qr-svg">${m.svg}</div><p><b>Scanne avec l'appareil photo de l'iPhone</b><br>(Tailscale doit y être connecté). Ce code contient ta clé d'accès : ne le montre à personne.</p><button class="btn-primary" type="button">Fermer</button></div>`;
      ov.onclick = (e) => { if (e.target === ov || e.target.tagName === "BUTTON") ov.remove(); };
      document.body.appendChild(ov);
      break;
    }
    case "cloud_result": {
      S.cloudBusy = false; toast(m.text);
      const st = $(m.relay ? "#relayStatus" : "#cloudStatus"); if (st) { st.textContent = m.text; st.className = "cloud-status " + (m.ok ? "ok" : "err"); }
      break;
    }
    case "diagnostics": renderDiag(m.checks); break;
    case "memory": { const t = $("#memText"); if (t) t.value = m.text; break; }
    case "toast": toast(m.text); break;
  }
}

/* ------------------------------------------------------------------ barre latérale */
function renderSidebar() {
  const list = $("#taskList"); list.innerHTML = "";
  const q = S.search.toLowerCase();
  const all = [...S.tasks.values()].filter((t) => !q || t.title.toLowerCase().includes(q)).sort((a, b) => b.updated - a.updated);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const groups = [["En cours", all.filter((t) => ACTIVE.has(t.status))],
                  ["Aujourd'hui", all.filter((t) => !ACTIVE.has(t.status) && t.updated * 1000 >= today)],
                  ["Plus tôt", all.filter((t) => !ACTIVE.has(t.status) && t.updated * 1000 < today)]];
  for (const [label, items] of groups) {
    if (!items.length) continue;
    list.appendChild(h("h6", null, esc(label) + (label === "En cours" ? ` · ${items.length}` : "")));
    for (const t of items) {
      const r = h("button", "task-row" + (t.id === S.current ? " on" : ""));
      r.type = "button";
      r.innerHTML = `<span class="st ${t.status}">${t.status === "done" ? "●" : t.status === "error" ? "!" : t.status === "stopped" || t.status === "idle" ? "○" : ""}</span>
        <span class="t">${esc(t.title)}</span>${t.pending ? `<span class="badge">${t.pending}</span>` : ""}`;
      r.onclick = () => { openTask(t.id); $("#sidebar").classList.remove("open"); };
      list.appendChild(r);
    }
  }
  if (!all.length) list.appendChild(h("p", "muted", q ? "Aucun résultat." : "&nbsp;Tes tâches apparaîtront ici."));
  const busy = [...S.tasks.values()].some((t) => ACTIVE.has(t.status));
  $("#brandOrb").classList.toggle("busy", busy); $("#heroOrb").classList.toggle("busy", busy);
  const n = [...S.tasks.values()].filter((t) => ACTIVE.has(t.status)).length;
  $("#brandSub").textContent = n ? `${n} tâche${n > 1 ? "s" : ""} en cours` : "local · privé";
  renderStatusRow();
}

function renderStatusRow() {
  const s = S.settings, row = $("#statusRow");
  if (!row) return;
  const n = [...S.tasks.values()].filter((t) => ACTIVE.has(t.status)).length;
  row.innerHTML = "";
  const chips = [
    s ? `Modèle <b>${esc(s.model)}</b>` : null,
    `<b>${n}</b> en cours${s ? ` · jusqu'à <b>${s.max_parallel_tasks}</b> en parallèle` : ""}`,
    s ? (s.sandbox && s.sandbox_available ? "Bac à sable <b>actif</b>" : "Bac à sable <b>inactif</b>") : null,
    s && s.remote_serving ? "Accès distant <b>activé</b>" : null,
    S.power && S.power.battery
      ? { warn: true, title: "Sur batterie, macOS limite la puce graphique : le modèle répond environ 40 % moins vite. Branche le Mac pour les grosses tâches.",
          html: `Sur batterie${S.power.percent != null ? ` (${S.power.percent} %)` : ""} · <b>vitesse réduite</b>` }
      : null,
    S.power && S.power.low_power ? { warn: true, title: "Mode économie d'énergie actif (Réglages Système › Batterie).", html: "Économie d'énergie · <b>plus lent</b>" } : null,
    S.power && S.power.thermal >= 2
      ? { warn: true, title: "macOS a détecté que le Mac chauffe et bride la puce : Jarvis passe à une tâche à la fois jusqu'au retour à la normale. Pose le Mac sur une surface dure et dégagée.",
          html: `Mac ${S.power.thermal >= 3 ? "très chaud" : "chaud"} · <b>1 tâche à la fois</b>` }
      : null,
  ];
  chips.filter(Boolean).forEach((c) => {
    const el = h("span", c.warn ? "warn" : null, typeof c === "string" ? c : c.html);
    if (c.title) el.title = c.title;
    row.appendChild(el);
  });
}

/* ------------------------------------------------------------------ navigation */
// Notifications (Web Push) : service worker + abonnement chiffré auprès du service d'Apple
async function swReg() {
  if (!("serviceWorker" in navigator)) return null;
  try { return await navigator.serviceWorker.register("/sw.js", { scope: "/" }); } catch (_) { return null; }
}
function keyBytes(b64) {
  const s = atob(b64.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (b64.length % 4)) % 4));
  return Uint8Array.from(s, (c) => c.charCodeAt(0));
}
async function enablePush() {
  const key = ((S.settings || {}).push || {}).key;
  if (!key) { toast("Notifications indisponibles sur le Mac (module de chiffrement manquant)."); return; }
  try {
    const perm = await Notification.requestPermission();
    if (perm !== "granted") { toast("Notifications refusées : Réglages de l'iPhone › Notifications › Jarvis."); return; }
    const reg = (await swReg()) || (await navigator.serviceWorker.ready);
    let sub = await reg.pushManager.getSubscription();
    if (!sub) sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key) });
    send({ type: "push_subscribe", sub: sub.toJSON() });
  } catch (e) { toast("Activation impossible : " + (e && e.message ? e.message : e)); }
}
if (location.protocol === "https:" || location.hostname === "127.0.0.1" || location.hostname === "localhost") swReg();
window.addEventListener("hashchange", () => {                 // notification touchée alors que l'app est ouverte
  const tk = location.hash.match(/task=([\w-]+)/);
  if (tk && S.tasks.has(tk[1])) openTask(tk[1]);
});
// Ajout à l'écran d'accueil : l'icône s'ouvre déjà connectée (clé de CET appareil, jamais celle du Mac)
function pinManifest() {
  if (!S.token || !S.token.startsWith("jv_")) return;
  const l = document.querySelector('link[rel="manifest"]');
  if (l) l.href = `/manifest.webmanifest?k=${encodeURIComponent(S.token)}`;
}
// Autorisation Calendrier/Rappels demandée par l'app native : elle rappelle agendaAccessDone(message)
window.agendaAccessDone = (msg) => { toast(msg); send({ type: "settings_get" }); };
// Raccourci global (⌥ Espace) : l'app native appelle quickAsk() → nouvelle demande, curseur prêt
window.quickAsk = () => {
  const busy = $("#input").value.trim() || document.querySelector(".modal:not([hidden])");
  if (!busy) showHome();
  setTimeout(() => $("#input").focus(), 40);
};
function showHome() {
  S.current = null; S.view = null; S.stream = null;
  document.body.classList.add("home-mode");
  $("#home").hidden = false; $("#thread").hidden = true;
  $("#home").insertBefore($("#composer"), $("#suggest"));
  $("#taskTitle").textContent = "Jarvis"; $("#taskStatus").hidden = true;
  ["#btnStop", "#btnUndo", "#btnDelete", "#btnBoost"].forEach((b) => ($(b).hidden = true));
  $("#composerHint").hidden = true;
  renderSidebar(); $("#input").focus();
}
function openTask(id) {
  S.current = id; S.stream = null; S.typing = null;
  document.body.classList.remove("home-mode");
  $("#home").hidden = true; $("#thread").hidden = false;
  $(".main").appendChild($("#composer"));
  $("#msgs").innerHTML = '<div class="msg info">Chargement…</div>';
  $("#plan").hidden = true; $("#subs").hidden = true;
  renderTop(); renderSidebar();
  send({ type: "open", task_id: id });
}
function renderTop() {
  const t = S.tasks.get(S.current);
  if (!t) return;
  $("#taskTitle").textContent = t.title;
  const p = $("#taskStatus"); p.hidden = false; p.className = "pill " + t.status; p.textContent = STATUS_TXT[t.status] || t.status;
  const act = ACTIVE.has(t.status);
  $("#btnStop").hidden = !act; $("#btnUndo").hidden = act || !t.can_undo; $("#btnDelete").hidden = act;
  const c = S.settings && S.settings.cloud;
  $("#btnBoost").hidden = act || !(c && c.enabled && c.mode !== "off" && c.has_key);
  const hint = $("#composerHint");
  hint.hidden = !act; hint.textContent = "Jarvis travaille sur cette tâche — ton message lancera une nouvelle tâche en parallèle.";
  if (!act && S.typing) { S.typing.remove(); S.typing = null; }
}

/* ------------------------------------------------------------------ fil */
function renderThread() {
  const box = $("#msgs"); box.innerHTML = ""; S.stream = null; S.typing = null;
  for (const ev of S.view.events) appendEvent(ev, false);
  renderPlan(S.view.plan || []); renderSubs();
  renderInlineConfirms();
  const t = S.tasks.get(S.current);
  if (t && t.status === "running") showTyping();
  scrollEnd(true);
}
function scrollEnd(force) {
  const th = $("#thread");
  const near = th.scrollHeight - th.scrollTop - th.clientHeight < 260;
  if (force || near) requestAnimationFrame(() => (th.scrollTop = th.scrollHeight));
}

function onEvent(tid, ev) {
  const meta = S.tasks.get(tid);
  if (meta) meta.updated = ev.ts || meta.updated;
  if (tid !== S.current || !S.view) return;
  if (ev.type === "delta") { streamAppend(ev.kind, ev.text); return; }
  if (ev.type === "step") { if (!S.stream) showTyping(); return; }
  if (ev.type === "tool_end") {
    const stored = S.view.events.find((x) => x.type === "tool" && x.id === ev.id);
    if (stored) Object.assign(stored, ev, { type: "tool" });
    updateTool(ev); return;
  }
  if (ev.type === "sub") {
    const i = S.view.subs.findIndex((s) => s.id === ev.sub.id);
    if (i >= 0) S.view.subs[i] = ev.sub; else S.view.subs.push(ev.sub);
    renderSubs(); return;
  }
  S.view.events.push(ev);
  appendEvent(ev, true);
}

function appendEvent(ev, live) {
  const box = $("#msgs");
  if (ev.type !== "plan") hideTyping();
  switch (ev.type) {
    case "user": {
      const u = h("div", "msg user", (ev.boost ? '<span class="boost-tag">⚡ Renfort</span> ' : "") + esc(ev.text));
      if (ev.files && ev.files.length) u.appendChild(userFiles(ev.files));
      box.appendChild(u); break;
    }
    case "assistant": endStream(); box.appendChild(mdNode("msg bot", ev.text)); break;
    case "final": endStream(); box.appendChild(mdNode("msg final glass", ev.text)); break;
    case "info": box.appendChild(h("div", "msg info", esc(ev.text))); break;
    case "decision": box.appendChild(h("div", `msg decision ${ev.answer === "no" ? "no" : "yes"}`,
      (ev.answer === "no" ? "Refusé : " : "Autorisé : ") + esc(ev.summary))); break;
    case "plan": renderPlan(ev.steps); return;
    case "tool": endStream(); if (ev.name !== "update_plan") box.appendChild(toolNode(ev)); break;
    default: return;
  }
  if (live) scrollEnd(false);
}

function toolNode(ev) {
  const [ic, label] = TOOL_UI[ev.name] || (ev.name.startsWith("mcp__") ? ["⧉", ev.name.split("__")[1] + " · " + ev.name.split("__")[2]] : ["•", ev.name]);
  const d = h("details", "msg tool " + (ev.state || "running"));
  d.dataset.id = ev.id;
  d.innerHTML = `<summary><span class="ti">${esc(ic)}</span><span class="tn">${esc(label)}</span><span class="ta">${esc(argPreview(ev.args))}</span><span class="ts"></span></summary>
    <pre>${esc(prettyArgs(ev.args))}${ev.output ? "\n\n→ " + esc(ev.output) : ""}</pre>`;
  return d;
}
function updateTool(ev) {
  const d = $(`.tool[data-id="${CSS.escape(ev.id)}"]`);
  if (!d) return;
  d.className = "msg tool " + ev.state;
  const pre = d.querySelector("pre");
  if (pre && ev.output != null && !pre.dataset.done) { pre.textContent += "\n\n→ " + ev.output; pre.dataset.done = "1"; }
  if (ev.state === "error" || ev.state === "denied") d.open = false;
}
function argPreview(a) {
  try {
    const o = JSON.parse(a);
    for (const k of ["command", "path", "url", "query", "args", "target", "folder", "host", "title", "script", "pattern", "note", "cwd", "src"])
      if (o[k]) return (k === "command" ? "$ " : "") + String(o[k]).replace(/\s+/g, " ").slice(0, 160);
    if (o.subtasks) return o.subtasks.map((s) => s.title).join(" · ");
    return a.slice(0, 160);
  } catch (_) { return String(a || "").slice(0, 160); }
}
function prettyArgs(a) { try { return JSON.stringify(JSON.parse(a), null, 2); } catch (_) { return a || ""; } }

/* streaming */
function showTyping() {
  if (S.typing || S.stream) return;
  S.typing = h("div", "msg bot", '<span class="dots"><i></i><i></i><i></i></span>');
  $("#msgs").appendChild(S.typing); scrollEnd(false);
}
function hideTyping() { if (S.typing) { S.typing.remove(); S.typing = null; } }
function streamAppend(kind, text) {
  hideTyping();
  if (!S.stream) {
    const wrap = h("div", "msg bot");
    S.stream = { wrap, raw: "", think: "", thinkEl: null, txtEl: null, body: h("div", "stream") };
    wrap.appendChild(S.stream.body);
    $("#msgs").appendChild(wrap);
  }
  const st = S.stream;
  if (kind === "thinking") st.think += text; else st.raw += text;
  let visible = st.raw, inline = "";
  visible = visible.replace(/<think>([\s\S]*?)(<\/think>|$)/g, (_, t) => { inline += t; return ""; });
  const thought = (st.think + inline).trim();
  if (thought) {
    if (!st.thinkEl) {
      st.thinkEl = h("details", "think"); st.thinkEl.open = true;
      st.thinkEl.innerHTML = '<summary>Réflexion…</summary><div class="tx"></div>';
      st.wrap.insertBefore(st.thinkEl, st.body);
    }
    const tx = st.thinkEl.querySelector(".tx"); tx.textContent = thought; tx.scrollTop = tx.scrollHeight;
  }
  st.body.textContent = visible.replace(/^\s+/, "");
  st.body.hidden = !st.body.textContent;
  scrollEnd(false);
}
function endStream() {
  const st = S.stream;
  if (!st) return;
  if (st.thinkEl) {
    st.thinkEl.open = false;
    st.thinkEl.querySelector("summary").textContent = "Réflexion";
    st.wrap.replaceWith(st.thinkEl);
  } else st.wrap.remove();
  S.stream = null;
}

/* plan & sous-tâches */
function renderPlan(steps) {
  const p = $("#plan");
  if (!steps || !steps.length) { p.hidden = true; return; }
  if (S.view) S.view.plan = steps;
  const done = steps.filter((s) => s.status === "done").length;
  p.hidden = false;
  p.innerHTML = `<div class="plan-head"><b>PLAN</b><span class="muted">${done}/${steps.length}</span></div>
    <div class="bar"><i style="width:${Math.round((done / steps.length) * 100)}%"></i></div>
    <ol>${steps.map((s) => `<li class="${s.status}">${esc(s.step)}</li>`).join("")}</ol>`;
}
function renderSubs() {
  const box = $("#subs"), subs = (S.view && S.view.subs) || [];
  if (!subs.length) { box.hidden = true; return; }
  box.hidden = false; box.innerHTML = "";
  for (const s of subs) {
    const plan = s.plan || [];
    const pct = plan.length ? Math.round((plan.filter((x) => x.status === "done").length / plan.length) * 100) : (s.status === "done" ? 100 : 0);
    const st = s.status || "running";
    const c = h("div", "sub glass", `<b><span class="st ${st}">${st === "done" ? "●" : st === "error" ? "!" : ""}</span>${esc(s.title || "Sous-tâche")}</b>
      <small>${esc(s.status === "done" ? (s.result || "Terminé").split("\n")[0] : s.last || "Démarrage…")}</small>
      <div class="bar"><i style="width:${pct}%"></i></div>`);
    box.appendChild(c);
  }
}

/* ------------------------------------------------------------------ confirmations */
function confirmBody(p, compact) {
  const risky = p.level === "risqué";
  const box = h("div", (compact ? "toast glass " : "msg confirm ") + (risky ? "" : "normal"));
  box.dataset.cid = p.cid;
  box.innerHTML = `${compact ? `<b>${esc(p.title || "Tâche")}</b>` : `<h4>${risky ? "⚠ Action importante — ton accord est nécessaire" : "Jarvis demande ton accord"}</h4>`}
    <pre>${esc(p.summary)}</pre>${p.detail ? `<div class="why">${esc(p.detail)}</div>` : ""}
    <div class="row"><button class="btn-primary" data-a="yes">Autoriser</button>
    ${p.can_always ? '<button class="btn-ghost" data-a="always">Toujours pour cette tâche</button>' : ""}
    <button class="btn-ghost danger" data-a="no">Refuser</button>
    ${compact ? '<button class="btn-ghost" data-a="open">Voir</button>' : ""}</div>`;
  box.querySelectorAll("[data-a]").forEach((b) => (b.onclick = () => {
    if (b.dataset.a === "open") { openTask(p.task_id); return; }
    send({ type: "confirm", task_id: p.task_id, cid: p.cid, answer: b.dataset.a });
    box.style.opacity = ".5";
  }));
  return box;
}
function renderToasts() {
  const box = $("#toasts");
  $$(".toast[data-cid]", box).forEach((n) => { if (!S.pending.has(n.dataset.cid)) n.remove(); });
  for (const p of S.pending.values()) {
    if (p.task_id === S.current && !$("#thread").hidden) continue;
    if (!$(`.toast[data-cid="${p.cid}"]`, box)) box.appendChild(confirmBody(p, true));
  }
  $$(".toast[data-cid]", box).forEach((n) => { const p = S.pending.get(n.dataset.cid); if (p && p.task_id === S.current) n.remove(); });
  if (S.pending.size && navigator.vibrate) navigator.vibrate(120);
}
function renderInlineConfirms() {
  const box = $("#msgs");
  for (const p of S.pending.values())
    if (p.task_id === S.current && !$(`.confirm[data-cid="${p.cid}"]`, box)) { box.appendChild(confirmBody(p, false)); scrollEnd(true); }
  renderToasts();
}
function toast(text) {
  const t = h("div", "toast glass", esc(text));
  $("#toasts").appendChild(t);
  setTimeout(() => { t.style.transition = "opacity .4s"; t.style.opacity = "0"; setTimeout(() => t.remove(), 400); }, 4200);
}

/* ------------------------------------------------------------------ pièces jointes */
const KIND_EXT = {
  pdf: ["pdf"], word: ["docx", "doc", "rtf", "odt", "pages"], excel: ["xlsx", "xlsm", "xls", "csv", "tsv", "numbers", "ods"],
  slides: ["pptx", "ppt", "key", "odp"], image: ["png", "jpg", "jpeg", "heic", "heif", "gif", "webp", "tif", "tiff", "bmp", "svg"],
  design: ["pxd", "pxm", "psd", "ai", "sketch", "fig", "af", "afdesign", "afphoto", "afpub", "eps", "indd", "canva"],
  audio: ["mp3", "m4a", "wav", "aac", "flac", "aiff"], video: ["mp4", "mov", "m4v", "avi", "mkv", "webm"], archive: ["zip", "tar", "gz", "tgz", "7z", "rar"],
};
const extOf = (n) => (String(n).split(".").pop() || "").toLowerCase();
function kindOf(n) { const e = extOf(n); for (const [k, v] of Object.entries(KIND_EXT)) if (v.includes(e)) return k; return "other"; }
function hsize(n) { const u = ["o", "Ko", "Mo", "Go"]; let i = 0; while (n >= 1024 && i < 3) { n /= 1024; i++; } return (i ? n.toFixed(1).replace(".", ",") : n) + " " + u[i]; }
function fileURL(p) { return `/api/file?path=${encodeURIComponent(p)}&t=${encodeURIComponent(S.token)}`; }

function addFiles(list) {
  for (const f of [...(list || [])]) {
    if (!f || f.size === undefined) continue;
    const a = { id: Math.random().toString(36).slice(2), file: f, name: f.name || "image-collée.png", size: f.size, kind: kindOf(f.name || "x.png"), progress: 0, path: null, error: null, xhr: null };
    if (a.kind === "image" && f.size < 40e6) a.preview = URL.createObjectURL(f);
    S.att.push(a); upload(a);
  }
  renderAtt();
}
function upload(a) {
  const x = new XMLHttpRequest(); a.xhr = x;
  x.open("POST", `/api/upload?name=${encodeURIComponent(a.name)}`);
  x.setRequestHeader("X-Jarvis-Token", S.token);
  x.setRequestHeader("Content-Type", "application/octet-stream");
  x.upload.onprogress = (e) => { if (e.lengthComputable) { a.progress = e.loaded / e.total; renderAtt(); } };
  x.onload = () => {
    a.xhr = null;
    try { const r = JSON.parse(x.responseText); if (x.status === 200) { a.path = r.path; a.name = r.name; a.progress = 1; } else a.error = r.error || ("erreur " + x.status); }
    catch (_) { a.error = "erreur " + x.status; }
    renderAtt(); if (S.submitWhenReady && !uploading()) { S.submitWhenReady = false; submit(); }
  };
  x.onerror = () => { a.xhr = null; a.error = "envoi impossible"; renderAtt(); };
  x.send(a.file);
}
const uploading = () => S.att.some((a) => !a.path && !a.error);
function removeAtt(id) {
  const i = S.att.findIndex((a) => a.id === id); if (i < 0) return;
  const a = S.att[i]; if (a.xhr) a.xhr.abort(); if (a.preview) URL.revokeObjectURL(a.preview);
  S.att.splice(i, 1); renderAtt();
}
function attChip(a, removable) {
  const c = h("div", "att" + (a.error ? " err" : ""));
  const ico = h("span", "ai " + a.kind, a.preview || a.thumb ? "" : esc(extOf(a.name).slice(0, 4).toUpperCase() || "?"));
  if (a.preview || a.thumb) ico.style.backgroundImage = `url("${a.preview || a.thumb}")`;
  const sub = a.error ? a.error : a.path || !removable ? hsize(a.size) : `${Math.round(a.progress * 100)} % · ${hsize(a.size)}`;
  c.append(ico, h("span", "an", `<b title="${esc(a.name)}">${esc(a.name)}</b><small>${esc(sub)}</small>`));
  if (removable) {
    const x = h("button", "ax", "✕"); x.type = "button"; x.title = "Retirer"; x.onclick = () => removeAtt(a.id); c.appendChild(x);
    if (!a.path && !a.error) { const p = h("i", "ap"); p.style.width = Math.round(a.progress * 100) + "%"; c.appendChild(p); }
  }
  return c;
}
function renderAtt() {
  const box = $("#attachments"); box.innerHTML = "";
  box.hidden = !S.att.length;
  S.att.forEach((a) => box.appendChild(attChip(a, true)));
  $("#btnSend").classList.toggle("wait", uploading());
}
function clearAtt() { S.att.forEach((a) => a.preview && URL.revokeObjectURL(a.preview)); S.att = []; renderAtt(); }
function userFiles(files) {
  const wrap = h("div", "files");
  for (const f of files) {
    if (f.kind === "image" && !/\.(heic|heif|tif|tiff)$/i.test(f.name)) {
      const im = new Image(); im.loading = "lazy"; im.alt = f.name; im.src = fileURL(f.path); im.onerror = () => im.replaceWith(attChip(f, false)); wrap.appendChild(im);
    } else wrap.appendChild(attChip(f, false));
  }
  return wrap;
}

/* ------------------------------------------------------------------ markdown */
function mdNode(cls, src) {
  const d = h("div", cls + " md", md(src));
  d.querySelectorAll(".code button").forEach((b) => (b.onclick = () => {
    copyText(b.parentElement.querySelector("pre").textContent).then(() => { b.textContent = "Copié ✓"; setTimeout(() => (b.textContent = "Copier"), 1500); });
  }));
  const imgs = [...new Set((src.match(/\/(?:Users|tmp|private)\/[^\s`'")\]]+\.(?:png|jpe?g|gif|webp)/gi) || []))].slice(0, 4);
  if (imgs.length && S.token) {
    const pv = h("div", "preview");
    imgs.forEach((p) => { const im = new Image(); im.loading = "lazy"; im.src = `/api/file?path=${encodeURIComponent(p)}&t=${encodeURIComponent(S.token)}`; im.onerror = () => im.remove(); pv.appendChild(im); });
    d.appendChild(pv);
  }
  return d;
}
function inline(s) {
  return s
    .replace(/`([^`]+)`/g, (_, c) => `<code>${c}</code>`)
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/(^|[\s(])\*([^*\s][^*]*)\*/g, "$1<i>$2</i>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
    .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener noreferrer">$2</a>');
}
function md(src) {
  const blocks = [];
  let s = String(src || "").replace(/```([\w+-]*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    blocks.push(`<div class="code">${lang ? `<span class="lang">${esc(lang)}</span>` : ""}<button type="button">Copier</button><pre>${esc(code.replace(/\n$/, ""))}</pre></div>`);
    return `\u0000${blocks.length - 1}\u0000`;
  });
  s = esc(s);
  const lines = s.split("\n"), out = [];
  let list = null, para = [];
  const flushP = () => { if (para.length) { out.push(`<p>${inline(para.join("<br>"))}</p>`); para = []; } };
  const flushL = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (let i = 0; i < lines.length; i++) {
    const ln = lines[i];
    let m;
    if (/^\u0000\d+\u0000$/.test(ln.trim())) { flushP(); flushL(); out.push(ln.trim()); continue; }
    if ((m = ln.match(/^(#{1,4})\s+(.*)/))) { flushP(); flushL(); out.push(`<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`); continue; }
    if (/^\s*(---|\*\*\*)\s*$/.test(ln)) { flushP(); flushL(); out.push("<hr>"); continue; }
    if ((m = ln.match(/^&gt;\s?(.*)/))) { flushP(); flushL(); out.push(`<blockquote>${inline(m[1])}</blockquote>`); continue; }
    if (/^\s*\|.*\|\s*$/.test(ln)) {
      flushP(); flushL();
      const rows = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) { rows.push(lines[i]); i++; }
      i--;
      const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const body = rows.filter((r) => !/^\s*\|?\s*:?-{2,}/.test(r));
      out.push("<table>" + body.map((r, k) => "<tr>" + cells(r).map((c) => (k === 0 ? `<th>${inline(c)}</th>` : `<td>${inline(c)}</td>`)).join("") + "</tr>").join("") + "</table>");
      continue;
    }
    if ((m = ln.match(/^\s*([-*•]|\d+[.)])\s+(.*)/))) {
      flushP();
      const kind = /\d/.test(m[1]) ? "ol" : "ul";
      if (list !== kind) { flushL(); out.push(`<${kind}>`); list = kind; }
      out.push(`<li${/^\s{2,}/.test(ln) ? ' style="margin-left:1.2em"' : ""}>${inline(m[2])}</li>`);
      continue;
    }
    if (!ln.trim()) { flushP(); flushL(); continue; }
    flushL(); para.push(ln);
  }
  flushP(); flushL();
  return out.join("").replace(/\u0000(\d+)\u0000/g, (_, k) => blocks[+k]);
}

/* ------------------------------------------------------------------ réglages */
function openSettings(tab) {
  if (tab) S.tab = tab;
  $("#settings").hidden = false;
  $$("#setTabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === S.tab));
  send({ type: "settings_get" });
  renderSettings();
}
function setSetting(changes) { send({ type: "settings_set", changes }); }
function field(label, help, ctl, col) {
  const f = h("div", "field" + (col ? " col" : ""));
  f.innerHTML = `<label>${label}</label>${help ? `<small>${help}</small>` : ""}`;
  const c = h("div", "ctl"); if (ctl instanceof Node) c.appendChild(ctl); else c.innerHTML = ctl; f.appendChild(c);
  return f;
}
function sw(on, onChange, disabled) {
  const b = h("button", "switch" + (on ? " on" : "")); b.type = "button"; b.disabled = !!disabled;
  b.onclick = () => { b.classList.toggle("on"); onChange(b.classList.contains("on")); };
  return b;
}
function seg(options, value, onChange) {
  const g = h("div", "seg");
  options.forEach(([v, label, dis]) => {
    const b = h("button", v === value ? "on" : "", esc(label)); b.type = "button"; b.disabled = !!dis;
    b.onclick = () => { $$("button", g).forEach((x) => x.classList.remove("on")); b.classList.add("on"); onChange(v); };
    g.appendChild(b);
  });
  return g;
}
function select(options, value, onChange) {
  const s = h("select");
  options.forEach(([v, l]) => { const o = h("option", null, esc(l)); o.value = v; if (v === value) o.selected = true; s.appendChild(o); });
  s.onchange = () => onChange(s.value);
  return s;
}
function range(min, max, value, onChange, suffix) {
  const w = h("div", "ctl"); const r = h("input"); r.type = "range"; r.min = min; r.max = max; r.value = value;
  const out = h("b", null, value + (suffix || "")); r.oninput = () => (out.textContent = r.value + (suffix || "")); r.onchange = () => onChange(+r.value);
  w.append(r, out); return w;
}
function renderSettings() {
  const s = S.settings, body = $("#setBody");
  if (!s) { body.innerHTML = '<p class="muted">Chargement…</p>'; return; }
  body.innerHTML = "";
  const chat = (s.models || []).filter((m) => !/embed/i.test(m));
  if (S.tab === "general") {
    body.append(
      field("Modèle principal", "Le cerveau de Jarvis. Plus gros = plus intelligent mais plus lent.",
        select(chat.map((m) => [m, m]).concat(chat.includes(s.model) ? [] : [[s.model, s.model + " (absent)"]]), s.model, (v) => setSetting({ model: v }))),
      field("Modèle vision", "Pour lire l'écran, les captures de sites et du simulateur.",
        select([["", "Aucun"]].concat(chat.map((m) => [m, m])), s.vision_model || "", (v) => setSetting({ vision_model: v }))),
      field("Autonomie", "Prudent : confirme tout · Autonome : confirme l'irréversible · Total : presque rien (protection anti-injection toujours active).",
        seg([["prudent", "Prudent"], ["autonome", "Autonome"], ["total", "Total", S.remote]], s.autonomy, (v) => setSetting({ autonomy: v }))),
      field("Tâches simultanées", "Nombre de tâches complexes menées en même temps.", range(1, 6, s.max_parallel_tasks, (v) => setSetting({ max_parallel_tasks: v }))),
      field("Sous-tâches par tâche", "Jarvis peut découper une tâche en sous-tâches parallèles.", range(1, 4, s.max_subtasks, (v) => setSetting({ max_subtasks: v }))),
      field("Auto-vérification", "Jarvis contrôle son travail avant de dire « terminé ».", sw(s.verify, (v) => setSetting({ verify: v }))),
      field("Apprendre de l'expérience", `Jarvis retient la méthode des tâches réussies et la réutilise pour les demandes proches (${s.recipes_count || 0} apprise${(s.recipes_count || 0) > 1 ? "s" : ""}). Tout reste sur ton Mac.`,
        (() => { const w = h("div", "ctl"); const f = h("button", "btn-ghost", "Oublier"); f.type = "button"; f.disabled = S.remote || !s.recipes_count;
          f.onclick = () => { if (confirm("Oublier toutes les méthodes apprises ?")) send({ type: "recipes_clear" }); };
          w.append(sw(s.recipes !== false, (v) => setSetting({ recipes: v })), f); return w; })()),
      ...(s.mlx_available || s.engine === "mlx" ? [field("Moteur", "MLX (Apple) : environ 30 % plus rapide sur ton Mac (mesuré : 40 contre 30 jetons par seconde). Ollama : moteur d'origine. Si MLX s'arrête, Ollama prend le relais tout seul.",
        seg([["ollama", "Ollama"], ["mlx", "MLX (Apple)"]], s.engine || "ollama", (v) => { toast(v === "mlx" ? "Démarrage du moteur MLX…" : "Retour à Ollama…"); send({ type: "engine_set", engine: v }); }))] : []),
      field("Fiches projet", `Jarvis tient une fiche par projet (type, commandes de compilation et de test qui marchent, pièges déjà corrigés) et la relit dès qu'il y travaille (${s.projects_count || 0} projet${(s.projects_count || 0) > 1 ? "s" : ""}). Rangées dans ~/.jarvis/projets : tes dépôts ne sont pas modifiés.`,
        sw(s.project_notes !== false, (v) => setSetting({ project_notes: v }))),
      field("Protection contre la chaleur", "Ton Mac n'a pas de ventilateur : quand macOS signale qu'il chauffe, Jarvis passe à une tâche à la fois pour ne pas tout ralentir.",
        sw(s.thermal_guard !== false, (v) => setSetting({ thermal_guard: v }))),
      field("Réflexion approfondie", "Le modèle réfléchit avant chaque action : plus juste sur les problèmes difficiles, mais beaucoup plus lent.", sw(s.think === true, (v) => setSetting({ think: v }))),
      field("Mémoire de travail", "Taille du contexte (plus grand = plus de RAM).",
        select([[8192, "8 k"], [16384, "16 k"], [24576, "24 k"], [32768, "32 k"], [65536, "64 k"]].map(([a, b]) => [String(a), b]), String(s.num_ctx), (v) => setSetting({ num_ctx: +v }))),
      field("Raccourci global", "Fait apparaître Jarvis par-dessus n'importe quelle app, prêt à écrire (encore une fois : il se masque). Fonctionne tant que l'app Jarvis est ouverte, même fenêtre fermée.",
        seg([["alt+space", "⌥ Espace"], ["cmd+shift+j", "⌘ ⇧ J"], ["off", "Désactivé"]], s.hotkey || "alt+space", (v) => {
          setSetting({ hotkey: v });
          try { window.webkit.messageHandlers.jarvis.postMessage({ type: "hotkey" }); } catch (_) {}
        })),
      (() => {
        const a = s.agenda || {}, ok = a.calendar === "autorise" && a.reminders === "autorise";
        const label = { autorise: "autorisé", refuse: "refusé", pas_demande: "pas encore demandé", ecriture_seule: "ajout seulement", absent: "outil absent" };
        const b = h("button", ok ? "btn-ghost" : "btn-primary", ok ? "Autorisé ✅" : "Autoriser"); b.type = "button";
        b.disabled = S.remote || ok || a.calendar === "absent";
        b.onclick = () => {
          try { window.webkit.messageHandlers.jarvis.postMessage({ type: "agenda_access" }); toast("Clique sur « Autoriser » dans les fenêtres de macOS."); }
          catch (_) { toast("Ouvre l'app Jarvis sur le Mac pour autoriser."); }
        };
        return field("Calendrier et Rappels", `Pour « qu'est-ce que j'ai demain ? » ou « rappelle-moi… ». Calendrier : ${label[a.calendar] || "?"} · Rappels : ${label[a.reminders] || "?"}. Rien ne quitte ton Mac.`, b);
      })(),
      field("Verre natif macOS", "Transparence réelle de la fenêtre (effet à la réouverture de l'app).", sw(s.native_glass !== false, (v) => setSetting({ native_glass: v }))),
      field("À propos", `Jarvis ${esc(s.version)} · 100 % local, open-source, gratuit`, ""),
    );
  } else if (S.tab === "security") {
    const dirs = h("div", "dirs");
    (s.project_dirs || []).forEach((d) => {
      const r = h("div", null, `<span>${esc(d)}</span>`); const x = h("button", "icon-btn", "✕"); x.type = "button";
      x.onclick = () => setSetting({ project_dirs: s.project_dirs.filter((y) => y !== d) }); r.appendChild(x); dirs.appendChild(r);
    });
    const add = h("div", "ctl"); const inp = h("input", "txt"); inp.placeholder = "~/Projets/MonProjet"; const ab = h("button", "btn-ghost", "Ajouter"); ab.type = "button";
    ab.onclick = () => { if (inp.value.trim()) setSetting({ project_dirs: [...(s.project_dirs || []), inp.value.trim()] }); };
    add.append(inp, ab); dirs.appendChild(add);
    const audit = h("button", "btn-ghost", "Ouvrir le journal"); audit.type = "button"; audit.onclick = openAudit;
    body.append(
      field("Bac à sable macOS", s.sandbox_available ? "Les commandes ne peuvent écrire que dans tes dossiers de travail et n'ont aucun accès à tes clés, mots de passe et cookies."
        : "⚠ Indisponible sur ce système.", sw(s.sandbox && s.sandbox_available, (v) => setSetting({ sandbox: v }), S.remote || !s.sandbox_available)),
      field("Espace de travail", esc(s.workspace), ""),
      field("Dossiers projets", "Dossiers où Jarvis peut écrire en plus de l'espace de travail (tes projets Xcode, Qt…).", dirs, true),
      field("Navigateur invisible", "Le navigateur de Jarvis travaille sans fenêtre.", sw(s.browser_headless, (v) => setSetting({ browser_headless: v }))),
      field("Journal de sécurité", "Chaque action, chaque refus, horodatés.", audit),
    );
  } else if (S.tab === "cloud") {
    const c = s.cloud || {}, provs = s.cloud_providers || {};
    S.cloudProv = S.cloudProv && provs[S.cloudProv] ? S.cloudProv : (c.provider || "gemini");
    const p = provs[S.cloudProv] || {};
    const sameProv = S.cloudProv === c.provider;
    const intro = h("div", "cloud-intro", `<b>Quand le modèle de ton Mac bloque</b>, Jarvis peut confier la suite de la tâche à un modèle en ligne
      gratuit, bien plus puissant (ex. Gemini). <b>Jamais sans ton accord</b>, sauf si tu choisis le mode automatique. Tu peux aussi
      cliquer sur <b>⚡ Renfort</b> dans une tâche. Sans clé, Jarvis reste 100 % local.`);
    const provSel = select(Object.entries(provs).map(([k, v]) => [k, v.label]), S.cloudProv, (v) => { S.cloudProv = v; renderSettings(); });
    const getKey = h("button", "btn-ghost", "Obtenir une clé gratuite ↗"); getKey.type = "button"; getKey.disabled = !p.key_url || S.remote;
    getKey.onclick = () => send({ type: "open_url", url: p.key_url });
    const keyIn = h("input", "txt"); keyIn.type = "password"; keyIn.autocomplete = "off"; keyIn.spellcheck = false;
    keyIn.placeholder = sameProv && c.has_key ? "•••••••• (clé enregistrée dans le Trousseau)" : "Colle ta clé ici"; keyIn.disabled = S.remote;
    const base = h("input", "txt"); base.placeholder = "https://…/v1"; base.hidden = S.cloudProv !== "custom";
    const save = h("button", "btn-primary", sameProv && c.has_key ? "Tester à nouveau" : "Enregistrer et tester"); save.type = "button"; save.disabled = S.remote;
    const status = h("div", "cloud-status" + (sameProv && c.enabled ? " ok" : ""),
      sameProv && c.enabled ? `Prêt · modèle <b>${esc(c.model)}</b>` : sameProv && c.has_key ? "Clé enregistrée, pas encore testée." : "Aucune clé pour ce service.");
    status.id = "cloudStatus";
    const used = sameProv && c.enabled ? (c.exhausted || []) : [];
    if (used.length) status.innerHTML += `<br><small>Quota gratuit du jour épuisé pour ${used.length} modèle${used.length > 1 ? "s" : ""}
      (${used.map(esc).join(", ")}) : Jarvis passe aux suivants. Remise à zéro chaque matin vers 9 h.</small>`;
    save.onclick = () => {
      if (S.cloudBusy) return; S.cloudBusy = true;
      status.className = "cloud-status"; status.textContent = "Vérification de la clé et choix du meilleur modèle…";
      send({ type: "cloud_setup", provider: S.cloudProv, key: keyIn.value.trim(), base_url: base.value.trim() });
      keyIn.value = "";
    };
    const clip = h("button", "btn-primary", "📋 Utiliser la clé copiée"); clip.type = "button"; clip.disabled = S.remote;
    clip.title = "Jarvis lit la clé dans ton presse-papiers sur le Mac, la range dans le Trousseau, puis vide le presse-papiers.";
    clip.onclick = () => {
      if (S.cloudBusy) return; S.cloudBusy = true;
      status.className = "cloud-status"; status.textContent = "Lecture de la clé copiée, vérification et choix du meilleur modèle…";
      send({ type: "cloud_setup", provider: S.cloudProv, from_clipboard: true, base_url: base.value.trim() });
    };
    save.className = "btn-ghost";
    const keyRow = h("div", "ctl"); keyRow.append(clip, keyIn, save);
    body.append(
      intro,
      field("Service", esc(p.note || ""), provSel, true),
      field("Clé API", "Gratuite, sans carte bancaire. Elle est rangée dans le Trousseau macOS, jamais dans un fichier.", keyRow, true),
    );
    if (S.cloudProv === "custom") body.append(field("Adresse du service", "Compatible OpenAI, en https.", base, true));
    body.append(field("Étapes", `1. « Obtenir une clé gratuite » (ton navigateur s'ouvre) · 2. Connecte-toi, clique sur « Create API key » puis copie la clé · 3. Reviens ici : « 📋 Utiliser la clé copiée ». C'est tout.`, getKey, true), status);
    if (sameProv && c.enabled) {
      body.append(
        field("Quand l'utiliser", "Me demander : Jarvis demande ton accord quand il bloque · Automatique : sans demander (tes données partent alors en ligne sans confirmation).",
          seg([["off", "Désactivé"], ["ask", "Me demander"], ["auto", "Automatique"]], c.mode || "ask", (v) => setSetting({ cloud: { mode: v } }))),
        field("Modèle du renfort", "Choisi automatiquement (le plus récent et le plus capable). Tu peux le changer.",
          select((c.models || [c.model]).map((x) => [x, x]), c.model, (v) => setSetting({ cloud: { model: v } }))),
      );
      // Relais : un 2e service gratuit quand les quotas du jour du premier sont épuisés
      const rel = c.relay || {};
      const rChoices = Object.entries(provs).filter(([k]) => k !== c.provider && k !== "custom");
      if (!S.relayProv || S.relayProv === c.provider || !provs[S.relayProv]) S.relayProv = rel.provider || "mistral";
      const rp = provs[S.relayProv] || {};
      const rOn = rel.enabled && rel.provider === S.relayProv;
      const rSel = select(rChoices.map(([k, v]) => [k, v.label]), S.relayProv, (v) => { S.relayProv = v; renderSettings(); });
      const rStatus = h("div", "cloud-status" + (rOn ? " ok" : ""), rOn ? `Relais prêt · modèle <b>${esc(rel.model)}</b>`
        : "Pas de relais : quand les quotas du jour sont épuisés, Jarvis termine avec le modèle du Mac.");
      rStatus.id = "relayStatus";
      const rClip = h("button", "btn-primary", "📋 Utiliser la clé copiée"); rClip.type = "button"; rClip.disabled = S.remote;
      rClip.onclick = () => {
        if (S.cloudBusy) return; S.cloudBusy = true;
        rStatus.className = "cloud-status"; rStatus.textContent = "Lecture de la clé copiée, vérification et choix du meilleur modèle…";
        send({ type: "cloud_setup", provider: S.relayProv, relay: true, from_clipboard: true });
      };
      const rGet = h("button", "btn-ghost", "Obtenir une clé gratuite ↗"); rGet.type = "button"; rGet.disabled = !rp.key_url || S.remote;
      rGet.onclick = () => send({ type: "open_url", url: rp.key_url });
      const rOff = h("button", "btn-ghost danger", "Retirer"); rOff.type = "button"; rOff.hidden = !rel.enabled; rOff.disabled = S.remote;
      rOff.onclick = () => send({ type: "cloud_relay_off" });
      const rRow = h("div", "ctl"); rRow.append(rClip, rGet, rOff);
      const mainName = ((provs[c.provider] || {}).label || "ton renfort").split(" (")[0];
      const ap = s.apple || {};
      const apSw = sw(!!ap.enabled, (v) => setSetting({ apple: { enabled: v } }), S.remote || !ap.installed);
      const apMake = h("button", "btn-ghost", ap.installed ? "Tester" : "Créer le raccourci (1 min)"); apMake.type = "button"; apMake.disabled = S.remote;
      apMake.onclick = () => send({ type: ap.installed ? "apple_test" : "apple_setup" });
      const apRow = h("div", "ctl"); apRow.append(apMake, apSw);
      body.append(field("Modèle privé d'Apple (facultatif)", ap.installed
        ? "Pour rédiger les rapports de recherche et les résumés quand la tâche n'a pas le renfort : Apple Intelligence « Cloud Pro », gratuit (limite par jour), sans clé, et Apple ne garde pas les données. Ne pilote pas les outils."
        : "Apple Intelligence « Cloud Pro » via un raccourci que tu crées une fois : gratuit, sans clé, Apple ne garde pas les données. Jarvis s'en sert pour rédiger (recherches, résumés).", apRow, true));
      body.append(
        field("Relais (facultatif)", `Quand les quotas gratuits du jour de ${esc(mainName)} sont épuisés, Jarvis passe tout seul à ce 2e service gratuit, avec le même accord. ${esc(rp.note || "")}`, rSel, true),
        field("Clé du relais", "1. « Obtenir une clé gratuite » · 2. Crée la clé et copie-la · 3. « 📋 Utiliser la clé copiée ». Rangée dans le Trousseau.", rRow, true),
        rStatus,
      );
    }
  } else if (S.tab === "remote") {
    // Sur l'iPhone (ou tout appareil à distance) : notifications + raccourcis Siri / Partager
    const pu = s.push || {};
    const standalone = window.navigator.standalone === true || matchMedia("(display-mode: standalone)").matches;
    const nb = h("button", "btn-primary", "🔔 Activer les notifications"); nb.type = "button";
    nb.disabled = !pu.available || !("serviceWorker" in navigator) || !("PushManager" in window);
    nb.onclick = enablePush;
    const pushHint = !("PushManager" in window)
      ? (S.remote ? "Sur iPhone : ouvre Jarvis depuis son icône de l'écran d'accueil (Partager › Sur l'écran d'accueil), puis reviens ici." : "Ce navigateur ne gère pas les notifications web.")
      : `Fin de tâche et demandes d'accord sur cet appareil, chiffrées de bout en bout, sans app à installer. ${pu.count ? `${pu.count} appareil(s) abonné(s).` : ""}`;
    if (S.remote) body.append(field("Notifications sur cet appareil", pushHint, nb));   // le Mac a déjà les siennes
    if (S.remote) {
      const sc = h("button", "btn-primary", "Installer les raccourcis"); sc.type = "button";
      sc.onclick = () => { sc.disabled = true; sc.textContent = "Préparation…"; send({ type: "ios_shortcuts" }); };
      const links = h("div", "ctl"); links.id = "iosLinks";
      body.append(
        field("Siri, bouton Action, Partager", "Deux raccourcis pour cet iPhone, avec une clé limitée (poser une question, envoyer un fichier) que tu peux retirer depuis le Mac : « Jarvis » (dis « Dis Siri, Jarvis » ou mets-le sur le bouton Action : Réglages › Bouton Action › Raccourci) et « Envoyer à Jarvis » (dans Partager, depuis Photos, Fichiers ou Safari).", sc, true),
        links,
        field("Tu es connecté à distance", standalone ? "App Jarvis de l'écran d'accueil. Les réglages sensibles se modifient depuis le Mac." : "Astuce : Partager › Sur l'écran d'accueil pour avoir Jarvis comme une app.", ""));
    } else {
      const tog = h("button", s.remote_serving ? "btn-ghost danger" : "btn-primary", s.remote_serving ? "Désactiver" : "Activer l'accès distant");
      tog.type = "button"; tog.onclick = () => send({ type: "remote", enable: !s.remote_serving });
      const qr = h("button", "btn-primary", "Associer un iPhone (QR code)"); qr.type = "button"; qr.disabled = !(s.remote_url && s.remote_serving);
      qr.onclick = () => send({ type: "remote_qr", name: "iPhone" });
      const devs = s.tailscale_devices || [];
      const phone = devs.find((d) => /ios|iphone/i.test(d.os + " " + d.name));
      const pname = phone && !/^localhost$/i.test(phone.name) ? ` (<b>${esc(phone.name)}</b>)` : "";
      const devTxt = phone ? `✅ Ton iPhone${pname} est dans ton réseau Tailscale${phone.online ? "" : " (hors ligne pour l'instant)"}.`
        : "Ton iPhone n'est pas encore dans ton réseau Tailscale : installe l'app <b>Tailscale</b> (App Store, gratuite) et connecte-toi avec le <b>même compte</b> que sur ce Mac.";
      const tools = h("div", "ctl"); tools.append(qr);
      body.append(
        field("Accès depuis l'iPhone", "Via Tailscale (gratuit) : réseau privé chiffré, aucun port ouvert sur ta box.", tog),
        field("Ton iPhone", devTxt, "", true),
        field("Adresse", s.remote_url ? `<span class="bigurl">${esc(s.remote_url)}</span>` : "Tailscale n'est pas connecté sur ce Mac.", tools, true),
        field("Mode d'emploi", "1. Tailscale sur l'iPhone, même compte · 2. Active l'accès ci-dessus · 3. « Associer un iPhone » et scanne le QR code avec l'appareil photo · 4. Dans Safari : Partager › Sur l'écran d'accueil · 5. Dans l'app : 🔔 notifications et raccourcis Siri.", "", true),
      );
      const list = s.devices || [];
      const when = (t) => (t ? new Date(t * 1000).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "jamais utilisé");
      list.forEach((d) => {
        const rm = h("button", "btn-ghost danger", "Retirer"); rm.type = "button";
        rm.onclick = () => send({ type: "device_revoke", id: d.id });
        body.append(field(`${d.scope === "ask" ? "⚡" : "📱"} ${esc(d.name)}`, `${d.scope === "ask" ? "Clé limitée (Siri, Partager)" : "App Jarvis"} · dernière connexion : ${when(d.last_seen)}`, rm));
      });
      if (!list.length) body.append(field("Appareils associés", "Aucun pour l'instant. Chaque appareil a sa propre clé, que tu peux retirer ici à tout moment ; la clé de ce Mac ne le quitte jamais.", ""));
    }
    const host = h("input", "txt"); host.value = s.remote_ollama_host || ""; host.placeholder = "http://100.x.y.z:11434"; host.disabled = S.remote;
    host.onchange = () => setSetting({ remote_ollama_host: host.value.trim() });
    const rm = h("input", "txt"); rm.value = s.remote_model || ""; rm.placeholder = "qwen3.6:27b"; rm.onchange = () => setSetting({ remote_model: rm.value.trim() });
    body.append(
      field("PC plus puissant (facultatif)", "Ollama d'une autre machine du réseau. Jarvis repasse sur le Mac si elle est éteinte.", host),
      field("Modèle de ce PC", "", rm),
      field("Utiliser ce PC en priorité", "", sw(s.prefer_remote, (v) => setSetting({ prefer_remote: v }))),
    );
  } else if (S.tab === "notif") {
    const v = s.voice || {};
    const ntfy = h("button", s.ntfy.enabled ? "btn-ghost" : "btn-primary", s.ntfy.enabled ? "Envoyer un test" : "Configurer"); ntfy.type = "button";
    ntfy.onclick = () => send({ type: "ntfy_setup" });
    const test = h("button", "btn-ghost", "▶︎ Écouter"); test.type = "button"; test.disabled = S.remote;
    test.onclick = () => send({ type: "voice_test" });
    const vs = (s.voices || []).length ? s.voices : [{ name: "Thomas", locale: "fr_FR", quality: 0 }];
    const tag = (q) => (q === 2 ? " ★ très naturelle" : q === 1 ? " · améliorée" : "");
    const pays = { fr_FR: "France", fr_CA: "Canada", fr_BE: "Belgique", fr_CH: "Suisse" };
    const cur = vs.some((x) => x.name === v.voice) ? v.voice : vs[0].name;
    const vsel = select(vs.map((x) => [x.name, `${x.name.replace(/ \(.*\)$/, "")} (${pays[x.locale] || x.locale})${tag(x.quality)}`]), cur,
      (x) => setSetting({ voice: { voice: x } }));
    const more = h("button", "btn-ghost", "Voix plus naturelles ↗"); more.type = "button"; more.disabled = S.remote;
    more.onclick = () => { send({ type: "voice_settings" }); toast("Réglages › Accessibilité › Contenu énoncé › Voix du système › Gérer les voix : télécharge une voix française « Premium » (gratuite)."); };
    const vrow = h("div", "ctl"); vrow.append(vsel, test, more);
    const hasPremium = vs.some((x) => x.quality === 2);
    body.append(
      field("Réponses à voix haute", "Jarvis lit le résumé de chaque tâche terminée (voix macOS locales).", sw(v.enabled, (x) => setSetting({ voice: { enabled: x } }))),
      field("Voix", hasPremium ? "Les voix ★ sont les plus naturelles." : "Pour une voix beaucoup plus naturelle, télécharge une voix française « Premium » d'Apple (gratuite, sur ton Mac).", vrow, true),
      field("Débit", "", range(140, 240, v.rate || 190, (x) => setSetting({ voice: { rate: x } }), " mots/min")),
      field("Notifications téléphone", s.ntfy.enabled ? `Sujet privé : <code>${esc(s.ntfy.topic)}</code> — abonne-toi dans l'app gratuite ntfy.` : "Fin de tâche et demandes d'accord sur ton téléphone (app gratuite ntfy).", ntfy),
      field("Activées", "", sw(s.ntfy.enabled, (x) => setSetting({ ntfy: { enabled: x } }))),
    );
  } else if (S.tab === "memory") {
    const t = h("textarea", "txt"); t.id = "memText"; t.placeholder = "Ce que Jarvis retient de toi…"; t.disabled = S.remote;
    const b = h("button", "btn-primary", "Enregistrer"); b.type = "button"; b.disabled = S.remote;
    b.onclick = () => send({ type: "memory_set", text: t.value });
    body.append(field("Mémoire de Jarvis", "Tes préférences et informations durables, utilisées dans chaque tâche. Modifiable librement.", t, true), b);
    const mf = s.my_files || {}, st = mf.state || {};
    const n = Object.values(st.folders || {}).reduce((a, f) => a + (f.extraits || 0), 0);
    const where = (mf.folders || []).map((f) => f.replace(/^\/Users\/[^/]+/, "~").replace("~/Library/Mobile Documents/com~apple~CloudDocs", "iCloud Drive")).join(", ");
    const etat = !mf.enabled ? "Désactivée." : st.running ? "Indexation en cours…" : n ? `${n} extraits indexés.` : "Pas encore indexé.";
    body.append(field("Recherche dans mes fichiers", `« Retrouve le cours sur le mix marketing », « le devis du camp » : Jarvis cherche par le sens dans ${esc(where)} (PDF, Word, PowerPoint, Excel, Pages…). L'index reste sur ton Mac. À l'activation, macOS demande l'accès à ces dossiers. ${etat}`,
      sw(!!mf.enabled, (v) => setSetting({ my_files: { enabled: v } }), S.remote)));
    send({ type: "memory_get" });
  } else if (S.tab === "diag") {
    const b = h("button", "btn-primary", "Lancer le diagnostic"); b.type = "button";
    b.onclick = () => { $("#diagOut").innerHTML = '<p class="muted">Analyse en cours…</p>'; send({ type: "diagnostics" }); };
    const out = h("div", "diag", ""); out.id = "diagOut";
    body.append(field("Diagnostic complet", "Vérifie le moteur IA, les modèles, le bac à sable, les autorisations, GitHub, Firebase…", b), out);
    const n = s.nightly_last || {};
    const last = n.status === "fait" ? `Dernier contrôle : ${esc(n.date || "")} · <b>${n.score}/${n.total}</b> réussis en ${n.minutes || "?"} min`
        + (n.failed && n.failed.length ? ` · à revoir : ${n.failed.map(esc).join(", ")}` : " · tout est bon ✅")
      : n.status === "interrompu" ? `Dernier essai interrompu (${esc(n.reason || "")}) : Jarvis réessaiera au prochain moment calme.`
      : "Pas encore fait : il aura lieu la prochaine fois que ton Mac sera branché et inutilisé 20 minutes.";
    body.append(field("Contrôle automatique", `Une fois par jour, quand ton Mac est branché et que tu ne t'en sers pas, Jarvis refait son banc d'essai (tâches types + copies de tes projets) et te prévient si son score baisse. Il s'arrête dès que tu reviens. ${last}`,
      sw(s.nightly !== false, (v) => setSetting({ nightly: v }), S.remote)));
  }
}
function renderDiag(checks) {
  const out = $("#diagOut"); if (!out) return;
  out.innerHTML = checks.map((c) => `<div><i>${c.status === "ok" ? "✅" : c.status === "warn" ? "🟡" : "❌"}</i><span>${esc(c.label)}${c.status !== "ok" && c.fix ? `<small>${esc(c.fix)}</small>` : ""}</span></div>`).join("");
}
async function openAudit() {
  $("#auditModal").hidden = false;
  const box = $("#auditList"); box.innerHTML = '<p class="muted">Chargement…</p>';
  try {
    const r = await fetch("/api/audit", { headers: { "X-Jarvis-Token": S.token } });
    const d = await r.json();
    box.innerHTML = (Array.isArray(d) ? d : []).reverse().map((x) =>
      `<div>${esc((x.ts || "").replace("T", " "))} · ${esc(x.type)} ${esc(x.tool || "")} ${x.allowed === false ? '<span class="no">REFUSÉ</span>' : ""} ${esc((x.action || x.text || x.reason || "").slice(0, 180))}</div>`).join("") || "Vide.";
  } catch (e) { box.textContent = "Impossible de charger le journal."; }
}

/* ------------------------------------------------------------------ interactions */
function grow() { const i = $("#input"); i.style.height = "auto"; i.style.height = Math.min(i.scrollHeight, 220) + "px"; }
function submit() {
  const i = $("#input"), text = i.value.trim();
  if (uploading()) { S.submitWhenReady = true; toast("Envoi des fichiers en cours… ton message partira juste après."); return; }
  const files = S.att.filter((a) => a.path).map((a) => ({ path: a.path }));
  if (!text && !files.length) return;
  const t = S.tasks.get(S.current);
  const msg = S.research && text ? `🔎 Recherche approfondie : ${text}` : text;
  const ok = (!S.current || (t && ACTIVE.has(t.status))) ? send({ type: "new", text: msg, files }) : send({ type: "send", task_id: S.current, text: msg, files });
  if (ok) { i.value = ""; grow(); clearAtt(); setResearch(false); }
}
function setResearch(on) {
  S.research = !!on;
  const b = $("#btnResearch"); if (!b) return;
  b.classList.toggle("on", S.research); b.setAttribute("aria-pressed", String(S.research));
  $("#input").placeholder = S.research ? "Pose ta question : Jarvis cherche, lit plusieurs sources et rédige un rapport sourcé…"
    : "Demande n'importe quoi à Jarvis…";
}
function bindUI() {
  $("#composer").onsubmit = (e) => { e.preventDefault(); submit(); };
  $("#btnAttach").onclick = () => $("#fileInput").click();
  $("#btnResearch").onclick = () => { setResearch(!S.research); $("#input").focus(); };
  $("#fileInput").onchange = (e) => { addFiles(e.target.files); e.target.value = ""; };
  let dragDepth = 0;
  const hasFiles = (e) => e.dataTransfer && [...(e.dataTransfer.types || [])].includes("Files");
  window.addEventListener("dragenter", (e) => { if (!hasFiles(e)) return; e.preventDefault(); dragDepth++; $("#dropzone").hidden = false; });
  window.addEventListener("dragover", (e) => { if (hasFiles(e)) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; } });
  window.addEventListener("dragleave", (e) => { if (!hasFiles(e)) return; dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) $("#dropzone").hidden = true; });
  window.addEventListener("drop", (e) => {
    if (!hasFiles(e)) return; e.preventDefault(); dragDepth = 0; $("#dropzone").hidden = true;
    addFiles(e.dataTransfer.files); $("#input").focus();
  });
  const inp = $("#input");
  inp.addEventListener("input", grow);
  inp.addEventListener("paste", (e) => {
    const files = [...((e.clipboardData && e.clipboardData.files) || [])];
    if (files.length) { e.preventDefault(); addFiles(files); }
  });
  inp.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing && !/Mobi|iPhone|iPad/.test(navigator.userAgent)) { e.preventDefault(); submit(); }
  });
  $("#newTask").onclick = () => { showHome(); $("#sidebar").classList.remove("open"); };
  $("#search").oninput = (e) => { S.search = e.target.value; renderSidebar(); };
  $("#openSettings").onclick = () => openSettings();
  $("#openSide").onclick = () => $("#sidebar").classList.add("open");
  $("#closeSide").onclick = () => $("#sidebar").classList.remove("open");
  $("#btnStop").onclick = () => send({ type: "stop", task_id: S.current });
  $("#btnBoost").onclick = () => {
    const c = (S.settings && S.settings.cloud) || {};
    if (confirm(`Confier la suite de cette tâche à ${c.model || "ton renfort en ligne"} ?\n\nLa conversation et le contenu des fichiers lus seront envoyés à ce service (gratuit). Ensuite Jarvis reprend où il en était.`))
      send({ type: "send", task_id: S.current, text: "Reprends cette tâche là où elle en est et termine-la correctement, en vérifiant le résultat.", boost: true });
  };
  $("#btnUndo").onclick = () => { if (confirm("Restaurer tous les fichiers modifiés par cette tâche (et mettre à la Corbeille ceux qu'elle a créés) ?")) send({ type: "undo", task_id: S.current }); };
  $("#btnDelete").onclick = () => { if (confirm("Supprimer cette conversation ?")) send({ type: "delete", task_id: S.current }); };
  const title = $("#taskTitle");
  title.ondblclick = () => { if (!S.current) return; title.contentEditable = "true"; title.focus(); document.execCommand && document.execCommand("selectAll", false, null); };
  title.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); title.blur(); } if (e.key === "Escape") { title.textContent = S.tasks.get(S.current)?.title || ""; title.blur(); } };
  title.onblur = () => { if (title.contentEditable === "true") { title.contentEditable = "false"; send({ type: "rename", task_id: S.current, title: title.textContent }); } };
  $$("#setTabs button").forEach((b) => (b.onclick = () => openSettings(b.dataset.tab)));
  $$("[data-close]").forEach((b) => (b.onclick = () => (b.closest(".modal").hidden = true)));
  $$(".modal").forEach((m) => m.addEventListener("click", (e) => { if (e.target === m && m.id !== "login") m.hidden = true; }));
  $("#loginGo").onclick = () => { S.token = $("#tokenInput").value.trim(); try { localStorage.setItem("jarvisToken", S.token); } catch (_) {} $("#loginErr").textContent = ""; connect(); };
  $("#tokenInput").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#loginGo").click(); });
  document.addEventListener("keydown", (e) => {
    const mod = e.metaKey || e.ctrlKey;
    if (mod && e.key.toLowerCase() === "n") { e.preventDefault(); showHome(); }
    else if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); $("#search").focus(); }
    else if (mod && e.key === ",") { e.preventDefault(); openSettings(); }
    else if (e.key === "Escape") $$(".modal").forEach((m) => { if (m.id !== "login") m.hidden = true; });
  });
  // dictée : Whisper local (enregistrement → transcription sur le Mac) ; sinon reconnaissance du navigateur ; sinon astuce
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const mic = $("#btnMic");
  const canRecord = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
  const whisperOn = () => canRecord && S.settings && S.settings.whisper;
  async function whisperToggle() {
    if (S.rec) { S.rec.stop(); return; }
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
    catch (_) { toast("Micro refusé : autorise Jarvis dans Réglages Système › Confidentialité et sécurité › Micro."); return; }
    const type = ["audio/mp4", "audio/webm;codecs=opus", "audio/webm"].find((t) => MediaRecorder.isTypeSupported(t)) || "";
    const rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    const chunks = [];
    rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    rec.onstop = () => {
      stream.getTracks().forEach((t) => t.stop()); clearTimeout(S.recTimer); S.rec = null; mic.classList.remove("rec");
      const mt = rec.mimeType || type || "audio/mp4";
      const blob = new Blob(chunks, { type: mt });
      if (blob.size < 2000) { toast("Trop court : maintiens la parole un peu plus longtemps."); return; }
      mic.classList.add("busy"); mic.title = "Transcription…";
      const x = new XMLHttpRequest();
      x.open("POST", `/api/upload?name=${mt.includes("mp4") ? "dictee.m4a" : "dictee.webm"}`);
      x.setRequestHeader("X-Jarvis-Token", S.token);
      x.setRequestHeader("Content-Type", "application/octet-stream");
      x.onload = () => {
        let r = {}; try { r = JSON.parse(x.responseText); } catch (_) { }
        if (x.status === 200 && r.path) send({ type: "transcribe", path: r.path });
        else { mic.classList.remove("busy"); toast("Dictée : envoi impossible."); }
      };
      x.onerror = () => { mic.classList.remove("busy"); toast("Dictée : envoi impossible."); };
      x.send(blob);
    };
    rec.start(); S.rec = rec; mic.classList.add("rec"); mic.title = "Clique pour arrêter";
    S.recTimer = setTimeout(() => { if (rec.state === "recording") rec.stop(); }, 90000);
  }
  S.onTranscript = (m) => {
    mic.classList.remove("busy"); mic.title = "Dicter";
    if (m.text) { inp.value = (inp.value ? inp.value.trimEnd() + " " : "") + m.text; grow(); inp.focus(); }
    else toast(m.error || "Je n'ai rien entendu.");
  };
  if (!SR) { mic.onclick = () => whisperOn() ? whisperToggle() : toast("Astuce : utilise la dictée de macOS (touche 🎤 ou deux fois sur Fn) directement dans la zone de texte."); }
  else {
    let rec = null;
    mic.onclick = () => {
      if (whisperOn()) { whisperToggle(); return; }
      if (rec) { rec.stop(); return; }
      rec = new SR(); rec.lang = "fr-FR"; rec.interimResults = true; rec.continuous = false;
      const base = inp.value ? inp.value + " " : "";
      rec.onresult = (ev) => { inp.value = base + [...ev.results].map((r) => r[0].transcript).join(""); grow(); };
      rec.onend = () => { mic.classList.remove("rec"); rec = null; inp.focus(); };
      rec.onerror = () => { toast("Dictée indisponible ici : utilise la dictée macOS (touche 🎤)."); };
      mic.classList.add("rec"); rec.start();
    };
  }
  setInterval(() => { if (S.connected) send({ type: "list" }); }, 30000);
}
