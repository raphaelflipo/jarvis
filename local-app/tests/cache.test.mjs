import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

const scope = 'https://example.test/jarvis/app/';
const shell = 'jarvis-local-shell-3.3.0-rc.2-web.4';
const previous = 'jarvis-local-shell-3.3.0-rc.2-web.1';
const modelCache = 'jarvis-local-models-v1';
const engineFiles = [
  'vendor/transformers.min.js',
  'vendor/ort-wasm-simd-threaded.jsep.mjs',
  'vendor/ort-wasm-simd-threaded.jsep.wasm',
];
const worker = readFileSync(new URL('../sw.js', import.meta.url), 'utf8');

function createWorker() {
  const handlers = new Map();
  const storage = new Map();
  const fetched = [];
  let online = true;
  const href = input => new URL(typeof input === 'string' ? input : input.url, scope).href;
  async function fetch(input) {
    if (!online) throw new TypeError('Network unavailable');
    fetched.push(href(input));
    return new Response(href(input));
  }
  const caches = {
    async open(name) {
      if (!storage.has(name)) storage.set(name, new Map());
      const saved = storage.get(name);
      return {
        async addAll(files) {
          for (const file of files) saved.set(href(file), await fetch(file));
        },
        async match(file, { ignoreSearch } = {}) {
          const url = new URL(href(file));
          if (ignoreSearch) url.search = '';
          return saved.get(url.href)?.clone();
        },
        async put(file, response) { saved.set(href(file), response); },
      };
    },
    async match(file) {
      for (const name of storage.keys()) {
        const found = await (await this.open(name)).match(file);
        if (found) return found;
      }
    },
    async keys() { return Array.from(storage.keys()); },
    async delete(name) { return storage.delete(name); },
  };
  const self = {
    registration: { scope },
    location: new URL(scope),
    clients: { async claim() {} },
    addEventListener(name, handler) { handlers.set(name, handler); },
  };
  runInNewContext(worker, { self, URL, Request, caches, fetch });
  function event(name, request) {
    const jobs = [];
    let response;
    handlers.get(name)({
      request,
      waitUntil(job) { jobs.push(job); },
      respondWith(value) { response = value; },
    });
    return { jobs: Promise.all(jobs), response };
  }
  return {
    event,
    caches,
    fetched,
    offline() { online = false; },
  };
}

test('shell install leaves the engine on demand while keeping language queries offline', async () => {
  const sw = createWorker();
  await sw.event('install').jobs;
  assert.ok(sw.fetched.length > 0);
  assert.ok(sw.fetched.every(url => !url.includes('/vendor/')));
  sw.offline();
  const f = sw.event('fetch', new Request(scope + '?lang=en'));
  assert.equal(await (await f.response).text(), scope);
});

test('engine loads on demand and its stored copy serves subsequent requests offline', async () => {
  const sw = createWorker();
  for (const file of engineFiles) {
    const target = scope + file;
    const live = sw.event('fetch', new Request(target));
    assert.equal(await (await live.response).text(), target);
    await live.jobs;
  }
  sw.offline();
  for (const file of engineFiles) {
    const target = scope + file;
    const cached = sw.event('fetch', new Request(target + '?view=local'));
    assert.equal(await (await cached.response).text(), target);
    await cached.jobs;
  }
  assert.deepEqual(sw.fetched, engineFiles.map(file => scope + file));
});

for (const legacyShell of [previous, 'jarvis-local-shell-3.3.0-rc.2']) test('upgrade retains engine and model cache from ' + legacyShell, async () => {
  const sw = createWorker();
  const old = await sw.caches.open(legacyShell);
  for (const file of engineFiles) await old.put(file, new Response(file));
  await sw.caches.open(modelCache);
  await sw.event('install').jobs;
  await sw.event('activate').jobs;
  sw.offline();
  assert.ok(!(await sw.caches.keys()).includes(legacyShell));
  assert.ok((await sw.caches.keys()).includes(shell));
  assert.ok((await sw.caches.keys()).includes(modelCache));
  for (const file of engineFiles) {
    const f = sw.event('fetch', new Request(scope + file));
    assert.equal(await (await f.response).text(), file);
    await f.jobs;
  }
});

test('only complete first-party application assets use the engine cache', async () => {
  const sw = createWorker();
  for (const request of [
    new Request('https://huggingface.co/weights.onnx'),
    new Request('https://example.test/about/'),
    new Request(scope + engineFiles[0], { method: 'POST' }),
    new Request(scope + engineFiles[2], { headers: { Range: 'bytes=0-512' } }),
  ]) {
    assert.equal(sw.event('fetch', request).response, undefined);
  }
});
