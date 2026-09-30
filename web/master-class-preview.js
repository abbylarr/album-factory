/* Preview of the current draft on a real class: pick a class with complete data, then page through the finished album. */
window.ClassPreview=(()=>{
  let host,ctx,result=null,classInfo=null,owner=null,index=0,loading=0,focusIssue=null;
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const plural=(n,one,few,many)=>n+' '+(n%10===1&&n%100!==11?one:n%10>=2&&n%10<=4&&(n%100<10||n%100>=20)?few:many);
  async function request(path,method='GET',body){const r=await fetch('/api'+path,{method,headers:{'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'Не удалось построить предпросмотр');return d;}
  function dialog(){
    if(host)return host;
    host=document.createElement('dialog');host.id='class-preview';host.setAttribute('aria-labelledby','class-preview-title');
    host.addEventListener('click',onClick);host.addEventListener('change',e=>{if(e.target.id==='class-preview-owner'){owner=e.target.value;index=0;focusIssue=null;draw();}});
    document.addEventListener('keydown',e=>{if(!host.open||!result||e.target.closest?.('select,input,summary'))return;if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();step(e.key==='ArrowRight'?1:-1);}});
    host.addEventListener('close',()=>{if(!host.open)loading++;});
    document.body.append(host);return host;
  }
  function open(context){ctx=context;focusIssue=null;result=null;classInfo=null;dialog().classList.remove('is-album');host.showModal();chooseClass();}
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
    const empty=`<div class="cp-empty"><h3>Нет класса со всеми данными</h3><p>Для предпросмотра нужен класс, где у каждого ученика есть портрет и заполненная анкета, а у класса — общие фотографии. Готовность данных для предпросмотра не означает, что макет готов к печати. ${classes.length?'Дополните один из классов ниже или создайте новый.':'Классов пока нет — создайте класс и загрузите фотографии.'}</p><a class="primary" href="/#orders?new=1" target="_blank" rel="noopener">＋ Создать класс</a></div>`;
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
      result=data;owner=data.document.variants[0]?.owner||null;index=0;focusIssue=null;host.classList.add('is-album');draw();
    }catch(error){if(run===loading)host.querySelector('.cp-status').outerHTML=`<p class="cp-status error">${esc(error.message)}</p>`;}
  }
  function grouped(issues){
    const map=new Map();issues.forEach((issue,n)=>{const key=issue.level+'|'+issue.message;
      if(!map.has(key))map.set(key,{issue,indices:[]});map.get(key).indices.push(n);});
    return [...map.values()].sort((a,b)=>(b.issue.level==='error')-(a.issue.level==='error'));
  }
  function issueLocation(issue){
    for(const variant of result.document.variants) for(let n=0;n<variant.sequence.length;n++){
      const spread=layoutSpread(result.document,variant.owner,n);
      if(!spread)continue;
      const element=spread.elements.find(e=>e.key===issue.key || issue.key?.startsWith(e.key+'/'));
      if(element || issue.key?.split('/')[0]===spread.key)return {variant,index:n,spread,element};
    }
    return null;
  }
  function issueRows(issues){
    return grouped(issues).map(({issue,indices})=>`<li class="${issue.level==='error'?'error':''}"><details><summary>${esc(issue.message)}${indices.length>1?` <b>×${indices.length}</b>`:''}</summary>${indices.map(n=>{
      const loc=issueLocation(issues[n]);
      return loc?`<button type="button" data-cp-issue="${n}">${esc(loc.variant.name)} → ${esc(label(loc.spread))} → разворот ${loc.index+1}${loc.element?' → объект':''}</button>`:`<p>Данные класса: ${esc(issues[n].message)}</p>`;
    }).join('')}</details></li>`).join('');
  }
  function sequence(){return result.document.variants.find(v=>v.owner===owner)?.sequence||[];}
  function label(spread){if(!spread)return '';if(spread.section==='cover')return 'Обложка';return ctx.sectionName(spread.section)||'Разворот';}
  function step(delta){focusIssue=null;const n=sequence().length;index=Math.max(0,Math.min(n-1,index+delta));draw();}
  function draw(){
    const doc=result.document,keys=sequence(),spread=layoutSpread(doc,owner,index),issues=doc.issues||[],errors=issues.filter(i=>i.level==='error');
    const summary=issues.length?`<details class="cp-issues${errors.length?' has-errors':''}"><summary>${errors.length?plural(errors.length,'ошибка','ошибки','ошибок'):'Нет ошибок'}${issues.length-errors.length?' · '+plural(issues.length-errors.length,'предупреждение','предупреждения','предупреждений'):''}</summary><ul>${issueRows(issues)}</ul></details>`:'<span class="cp-ok">Предпросмотр без ошибок</span>';
    host.innerHTML=`<div class="cp-album${focusIssue !== null ? ' has-context' : ''}">${heading(`${esc(classInfo.school)} · ${esc(classInfo.class_name)}`,`Предпросмотр черновика · ${plural(doc.spread_count,'разворот','разворота','разворотов')} · ничего не сохраняется в заказ`,true)}
      <div class="cp-toolbar"><label>Экземпляр<select id="class-preview-owner">${doc.variants.map(v=>`<option value="${esc(v.owner)}"${v.owner===owner?' selected':''}>${esc(v.name)}</option>`).join('')}</select></label>${summary}</div>${focusIssue !== null ? `<div class="cp-issue-context">${esc(issues[focusIssue]?.message)} <button type="button" data-cp="edit-issue">Открыть в редакторе</button> <a href="/#order/${encodeURIComponent(classInfo.id)}/photos" target="_blank" rel="noopener">Данные класса ↗</a></div>` : ''}
      <div class="cp-body"><div class="cp-thumbs" aria-label="Развороты">${keys.map((_,i)=>{const s=layoutSpread(doc,owner,i);return s?`<button type="button" class="cp-thumb${i===index?' active':''}" data-cp-spread="${i}" aria-label="${esc(label(s))}, ${i+1}">${layoutCanvas(s,doc,result.photos,false)}<small>${i+1} · ${esc(label(s))}</small></button>`:'';}).join('')}</div>
      <div class="cp-stage"><div class="cp-spread">${spread?layoutCanvas(spread,doc,result.photos,false,true):''}</div><div class="cp-nav">${spread?.section==='cover' && ctx.inspectCover ? `<button type="button" data-cp="inspect-cover">Посмотреть эту обложку в редакторе</button><span>${plural(keys.filter(k=>!k.startsWith('cover[')).length,'разворот','разворота','разворотов')} · корешок ${spread.spine_mm} мм</span>` : ''}<button type="button" data-cp="prev" aria-label="Предыдущий разворот"${index?'':' disabled'}>‹</button><span>${esc(label(spread))} · ${index+1} / ${keys.length}</span><button type="button" data-cp="next" aria-label="Следующий разворот"${index<keys.length-1?'':' disabled'}>›</button></div></div></div></div>`;
    host.querySelector('.cp-thumb.active')?.scrollIntoView({block:'nearest'});
    if(focusIssue !== null){
      const loc=issueLocation(issues[focusIssue]);
      if(loc?.element && loc.variant.owner===owner && loc.index===index){
        const [x,y,w,h]=loc.element.box, [sw,sh]=spread.size_mm||doc.spread_size_mm;
        const outline=document.createElement('div');outline.className='cp-issue-focus';
        outline.style.cssText=`left:${x/sw*100}%;top:${y/sh*100}%;width:${w/sw*100}%;height:${h/sh*100}%`;
        host.querySelector('.cp-stage .layout-canvas')?.append(outline);
      }
    }
    fit();
  }
  function fit(){const box=host?.querySelector('.cp-spread'),canvas=box?.querySelector('.layout-canvas');if(!canvas)return;const [w,h]=canvas.style.aspectRatio.split('/').map(Number),scale=Math.min(box.clientWidth/w,box.clientHeight/h);canvas.style.width=w*scale+'px';canvas.style.height=h*scale+'px';}
  addEventListener('resize',()=>{if(host?.open&&result)fit();});
  function onClick(e){
    if(e.target===host){host.close();return;}
    const t=e.target.closest('[data-cp],[data-cp-class],[data-cp-spread],[data-cp-issue]');if(!t)return;
    if(t.hasAttribute('data-cp-issue')){focusIssue=+t.dataset.cpIssue;const loc=issueLocation(result.document.issues[focusIssue]);if(loc){owner=loc.variant.owner;index=loc.index;}draw();return;}
    if(t.dataset.cp==='edit-issue'){if(ctx.revealIssue?.(result.document.issues[focusIssue]?.key))host.close();return;}
    if(t.dataset.cp==='inspect-cover'){ctx.inspectCover?.(sequence().filter(k=>!k.startsWith('cover[')).length,`${classInfo.school} · ${classInfo.class_name} · ${result.document.variants.find(v=>v.owner===owner)?.name}`);host.close();return;}
    if(t.dataset.cpClass){build(t.dataset.cpClass);return;}
    if(t.dataset.cpSpread){focusIssue=null;index=+t.dataset.cpSpread;draw();return;}
    ({close:()=>host.close(),back:()=>{result=null;chooseClass();},prev:()=>step(-1),next:()=>step(1)})[t.dataset.cp]?.();
  }
  return {open};
})();
