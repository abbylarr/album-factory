/* What runs alongside the order's next step: one row per process under the head plate,
   small marks under the plate on board cards. The plate itself keeps only the next move. */
const OrderActivities=(()=>{
  const FLASH=5000,flashes=new Map();
  const spin='<svg class="act-spin" viewBox="0 0 28 28" aria-hidden="true"><circle cx="14" cy="14" r="12.5"/></svg>';
  const here=o=>state.uploading&&state.progress?.orderId===o.id;
  // The browser that uploads knows best; any other view reads the run the server keeps.
  function upload(o){
    if(here(o)){const p=state.progress;return {running:true,done:p.done,total:p.total};}
    const u=o.upload;return u&&u.done<u.total?{running:!u.stalled,done:u.done,total:u.total,shoot:u.shoot_id}:null;}
  // Portraits and general shoots plus teacher frames uploaded from this order.
  const work=o=>{const s=stats(o);return {total:s.total+(o.teacher_total||0),pending:s.pending+(o.teacher_pending||0)};};
  const errors=o=>o.photos?o.photos.filter(p=>p.status==='error').length:o.error_count||0;
  const eta=sec=>sec==null?'':sec<60?'меньше минуты':`~${Math.max(2,Math.ceil(sec/60))} мин`;
  function flash(orderId,kind,detail){flashes.set(orderId,{...flashes.get(orderId),[kind]:{at:Date.now(),detail}});
    setTimeout(()=>{if(state.order?.id===orderId)syncSummary(state.order);},FLASH+100);}
  const fresh=(o,kind)=>{const f=flashes.get(o.id)?.[kind];return f&&Date.now()-f.at<FLASH?f:null;};

  function rows(o){
    const list=[],s=stats(o),q=o.layout_queue,waits=q&&!q.error?'макет ждёт':'',u=upload(o);
    if(u?.running)list.push({key:'upload',icon:'upload',motion:'rise',label:'Загрузка',detail:`${u.done} из ${u.total}`,bar:u.done/Math.max(1,u.total),tag:waits});
    else if(u)list.push({key:'upload',tone:'alert',icon:'upload',label:'Загрузка прервана',detail:`не загружено ${u.total-u.done}`,tag:waits,actions:[['upload-resume','Догрузить'],['upload-dismiss','Скрыть','quiet']]});
    else{const f=fresh(o,'upload');if(f)list.push({key:'upload-done',tone:'done',icon:'check',label:'Загружено',detail:f.detail});}
    const w=work(o);
    if(w.pending)list.push({key:'processing',icon:'photo',motion:'spin',label:'Обработка',detail:`${w.total-w.pending} из ${w.total}`,bar:(w.total-w.pending)/Math.max(1,w.total),eta:eta(o.processing?.eta_seconds),tag:waits});
    else{const f=fresh(o,'processing');if(f)list.push({key:'processing-done',tone:'done',icon:'check',label:'Фото обработаны',detail:f.detail});}
    const failed=errors(o);
    if(failed)list.push({key:'errors',tone:'alert',icon:'alert',label:'Не обработались',detail:count(failed,'фото','фото','фото'),actions:[['retry-photos','Повторить']]});
    if(s.review&&!['new','photos'].includes(o.stage))list.push({key:'review',tone:'task',icon:'eye',label:'Фото на проверку',detail:count(s.review,'снимок','снимка','снимков'),link:[`#order/${o.id}/review`,'Проверить']});
    return list;}

  function row(x){
    const acts=(x.actions||[]).map(([v,l,cls])=>`<button type="button" class="act-action ${cls||''}" data-v2="${v}">${esc(l)}</button>`).join('')+(x.link?`<a class="act-action" href="${x.link[0]}">${esc(x.link[1])}</a>`:'');
    return `<div class="act ${x.tone||''}" data-key="${x.key}"><span class="act-ico ${x.motion==='rise'?'rise':''}">${x.motion==='spin'?spin:''}${svgIcon(x.icon,15)}</span><span class="act-label">${esc(x.label)}</span><span class="act-detail">${esc(x.detail||'')}</span>${x.bar!=null?`<span class="act-bar"><i style="width:${Math.round(x.bar*100)}%"></i></span>`:'<span class="act-fill"></span>'}${x.eta?`<span class="act-eta">${esc(x.eta)}</span>`:''}${x.tag?`<span class="act-tag">${esc(x.tag)}</span>`:''}${acts}</div>`;}
  const html=o=>{const list=rows(o);return list.length?`<div class="act-list">${list.map(row).join('')}</div>`:'';};

  // Board cards: only what runs or broke, as one quiet line under the plate. On the photos stage
  // the plate itself already counts processing, so the card does not repeat it.
  function mini(o){
    const marks=rows(o).filter(x=>(x.motion||x.tone==='alert')&&!(x.key==='processing'&&o.stage==='photos')).map(x=>x.tone==='alert'?`<span class="alert">${svgIcon('alert',12)}${esc(x.label)}</span>`:`<span><span class="mini-spin">${svgIcon('loader',12)}</span>${esc(x.label)}${x.bar!=null?' '+Math.round(x.bar*100)+'%':''}</span>`);
    return marks.length?`<div class="act-mini">${marks.join('')}</div>`:'';}

  // Cards keep a fixed slot for the marks: the marks change every few seconds while the rest of the card
  // stays put, so only the slot is patched and the cards neither redraw nor replay their animations.
  const slot=o=>`<div class="act-slot" data-card-marks="${esc(o.id)}"></div>`;
  function refreshCards(){for(const el of document.querySelectorAll('[data-card-marks]')){const id=el.dataset.cardMarks,o=state.orders?.find(x=>x.id===id);if(o)morph(el,mini(o));}}

  function observe(previous,next){
    if(work(previous).pending&&!work(next).pending)flash(next.id,'processing',count(work(next).total,'снимок','снимка','снимков'));}
  // The run is over for this tab: forget the server's last count so no card or head shows a stale share.
  function uploaded(orderId,n){for(const o of [state.order,...(state.orders||[])])if(o?.id===orderId)o.upload=null;
    flash(orderId,'upload',count(n,'фото','фото','фото'));refreshCards();}

  // Patch the live DOM towards new markup: kept elements keep their animations, rows match by data-key.
  function morph(el,markup){const t=document.createElement('div');t.innerHTML=markup;patchChildren(el,t);}
  const same=(a,b)=>a.nodeType===b.nodeType&&a.nodeName===b.nodeName&&(a.nodeType!==1||(a.dataset?.key||'')===(b.dataset?.key||''));
  function patchNode(a,b){
    if(a.nodeType!==1){if(a.nodeValue!==b.nodeValue)a.nodeValue=b.nodeValue;return;}
    for(const {name,value} of [...b.attributes])if(a.getAttribute(name)!==value)a.setAttribute(name,value);
    for(const {name} of [...a.attributes])if(!b.hasAttribute(name))a.removeAttribute(name);
    if(a.nodeName==='PROGRESS'){a.value=b.value;a.max=b.max;}
    patchChildren(a,b);}
  function patchChildren(a,b){const next=[...b.childNodes];
    next.forEach((nb,i)=>{const cur=a.childNodes[i];
      if(cur&&same(cur,nb)){patchNode(cur,nb);return;}
      const key=nb.nodeType===1&&nb.dataset?.key,found=key&&[...a.childNodes].slice(i).find(n=>n.nodeType===1&&n.dataset?.key===key);
      if(found){a.insertBefore(found,cur||null);patchNode(found,nb);}else a.insertBefore(nb,cur||null);});
    while(a.childNodes.length>next.length)a.lastChild.remove();}

  // «Догрузить»: pick the files again for the same shoot; the ones already on the server are skipped.
  function resume(){const o=state.order,u=upload(o),input=document.createElement('input');
    input.type='file';input.multiple=true;input.accept='image/jpeg,image/png,.jpg,.jpeg,.png';
    input.onchange=()=>{const files=[...input.files];if(files.length)uploadFiles(files,u?.shoot||state.shootId);};input.click();}
  async function action(name){const id=state.order.id;
    if(name==='upload-resume')resume();
    if(name==='upload-dismiss'){await api(`/orders/${id}/uploads`,{method:'DELETE'});
      // Not uploading the rest: a queued layout now waits for processing only.
      if(state.order.layout_queue)await api(`/orders/${id}/layout/queue`,json('PATCH',{uploading:false}));await refreshOrder();}
    if(name==='retry-photos'){await api(`/orders/${id}/retry`,json('POST',{}));await refreshOrder();toast('Обрабатываем заново');}}
  return {html,slot,refreshCards,observe,uploaded,morph,action,ACTIONS:['upload-resume','upload-dismiss','retry-photos']};
})();
