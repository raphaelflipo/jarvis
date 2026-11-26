import { MODEL_CACHE, modelURL } from './models.js';
export const PARTIAL_CACHE = 'jarvis-local-downloads-v1';
const block = 4 * 1024 * 1024;

// Each immutable model URL has independent range keys. A partial response never enters the model cache.
export async function prepareWeights(key, progress) {
  const url = modelURL(key);
  if (!globalThis.caches || !globalThis.navigator?.locks) return;
  await navigator.locks.request('jarvis-weights-' + url, async () => {
    const complete = await caches.open(MODEL_CACHE);
    if (await complete.match(url)) return;
    const partial = await caches.open(PARTIAL_CACHE);
    const prefix = new URL('./download-block/' + encodeURIComponent(url) + '/', import.meta.url).href;
    const existing = async () => (await partial.keys()).filter(request => request.url.startsWith(prefix));
    async function cleanup() { for (const request of await existing()) await partial.delete(request); }
    let offset = 0, total, ranges = [];
    const stored = new Map((await existing()).map(request => [request.url, request]));
    while (total === undefined || offset < total) {
      const cacheKey = prefix + offset;
      let piece = stored.has(cacheKey) ? await partial.match(cacheKey) : undefined;
      if (!piece) {
        const r = await fetch(url, { headers: { Range: 'bytes=' + offset + '-' + (offset + block - 1) } });
        if (r.status === 200) {
          await complete.put(url, r); await cleanup(); return;
        }
        if ([400,403,405,416].includes(r.status)) { await r.body?.cancel(); return; }
        if (r.status !== 206) throw Error('HTTP ' + r.status);
        const match = /^bytes (\d+)-(\d+)\/(\d+)$/.exec(r.headers.get('Content-Range') || '');
        if (!match) { await r.body?.cancel(); return; } // Cross-origin server did not expose its range metadata.
        const [start, end, size] = match.slice(1).map(Number);
        if (start !== offset || size <= end || end !== Math.min(start + block, size) - 1 || total !== undefined && size !== total) throw Error('Invalid content range');
        const bytes = await r.arrayBuffer();
        if (bytes.byteLength !== end - start + 1) throw Error('Incomplete range');
        piece = new Response(bytes,{headers:{'X-Range-Total':String(size),'X-Range-Size':String(bytes.byteLength)}});
        try { await partial.put(cacheKey,piece.clone()); } catch { await cleanup(); return; }
      }
      const size = Number(piece.headers.get('X-Range-Total')), length = Number(piece.headers.get('X-Range-Size'));
      if (!Number.isSafeInteger(size) || size <= offset || length !== Math.min(block, size-offset) || total!==undefined && size!==total) { await cleanup(); return; }
      total = size; offset += length; ranges.push(cacheKey);
      progress({file:'onnx/model_quantized.onnx',loaded:offset,total,progress:offset*100/total});
    }
    let index=0;
    const stream=new ReadableStream({async pull(controller){
      try {
        if(index===ranges.length){controller.close();return;}
        const saved=await partial.match(ranges[index++]);
        if(!saved)throw Error('Missing saved range');
        controller.enqueue(new Uint8Array(await saved.arrayBuffer()));
      } catch(e){controller.error(e);}
    }});
    try { await complete.put(url,new Response(stream,{headers:{'Content-Length':String(total),'Content-Type':'application/octet-stream'}})); }
    catch { await cleanup(); return; }
    await cleanup();
  });
}
