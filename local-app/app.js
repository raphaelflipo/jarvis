import { PARTIAL_CACHE } from './download.js';
import { MODEL_CACHE, MODELS, boundedHistory, cacheState, restoreHistory } from './models.js';

const $ = id => document.getElementById(id);
const storeKey = 'jarvis-local-history-v1';
const languageKey = 'jarvis-local-language';
const readStored = key => {
  try { return localStorage.getItem(key); } catch { return null; }
};
const writeStored = (key, value) => {
  try { localStorage.setItem(key, value); return true; } catch { return false; }
};
const preferred = new URL(location.href).searchParams.get('lang');
const english = (preferred === 'en' || preferred === 'fr' ? preferred : readStored(languageKey)) === 'en';
const language = english ? 'en' : 'fr';
const t = (fr, en) => english ? en : fr;
const native = Boolean(document.querySelector('meta[name="jarvis-native"]'));
const number = new Intl.NumberFormat(language, { maximumFractionDigits: 1 });
const engineFiles = [
  './vendor/transformers.min.js',
  './vendor/ort-wasm-simd-threaded.jsep.mjs',
  './vendor/ort-wasm-simd-threaded.jsep.wasm',
];

document.documentElement.lang = language;
if (preferred === 'fr' || preferred === 'en') writeStored(languageKey, language);
if (english) {
  document.title = 'Jarvis Local — AI on your device';
  document.querySelector('meta[name="description"]').content = 'Jarvis Local runs AI chat on your device. Download a compatible model to get started, without an account.';
  for (const node of document.querySelectorAll('[data-en]')) node.textContent = node.dataset.en;
  for (const attribute of ['aria-label', 'placeholder']) {
    for (const node of document.querySelectorAll('[data-en-' + attribute + ']')) {
      node.setAttribute(attribute, node.getAttribute('data-en-' + attribute));
    }
  }
  const link = $('language-link');
  link.href = '?lang=fr';
  link.lang = link.hreflang = 'fr';
  link.textContent = 'FR';
  link.setAttribute('aria-label', 'Interface en français');
}
$('brand-link').href = '?lang=' + language;

const welcomeTemplate = $('messages').querySelector('.empty-state').cloneNode(true);
let worker, ready = false, busy = false, loadedKey, generating = false, installPrompt, modelCached = false, replyNode;
let operation = 0, deleting = false, partial = false, renderFrame = 0;
let messages = [];
try { messages = restoreHistory(JSON.parse(readStored(storeKey) || '[]')); } catch { /* Malformed local data is ignored. */ }
const selected = readStored('jarvis-local-model');
if (Object.hasOwn(MODELS, selected)) $('model-select').value = selected;
const modelNote = $('model-note');
const compatible = Boolean(window.isSecureContext && window.Worker && window.WebAssembly && window.caches);
const deviceMemory = navigator.deviceMemory;
const limitedMemory = Number.isFinite(deviceMemory) && deviceMemory <= 4;
if (!compatible) {
  $('device-advice').textContent = t('Ouvrez Jarvis en HTTPS avec un navigateur récent qui autorise le stockage local.', 'Open Jarvis over HTTPS in a current browser with local storage enabled.');
} else if (limitedMemory) {
  $('device-advice').textContent = t('Mémoire signalée limitée. Commencez par SmolLM2, le modèle le plus léger.', 'Your browser reports limited memory. Start with the lighter SmolLM2 model.');
}

function status(text, state = 'idle') {
  const badge = $('status');
  badge.textContent = text;
  badge.title = text;
  badge.dataset.state = state;
}

function error(text = '') {
  $('error').textContent = text;
  $('error').hidden = !text;
}

function save() {
  if (!writeStored(storeKey, JSON.stringify(messages.slice(-40)))) {
    error(t('La conversation fonctionne. Ce navigateur n’a pas pu enregistrer l’historique.', 'You can keep chatting. This browser could not save the history.'));
  }
}

function append(role, content) {
  $('messages').querySelector('.empty-state')?.remove();
  const row = document.createElement('article');
  row.className = 'message ' + role;
  const label = document.createElement('p');
  label.className = 'message-meta';
  label.textContent = role === 'user' ? t('Vous', 'You') : 'Jarvis';
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = content;
  row.append(label, bubble);
  $('messages').append(row);
  return bubble;
}

