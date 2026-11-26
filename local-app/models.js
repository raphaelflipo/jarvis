export const MODEL_CACHE = 'jarvis-local-models-v1';
export const MODELS = Object.freeze({
  small: { id: 'HuggingFaceTB/SmolLM2-135M-Instruct', revision: '12fd25f77366fa6b3b4b768ec3050bf629380bac', bytes: 140000000 },
  balanced: { id: 'onnx-community/Qwen3-0.6B-ONNX', revision: '58ca03a5e7b354b480b1a82b34bde8dc7b854cc0', bytes: 628000000 },
});
const modelFiles = ['onnx/model_quantized.onnx', 'tokenizer.json', 'tokenizer_config.json', 'config.json', 'generation_config.json'];
export function modelURL(key, file = 'onnx/model_quantized.onnx') {
  const m = MODELS[key];
  if (!m) throw new Error('Modèle inconnu');
  return `https://huggingface.co/${m.id}/resolve/${m.revision}/${file}`;
}
export async function cacheState(key) {
  try {
    const cache = await caches.open(MODEL_CACHE);
    const files = await Promise.all(modelFiles.map(file => cache.match(modelURL(key, file))));
    return { complete: files.every(Boolean), weights: Boolean(files[0]) };
  } catch { return { complete: false, weights: false }; }
}
export function restoreHistory(messages) {
  if (!Array.isArray(messages)) return [];
  return messages.filter(m => m && ['user', 'assistant'].includes(m.role) && typeof m.content === 'string' && m.content.trim())
    .slice(-40).map(m => ({ role: m.role, content: m.content.slice(0, 16000) }));
}
export function boundedHistory(messages) {
  return restoreHistory(messages).slice(-12).map(m => ({ role: m.role, content: m.content.slice(0, 4000) }));
}
