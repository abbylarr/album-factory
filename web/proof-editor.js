'use strict';
/* Final layout proofing: the photographer walks every person's album, fixes photos, crops
   and captions within the published master design, marks each variant as checked and
   publishes the revision to the class. Geometry comes from the compiled document (mm). */
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const PT=.3528, TEXT_LIMIT=300, GOOD_DPI=200;
const LEGACY_SECTIONS={cover:'Обложка',intro:'Наш выпуск',personal:'Портрет',teachers:'Наши учителя',students:'Наш класс',moments:'Вместе',story:'В деталях',final:'Финал',custom:'Добавленный разворот'};
const FAMILIES={main:'Arial,Helvetica,sans-serif',display:'Georgia,serif',times:'"Times New Roman",Times,serif'};
const params=new URLSearchParams(location.search);
const P={order:params.get('order'),orderInfo:null,data:null,pub:null,mode:'work',owner:params.get('owner'),spread:0,selected:null,
  left:'people',right:'element',zoom:1,history:[],future:[],busy:false,query:'',filter:'all',photoTab:null,photoPerson:null,
  draft:null,crop:null,marks:true,scope:'all',info:null,missing:false,loadError:null};

async function api(path,method='GET',body){
  const response=await fetch('/api'+path,{method,headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});
  let value=null;try{value=await response.json();}catch{}
  if(!response.ok){const error=new Error(typeof value?.detail==='string'?value.detail:response.status===401?'Откройте главную страницу приложения':'Не удалось выполнить действие');error.status=response.status;throw error;}
  return value;
}
function toast(text){const el=$('#toast');el.textContent=text;el.classList.add('show');clearTimeout(toast.timer);toast.timer=setTimeout(()=>el.classList.remove('show'),2600);}
function saveState(text,kind=''){const el=$('#save-state');el.textContent=text;el.className='save-state'+(kind?' '+kind:'');}
function plural(n,one,few,many){const a=Math.abs(n)%100,b=a%10;return `${n} ${a>10&&a<20?many:b===1?one:b>1&&b<5?few:many}`;}
function date(value){if(!value)return '';const d=new Date(value);return isNaN(d)?value:d.toLocaleString('ru-RU',{day:'numeric',month:'long',hour:'2-digit',minute:'2-digit'});}

/* ---------------------------------------------------------------- document model */
const doc=()=>P.mode==='published'&&P.pub?P.pub.document:P.data?.document;
const editable=()=>P.mode==='work'&&!!P.data;
const ownerWildcard=key=>{const i=key.indexOf('/'),head=i<0?key:key.slice(0,i);return head.replace(/\[student:[^\]]*\]/g,'[*]')+(i<0?'':key.slice(i));};
function spreadFor(d,owner,key){if(!key)return null;return String(key).startsWith('cover[')?d.covers?.[owner]:d.shared_spreads?.[key]||d.variant_spreads?.[owner]?.[key];}
const variant=()=>doc()?.variants.find(v=>v.owner===P.owner);
const currentSpread=()=>spreadFor(doc(),P.owner,variant()?.sequence[P.spread]);
const photoMeta=id=>P.photoIndex?.get(id);
const selectedElement=()=>currentSpread()?.elements.find(e=>e.key===P.selected);
const interactive=e=>e.type==='photo'||e.type==='text';
const personOf=owner=>String(owner||'').replace(/^(student|teacher):/,'');
function isCommonSpread(spread){return !!spread&&(!!doc().shared_spreads?.[spread.key]);}
function spreadScope(spread){
  if(!spread)return '';
  if(spread.section==='cover'||String(spread.key).startsWith('cover['))return 'Обложка варианта';
  if(isCommonSpread(spread))return 'Общий для всех вариантов';
  const items=spread.elements.filter(interactive);if(!items.length)return (doc().variants.length>1)?'Общий фон':'';
  const shared=items.filter(e=>e.shared).length;
  return shared===items.length?'Одинаков во всех вариантах':shared?'Общий, с личными элементами':'Личный разворот';
}
function sectionName(spread){if(!spread)return '';if(spread.section==='cover')return 'Обложка';return P.data?.sections?.[spread.section]||LEGACY_SECTIONS[spread.section]||spread.section;}
function overriddenKinds(e){return (e.overridden||[]).map(o=>typeof o==='string'?{type:o,scope:'variant'}:o);}
function elementScope(e){
  if(isCommonSpread(currentSpread()))return {fixed:'all',count:doc().variants.length};
  if(e.shared)return {choice:true,count:e.shared};
  return {fixed:'variant'};
}

function analyse(d){
  const variants=d.variants||[],byKey=new Map(),bySlot=new Map(),byWild=new Map(),spreadsOf=new Map();
  const push=(map,key,value)=>{if(!map.has(key))map.set(key,[]);map.get(key).push(value);};
  for(const v of variants){
    const list=v.sequence.map(key=>spreadFor(d,v.owner,key));spreadsOf.set(v.owner,list);
    list.forEach((spread,index)=>{if(!spread)return;for(const e of spread.elements){const loc={owner:v.owner,index,key:e.key};push(byKey,e.key,loc);if(e.slot)push(bySlot,e.slot,loc);const w=ownerWildcard(e.key);if(w!==e.key)push(byWild,w,loc);}});
  }
  // The same defect compiled into every album (e.g. an empty common frame) is one problem, not N.
  const grouped=new Map();
  for(const issue of d.issues||[]){
    const key=String(issue.key||''),locs=byKey.get(key)||bySlot.get(key)||byWild.get(key)||byWild.get(key.split('|')[0])||[];
    const group=`${issue.level}|${issue.message}|${ownerWildcard(key)}`;
    if(grouped.has(group))grouped.get(group).locs.push(...locs);else grouped.set(group,{...issue,locs:[...locs]});
  }
  const issues=[...grouped.values()].map((issue,id)=>{
    const owners=new Set(issue.locs.map(l=>l.owner));
    return {...issue,id,owners,common:variants.length>1&&owners.size===variants.length};
  });
  const perOwner=new Map(variants.map(v=>[v.owner,{errors:0,warnings:0,ownErrors:0,ownWarnings:0,issues:[]}]));
  const marks=new Map();
  for(const issue of issues){
    for(const owner of issue.owners){const s=perOwner.get(owner);if(!s)continue;s.issues.push(issue);issue.level==='error'?s.errors++:s.warnings++;if(!issue.common)issue.level==='error'?s.ownErrors++:s.ownWarnings++;}
    for(const l of issue.locs)if(marks.get(l.key)!=='error')marks.set(l.key,issue.level);
  }
  return {variants,spreadsOf,issues,perOwner,marks,global:issues.filter(i=>!i.owners.size),
    errors:issues.filter(i=>i.level==='error').length,warnings:issues.filter(i=>i.level!=='error').length};
}
function reviewOf(owner){return P.mode==='work'?P.data?.status?.reviews?.[owner]:null;}
function reviewed(owner){return !!reviewOf(owner)?.current;}