function render() {
  $('messages').replaceChildren();
  if (!messages.length) $('messages').append(welcomeTemplate.cloneNode(true));
  else for (const message of messages) append(message.role, message.content);
}

function controls() {
  const currentReady = ready && loadedKey === $('model-select').value;
  $('send-button').disabled = !currentReady || busy || !$('prompt').value.trim();
  $('load-model').disabled = !compatible || busy || currentReady;
  $('load-model-label').textContent = currentReady
    ? t('Modèle chargé', 'Model loaded')
    : partial ? t('Reprendre le chargement', 'Retry loading') : t('Télécharger ou charger', 'Download or load');
  $('model-select').disabled = busy;
  $('stop-button').hidden = !busy || deleting;
  $('stop-label').textContent = generating ? t('Arrêter la réponse', 'Stop reply') : t('Annuler le chargement', 'Cancel loading');
  $('new-chat').disabled = busy;
  $('delete-model').disabled = busy;
  $('clear-history').disabled = busy;
  $('messages').setAttribute('aria-busy', String(generating));
}

function idleStatus() {
  if (!compatible) status(t('Navigateur incompatible', 'Browser unsupported'), 'unsupported');
  else status(navigator.onLine ? t('Modèle à charger', 'Load a model') : t('Hors connexion', 'Offline'), navigator.onLine ? 'idle' : 'offline');
}

async function hasEngine() {
  if (native) return true;
  try {
    return (await Promise.all(engineFiles.map(file => caches.match(new URL(file, import.meta.url))))).every(Boolean);
  } catch { return false; }
}

async function readyStatus() {
  const attempt = operation;
  const engineCached = await hasEngine();
  if (attempt !== operation || !ready || busy) return;
  const offlineReady = modelCached && engineCached;
  const badge = offlineReady ? t('Prêt hors ligne', 'Ready offline') : t('Prêt · cache partiel', 'Ready · partial cache');
  status(badge, 'ready');
  $('status').title = MODELS[loadedKey].id.split('/').at(-1) + ' · ' + badge;
}

function resetProgress(label = '') {
  $('progress').hidden = true;
  $('progress-label').textContent = label;
}

function progress(data) {
  if (!data.file?.endsWith('.onnx')) return;
  if (Number.isFinite(data.progress)) $('progress').value = data.progress;
  const loaded = number.format((data.loaded || 0) / 1e6);
  const unit = t('Mo', 'MB');
  const bytes = data.total ? loaded + ' / ' + number.format(data.total / 1e6) + ' ' + unit : loaded + ' ' + unit;
  $('progress-label').textContent = data.progress >= 100
    ? t('Préparation du modèle en mémoire…', 'Preparing the model in memory…')
    : bytes + ' · ' + t('Gardez l’application ouverte', 'Keep this app open');
}

function keepPartial() {
  cancelAnimationFrame(renderFrame);
  renderFrame = 0;
  if (messages.at(-1)?.role === 'assistant' && !messages.at(-1).content) messages.pop();
  save();
  render();
}

function endWorker() {
  worker?.terminate();
  worker = null;
  ready = busy = generating = modelCached = false;
}

function failed(message, loading) {
  endWorker();
  partial = loading;
  keepPartial();
  resetProgress(loading ? t('Les fichiers terminés et les blocs de poids enregistrés seront réutilisés.', 'The next attempt reuses saved files and completed weight blocks.') : '');
  idleStatus();
  error(message);
  controls();
}

