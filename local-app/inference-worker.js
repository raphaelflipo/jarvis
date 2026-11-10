import { AutoTokenizer, AutoModelForCausalLM, TextStreamer, env } from './vendor/transformers.min.js';
import { MODEL_CACHE, MODELS, boundedHistory } from './models.js';

// No prompt, response or history is sent to a server. Only public model files are fetched.
env.allowLocalModels = false;
env.useBrowserCache = false;
env.useCustomCache = true;
env.backends.onnx.wasm.numThreads = 1;
env.backends.onnx.wasm.proxy = false;
env.backends.onnx.wasm.wasmPaths = new URL('./vendor/', import.meta.url).href;
let cacheFailed = false;
env.customCache = {
  async match(request) { return (await caches.open(MODEL_CACHE)).match(request); },
  async put(request, response) {
    try { await (await caches.open(MODEL_CACHE)).put(request, response); }
    catch (error) { cacheFailed = true; postMessage({ type: 'cache-warning' }); throw error; }
  },
};
let tokenizer, model, modelKey, busy = false;
const send = (type, extra = {}) => postMessage({ type, ...extra });
self.onmessage = async ({ data }) => {
  if (busy) return;
  busy = true;
  try {
    if (data.type === 'load') {
      const selected = MODELS[data.key];
      if (!selected) throw new Error('Modèle inconnu');
      modelKey = data.key;
      env.allowLocalModels = Boolean(data.offline);
      env.allowRemoteModels = !data.offline;
      cacheFailed = false;
      const options = { revision: selected.revision, local_files_only: data.offline,
        progress_callback: p => { if (p.status === 'progress') send('progress', { file: p.file, loaded: p.loaded, total: p.total, progress: p.progress }); } };
      tokenizer = await AutoTokenizer.from_pretrained(selected.id, options);
      tokenizer.truncation_side = 'left';
      model = await AutoModelForCausalLM.from_pretrained(selected.id, { ...options, device: 'wasm', dtype: 'q8' });
      send('ready', { cached: !cacheFailed });
    } else if (data.type === 'generate') {
      if (!model || !tokenizer) throw new Error('Chargez d’abord un modèle.');
      const history = boundedHistory(data.messages);
      const prompt = tokenizer.apply_chat_template([
        { role: 'system', content: 'You are Jarvis, a helpful local assistant. Reply briefly in the language of the user. You cannot browse the web or control other apps. Be honest when unsure.' },
        ...history,
      ], { tokenize: false, add_generation_prompt: true, enable_thinking: false });
      const inputs = tokenizer(prompt, { truncation: true, max_length: 1024 });
      const start = performance.now();
      const streamer = new TextStreamer(tokenizer, { skip_prompt: true, skip_special_tokens: true,
        callback_function: text => send('token', { text }) });
      const sampling = modelKey === 'balanced' ? { do_sample: true, temperature: 0.7, top_p: 0.8, top_k: 20 } : { do_sample: false };
      const output = await model.generate({ ...inputs, ...sampling, max_new_tokens: 192, repetition_penalty: 1.08, streamer });
      const generated = output.tolist()[0].slice(inputs.input_ids.dims[1]);
      send('done', { text: tokenizer.decode(generated, { skip_special_tokens: true }), seconds: (performance.now() - start) / 1000 });
    }
  } catch (error) {
    send('error', { message: String(error.message || error).slice(0, 500), phase: data.type });
  } finally { busy = false; }
};