/* ---------------------------------------------------------------- loading */
async function loadFonts(){
  for(const font of P.data?.fonts||[]){
    const family='custom-'+font.id;if([...document.fonts].some(f=>f.family===family))continue;
    try{const face=new FontFace(family,`url(${font.dataUrl})`);document.fonts.add(await face.load());}catch{}
  }
}
function adopt(data,{keepSelection=true}={}){
  P.data=data;P.photoIndex=new Map((data.photos||[]).map(p=>[p.id,p]));
  if(P.mode==='work')P.info=analyse(data.document);
  const variants=data.document.variants||[];
  if(!variants.some(v=>v.owner===P.owner)){P.owner=variants[0]?.owner||null;P.spread=0;}
  const length=variants.find(v=>v.owner===P.owner)?.sequence.length||1;
  P.spread=Math.max(0,Math.min(P.spread,length-1));
  if(!keepSelection||!selectedElement())P.selected=null;
  P.crop=null;
}
async function load(){
  if(!P.order){fail('Не указан заказ. Откройте макет из карточки заказа.');return;}
  $('#back').href=`/#order/${encodeURIComponent(P.order)}/layout`;$('#order-link').href=`/#order/${encodeURIComponent(P.order)}/layout`;
  try{
    P.orderInfo=await api('/orders/'+encodeURIComponent(P.order));
    $('#order-title').textContent=`${P.orderInfo.school} / ${P.orderInfo.class_name}`;document.title=`Макет ${P.orderInfo.class_name} · Album Factory`;
    try{adopt(await api(`/orders/${encodeURIComponent(P.order)}/layout`));P.missing=false;}
    catch(error){if(error.status===404){P.missing=true;}else throw error;}
    await loadFonts();
  }catch(error){fail(error.message);return;}
  render();
}
function fail(message){P.loadError=message;render();}

/* ---------------------------------------------------------------- rendering: canvas */
function fontFamily(key){
  const m=String(key||'main').match(/^(.*?)(-bold|-italic|-bolditalic)?$/),base=m[1],style=m[2]||'';
  const family=base.startsWith('custom-')?`"${base}",Arial,sans-serif`:FAMILIES[base]||FAMILIES.main;
  return `font-family:${family};font-weight:${style.includes('bold')?700:400};font-style:${style.includes('italic')?'italic':'normal'};`;
}
function photoImage(e,live,thumb){
  const meta=photoMeta(e.photo),crop=live||e.crop;if(!meta||!crop)return '';
  const src=meta.url||`/media/${encodeURIComponent(e.photo)}/${thumb?'thumb':'full'}`;
  return `<img src="${esc(src)}" alt="" draggable="false" style="width:${meta.width/crop[2]*100}%;height:${meta.height/crop[3]*100}%;left:${-crop[0]/crop[2]*100}%;top:${-crop[1]/crop[3]*100}%">`;
}
function spreadMarkup(spread,d,{live=false,thumb=false}={}){
  const [width,height]=(spread.section==='cover'||String(spread.key).startsWith('cover['))?d.cover_size_mm||d.spread_size_mm:d.spread_size_mm;
  const pct=(v,of)=>v/of*100, cq=v=>v/width*100;
  const layers=spread.elements.map(e=>{
    const hidden=!!e.hidden;if(hidden&&!live)return '';
    const [rawX,rawY,rawW,rawH]=e.box,stroke=e.type==='frame'?(e.strokeWidth||0):0;
    const pad=e.type==='frame'?(e.strokeAlign==='outside'?stroke:e.strokeAlign==='center'?stroke/2:0):0;
    const [x,y,w,h]=[rawX-pad,rawY-pad,rawW+2*pad,rawH+2*pad],center=e.rotation_center||[rawX+rawW/2,rawY+rawH/2];
    const shadow=e.shadow?`box-shadow:${cq(e.shadow.offsetX||0)}cqw ${cq(e.shadow.offsetY||0)}cqw ${cq(e.shadow.blur||0)}cqw ${esc(e.shadow.color||'#000000')}${Math.round((e.shadow.opacity??35)/100*255).toString(16).padStart(2,'0')};`:'';
    const border=(e.strokeWidth||0)&&e.type!=='text'?`border:${cq(e.strokeWidth)}cqw ${e.strokeDash==='dash'?'dashed':e.strokeDash==='dot'?'dotted':'solid'} ${esc(e.stroke||'#333333')};`:'';
    const box=`left:${pct(x,width)}%;top:${pct(y,height)}%;width:${pct(w,width)}%;height:${pct(h,height)}%;opacity:${(e.opacity??100)/100};${shadow}transform:rotate(${e.angle||0}deg);transform-origin:${(center[0]-x)/w*100}% ${(center[1]-y)/h*100}%;border-radius:${e.mask==='ellipse'||e.type==='ellipse'?'50%':cq(e.radius||0)+'cqw'};`;
    if(e.type==='svg')return `<div class="pl" style="${box}"><img alt="" src="data:image/svg+xml;charset=utf-8,${encodeURIComponent(e.svg||'')}" style="transform:scale(${e.flipX?-1:1},${e.flipY?-1:1})"></div>`;
    if(e.type==='rect'||e.type==='ellipse'||e.type==='line'||e.type==='frame')return `<div class="pl" style="${box}${border}background:${e.type==='frame'?'transparent':esc(e.fill||'transparent')}"></div>`;
    const mark=live&&P.marks&&P.mode==='work'?P.info?.marks.get(e.key):null;
    const cls=['pl',e.type==='photo'?'pl-photo':'pl-text',live&&P.selected===e.key?'selected':'',mark?'mark-'+mark:'',hidden?'is-hidden':'',live&&overriddenKinds(e).length?'is-edited':''].filter(Boolean).join(' ');
    const attrs=live?` data-key="${esc(e.key)}" role="button" tabindex="-1" aria-label="${e.type==='photo'?'Фото':'Текст'}${hidden?' (скрыт)':''}"`:'';
    if(e.type==='photo'){
      const cropLive=P.crop&&P.crop.key===e.key&&live?P.crop.crop:null;
      const image=photoImage(e,cropLive,thumb);
      return `<div class="${cls}${image?'':' empty'}"${attrs} style="${box}${border}">${image||(live?'<span class="pl-empty">Нет фото</span>':'')}</div>`;
    }
    if(e.type==='text'){
      const text=live&&P.draft?.key===e.key?P.draft.value:e.text;
      const size=(e.size||10)*PT,line=e.leading&&e.size?e.leading/e.size:1.2;
      const valign=e.valign==='middle'?`display:flex;flex-direction:column;justify-content:center;`:e.valign==='bottom'?'display:flex;flex-direction:column;justify-content:flex-end;':'';
      const deco=[e.underline?'underline':'',e.strike?'line-through':''].filter(Boolean).join(' ');
      return `<div class="${cls}${text?'':' empty'}"${attrs} style="${box}${valign}${fontFamily(e.font)}font-size:${cq(size)}cqw;line-height:${line};color:${esc(e.color||'#1d1d1d')};text-align:${esc(e.align||'left')};${e.letterSpacing?`letter-spacing:${e.letterSpacing/100}em;`:''}${deco?`text-decoration:${deco};`:''}"><span>${esc(text)}</span></div>`;
    }
    return '';
  }).join('');
  const gutter=spread.section!=='cover'&&!String(spread.key).startsWith('cover[')?'<i class="gutter" aria-hidden="true"></i>':'';
  return `<div class="proof-spread${live?' live':''}" style="aspect-ratio:${width}/${height}" data-width="${width}" data-height="${height}">${layers}${gutter}</div>`;
}
function renderCanvas(){
  const d=doc(),inner=$('#stage-inner'),spread=currentSpread();
  if(!d||!spread){inner.innerHTML='';return;}
  let ghost='';
  if(P.crop&&P.crop.ghost){
    const e=spread.elements.find(item=>item.key===P.crop.key),meta=e&&photoMeta(e.photo);
    const cover=spread.section==='cover'||String(spread.key).startsWith('cover[');
    if(e&&meta){const [bx,by,bw,bh]=e.box,[cx,cy,cw,ch]=P.crop.crop,[W,H]=cover?d.cover_size_mm||d.spread_size_mm:d.spread_size_mm,sx=bw/cw,sy=bh/ch;
      ghost=`<img class="crop-ghost" alt="" src="${esc(meta.url||`/media/${encodeURIComponent(e.photo)}/full`)}" style="left:${(bx-cx*sx)/W*100}%;top:${(by-cy*sy)/H*100}%;width:${meta.width*sx/W*100}%;height:${meta.height*sy/H*100}%">`;}
  }
  inner.innerHTML=spreadMarkup(spread,d,{live:true});
  if(ghost)inner.querySelector('.proof-spread').insertAdjacentHTML('afterbegin',ghost);
  fit();
}
function fit(){
  const stage=$('#stage'),canvas=$('#stage-inner .proof-spread');if(!canvas)return;
  const ratio=Number(canvas.dataset.width)/Number(canvas.dataset.height),pad=window.innerWidth<540?16:56;
  const availableW=Math.max(120,stage.clientWidth-pad*2),availableH=Math.max(120,stage.clientHeight-pad*2-40);
  const base=Math.min(availableW,availableH*ratio),width=base*P.zoom;
  canvas.style.width=`${width}px`;canvas.style.height=`${width/ratio}px`;
  $('#stage-inner').classList.toggle('zoomed',P.zoom>1);
  $('#zoom-value').textContent=`${Math.round(P.zoom*100)}%`;
}