async function load() {
  if (busy || !compatible) return;
  error();
  const key = $('model-select').value;
  const attempt = ++operation;
  busy = true;
  controls();
  const cached = await cacheState(key);
  if (attempt !== operation) return;
  if (!navigator.onLine && !(cached.complete && await hasEngine())) {
    if (attempt !== operation) return;
    busy = false;
    controls();
    error(t('Connectez-vous pour terminer le téléchargement du modèle et du moteur.', 'Connect to the internet to finish downloading the model and engine.'));
    return;
  }
  if (attempt !== operation) return;
  try {
    const storage = await navigator.storage?.estimate?.();
    if (attempt !== operation) return;
    const required = cached.weights ? 12000000 : MODELS[key].bytes * 1.1;
    if (!cached.complete && storage?.quota && storage.quota - (storage.usage || 0) < required) {
      busy = false;
      controls();
      error(t('Libérez de l’espace dans le navigateur ou sélectionnez le modèle léger.', 'Free up browser storage or select the smaller model.'));
      return;
    }
    await navigator.storage?.persist?.();
  } catch { /* Storage estimation and persistence are optional. */ }
  if (attempt !== operation) return;
  endWorker();
  busy = true;
  loadedKey = key;
  controls();
  $('progress').hidden = false;
  $('progress').removeAttribute('value');
  $('progress-label').textContent = cached.complete
    ? t('Lecture du modèle conservé sur cet appareil…', 'Reading the model stored on this device…')
    : t('Ouverture du moteur et récupération des fichiers manquants…', 'Starting the engine and fetching missing files…');
  status(t('Chargement du modèle…', 'Loading model…'), 'loading');
  try { worker = new Worker(new URL('./inference-worker.js', import.meta.url), { type: 'module' }); }
  catch {
    failed(t('Le navigateur ne peut pas démarrer le moteur local. Essayez un autre navigateur récent.', 'This browser could not start the local engine. Try another current browser.'), true);
    return;
  }
  const active = worker;
  worker.onmessage = async ({ data }) => {
    if (attempt !== operation || active !== worker) return;
    if (data.type === 'progress') {
      progress(data);
    } else if (data.type === 'cache-warning') {
      error(t('Le navigateur a refusé de conserver un fichier. Le stockage hors ligne peut être incomplet.', 'The browser could not save a file. Offline storage may be incomplete.'));
    } else if (data.type === 'ready') {
      const current = await cacheState(key);
      if (attempt !== operation || active !== worker) return;
      ready = true;
      busy = false;
      partial = false;
      modelCached = current.complete;
      writeStored('jarvis-local-model', loadedKey);
      resetProgress(t('Le modèle est prêt.', 'The model is ready.'));
      status(t('Modèle prêt', 'Model ready'), 'ready');
      readyStatus();
      controls();
      $('prompt').focus({ preventScroll: true });
    } else if (data.type === 'token' && generating) {
      messages.at(-1).content += data.text;
      if (!renderFrame) renderFrame = requestAnimationFrame(() => {
        renderFrame = 0;
        if (generating) replyNode.textContent = messages.at(-1).content;
      });
    } else if (data.type === 'done' && generating) {
      cancelAnimationFrame(renderFrame);
      renderFrame = 0;
      messages.at(-1).content = data.text || messages.at(-1).content ||
        t('Le modèle n’a rien produit. Essayez de reformuler.', 'The model returned no text. Try rephrasing your prompt.');
      replyNode.textContent = messages.at(-1).content;
      const timing = document.createElement('span');
      timing.className = 'message-meta';
      const rate = Number.isFinite(data.tokens) && Number.isFinite(data.seconds) && data.seconds > 0 && data.tokens > 0
        ? ' · ' + number.format(data.tokens / data.seconds) + ' tokens/s' : '';
      timing.textContent = number.format(data.seconds) + ' s' + rate + ' · ' + t('Calcul local', 'Local inference');
      replyNode.after(timing);
      generating = busy = false;
      save();
      status(t('Modèle prêt', 'Model ready'), 'ready');
      readyStatus();
      controls();
    } else if (data.type === 'error') {
      const loading = data.phase === 'load';
      failed(loading
        ? t('Le chargement a échoué. Vérifiez la connexion et le stockage, ou choisissez SmolLM2 si la mémoire est limitée.', 'Loading failed. Check your connection and storage, or choose SmolLM2 if memory is limited.')
        : t('La génération s’est interrompue. Essayez une demande plus courte ou le modèle léger.', 'Generation stopped. Try a shorter prompt or the smaller model.'), loading);
    }
  };
  worker.onerror = () => {
    if (attempt !== operation || active !== worker) return;
    failed(t('Le navigateur a interrompu le moteur. Réessayez avec le modèle léger.', 'The browser interrupted the engine. Try again with the smaller model.'), !generating);
  };
  worker.postMessage({ type: 'load', key, offline: cached.complete || !navigator.onLine });
}

function updateModelNote() {
  const key = $('model-select').value;
  modelNote.textContent = key === 'small'
    ? t('Environ 140 Mo. Le plus léger, surtout adapté aux échanges en anglais.', 'About 140 MB. The smallest download, best suited to English.')
    : t('Environ 628 Mo. Plus adapté au français et plus exigeant en mémoire.', 'About 628 MB. Better suited to French and requires more memory.');
  controls();
}

