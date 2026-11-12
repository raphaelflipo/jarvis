const CACHE = 'jarvis-local-shell-3.3.0-rc.1';
const FILES = ['./', './index.html', './styles.css', './app.js', './models.js', './inference-worker.js', './manifest.webmanifest', './icon-192.png', './icon-512.png', './apple-touch-icon.png', './vendor/transformers.min.js', './vendor/ort-wasm-simd-threaded.jsep.mjs', './vendor/ort-wasm-simd-threaded.jsep.wasm'];
self.addEventListener('install', event => event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(FILES))));
self.addEventListener('activate', event => event.waitUntil((async () => {
  for (const name of await caches.keys()) if (name.startsWith('jarvis-local-shell-') && name !== CACHE) await caches.delete(name);
  await self.clients.claim();
})()));
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin || !url.href.startsWith(self.registration.scope)) return;
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