/* ---------------------------------------------------------------- rendering: panels */
function renderHeader(){
  const d=P.data?.document,status=P.data?.status,info=P.info,state=$('#doc-state');
  const publication=status?.publication,approval=status?.approval;
  let label='',kind='';
  if(P.mode==='published'){label=`Опубликована ${date(P.pub?.published_at)}`;kind='published';}
  else if(!publication){label='Черновик · не опубликован';kind='draft';}
  else if(publication.current){label=approval&&approval.revision===publication.revision?'Опубликован · согласован':'Опубликован';kind='ok';}
  else{label=`Есть неопубликованные правки · ${plural(publication.changed.length,'вариант','варианта','вариантов')}`;kind='changed';}
  state.hidden=!d;state.textContent=label;state.className='doc-state '+kind;
  $('#mode-switch').hidden=!publication;
  for(const b of document.querySelectorAll('[data-mode]'))b.setAttribute('aria-pressed',String(b.dataset.mode===P.mode));
  $('#undo').disabled=!P.history.length||P.busy||!editable();$('#redo').disabled=!P.future.length||P.busy||!editable();
  const pdf=$('#pdf'),blocked=!d||info?.errors||P.mode!=='work';
  pdf.classList.toggle('disabled',!!blocked);pdf.href=blocked?'#':`/api/orders/${encodeURIComponent(P.order)}/layout/pdf/${encodeURIComponent(P.owner||'')}`;
  pdf.title=info?.errors?'Исправьте ошибки, чтобы скачать PDF':'Контрольный PDF выбранного варианта';
  $('#publish').disabled=!d||P.mode!=='work'||P.busy;
  $('#refresh').disabled=P.busy;
  $('#toggle-marks').textContent=P.marks?'Скрыть подсветку замечаний':'Показать подсветку замечаний';
  const count=$('#check-count');count.textContent=info?(info.errors||info.warnings||'')+'':'';count.className='tab-count'+(info?.errors?' error':info?.warnings?' warning':'');
}
function initials(name){return String(name||'?').split(/\s+/).filter(Boolean).slice(0,2).map(p=>p[0]).join('').toUpperCase()||'?';}
function ownerPortrait(owner){
  const spreads=P.info?.spreadsOf.get(owner)||[],id=personOf(owner);
  for(const spread of spreads)for(const e of spread?.elements||[])if(e.type==='photo'&&e.photo&&photoMeta(e.photo)?.person_id===id)return e.photo;
  return null;
}
function renderPeople(){
  const el=$('#people-panel'),d=doc();if(!d){el.innerHTML='';return;}
  const variants=d.variants,status=P.data.status,info=P.mode==='work'?P.info:analyse(d),changed=new Set(status?.publication?.changed||[]);
  const done=variants.filter(v=>reviewed(v.owner)).length,query=P.query.trim().toLowerCase();
  const list=variants.filter(v=>(!query||String(v.name||'').toLowerCase().includes(query))&&(P.filter==='all'||(P.filter==='issues'&&info.perOwner.get(v.owner)?.ownErrors+info.perOwner.get(v.owner)?.ownWarnings)||(P.filter==='todo'&&!reviewed(v.owner))||(P.filter==='changed'&&changed.has(v.owner))));
  const filters=[['all','Все',variants.length],['todo','Не проверены',variants.length-done],['issues','С личными замечаниями',variants.filter(v=>{const s=info.perOwner.get(v.owner);return s&&(s.ownErrors+s.ownWarnings);}).length]];
  if(status?.publication&&!status.publication.current)filters.push(['changed','Изменены',changed.size]);
  el.innerHTML=`${P.mode==='work'?`<div class="review-progress" aria-label="Проверено вариантов"><div><strong>Проверено ${done} из ${variants.length}</strong><span>${done===variants.length?'Все варианты просмотрены':'Отмечайте каждого после просмотра'}</span></div><progress max="${variants.length}" value="${done}"></progress></div>`:'<p class="muted small-note">Опубликованная редакция — только просмотр.</p>'}
    ${variants.length>6?`<input id="people-search" type="search" placeholder="Найти по имени" aria-label="Поиск по имени" value="${esc(P.query)}">`:''}
    ${P.mode==='work'?`<div class="people-filters" role="group" aria-label="Фильтр">${filters.map(([key,label,n])=>`<button type="button" data-filter="${key}" aria-pressed="${P.filter===key}">${label} <small>${n}</small></button>`).join('')}</div>`:''}
    <div class="people-list">${list.map(v=>{const s=info.perOwner.get(v.owner)||{ownErrors:0,ownWarnings:0},review=reviewOf(v.owner),portrait=ownerPortrait(v.owner);
      const badges=[s.ownErrors?`<b class="badge error" title="Личные ошибки варианта">${s.ownErrors}</b>`:'',s.ownWarnings?`<b class="badge warning" title="Личные предупреждения варианта">${s.ownWarnings}</b>`:'',P.mode==='work'&&changed.has(v.owner)&&status.publication?'<b class="badge changed" title="Изменён после публикации">●</b>':''].join('');
      const state=P.mode!=='work'?'':review?.current?'<span class="check done" title="Проверен">✓</span>':review?'<span class="check stale" title="Изменён после проверки">!</span>':'<span class="check" aria-hidden="true"></span>';
      return `<button type="button" class="person-row${v.owner===P.owner?' active':''}" data-owner="${esc(v.owner)}" aria-current="${v.owner===P.owner}">${portrait&&photoMeta(portrait)?`<img class="avatar" src="${esc(photoMeta(portrait).url||`/media/${encodeURIComponent(portrait)}/thumb`)}" alt="" loading="lazy">`:`<span class="avatar">${esc(initials(v.name))}</span>`}<span class="person-name"><span>${esc(v.name||'Общий вариант')}</span><small>${v.kind==='teacher'?'Учитель':review&&!review.current?'Изменён после проверки':review?'Проверен':'Ученик'}</small></span>${badges}${state}</button>`;}).join('')||'<p class="muted small-note">Никого не найдено.</p>'}</div>`;
  const search=$('#people-search');if(search)search.oninput=e=>{P.query=e.target.value;renderPeople();const again=$('#people-search');again.focus();again.setSelectionRange(again.value.length,again.value.length);};
}
function renderSpreads(){
  const el=$('#spreads-panel'),d=doc(),v=variant();if(!d||!v){el.innerHTML='';return;}
  const info=P.mode==='work'?P.info:null;let lastSection=null;
  el.innerHTML=`<div class="panel-heading"><span>${esc(v.name||'Вариант')} · ${plural(v.sequence.length,'разворот','разворота','разворотов')}</span></div>`+v.sequence.map((key,index)=>{
    const spread=spreadFor(d,v.owner,key);if(!spread)return '';
    const name=sectionName(spread),head=name!==lastSection?`<div class="section-label">${esc(name)}</div>`:'';lastSection=name;
    const level=info?spread.elements.reduce((worst,e)=>{const m=info.marks.get(e.key);return m==='error'||worst==='error'?'error':m||worst;},null):null;
    const edited=spread.elements.some(e=>overriddenKinds(e).length);
    return `${head}<button type="button" class="spread-thumb${index===P.spread?' active':''}" data-spread="${index}" aria-current="${index===P.spread}" aria-label="Разворот ${index+1}: ${esc(name)}">${spreadMarkup(spread,d,{thumb:true})}<span class="spread-caption"><span>${index+1} · ${esc(spreadScope(spread)||name)}</span>${edited?'<i class="dot edited" title="Есть ручные правки"></i>':''}${level?`<i class="dot ${level}" title="${level==='error'?'Есть ошибки':'Есть предупреждения'}"></i>`:''}</span></button>`;
  }).join('');
  el.querySelector('.spread-thumb.active')?.scrollIntoView({block:'nearest'});
}
function renderTopline(){
  const v=variant(),spread=currentSpread(),select=$('#spread-select');
  $('#spread-title').textContent=spread?sectionName(spread):'';
  $('#spread-label').textContent=spread?`${v.name||'Общий вариант'} · ${spreadScope(spread)}`:'';
  select.innerHTML=(v?.sequence||[]).map((key,index)=>`<option value="${index}" ${index===P.spread?'selected':''}>${index+1} / ${v.sequence.length}</option>`).join('');
  $('#prev-spread').disabled=!v||P.spread<=0;$('#next-spread').disabled=!v||P.spread>=v.sequence.length-1;
}
function renderReviewBar(){
  const el=$('#review-bar'),v=variant();
  if(!v||P.mode!=='work'){el.innerHTML='';return;}
  const review=reviewOf(v.owner),s=P.info.perOwner.get(v.owner)||{errors:0},last=P.spread>=v.sequence.length-1;
  el.innerHTML=`<span class="review-hint">${review?.current?`Проверен ${date(review.reviewed_at)}`:review?'Изменён после проверки':last?'Последний разворот':`Разворот ${P.spread+1} из ${v.sequence.length}`}</span>${s.errors?`<span class="review-errors">${plural(s.errors,'ошибка','ошибки','ошибок')}</span>`:''}<button type="button" id="mark-reviewed" class="${review?.current?'':'primary'}" aria-pressed="${!!review?.current}" title="⌘/Ctrl+Enter">${review?.current?'✓ Проверен':'Отметить проверенным'}</button><button type="button" id="next-person" title="Следующий непроверенный">Дальше →</button>`;
}

