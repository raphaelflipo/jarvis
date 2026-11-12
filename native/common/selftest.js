(async () => {
  const params = new URLSearchParams(location.search);
  const offline = params.get('offline') === '1';
  const model = params.get('model') || 'small';
  const report = { secureContext: isSecureContext, cacheAPI: typeof caches !== 'undefined', offline, origin: location.origin };
  if (!report.secureContext || !report.cacheAPI) throw Error('Contexte local incompatible');
  const historyKey = 'jarvis-local-history-v1';
  if (offline) {
    if (JSON.parse(localStorage.getItem(historyKey) || '[]').length !== 40) throw Error('Historique non conservé');
  } else {
    localStorage.setItem(historyKey, JSON.stringify(Array.from({length:40}, (_,i) => ({ role:i%2?'assistant':'user', content:`test ${i}` }))));
  }
  report.history = JSON.parse(localStorage.getItem(historyKey)).length;
  const worker = new Worker('./inference-worker.js', {type:'module'});
  const result = await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => { worker.terminate(); reject(Error('Délai de test dépassé')); }, 600000);
    worker.onerror = e => { clearTimeout(timeout); reject(Error(e.message)); };
    worker.onmessage = ({data}) => {
      if (data.type === 'ready') {
        report.modelCached = data.cached;
        worker.postMessage({type:'generate', messages:[{role:'user',content:model === 'balanced' ? 'Réponds uniquement en français : dis bonjour en une courte phrase.' : 'Say hello in one short sentence.'}]});
      } else if (data.type === 'error') { clearTimeout(timeout); reject(Error(data.message)); }
      else if (data.type === 'done') { clearTimeout(timeout); resolve({text:data.text, seconds:data.seconds}); }
    };
    worker.postMessage({type:'load', key:model, offline});
  });
  worker.terminate();
  if (!result.text.trim()) throw Error('Réponse vide');
  return {...report, ...result, ok:true};
})()