$('load-model').addEventListener('click', load);
$('model-select').addEventListener('change', () => {
  partial = false;
  if (ready && loadedKey === $('model-select').value) readyStatus();
  else idleStatus();
  updateModelNote();
});
$('chat-form').addEventListener('submit', event => {
  event.preventDefault();
  const text = $('prompt').value.trim();
  if (!ready || busy || !text || loadedKey !== $('model-select').value) return;
  error();
  const content = text.slice(0, 4000);
  messages.push({ role: 'user', content });
  append('user', content);
  const history = boundedHistory(messages);
  messages.push({ role: 'assistant', content: '' });
  replyNode = append('assistant', '');
  $('prompt').value = '';
  busy = generating = true;
  controls();
  save();
  status(t('Génération sur cet appareil…', 'Generating on this device…'), 'generating');
  replyNode.scrollIntoView({ block: 'nearest', behavior: 'auto' });
  worker.postMessage({ type: 'generate', messages: history });
});
$('prompt').addEventListener('input', controls);
$('prompt').addEventListener('keydown', event => {
  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    $('chat-form').requestSubmit();
  }
});
$('stop-button').addEventListener('click', () => {
  operation++;
  partial = !generating;
  endWorker();
  keepPartial();
  resetProgress(partial ? t('Le prochain essai réutilise les fichiers et les blocs de poids conservés.', 'Retrying reuses saved files and weight blocks.') : '');
  status(t('Arrêté · Chargez le modèle pour reprendre', 'Stopped · Load the model to continue'));
  controls();
});
function clearHistory() { messages = []; save(); render(); }
$('new-chat').addEventListener('click', clearHistory);
$('clear-history').addEventListener('click', () => { clearHistory(); $('settings-dialog').close(); });
$('delete-model').addEventListener('click', async () => {
  if (busy) return;
  operation++;
  endWorker();
  partial = false;
  busy = deleting = true;
  controls();
  try {
    await Promise.all([caches.delete(MODEL_CACHE), caches.delete(PARTIAL_CACHE)]);
    resetProgress();
    status(t('Modèles supprimés de cet appareil', 'Models removed from this device'));
  } catch {
    error(t('Impossible de supprimer les modèles. Vous pouvez effacer les données du site dans le navigateur.', 'The models could not be removed. You can clear this site’s data in your browser.'));
  } finally {
    busy = deleting = false;
    controls();
    $('settings-dialog').close();
  }
});
$('open-settings').addEventListener('click', () => $('settings-dialog').showModal());
$('close-settings').addEventListener('click', () => $('settings-dialog').close());
window.addEventListener('beforeinstallprompt', event => {
  event.preventDefault();
  installPrompt = event;
  $('install-button').hidden = native;
});
$('install-button').addEventListener('click', async () => {
  if (installPrompt) { await installPrompt.prompt(); installPrompt = null; $('install-button').hidden = true; }
});
window.addEventListener('appinstalled', () => {
  $('install-button').hidden = true;
  navigator.storage?.persist?.().catch(() => {});
});
for (const name of ['online', 'offline']) window.addEventListener(name, () => {
  if (busy) return;
  if (ready) readyStatus();
  else idleStatus();
});
if (native) {
  document.querySelector('.install-help').hidden = true;
} else if ('serviceWorker' in navigator && window.isSecureContext) {
  navigator.serviceWorker.register('./sw.js', { scope: './' }).then(registration => {
    const announceUpdate = () => error(t('Une mise à jour est prête. Fermez les fenêtres de Jarvis puis rouvrez l’application.', 'An update is ready. Close the Jarvis windows, then reopen the app.'));
    if (registration.waiting) announceUpdate();
    registration.addEventListener('updatefound', () => {
      const installing = registration.installing;
      installing?.addEventListener('statechange', () => {
        if (installing.state === 'installed' && navigator.serviceWorker.controller && registration.waiting) announceUpdate();
      });
    });
  }).catch(() => error(t('Le navigateur n’a pas pu préparer l’interface hors ligne.', 'The browser could not prepare the offline interface.')));
}
if (messages.length) render();
updateModelNote();
idleStatus();