/* ---------------------------------------------------------------- rendering: inspector */
function issuePlace(issue){
  const loc=issue.locs.find(l=>l.owner===P.owner)||issue.locs[0];if(!loc)return '';
  const spread=P.info.spreadsOf.get(loc.owner)?.[loc.index],who=loc.owner!==P.owner?` · ${doc().variants.find(v=>v.owner===loc.owner)?.name||''}`:'';
  return `Разворот ${loc.index+1} · ${sectionName(spread)}${who}`;
}
function issueRow(issue,showScope=true){
  const where=issue.common?'все варианты':issue.owners.size>1?plural(issue.owners.size,'вариант','варианта','вариантов'):'';
  return `<button type="button" class="issue ${issue.level==='error'?'error':'warning'}" data-issue="${issue.id}"><strong>${issue.level==='error'?'Ошибка':'Предупреждение'}</strong><span>${esc(issue.message)}</span><small>${esc(issuePlace(issue))}${showScope&&where?` · ${where}`:''}</small></button>`;
}
function renderCheck(){
  const el=$('#inspector'),info=P.info;
  if(P.mode!=='work'){el.innerHTML='<div class="inspector-section"><p>Проверка доступна в рабочей редакции.</p></div>';return;}
  const v=variant(),mine=(info.perOwner.get(v?.owner)?.issues||[]),personal=mine.filter(i=>!i.common),common=info.issues.filter(i=>i.common);
  const seen=new Set(),conflicts=(P.data.document.overrides?.conflicts||[]).map((c,n)=>({...c,n})).filter(c=>{const id=`${c.key}|${c.type||''}`;if(seen.has(id))return false;seen.add(id);return true;});
  const section=(title,items,empty)=>`<div class="inspector-section"><h3>${title}</h3>${items.length?items.join(''):`<p class="muted">${empty}</p>`}</div>`;
  el.innerHTML=`<div class="inspector-section check-summary"><div class="big-count ${info.errors?'error':'ok'}">${info.errors?plural(info.errors,'ошибка','ошибки','ошибок'):'Ошибок нет'}</div><p>${info.errors?'Ошибки блокируют публикацию и PDF. Нажмите на замечание, чтобы перейти к месту.':info.warnings?`${plural(info.warnings,'предупреждение','предупреждения','предупреждений')} — просмотрите перед публикацией.`:'Макет можно публиковать.'}</p></div>`
    +section(`${esc(v?.name||'Этот вариант')}`,personal.map(i=>issueRow(i,false)),'Личных замечаний нет.')
    +(common.length?section('Во всех вариантах',common.map(i=>issueRow(i,false)),''):'')
    +(info.global.length?section('Альбом целиком',info.global.map(i=>`<div class="issue static ${i.level==='error'?'error':'warning'}"><strong>${i.level==='error'?'Ошибка':'Предупреждение'}</strong><span>${esc(i.message)}</span></div>`),''):'')
    +(conflicts.length?section('Правки не применились',conflicts.map(c=>`<div class="issue static warning"><strong>${esc(c.reason||'Конфликт')}</strong><span>${esc(kindLabel(c.type))}${String(c.key).includes('[*]')?' · всем':''}</span><button type="button" class="link-button" data-drop-conflict="${c.n}">Удалить правку</button></div>`),''):'');
}
function kindLabel(type){return {photo:'Замена фото',crop:'Кадр',text:'Текст',hide:'Скрытие'}[type]||'Правка';}
function dpiOf(e){return e.photo&&e.crop?Math.floor(e.crop[2]/(e.box[2]/25.4)):null;}
function scopeControl(e){
  const scope=elementScope(e),v=variant();
  if(scope.fixed==='all')return `<p class="scope-note">Общий разворот: правка изменит все ${plural(scope.count,'вариант','варианта','вариантов')}.</p>`;
  if(scope.fixed==='variant')return `<p class="scope-note">Правка только для варианта «${esc(v.name)}».</p>`;
  return `<div class="field-label">Кому применить</div><div class="segments scope-switch" role="group" aria-label="Область правки"><button type="button" data-scope="all" aria-pressed="${P.scope==='all'}">Всем · ${scope.count}</button><button type="button" data-scope="variant" aria-pressed="${P.scope==='variant'}">Только ${esc(String(v.name||'').split(' ')[0]||'этому')}</button></div>`;
}
function editedNote(e){
  const kinds=overriddenKinds(e);if(!kinds.length)return '';
  return `<div class="edited-note"><span>Изменено вручную: ${kinds.map(k=>kindLabel(k.type).toLowerCase()+(k.scope==='all'?' (всем)':'')).join(', ')}</span><button type="button" class="link-button" id="reset-element">Вернуть как было</button></div>`;
}
function photoPeople(){
  const people=new Map();for(const p of P.data.photos)if(p.shoot_type==='portrait'&&p.person_id&&!people.has(p.person_id))people.set(p.person_id,null);
  for(const v of P.data.document.variants){const id=personOf(v.owner);if(people.has(id))people.set(id,v.name);}
  for(const person of P.orderInfo?.persons||[])if(people.has(person.id)&&!people.get(person.id))people.set(person.id,person.name);
  return [...people.entries()].map(([id,name])=>({id,name:name||'Без имени'})).sort((a,b)=>a.name.localeCompare(b.name,'ru'));
}
function elementPerson(e){
  const all=[...String(e.key).matchAll(/\[(?:student|teacher):([^\]]+)\]/g)],current=photoMeta(e.photo)?.person_id;
  if(current)return current;
  return all.length?all.at(-1)[1]:personOf(P.owner);
}
function photoChoices(e){
  const ranked=P.data.document.photo_report?.slots?.[e.slot]?.ranked||[],general=P.data.photos.filter(p=>p.shoot_type==='general');
  const tabs=[];
  if(ranked.length)tabs.push(['fit','Подходят']);
  tabs.push(['portrait','Портреты'],['general','Общие']);
  if(!P.photoTab||!tabs.some(([k])=>k===P.photoTab))P.photoTab=photoMeta(e.photo)?.shoot_type==='portrait'||!e.slot?'portrait':ranked.length?'fit':'general';
  let list=[];
  if(P.photoTab==='fit')list=ranked.map(id=>photoMeta(id)).filter(Boolean);
  if(P.photoTab==='general')list=[...general].sort((a,b)=>(b.quality??0)-(a.quality??0));
  if(P.photoTab==='portrait'){const person=P.photoPerson||elementPerson(e);list=P.data.photos.filter(p=>p.shoot_type==='portrait'&&p.person_id===person);}
  return {tabs,list,suits:new Set(ranked)};
}
function renderPhotoInspector(e){
  const meta=photoMeta(e.photo),dpi=dpiOf(e),{tabs,list,suits}=photoChoices(e),people=P.photoTab==='portrait'?photoPeople():[];
  const person=P.photoPerson||elementPerson(e),zoom=cropZoom(e);
  return `<div class="inspector-section"><div class="inspector-head"><h3>Фото</h3>${e.hidden?'<span class="pill">Скрыто</span>':''}</div>
    ${meta?`<div class="current-photo"><div class="current-thumb">${photoImage(e,P.crop?.key===e.key?P.crop.crop:null,true)}</div><div><strong>${esc(meta.filename||'Снимок')}</strong><span class="${dpi!=null&&dpi<GOOD_DPI?'warn':''}">${dpi!=null?`≈ ${dpi} dpi${dpi<GOOD_DPI?' · мало для печати':''}`:''}</span></div></div>`:'<p class="muted">В рамке нет фото. Выберите снимок ниже.</p>'}
    ${scopeControl(e)}${editedNote(e)}</div>
    ${meta?`<div class="inspector-section"><h3>Кадр</h3><p class="muted hint">Перетащите фото в рамке, колёсико мыши — масштаб.</p><label class="range-row"><span>Масштаб</span><input id="crop-zoom" type="range" min="1" max="4" step="0.01" value="${zoom.toFixed(2)}" aria-label="Масштаб кадра"><output>${Math.round(zoom*100)}%</output></label><div class="button-row"><button type="button" id="crop-center">По центру</button>${overriddenKinds(e).some(k=>k.type==='crop')?'<button type="button" id="crop-reset">Исходный кадр</button>':''}</div></div>`:''}
    <div class="inspector-section photo-picker"><h3>Заменить</h3><div class="segments photo-tabs" role="tablist">${tabs.map(([key,label])=>`<button type="button" role="tab" data-photo-tab="${key}" aria-selected="${P.photoTab===key}" aria-pressed="${P.photoTab===key}">${label}</button>`).join('')}</div>
    ${P.photoTab==='portrait'&&people.length?`<select id="photo-person" aria-label="Чьи портреты">${people.map(p=>`<option value="${esc(p.id)}" ${p.id===person?'selected':''}>${esc(p.name)}</option>`).join('')}</select>`:''}
    ${list.length?`<div class="photo-grid">${list.map(p=>`<button type="button" data-photo="${esc(p.id)}" class="${p.id===e.photo?'selected':''}" title="${esc(p.filename)}" aria-label="Поставить ${esc(p.filename)}"><img src="${esc(p.url||`/media/${encodeURIComponent(p.id)}/thumb`)}" alt="" loading="lazy">${suits.has(p.id)&&P.photoTab!=='fit'?'<em>Подходит</em>':''}</button>`).join('')}</div>`:`<p class="muted">${P.photoTab==='portrait'?'У этой персоны нет готовых портретов.':'Снимков нет. Загрузите общую съёмку в заказе.'}</p>`}</div>
    <div class="inspector-section"><button type="button" id="toggle-hidden" class="wide">${e.hidden?'Показать фото':'Скрыть фото в этом месте'}</button></div>`;
}
function renderTextInspector(e){
  const value=P.draft?.key===e.key?P.draft.value:e.text,dirty=P.draft?.key===e.key&&P.draft.value!==e.text;
  const bound=/\/(name|detail)$/.test(e.key);
  return `<div class="inspector-section"><div class="inspector-head"><h3>Текст</h3>${e.hidden?'<span class="pill">Скрыт</span>':''}</div>
    <label class="text-field"><span class="sr-only">Текст</span><textarea id="text-value" maxlength="${TEXT_LIMIT}" rows="6">${esc(value)}</textarea></label>
    <div class="text-meta"><span>${value.length} / ${TEXT_LIMIT}</span>${bound?'<span>Имя и цитата берутся из анкеты — правка меняет только макет</span>':''}</div>
    ${scopeControl(e)}
    <div class="button-row"><button type="button" id="text-save" class="primary" ${dirty?'':'disabled'} title="⌘/Ctrl+Enter">Сохранить</button><button type="button" id="text-cancel" ${dirty?'':'disabled'}>Отменить</button></div>
    ${editedNote(e)}</div>
    <div class="inspector-section"><button type="button" id="toggle-hidden" class="wide">${e.hidden?'Показать текст':'Скрыть текст'}</button></div>`;
}
function renderVariantSummary(){
  const v=variant(),d=doc();if(!v)return '<div class="inspector-section"><p>Выберите вариант.</p></div>';
  const s=P.mode==='work'?P.info.perOwner.get(v.owner):null,review=reviewOf(v.owner);
  const edits=[];if(P.mode==='work')for(const [index,spread] of (P.info.spreadsOf.get(v.owner)||[]).entries())for(const e of spread?.elements||[])for(const k of overriddenKinds(e))edits.push({index,e,k});
  return `<div class="inspector-section variant-card"><div class="variant-title"><span class="avatar">${esc(initials(v.name))}</span><div><strong>${esc(v.name||'Общий вариант')}</strong><span>${plural(v.sequence.length,'разворот','разворота','разворотов')}</span></div></div>
    ${P.mode==='work'?`<p>${review?.current?`Проверен ${date(review.reviewed_at)}.`:review?'После проверки вариант изменился — просмотрите ещё раз.':'Пролистайте развороты и отметьте вариант проверенным.'}</p>`:`<p>Опубликованная редакция ${esc(P.pub?.revision?.slice(0,8)||'')} от ${date(P.pub?.published_at)}. Переключитесь на рабочую, чтобы вносить правки.</p>`}
    ${s?`<div class="stat-row"><span class="${s.errors?'error':''}">${plural(s.errors,'ошибка','ошибки','ошибок')}</span><span>${plural(s.warnings,'предупреждение','предупреждения','предупреждений')}</span></div>`:''}</div>
    ${P.mode==='work'?`<div class="inspector-section"><h3>Что можно сделать</h3><ul class="howto"><li>Нажмите на фото — замените снимок или поправьте кадр.</li><li>Нажмите на подпись — исправьте текст или скройте его.</li><li>Правка общего разворота применяется всем или только этому человеку.</li></ul></div>`:''}
    ${edits.length?`<div class="inspector-section"><h3>Ручные правки · ${edits.length}</h3>${edits.slice(0,40).map(({index,e,k})=>`<button type="button" class="edit-row" data-goto="${index}" data-key="${esc(e.key)}"><span>${kindLabel(k.type)}${k.scope==='all'?' · всем':''}</span><small>разворот ${index+1}</small></button>`).join('')}</div>`:''}
    ${d&&P.mode==='work'&&P.data.generated_at?`<div class="inspector-section"><p class="muted">Собран из данных заказа ${date(P.data.generated_at)}.</p></div>`:''}`;
}
function renderInspector(){
  for(const b of document.querySelectorAll('[data-right]'))b.classList.toggle('active',b.dataset.right===P.right),b.setAttribute('aria-selected',String(b.dataset.right===P.right));
  const el=$('#inspector');
  if(!doc()){el.innerHTML='';return;}
  if(P.right==='check'){renderCheck();return;}
  const e=selectedElement();
  if(!e||P.mode!=='work'){el.innerHTML=renderVariantSummary();return;}
  el.innerHTML=e.type==='photo'?renderPhotoInspector(e):renderTextInspector(e);
  const area=$('#text-value');
  if(area){area.oninput=()=>{P.draft={key:e.key,value:area.value};renderCanvas();const meta=el.querySelector('.text-meta span');if(meta)meta.textContent=`${area.value.length} / ${TEXT_LIMIT}`;const dirty=area.value!==e.text;$('#text-save').disabled=!dirty;$('#text-cancel').disabled=!dirty;};}
  const zoom=$('#crop-zoom');if(zoom){zoom.oninput=()=>{setCropZoom(e,Number(zoom.value));zoom.nextElementSibling.textContent=`${Math.round(Number(zoom.value)*100)}%`;};zoom.onchange=()=>commitCrop(e);}
}
function renderEmpty(){
  const el=$('#empty');
  if(P.loadError){el.hidden=false;el.innerHTML=`<h2>Не удалось открыть макет</h2><p>${esc(P.loadError)}</p><a class="primary" href="/">На главную</a>`;return true;}
  if(P.missing){el.hidden=false;el.innerHTML=`<h2>Макет ещё не собран</h2><p>Генератор соберёт альбом каждого ученика из опубликованного мастер-макета, портретов и анкет.</p><button type="button" class="primary" id="generate">Собрать макет</button><p class="form-error" id="generate-error" role="alert"></p>`;return true;}
  el.hidden=true;return false;
}
function render(){
  document.body.classList.toggle('is-published',P.mode==='published');
  const empty=renderEmpty();
  $('#workspace').classList.toggle('is-empty',empty);
  renderHeader();
  if(empty){for(const id of ['#people-panel','#spreads-panel','#inspector','#stage-inner','#review-bar'])$(id).innerHTML='';return;}
  for(const b of document.querySelectorAll('[data-left]'))b.classList.toggle('active',b.dataset.left===P.left),b.setAttribute('aria-selected',String(b.dataset.left===P.left));
  $('#people-panel').hidden=P.left!=='people';$('#spreads-panel').hidden=P.left!=='spreads';
  renderPeople();renderSpreads();renderTopline();renderCanvas();renderReviewBar();renderInspector();
  const url=new URL(location.href);url.searchParams.set('order',P.order);if(P.owner)url.searchParams.set('owner',P.owner);history.replaceState(null,'',url);
}

