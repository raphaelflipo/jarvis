(async () => {
  const offline=new URLSearchParams(location.search).get('offline')==='1';
  if(offline) Object.defineProperty(navigator,'onLine',{configurable:true,get:()=>false});
  const wait=async predicate=>{const deadline=Date.now()+180000;while(!predicate()){if(Date.now()>deadline)throw Error('Interface: délai dépassé');await new Promise(resolve=>setTimeout(resolve,100));}};
  const history=JSON.parse(localStorage.getItem('jarvis-local-history-v1')||'[]');
  if(history.length!==40)throw Error('Historique perdu dans l’interface');
  document.getElementById('load-model').click();
  await wait(()=>document.getElementById('load-model').textContent==='Modèle chargé');
  const prompt=document.getElementById('prompt');prompt.value='Say hello in one short sentence.';prompt.dispatchEvent(new Event('input',{bubbles:true}));
  const send=document.getElementById('send-button');if(send.disabled)throw Error('Envoi désactivé');send.click();
  await wait(()=>document.querySelectorAll('#messages .message').length>=42 && document.getElementById('stop-button').hidden);
  if(JSON.parse(localStorage.getItem('jarvis-local-history-v1')).length!==40)throw Error('Historique non borné');
  return {ok:true,offline,history:40,reply:document.querySelector('#messages .message:last-child').textContent.trim(),status:document.getElementById('status').textContent};
})()
