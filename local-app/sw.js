const CACHE = 'jarvis-local-shell-3.3.0-rc.2-web.3';
const LEGACY_SHELLS = ['jarvis-local-shell-3.3.0-rc.2', 'jarvis-local-shell-3.3.0-rc.2-web.1'];
const ENGINE = 'jarvis-local-engine-onnx-1.22.0-dev.20250409-89f8206ba4';
const FILES = [
  './', './index.html', './styles.css', './app.js', './models.js', './download.js', './inference-worker.js',
  './manifest.webmanifest', './icon-192.png', './icon-512.png', './apple-touch-icon.png',
];
const ENGINE_FILES = [
  './vendor/transformers.min.js',
  './vendor/ort-wasm-simd-threaded.jsep.mjs',
  './vendor/ort-wasm-simd-threaded.jsep.wasm',
];
const engineURLs = new Set(ENGINE_FILES.map(file => new URL(file, self.registration.scope).href));

self.addEventListener('install', event => event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(FILES.map(file => new Request(new URL(file, self.registration.scope), { cache: 'reload' }))))));
self.addEventListener('activate', event => event.waitUntil((async () => {
  const names = await caches.keys();
  const retained = new Set();
  for (const legacy of LEGACY_SHELLS.filter(name => names.includes(name))) {
    const previous = await caches.open(legacy);
    const engine = await caches.open(ENGINE);
    for (const file of ENGINE_FILES) {
      const saved = await previous.match(file);
      if (!saved || await engine.match(file)) continue;
      try { await engine.put(file, saved); }
      catch { retained.add(legacy); }
    }
  }
  for (const name of names) {
    if (name === CACHE || retained.has(name)) continue;
    if (name.startsWith('jarvis-local-shell-')) await caches.delete(name);
  }
  await self.clients.claim();
})()));

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin || !url.href.startsWith(self.registration.scope)) return;
  url.search = '';
  if (engineURLs.has(url.href)) {
    if (event.request.headers.has('Range')) return;
    const response = caches.match(url.href).then(cached => cached || fetch(event.request));
    event.waitUntil(response.then(async result => {
      if (!result.ok || result.status !== 200) return;
      const copy = result.clone();
      const cache = await caches.open(ENGINE);
      if (!await cache.match(url.href)) await cache.put(url.href, copy);
      else await copy.body?.cancel();
    }).catch(() => {}));
    event.respondWith(response);
    return;
  }
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const cached = await cache.match(event.request, { ignoreSearch: true });
    if (cached) return cached;
    try { return await fetch(event.request); }
    catch (error) {
      if (event.request.mode === 'navigate') return cache.match('./index.html');
      throw error;
    }
  })());
});