/* ---------------------------------------------------------------- crop maths */
function coverSize(e){const meta=photoMeta(e.photo),ratio=e.box[2]/e.box[3];return meta.width/meta.height>ratio?[meta.height*ratio,meta.height]:[meta.width,meta.width/ratio];}
function liveCrop(e){return P.crop?.key===e.key?P.crop.crop:e.crop;}
function cropZoom(e){const meta=photoMeta(e.photo),crop=liveCrop(e);if(!meta||!crop)return 1;return Math.max(1,Math.min(4,coverSize(e)[0]/crop[2]));}
function clampCrop(e,[x,y,w,h]){const meta=photoMeta(e.photo);return [Math.min(Math.max(x,0),meta.width-w),Math.min(Math.max(y,0),meta.height-h),w,h];}
function setCropZoom(e,zoom){
  const crop=liveCrop(e),[cw0,ch0]=coverSize(e),w=cw0/zoom,h=ch0/zoom,cx=crop[0]+crop[2]/2,cy=crop[1]+crop[3]/2;
  P.crop={key:e.key,crop:clampCrop(e,[cx-w/2,cy-h/2,w,h])};renderCanvas();syncCropThumb(e);
}
function syncCropThumb(e){const thumb=document.querySelector('.current-thumb');if(thumb)thumb.innerHTML=photoImage(e,P.crop?.key===e.key?P.crop.crop:null,true);}
let cropTimer=null;
function commitCrop(e,delay=0){
  clearTimeout(cropTimer);
  cropTimer=setTimeout(()=>{
    if(!P.crop||P.crop.key!==e.key)return;
    const meta=photoMeta(e.photo),[x,y,w,h]=P.crop.crop;
    const rect=[x/meta.width,y/meta.height,Math.min(1,w/meta.width),Math.min(1,h/meta.height)].map(v=>Math.round(v*1e6)/1e6);
    if(e.crop&&e.crop.every((v,i)=>Math.abs(v-P.crop.crop[i])<.5)){P.crop=null;return;}
    operate([{key:e.key,type:'crop',value:{rect},scope:scopeFor(e)}],'Кадр');
  },delay);
}

