/* Preview of the current draft on a real class: pick a class with complete data, then page through the finished album. */
window.ClassPreview=(()=>{
  let host,ctx,result=null,classInfo=null,owner=null,index=0,loading=0;
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const plural=(n,one,few,many)=>n+' '+(n%10===1&&n%100!==11?one:n%10>=2&&n%10<=4&&(n%100<10||n%100>=20)?few:many);
  async function request(path,method='GET',body){const r=await fetch('/api'+path,{method,headers:{'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'Не удалось построить предпросмотр');return d;}
  function dialog(){
    if(host)return host;
    host=document.createElement('dialog');host.id='class-preview';host.setAttribute('aria-labelledby','class-preview-title');
    host.addEventListener('click',onClick);host.addEventListener('change',e=>{if(e.target.id==='class-preview-owner'){owner=e.target.value;index=0;draw();}});
    document.addEventListener('keydown',e=>{if(!host.open||!result||e.target.closest?.('select,input,summary'))return;if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();step(e.key==='ArrowRight'?1:-1);}});
    host.addEventListener('close',()=>{if(!host.open)loading++;});
    document.body.append(host);return host;
  }
  function open(context){ctx=context;result=null;classInfo=null;dialog().classList.remove('is-album');host.showModal();chooseClass();}
  function heading(title,sub,back=false){return `<div class="dialog-heading cp-head">${back?'<button type="button" class="cp-back" data-cp="back" aria-label="Выбрать другой класс">←</button>':''}<div><h2 id="class-preview-title">${title}</h2>${sub?`<p class="muted">${sub}</p>`:''}</div><button type="button" data-cp="close" aria-label="Закрыть">×</button></div>`;}
  async function chooseClass(){
    const run=++loading;host.classList.remove('is-album');
    host.innerHTML=`<div class="cp-inner">${heading('Предпросмотр на классе','Выберите класс — макет соберётся по его фотографиям и анкетам так, как будет напечатан.')}<p class="cp-status">Загружаем классы…</p></div>`;
    let classes;
    try{classes=await request('/preview-classes');}catch(error){if(run===loading)host.querySelector('.cp-status').outerHTML=`<p class="cp-status error">${esc(error.message)}</p>`;return;}
    if(run!==loading)return;
    const ready=classes.filter(c=>c.ready),blocked=classes.filter(c=>!c.ready);
    const facts=c=>`<span>${plural(c.students,'ученик','ученика','учеников')}</span><span>портреты ${c.with_portrait}/${c.students}</span><span>общих фото ${c.general}</span><span>анкеты ${c.forms}/${c.students}</span>`;
    const title=c=>`${esc(c.school)} · ${esc(c.class_name)}<small>${esc(c.graduation_year||'')}</small>`;
    const empty=`<div class="cp-empty"><h3>Нет класса со всеми данными</h3><p>Для предпросмотра нужен класс, где у каждого ученика есть портрет и заполненная анкета, а у класса — общие фотографии. ${classes.length?'Дополните один из классов ниже или создайте новый.':'Классов пока нет — создайте класс и загрузите фотографии.'}</p><a class="primary" href="/#orders?new=1" target="_blank" rel="noopener">＋ Создать класс</a></div>`;
    host.querySelector('.cp-status').outerHTML=(ready.length?`<div class="cp-list" role="list">${ready.map(c=>`<button type="button" class="cp-class" role="listitem" data-cp-class="${esc(c.id)}"><strong>${title(c)}</strong><span class="cp-facts">${facts(c)}</span></button>`).join('')}</div>`:empty)+
      (blocked.length?`<details class="cp-blocked"${ready.length?'':' open'}><summary>Не хватает данных · ${blocked.length}</summary>${blocked.map(c=>`<div class="cp-class is-blocked"><strong>${title(c)}</strong><span class="cp-facts">${facts(c)}</span><span class="cp-miss">${c.missing.map(esc).join(' · ')}</span><a href="/#order/${encodeURIComponent(c.id)}" target="_blank" rel="noopener">Открыть заказ ↗</a></div>`).join('')}</details>`:'');
    host._classes=classes;
  }
  async function build(id){
    const run=++loading;classInfo=host._classes.find(c=>c.id===id);
    host.innerHTML=`<div class="cp-inner">${heading(`${esc(classInfo.school)} · ${esc(classInfo.class_name)}`,'Собираем альбом по данным класса…',true)}<p class="cp-status">Собираем альбом…</p></div>`;
    try{
      const templateId=await ctx.templateId();
      const data=await request(`/master-templates/${encodeURIComponent(templateId)}/class-preview`,'POST',{document:ctx.document(),order_id:id});
      if(run!==loading)return;
      result=data;owner=data.document.variants[0]?.owner||null;index=0;host.classList.add('is-album');draw();
    }catch(error){if(run===loading)host.querySelector('.cp-status').outerHTML=`<p class="cp-status error">${esc(error.message)}</p>`;}
  }
  function grouped(issues){const map=new Map();for(const i of issues){const k=i.level+'|'+i.message;map.set(k,[map.get(k)?.[0]||i,(map.get(k)?.[1]||0)+1]);}return [...map.values()].sort((a,b)=>(b[0].level==='error')-(a[0].level==='error'));}
  function sequence(){return result.document.variants.find(v=>v.owner===owner)?.sequence||[];}
  function label(spread){if(!spread)return '';if(spread.section==='cover')return 'Обложка';return ctx.sectionName(spread.section)||'Разворот';}
  function step(delta){const n=sequence().length;index=Math.max(0,Math.min(n-1,index+delta));draw();}
  function draw(){
    const doc=result.document,keys=sequence(),spread=layoutSpread(doc,owner,index),issues=doc.issues||[],errors=issues.filter(i=>i.level==='error');
    const summary=issues.length?`<details class="cp-issues${errors.length?' has-errors':''}"><summary>${errors.length?plural(errors.length,'ошибка','ошибки','ошибок'):'Нет ошибок'}${issues.length-errors.length?' · '+plural(issues.length-errors.length,'предупреждение','предупреждения','предупреждений'):''}</summary><ul>${grouped(issues).map(([i,n])=>`<li class="${i.level==='error'?'error':''}">${esc(i.message)}${n>1?` <b>×${n}</b>`:''}</li>`).join('')}</ul></details>`:'<span class="cp-ok">Без ошибок</span>';
    host.innerHTML=`<div class="cp-album">${heading(`${esc(classInfo.school)} · ${esc(classInfo.class_name)}`,`Предпросмотр черновика · ${plural(doc.spread_count,'разворот','разворота','разворотов')} · ничего не сохраняется в заказ`,true)}
      <div class="cp-toolbar"><label>Экземпляр<select id="class-preview-owner">${doc.variants.map(v=>`<option value="${esc(v.owner)}"${v.owner===owner?' selected':''}>${esc(v.name)}</option>`).join('')}</select></label>${summary}</div>
      <div class="cp-body"><div class="cp-thumbs" aria-label="Развороты">${keys.map((_,i)=>{const s=layoutSpread(doc,owner,i);return s?`<button type="button" class="cp-thumb${i===index?' active':''}" data-cp-spread="${i}" aria-label="${esc(label(s))}, ${i+1}">${layoutCanvas(s,doc,result.photos,false)}<small>${i+1} · ${esc(label(s))}</small></button>`:'';}).join('')}</div>
      <div class="cp-stage"><div class="cp-spread">${spread?layoutCanvas(spread,doc,result.photos,false,true):''}</div><div class="cp-nav"><button type="button" data-cp="prev" aria-label="Предыдущий разворот"${index?'':' disabled'}>‹</button><span>${esc(label(spread))} · ${index+1} / ${keys.length}</span><button type="button" data-cp="next" aria-label="Следующий разворот"${index<keys.length-1?'':' disabled'}>›</button></div></div></div></div>`;
    host.querySelector('.cp-thumb.active')?.scrollIntoView({block:'nearest'});fit();
  }
  function fit(){const box=host?.querySelector('.cp-spread'),canvas=box?.querySelector('.layout-canvas');if(!canvas)return;const [w,h]=canvas.style.aspectRatio.split('/').map(Number),scale=Math.min(box.clientWidth/w,box.clientHeight/h);canvas.style.width=w*scale+'px';canvas.style.height=h*scale+'px';}
  addEventListener('resize',()=>{if(host?.open&&result)fit();});
  function onClick(e){
    if(e.target===host){host.close();return;}
    const t=e.target.closest('[data-cp],[data-cp-class],[data-cp-spread]');if(!t)return;
    if(t.dataset.cpClass){build(t.dataset.cpClass);return;}
    if(t.dataset.cpSpread){index=+t.dataset.cpSpread;draw();return;}
    ({close:()=>host.close(),back:()=>{result=null;chooseClass();},prev:()=>step(-1),next:()=>step(1)})[t.dataset.cp]?.();
  }
  return {open};
})();
