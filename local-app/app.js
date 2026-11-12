import { MODEL_CACHE, MODELS, modelURL, boundedHistory } from './models.js';
const $ = id => document.getElementById(id);
const storeKey = 'jarvis-local-history-v1';
const welcomeTemplate = $('messages').querySelector('.empty-state')?.cloneNode(true);
let worker, ready = false, busy = false, loadedKey, generating = false, installPrompt, shellCached = false, modelCached = false, replyNode;
let operation = 0;
let deleting = false;
let messages = [];
try { messages = boundedHistory(JSON.parse(localStorage.getItem(storeKey) || '[]')); } catch { /* Storage is optional. */ }
try { const selected = localStorage.getItem('jarvis-local-model'); if (MODELS[selected]) $('model-select').value = selected; } catch { /* Optional preference. */ }
const modelNote = document.createElement('p');
modelNote.className = 'muted'; modelNote.id = 'model-note';
$('model-select').parentElement.after(modelNote);
$('model-select').setAttribute('aria-describedby', 'model-help model-note');
$('prompt').maxLength = 4000;
function status(text, state = 'idle') { $('status').textContent = text; $('status').title = text; $('status').dataset.state = state; }
function error(text = '') { $('error').textContent = text; $('error').hidden = !text; }
function save() {
  try { localStorage.setItem(storeKey, JSON.stringify(messages.slice(-40))); }
  catch { error('L’historique ne peut pas être conservé sur cet appareil. La conversation reste utilisable.'); }
}
function append(role, content) {
  $('messages').querySelector('.empty-state')?.remove();
  const row = document.createElement('article'); row.className = `message ${role}`;
  const label = document.createElement('p'); label.className = 'message-meta'; label.textContent = role === 'user' ? 'Vous' : 'Jarvis';
  const bubble = document.createElement('div'); bubble.className = 'bubble'; bubble.textContent = content;
  row.append(label, bubble); $('messages').append(row);
  return bubble;
}
function render() {
  $('messages').replaceChildren();
  if (!messages.length) {
    if (welcomeTemplate) { $('messages').append(welcomeTemplate.cloneNode(true)); return; }
    const welcome = document.createElement('div'); welcome.className = 'empty-state';
    const title = document.createElement('h2'); title.textContent = 'Commencez une conversation.';
    const text = document.createElement('p'); text.textContent = 'Chargez un modèle, puis posez une question ou donnez un texte à reformuler. Vos échanges restent sur cet appareil.';
    welcome.append(title, text); $('messages').append(welcome);
  } else for (const message of messages) append(message.role, message.content);
}
function controls() {
  $('send-button').disabled = !ready || busy || loadedKey !== $('model-select').value || !$('prompt').value.trim();
  $('load-model').disabled = busy || (ready && loadedKey === $('model-select').value);
  $('load-model').textContent = ready && loadedKey === $('model-select').value ? 'Modèle chargé' : 'Télécharger / charger le modèle';
  $('model-select').disabled = busy;
  $('stop-button').hidden = !busy || deleting;
  $('stop-button').textContent = generating ? 'Arrêter la réponse' : 'Annuler le chargement';
  $('new-chat').disabled = busy;
  $('delete-model').disabled = busy;
  $('clear-history').disabled = busy;
  $('messages').setAttribute('aria-busy', String(generating));
}
function readyStatus() {
  const offline = !navigator.onLine;
  const cached = shellCached && modelCached;
  status(`Prêt · ${MODELS[loadedKey].label} · ${offline ? 'Hors connexion' : 'Calcul sur cet appareil'}${cached ? ' · Prêt hors ligne' : ' · Cache hors ligne incomplet'}`, 'ready');
}
async function hasModel(key) {
  try {
    const cache = await caches.open(MODEL_CACHE);
    const files = ['onnx/model_quantized.onnx', 'tokenizer.json', 'tokenizer_config.json', 'config.json', 'generation_config.json'];
    const found = await Promise.all(files.map(file => cache.match(modelURL(key, file))));
    return found.every(Boolean);
  } catch { return false; }
}
async function load() {
  if (busy) return;
  error();
  if (!window.isSecureContext || !window.Worker || !window.WebAssembly || !window.caches) {
    error('Ce navigateur ne permet pas l’exécution locale. Ouvrez le lien HTTPS avec une version récente de Safari, Chrome ou Edge.'); return;
  }
  const key = $('model-select').value;
  const attempt = ++operation;
  busy = true; controls();
  const cached = await hasModel(key);
  if (attempt !== operation) return;
  if (!navigator.onLine && !cached) { busy = false; controls(); error('Connectez-vous une première fois pour télécharger ce modèle.'); return; }
  try {
    const storage = await navigator.storage?.estimate?.();
    if (attempt !== operation) return;
    if (!cached && storage?.quota && storage.quota - storage.usage < MODELS[key].bytes * 1.1) {
      busy = false; controls(); error('L’espace de stockage disponible est insuffisant. Libérez de la place ou choisissez le modèle léger.'); return;
    }
    await navigator.storage?.persist?.();
  } catch { /* Some browsers do not expose storage estimates. */ }
  if (attempt !== operation) return;
  worker?.terminate(); ready = false; busy = true; generating = false;
  loadedKey = key; modelCached = false; controls();
  $('progress').hidden = false; $('progress').removeAttribute('value');
  $('progress-label').textContent = cached ? 'Lecture du modèle conservé sur cet appareil…' : 'Téléchargement des fichiers du modèle…';
  status('Chargement du modèle…', 'loading');
  try { worker = new Worker(new URL('./inference-worker.js', import.meta.url), { type: 'module' }); }
  catch { failed('Ce navigateur ne peut pas démarrer le moteur local. Essayez une version récente de Safari, Chrome ou Edge.'); return; }
  worker.onmessage = ({ data }) => {
    if (data.type === 'progress') {
      if (data.file?.endsWith('.onnx')) {
        if (Number.isFinite(data.progress)) $('progress').value = data.progress;
        const mb = Math.round((data.loaded || 0) / 1e6);
        $('progress-label').textContent = `${mb} Mo lus${data.total ? ` / ${Math.round(data.total / 1e6)} Mo` : ''} · Gardez l’application ouverte`;
        if (data.progress >= 100) $('progress-label').textContent = 'Préparation du modèle en mémoire…';
      }
    } else if (data.type === 'cache-warning') {
      error('Le modèle n’a pas pu être conservé. Libérez du stockage pour l’utiliser hors connexion.');
    } else if (data.type === 'ready') {
      ready = true; busy = false; modelCached = data.cached;
      try { localStorage.setItem('jarvis-local-model', loadedKey); } catch { /* Optional preference. */ }
      $('progress').hidden = true; $('progress-label').textContent = 'Le modèle est prêt. Le premier message peut demander un peu de temps.';
      readyStatus(); controls(); $('prompt').focus({ preventScroll: true });
    } else if (data.type === 'token') {
      messages.at(-1).content += data.text; replyNode.textContent = messages.at(-1).content;
    } else if (data.type === 'done') {
      messages.at(-1).content = data.text || messages.at(-1).content || 'Le modèle n’a pas produit de réponse. Reformulez votre demande.';
      replyNode.textContent = messages.at(-1).content;
      const timing = document.createElement('span'); timing.className = 'message-meta'; timing.textContent = `${Math.round(data.seconds)} s · Calcul local`;
      replyNode.after(timing); generating = false; busy = false; save(); readyStatus(); controls();
    } else if (data.type === 'error') {
      failed(data.phase === 'load' ? 'Le chargement a échoué. Vérifiez votre connexion et l’espace disponible, ou essayez le modèle léger. Ce navigateur ou cet appareil peut manquer de mémoire.' : 'Le modèle n’a pas pu répondre. Essayez une demande plus courte ou le modèle léger.');
      console.warn('Jarvis Local:', data.message);
    }
  };
  worker.onerror = event => { console.warn('Jarvis Local worker:', event.message); failed('Le moteur local a été interrompu. Essayez le modèle léger ou un navigateur à jour.'); };
  worker.postMessage({ type: 'load', key, offline: !navigator.onLine });
}
function failed(message) {
  worker?.terminate(); worker = null; busy = false; ready = false; generating = false;
  if (messages.at(-1)?.role === 'assistant' && !messages.at(-1).content) messages.pop();
  save(); render(); $('progress').hidden = true; $('progress-label').textContent = '';
  status('Modèle à charger', 'idle'); error(message); controls();
}
$('load-model').addEventListener('click', load);
$('model-select').addEventListener('change', () => { modelNote.textContent = MODELS[$('model-select').value].note; controls(); });
modelNote.textContent = MODELS[$('model-select').value].note;
$('chat-form').addEventListener('submit', event => {
  event.preventDefault();
  const text = $('prompt').value.trim();
  if (!ready || busy || !text || loadedKey !== $('model-select').value) return;
  error(); messages.push({ role: 'user', content: text.slice(0, 4000) });
  append('user', text.slice(0, 4000));
  const history = boundedHistory(messages);
  messages.push({ role: 'assistant', content: '' }); replyNode = append('assistant', '');
  $('prompt').value = ''; busy = true; generating = true; controls(); save();
  status('Jarvis réfléchit sur cet appareil…', 'loading');
  replyNode.scrollIntoView({ block: 'nearest', behavior: 'auto' });
  worker.postMessage({ type: 'generate', messages: history });
});
$('prompt').addEventListener('input', controls);
$('prompt').addEventListener('keydown', event => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); $('chat-form').requestSubmit(); } });
$('stop-button').addEventListener('click', () => {
  operation++;
  worker?.terminate(); worker = null; ready = false; busy = false; generating = false;
  if (messages.at(-1)?.role === 'assistant' && !messages.at(-1).content) messages.pop();
  save(); render(); controls(); $('progress').hidden = true; $('progress-label').textContent = '';
  status('Arrêté · Chargez le modèle pour reprendre', 'idle');
});
function clearHistory() { messages = []; save(); render(); }
$('new-chat').addEventListener('click', clearHistory);
$('clear-history').addEventListener('click', () => { clearHistory(); $('settings-dialog').close(); });
$('delete-model').addEventListener('click', async () => {
  if (busy) return;
  worker?.terminate(); worker = null; ready = false; modelCached = false;
  busy = true; deleting = true; controls();
  try { await caches.delete(MODEL_CACHE); status('Modèles supprimés de cet appareil', 'idle'); }
  catch { error('Impossible de supprimer les modèles. Réessayez ou effacez les données de ce site dans votre navigateur.'); }
  finally { busy = false; deleting = false; controls(); $('settings-dialog').close(); }
});
$('open-settings').addEventListener('click', () => $('settings-dialog').showModal());
$('close-settings').addEventListener('click', () => $('settings-dialog').close());
window.addEventListener('beforeinstallprompt', event => { event.preventDefault(); installPrompt = event; $('install-button').hidden = false; });
$('install-button').addEventListener('click', async () => {
  if (installPrompt) { await installPrompt.prompt(); installPrompt = null; $('install-button').hidden = true; }
});
window.addEventListener('appinstalled', () => { $('install-button').hidden = true; navigator.storage?.persist?.(); });
for (const name of ['online', 'offline']) window.addEventListener(name, () => { if (ready && !busy) readyStatus(); else if (!busy) status(navigator.onLine ? 'Modèle à charger' : 'Hors connexion · Chargez un modèle déjà téléchargé'); });
if ('serviceWorker' in navigator && window.isSecureContext) {
  navigator.serviceWorker.register('./sw.js', { scope: './' }).then(async registration => {
    await navigator.serviceWorker.ready;
    shellCached = true; if (ready && !busy) readyStatus();
    if (registration.waiting) error('Une mise à jour est prête. Fermez les fenêtres de Jarvis puis rouvrez l’application pour l’appliquer.');
  }).catch(() => error('L’application n’a pas pu être conservée hors ligne. Utilisez une fenêtre normale et autorisez le stockage du site.'));
}
render(); controls(); status(navigator.onLine ? 'Modèle à charger' : 'Hors connexion · Chargez un modèle déjà téléchargé');