/* ---------------------------------------------------------------- mutations */
function scopeFor(e){const scope=elementScope(e);return scope.choice?P.scope:'variant';}
async function mutate(label,request,{undoable=true}={}){
  if(P.busy)return false;P.busy=true;saveState('Сохраняем…','saving');renderHeader();
  const before=P.data.overrides||[];
  try{
    const data=await request();adopt(data);
    if(undoable){P.history.push({label,before,after:data.overrides||[]});if(P.history.length>100)P.history.shift();P.future=[];}
    P.draft=null;saveState('Сохранено','saved');return true;
  }catch(error){
    P.crop=null;
    if(error.status===409){saveState('Макет изменился','error');toast(error.message);}
    else{saveState('Не сохранено','error');toast(error.message);}
    return false;
  }finally{P.busy=false;render();}
}
function operate(ops,label){
  const custom=ops.some(op=>Object.hasOwn(P.data.document.custom_positions||{},op.key.split('/')[0]));
  return mutate(label,()=>api(`/orders/${encodeURIComponent(P.order)}/layout/edits`,'POST',{revision:P.data.document.revision,ops}),{undoable:!custom});
}
async function replaceOverrides(list){
  return api(`/orders/${encodeURIComponent(P.order)}/layout/overrides`,'PUT',{revision:P.data.document.revision,overrides:list});
}
async function undo(){
  const step=P.history.at(-1);if(!step||P.busy)return;
  P.busy=true;saveState('Отменяем…','saving');renderHeader();
  try{adopt(await replaceOverrides(step.before));P.history.pop();P.future.push(step);saveState(`Отменено: ${step.label.toLowerCase()}`,'saved');}
  catch(error){saveState('Не отменено','error');toast(error.message);}
  finally{P.busy=false;render();}
}
async function redo(){
  const step=P.future.at(-1);if(!step||P.busy)return;
  P.busy=true;saveState('Возвращаем…','saving');renderHeader();
  try{adopt(await replaceOverrides(step.after));P.future.pop();P.history.push(step);saveState(`Возвращено: ${step.label.toLowerCase()}`,'saved');}
  catch(error){saveState('Не возвращено','error');toast(error.message);}
  finally{P.busy=false;render();}
}
async function commitText(){
  const e=selectedElement();if(!e||e.type!=='text'||P.draft?.key!==e.key)return;
  if(P.draft.value===e.text){P.draft=null;return;}
  await operate([{key:e.key,type:'text',value:P.draft.value,scope:scopeFor(e)}],'Текст');
}
async function setReviewed(owner,value){
  try{const result=await api(`/orders/${encodeURIComponent(P.order)}/layout/reviews`,'PUT',{owner,reviewed:value});P.data.status=result.status;render();return true;}
  catch(error){toast(error.message);return false;}
}
function nextUnreviewed(){
  const variants=doc().variants,start=variants.findIndex(v=>v.owner===P.owner);
  for(let step=1;step<=variants.length;step++){const v=variants[(start+step)%variants.length];if(!reviewed(v.owner))return v.owner;}
  return null;
}

