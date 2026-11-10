export const MODEL_CACHE = 'jarvis-local-models-v1';
export const MODELS = Object.freeze({
  small: { id: 'HuggingFaceTB/SmolLM2-135M-Instruct', revision: '12fd25f77366fa6b3b4b768ec3050bf629380bac', label: 'Léger · SmolLM2 135M', bytes: 140000000, note: 'Environ 140 Mo. Le plus léger ; réponses surtout en anglais, français limité.' },
  balanced: { id: 'onnx-community/Qwen3-0.6B-ONNX', revision: '58ca03a5e7b354b480b1a82b34bde8dc7b854cc0', label: 'Français · Qwen3 0.6B', bytes: 628000000, note: 'Environ 628 Mo. Plus adapté au français ; chargement et réponses plus lents sur téléphone.' },
});
export function modelURL(key, file = 'onnx/model_quantized.onnx') {
  const m = MODELS[key];
  if (!m) throw new Error('Modèle inconnu');
  return `https://huggingface.co/${m.id}/resolve/${m.revision}/${file}`;
}
export function boundedHistory(messages) {
  return messages.filter(m => ['user', 'assistant'].includes(m.role) && typeof m.content === 'string' && m.content.trim())
    .slice(-12).map(m => ({ role: m.role, content: m.content.slice(0, 4000) }));
}