/* ---------------------------------------------------------------- navigation */
async function leaveElement(){if(P.draft)await commitText();}
async function select(key){await leaveElement();P.selected=key;P.photoPerson=null;P.photoTab=null;P.crop=null;P.right='element';defaultScope();openProperties();render();}
function defaultScope(){const kinds=overriddenKinds(selectedElement()||{});P.scope=kinds.some(k=>k.scope==='variant')?'variant':'all';}
async function goSpread(index,key=null){
  const v=variant();if(!v)return;await leaveElement();
  P.spread=Math.max(0,Math.min(index,v.sequence.length-1));P.selected=key;P.crop=null;P.photoTab=null;defaultScope();render();
}
async function goOwner(owner,{keepSpread=true}={}){
  if(!owner||owner===P.owner)return;await leaveElement();
  const before=currentSpread(),section=before?.section,offset=variant()?.sequence.slice(0,P.spread+1).filter(key=>spreadFor(doc(),P.owner,key)?.section===section).length;
  P.owner=owner;P.selected=null;P.crop=null;
  if(keepSpread){const seq=variant().sequence;let seen=0,found=-1;for(let i=0;i<seq.length;i++){if(spreadFor(doc(),owner,seq[i])?.section===section){seen++;if(seen===offset){found=i;break;}}}P.spread=found>=0?found:Math.min(P.spread,seq.length-1);}
  else P.spread=0;
  render();
}
function gotoIssue(issue){
  if(!issue.locs.length)return;
  const loc=issue.locs.find(l=>l.owner===P.owner)||issue.locs[0];
  if(loc.owner!==P.owner){P.owner=loc.owner;}
  P.spread=loc.index;P.selected=loc.key;P.crop=null;P.photoTab=null;P.right='element';defaultScope();render();
  document.querySelector(`.proof-spread.live [data-key="${CSS.escape(loc.key)}"]`)?.scrollIntoView({block:'nearest',inline:'nearest'});
}
function openProperties(){document.querySelector('.right-panel').classList.add('mobile-open');}

/* ---------------------------------------------------------------- events */
document.addEventListener('click',async event=>{
  const t=event.target;
  const ownerButton=t.closest('[data-owner]');if(ownerButton){goOwner(ownerButton.dataset.owner);return;}
  const spreadButton=t.closest('[data-spread]');if(spreadButton){goSpread(Number(spreadButton.dataset.spread));return;}
  const filter=t.closest('[data-filter]');if(filter){P.filter=filter.dataset.filter;renderPeople();return;}
  const left=t.closest('[data-left]');if(left){P.left=left.dataset.left;render();return;}
  const right=t.closest('[data-right]');if(right){P.right=right.dataset.right;renderInspector();return;}
  const mode=t.closest('[data-mode]');if(mode){await switchMode(mode.dataset.mode);return;}
  const issue=t.closest('[data-issue]');if(issue){gotoIssue(P.info.issues[Number(issue.dataset.issue)]);return;}
  const goto=t.closest('[data-goto]');if(goto){goSpread(Number(goto.dataset.goto),goto.dataset.key);return;}
  const scope=t.closest('[data-scope]');if(scope){P.scope=scope.dataset.scope;renderInspector();return;}
  const tab=t.closest('[data-photo-tab]');if(tab){P.photoTab=tab.dataset.photoTab;renderInspector();return;}
  const photo=t.closest('[data-photo]');if(photo){const e=selectedElement();if(e&&photo.dataset.photo!==e.photo)operate([{key:e.key,type:'photo',value:photo.dataset.photo,scope:scopeFor(e)}],'Замена фото');return;}
  const conflict=t.closest('[data-drop-conflict]');if(conflict){const c=P.data.document.overrides.conflicts[Number(conflict.dataset.dropConflict)];mutate('Удаление правки',()=>replaceOverrides(P.data.overrides.filter(o=>!(o.key===c.key&&(!c.type||o.type===c.type)))));return;}
  const layer=t.closest('.proof-spread.live [data-key]');
  if(layer&&editable()){if(P.dragged){P.dragged=false;return;}if(layer.dataset.key!==P.selected)select(layer.dataset.key);return;}
  if(t.closest('#stage')&&!t.closest('[data-key]')&&P.selected){await leaveElement();P.selected=null;P.crop=null;render();return;}
  switch(t.closest('button,a')?.id){
    case 'undo':undo();break;
    case 'redo':redo();break;
    case 'prev-spread':goSpread(P.spread-1);break;
    case 'next-spread':goSpread(P.spread+1);break;
    case 'zoom-in':P.zoom=Math.min(4,+(P.zoom*1.25).toFixed(2));fit();break;
    case 'zoom-out':P.zoom=Math.max(.5,+(P.zoom/1.25).toFixed(2));fit();break;
    case 'zoom-fit':P.zoom=1;fit();break;
    case 'text-save':commitText();break;
    case 'text-cancel':P.draft=null;render();break;
    case 'toggle-hidden':{const e=selectedElement();if(e)operate([{key:e.key,type:'hide',value:!e.hidden,scope:scopeFor(e)}],e.hidden?'Показ элемента':'Скрытие элемента');break;}
    case 'reset-element':{const e=selectedElement();if(!e)break;const kinds=overriddenKinds(e),ops=[];if(kinds.some(k=>k.scope!=='all'))ops.push({key:e.key,type:'reset',scope:'variant'});if(kinds.some(k=>k.scope==='all')&&e.shared)ops.push({key:e.key,type:'reset',scope:'all'});if(ops.length)operate(ops,'Возврат исходного');break;}
    case 'crop-center':{const e=selectedElement();if(!e)break;const crop=liveCrop(e),meta=photoMeta(e.photo);P.crop={key:e.key,crop:clampCrop(e,[(meta.width-crop[2])/2,(meta.height-crop[3])/2,crop[2],crop[3]])};renderCanvas();commitCrop(e);break;}
    case 'crop-reset':{const e=selectedElement();if(e)operate([{key:e.key,type:'reset',value:'crop',scope:overriddenKinds(e).some(k=>k.type==='crop'&&k.scope==='all')?'all':'variant'}],'Исходный кадр');break;}
    case 'mark-reviewed':{const v=variant(),value=!reviewed(v.owner);if(await setReviewed(v.owner,value)&&value)toast(`${v.name||'Вариант'}: проверен`);break;}
    case 'next-person':{const next=nextUnreviewed();if(next)goOwner(next,{keepSpread:false});else toast('Все варианты проверены');break;}
    case 'publish':openPublish();break;
    case 'confirm-publish':publish();break;
    case 'refresh':t.closest('details')?.removeAttribute('open');$('#refresh-error').textContent='';$('#refresh-dialog').showModal();break;
    case 'confirm-refresh':regenerate();break;
    case 'generate':generate();break;
    case 'toggle-marks':P.marks=!P.marks;t.closest('details')?.removeAttribute('open');render();break;
    case 'show-properties':openProperties();break;
    case 'close-properties':document.querySelector('.right-panel').classList.remove('mobile-open');break;
    case 'pdf':if(t.closest('a').classList.contains('disabled')){event.preventDefault();toast(P.info?.errors?'Исправьте ошибки, чтобы скачать PDF':'PDF доступен в рабочей редакции');}break;
  }
});
document.addEventListener('change',event=>{
  if(event.target.id==='spread-select')goSpread(Number(event.target.value));
  if(event.target.id==='photo-person'){P.photoPerson=event.target.value;renderInspector();}
});
document.addEventListener('focusout',event=>{if(event.target.id==='text-value'&&!event.relatedTarget?.closest?.('#text-save,#text-cancel'))commitText();});
document.addEventListener('keydown',event=>{
  const typing=event.target.closest('input,textarea,select,[contenteditable]'),mod=event.metaKey||event.ctrlKey;
  if(mod&&event.key==='Enter'){event.preventDefault();if(event.target.id==='text-value')commitText();else if(P.mode==='work')$('#mark-reviewed')?.click();return;}
  if(mod&&event.key.toLowerCase()==='z'&&!typing){event.preventDefault();event.shiftKey?redo():undo();return;}
  if(mod&&event.key.toLowerCase()==='y'&&!typing){event.preventDefault();redo();return;}
  if(typing||!doc())return;
  if(event.key==='Escape'&&P.selected){P.selected=null;P.crop=null;P.draft=null;render();return;}
  if(event.key==='ArrowRight'||event.key==='PageDown'){event.preventDefault();goSpread(P.spread+1);}
  if(event.key==='ArrowLeft'||event.key==='PageUp'){event.preventDefault();goSpread(P.spread-1);}
  if(event.key==='ArrowDown'||event.key==='ArrowUp'){const list=doc().variants,i=list.findIndex(v=>v.owner===P.owner),next=list[i+(event.key==='ArrowDown'?1:-1)];if(next){event.preventDefault();goOwner(next.owner);}}
});
/* Drag inside the selected frame moves the crop; the wheel zooms it. */
let drag=null;
document.addEventListener('pointerdown',event=>{
  const layer=event.target.closest('.proof-spread.live .pl-photo.selected');if(!layer||!editable()||event.button!==0)return;
  const e=selectedElement();P.dragged=false;if(!e?.photo||!photoMeta(e.photo))return;
  const rect=layer.getBoundingClientRect();
  drag={e,startX:event.clientX,startY:event.clientY,crop:[...liveCrop(e)],scale:liveCrop(e)[2]/rect.width,moved:false};
  layer.setPointerCapture(event.pointerId);event.preventDefault();
});
document.addEventListener('pointermove',event=>{
  if(!drag)return;const dx=event.clientX-drag.startX,dy=event.clientY-drag.startY;
  if(!drag.moved&&Math.hypot(dx,dy)<3)return;drag.moved=true;
  const [x,y,w,h]=drag.crop;P.crop={key:drag.e.key,crop:clampCrop(drag.e,[x-dx*drag.scale,y-dy*drag.scale,w,h]),ghost:true};
  renderCanvas();
});
document.addEventListener('pointerup',()=>{
  if(!drag)return;const {e,moved}=drag;drag=null;
  if(moved){P.dragged=true;if(P.crop)P.crop.ghost=false;renderCanvas();syncCropThumb(e);commitCrop(e);}
});
document.addEventListener('wheel',event=>{
  const layer=event.target.closest('.proof-spread.live .pl-photo.selected');if(!layer||!editable())return;
  const e=selectedElement();if(!e?.photo||!photoMeta(e.photo))return;
  event.preventDefault();setCropZoom(e,Math.max(1,Math.min(4,cropZoom(e)*(event.deltaY<0?1.06:1/1.06))));
  const zoom=$('#crop-zoom');if(zoom){zoom.value=cropZoom(e).toFixed(2);zoom.nextElementSibling.textContent=`${Math.round(cropZoom(e)*100)}%`;}
  commitCrop(e,450);
},{passive:false});
window.addEventListener('resize',fit);
window.addEventListener('beforeunload',event=>{if(P.busy||(P.draft&&P.draft.value!==selectedElement()?.text)){event.preventDefault();event.returnValue='';}});

/* ---------------------------------------------------------------- publication and regeneration */
async function switchMode(mode){
  if(mode===P.mode)return;await leaveElement();
  if(mode==='published'){
    try{P.pub=await api(`/orders/${encodeURIComponent(P.order)}/layout/publication`);}catch(error){toast(error.message);return;}
    if(!P.pub.document.variants?.some(v=>v.owner===P.owner))P.owner=P.pub.document.variants?.[0]?.owner;
  }
  P.mode=mode;P.selected=null;P.crop=null;P.draft=null;
  const length=variant()?.sequence.length||1;P.spread=Math.min(P.spread,length-1);
  if(mode==='work'&&!P.data.document.variants.some(v=>v.owner===P.owner))P.owner=P.data.document.variants[0]?.owner;
  render();
}
function openPublish(){
  const info=P.info,d=P.data.document,status=P.data.status,variants=d.variants,done=variants.filter(v=>reviewed(v.owner)).length;
  const publication=status.publication,approval=status.approval;
  const rows=[
    ['Варианты',plural(variants.length,'вариант','варианта','вариантов')],
    ['Разворотов в каждом',d.spread_count],
    ['Проверено',`${done} из ${variants.length}`],
    ['Ошибки',info.errors||'нет'],['Предупреждения',info.warnings||'нет'],
    ['Предыдущая публикация',publication?date(publication.published_at):'нет'],
  ];
  if(publication&&!publication.current)rows.push(['Изменятся',plural(publication.changed.length,'вариант','варианта','вариантов')]);
  const notes=[];
  if(info.errors)notes.push(`<p class="form-error">Исправьте ошибки: публикация с ними невозможна.</p>`);
  if(done<variants.length)notes.push(`<p class="note warning">Не все варианты отмечены проверенными. Публиковать можно, но класс увидит непросмотренные альбомы.</p>`);
  if(publication?.current)notes.push('<p class="note">Эта редакция уже опубликована.</p>');
  if(approval&&publication&&!publication.current)notes.push('<p class="note warning">Класс уже согласовал прежнюю редакцию. После публикации потребуется повторное согласование или ваша отдельная ответственность при разрешении производства.</p>');
  $('#publish-body').innerHTML=`<dl class="publish-summary">${rows.map(([k,v])=>`<dt>${k}</dt><dd>${esc(v)}</dd>`).join('')}</dl>${notes.join('')}<p class="muted">Класс увидит опубликованную редакцию. Рабочая останется доступной для правок.</p>`;
  $('#publish-error').textContent='';$('#confirm-publish').disabled=!!info.errors||!!publication?.current;
  $('#publish-dialog').showModal();
}
async function publish(){
  const button=$('#confirm-publish');button.disabled=true;
  try{await api(`/orders/${encodeURIComponent(P.order)}/layout/publish`,'POST',{});adopt(await api(`/orders/${encodeURIComponent(P.order)}/layout`));$('#publish-dialog').close();toast('Макет опубликован для класса');render();}
  catch(error){$('#publish-error').textContent=error.message;button.disabled=false;}
}
async function regenerate(){
  const button=$('#confirm-refresh');button.disabled=true;
  try{adopt(await api(`/orders/${encodeURIComponent(P.order)}/layout`,'POST',{}));P.history=[];P.future=[];$('#refresh-dialog').close();toast('Макет обновлён из данных заказа');render();}
  catch(error){$('#refresh-error').textContent=error.message;}
  finally{button.disabled=false;}
}
async function generate(){
  const button=$('#generate');button.disabled=true;
  try{adopt(await api(`/orders/${encodeURIComponent(P.order)}/layout`,'POST',{}),{keepSelection:false});P.missing=false;await loadFonts();render();toast('Макет собран');}
  catch(error){$('#generate-error').textContent=error.message;button.disabled=false;}
}

load();
