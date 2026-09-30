/* Photo selection, the action panel by the last selected photo, review by person and page-wide upload.
   Uses the V2 globals (state, $, api, json, esc, toast, count, svgIcon, ICONS, personName, statuses …). */
Object.assign(ICONS,{
  x:'<path d="M18 6 6 18M6 6l12 12"/>',
  ok:'<path d="m5 12 5 5 9-10"/>',
  user:'<circle cx="12" cy="8" r="4"/><path d="M4 21c1-4 4-6 8-6s7 2 8 6"/>',
  swap:'<circle cx="9" cy="8" r="4"/><path d="M2 21c1-4 3.5-6 7-6 1.4 0 2.6.3 3.6.9M15 15h7m-2.5-2.5L22 15l-2.5 2.5M22 20h-7m2.5-2.5L15 20l2.5 2.5"/>',
  star:'<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z"/>',
  trash:'<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  folder:'<path d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  left:'<path d="m15 18-6-6 6-6"/>',right:'<path d="m9 18 6-6-6-6"/>',
  selectAll:'<rect x="3" y="3" width="18" height="18" rx="4"/><path d="m8 12 3 3 5-6"/>',
  eye:'<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  scene:'<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 16 5-5 4 4 3-3 6 6"/><circle cx="16" cy="9" r="1.5"/>',
  retry:'<path d="M3 12a9 9 0 0 1 15.5-6.2L21 8M21 3v5h-5M21 12a9 9 0 0 1-15.5 6.2L3 16M3 21v-5h5"/>'
});

window.PhotoTools=(()=>{
  let anchor=null,lasso=null,dragIds=null,dropDepth=0,pillTimer=null;
  const photo=id=>state.order?.photos.find(p=>p.id===id);
  const personIndex=id=>state.order.persons.findIndex(p=>p.id===id);
  const scope=()=>$('#person-dialog')?.open?$('#person-dialog'):$('#workspace');
  const boxes=()=>[...(scope()?.querySelectorAll('input[data-photo]')||[])];
  const ids=()=>boxes().map(i=>i.dataset.photo);
  const typing=el=>!!el&&(el.isContentEditable||['TEXTAREA','SELECT'].includes(el.tagName)||el.tagName==='INPUT'&&!['checkbox','radio'].includes(el.type));
  const isPortrait=p=>p&&p.shoot_type!=='general';
  const busy=p=>['pending','processing'].includes(p.status);

  /* Shift-click range in the order the tiles are shown. An unknown anchor selects only the clicked photo. */
  function rangeBetween(list,from,to){const a=list.indexOf(from),b=list.indexOf(to);return a<0||b<0?[to]:list.slice(Math.min(a,b),Math.max(a,b)+1);}
  function changed(){document.querySelectorAll('input[data-photo]').forEach(i=>{i.checked=state.selected.has(i.dataset.photo);});dock();}
  function select(list,on=true){list.forEach(id=>on?state.selected.add(id):state.selected.delete(id));changed();}
  function clear(){state.selected.clear();anchor=null;changed();}
  function selectAll(){const list=ids(),all=list.length&&list.every(id=>state.selected.has(id));select(list,!all);}

  document.addEventListener('click',e=>{
    const box=e.target.closest('.photo-tile')?.querySelector('input[data-photo]');
    if(!box||e.target.closest('button,a,select,summary'))return;
    const id=box.dataset.photo;last=id;picking=false;
    if(e.shiftKey&&anchor&&anchor!==id&&ids().includes(anchor)){e.preventDefault();select(rangeBetween(ids(),anchor,id),state.selected.has(anchor));anchor=id;return;}
    anchor=id;
  },true);

  /* Rubber-band selection from empty space around the tiles. Shift or ⌘ adds to the current selection. */
  document.addEventListener('pointerdown',e=>{
    if(e.button!==0||e.pointerType==='touch'||!state.order)return;
    const area=e.target.closest('.photo-grid,#photo-results,.review-board,#person-content');
    if(!area||e.target.closest('.photo-tile,button,a,input,select,label,form,.ref-tile'))return;
    lasso={x:e.clientX,y:e.clientY,sy:scrollY,id:e.pointerId,base:e.shiftKey||e.metaKey||e.ctrlKey?new Set(state.selected):new Set(),el:null,frame:0};
  });
  document.addEventListener('pointermove',e=>{
    if(!lasso||e.pointerId!==lasso.id)return;
    if(!lasso.el){if(Math.hypot(e.clientX-lasso.x,e.clientY-lasso.y)<6)return;lasso.el=document.createElement('div');lasso.el.className='lasso';(scope()?.tagName==='DIALOG'?scope():document.body).append(lasso.el);document.body.classList.add('lassoing');}
    e.preventDefault();
    if(e.clientY>innerHeight-40)scrollBy(0,18);else if(e.clientY<40)scrollBy(0,-18);
    const top=lasso.y-(scrollY-lasso.sy),r={left:Math.min(lasso.x,e.clientX),right:Math.max(lasso.x,e.clientX),top:Math.min(top,e.clientY),bottom:Math.max(top,e.clientY)};
    Object.assign(lasso.el.style,{left:r.left+'px',top:r.top+'px',width:r.right-r.left+'px',height:r.bottom-r.top+'px'});
    cancelAnimationFrame(lasso.frame);
    lasso.frame=requestAnimationFrame(()=>{if(!lasso)return;const next=new Set(lasso.base);for(const box of boxes()){const t=box.closest('.photo-tile').getBoundingClientRect();if(t.right>r.left&&t.left<r.right&&t.bottom>r.top&&t.top<r.bottom){next.add(box.dataset.photo);last=box.dataset.photo;}}state.selected=next;changed();});
  });
  const endLasso=e=>{if(!lasso||e.pointerId!==lasso.id)return;lasso.el?.remove();document.body.classList.remove('lassoing');lasso=null;};
  document.addEventListener('pointerup',endLasso);document.addEventListener('pointercancel',endLasso);

  document.addEventListener('keydown',e=>{
    if(picking&&!$('#selection-dock')?.hidden&&pickerKey(e))return;
    if(typing(e.target)||[...document.querySelectorAll('dialog[open]')].some(d=>d.id!=='person-dialog'))return;
    if(!boxes().length)return;
    const mod=e.metaKey||e.ctrlKey;
    if(mod&&e.code==='KeyA'){e.preventDefault();select(ids(),true);return;}
    if(e.key==='Escape'&&state.selected.size){e.preventDefault();clear();return;}
    if(mod||e.altKey||e.target.closest?.('button,a'))return;
    if((e.key==='Delete'||e.key==='Backspace')&&state.selected.size){e.preventDefault();confirmRemoval('photos');return;}
    const act=e.code==='KeyP'?'move':e.code==='KeyN'?'to-general':null,btn=act&&state.selected.size&&$(`#selection-dock [data-photo-tools="${act}"]`);
    if(btn){e.preventDefault();btn.click();return;}
    if(e.key==='Enter'&&state.selected.size){const b=$('#selection-dock [data-v2="confirm-photos"]');if(b&&!b.disabled){e.preventDefault();b.click();}}
  });

  /* Actions panel next to the last selected photo; «Другой персоне» turns it into a person search in place. */
  let last=null,picking=false,hot=0,query='',hints=new Map(),hintGen=0;
  const button=(attrs,icon,label,title,cls='',key='')=>`<button class="sel-act ${cls}" ${attrs} title="${esc(title)}">${svgIcon(icon,16)}<span>${esc(label)}</span>${key?`<kbd>${key}</kbd>`:''}</button>`;
  function actions(){
    const chosen=state.order.photos.filter(p=>state.selected.has(p.id)),one=chosen.length===1;
    const cover=one?button('data-v2="set-cover"','star','На обложку','Сделать обложкой заказа'):'';
    const del=button('data-v2="delete-photos"','trash','Удалить','Удалить выбранные · Delete','danger');
    if(state.view==='photos'&&globalThis.GeneralReview?.isGeneral())return GeneralReview.dockActions(button)+cover+del;
    const portrait=chosen.length&&chosen.every(p=>isPortrait(p)&&!busy(p));
    return (chosen.some(p=>p.uncertain&&canConfirmMatch(p))?`<button class="sel-act primary" data-v2="confirm-photos"></button>`:'')
      +(portrait?button('data-photo-tools="move"','swap','Другой персоне','Назначить другую или новую персону','','P'):'')
      +(portrait?button('data-photo-tools="to-general"','scene','Не портрет','Перенести в общую съёмку','','N'):'')+cover+del;
  }
  /* While something is selected the shoot row shows the count instead of its tools. */
  function countRow(n){
    const head=$('.shoot-head'),bar=head?.querySelector('.shoot-tools');if(!bar)return;
    head.classList.toggle('selecting',!!n);let row=bar.querySelector('.sel-slim');
    if(!n){row?.remove();return;}
    if(!row){row=document.createElement('div');row.className='sel-slim';bar.prepend(row);}
    const list=ids();
    row.innerHTML=`<b>Выбрано ${n}</b><button type="button" data-photo-tools="clear">Снять</button>${list.length&&!list.every(id=>state.selected.has(id))?`<button type="button" data-photo-tools="select-all">Выбрать все ${list.length}</button>`:''}`;
  }
  function dock(){
    let el=$('#selection-dock');
    if(!el){el=document.createElement('div');el.id='selection-dock';el.className='selection-dock';el.setAttribute('role','toolbar');el.setAttribute('aria-label','Действия с выбранными фото');}
    const dialog=$('#person-dialog')?.open?$('#person-dialog'):null,host=dialog||document.body;
    if(el.parentElement!==host)host.append(el);
    el.classList.toggle('in-dialog',!!dialog);
    const n=state.order?state.selected.size:0;
    document.body.classList.toggle('has-selection',!!n);
    countRow(n);
    if(!n){el.hidden=true;el.innerHTML='';picking=false;return;}
    // Appear in place; only moves between photos are animated.
    const appearing=el.hidden;if(appearing)el.style.transition='none';
    el.hidden=false;el.classList.toggle('picking',picking);
    el.innerHTML=picking?pickerHtml():`<div class="near-row"><span class="near-count"><button type="button" class="ico-btn" data-photo-tools="clear" title="Снять выделение · Esc" aria-label="Снять выделение">${svgIcon('x',16)}</button>${n}</span>${actions()}</div>`;
    if(picking){const q=$('#pick-q');q.oninput=()=>{query=q.value;hot=0;refreshPicker();};}else syncConfirmation();
    place();
    if(appearing){void el.offsetWidth;el.style.transition='';}
  }
  function dockBounds(){
    const dialog=$('#person-dialog')?.open?$('#person-dialog'):null;
    const area=(dialog||$('#workspace')||document.body).getBoundingClientRect(),bar=dialog?null:$('.shoot-head');
    return {dialog,left:Math.max(0,area.left)+12,right:Math.min(innerWidth,area.right)-12,
      top:dialog?Math.max(0,area.top)+12:Math.max(10,bar?bar.getBoundingClientRect().bottom+8:10),
      bottom:dialog?Math.min(innerHeight,area.bottom)-12:innerHeight-10};
  }
  /* Same photo anchor on the page and in the person dialog, within the active surface. */
  function place(){
    const el=$('#selection-dock');if(!el||el.hidden)return;
    const all=boxes(),box=all.find(b=>b.dataset.photo===last&&state.selected.has(last))||all.find(b=>state.selected.has(b.dataset.photo));
    const tile=box?.closest('.photo-tile'),bounds=dockBounds(),room=Math.max(0,bounds.right-bounds.left);
    el.style.maxWidth=room+'px';
    // Narrow window: key hints go first, then labels; icons keep their titles.
    el.classList.remove('no-kbd','icons');if(el.scrollWidth>room)el.classList.add('no-kbd');if(el.scrollWidth>room)el.classList.add('icons');
    const list=el.querySelector('.pp-list');if(list)list.style.maxHeight=Math.max(52,Math.min(292,bounds.bottom-bounds.top-150))+'px';
    const w=el.offsetWidth,h=el.offsetHeight,minTop=bounds.top,minLeft=bounds.left,maxLeft=Math.max(minLeft,bounds.right-w),maxTop=Math.max(minTop,bounds.bottom-h);
    if(!tile){el.classList.remove('below','above');el.style.top=maxTop+'px';el.style.left=Math.max(minLeft,Math.min(maxLeft,minLeft+(room-w)/2))+'px';return;}
    const r=tile.getBoundingClientRect(),below=r.bottom+10+h<=bounds.bottom||r.top-10-h<minTop;
    const top=Math.max(minTop,Math.min(maxTop,below?r.bottom+10:r.top-h-10)),left=Math.max(minLeft,Math.min(maxLeft,r.left+r.width/2-w/2));
    el.style.top=top+'px';el.style.left=left+'px';el.style.setProperty('--tip',Math.max(18,Math.min(w-18,r.left+r.width/2-left))+'px');
    el.style.setProperty('--arrow',r.bottom<minTop||r.top>bounds.bottom?'0':'1');
    el.classList.toggle('below',below);el.classList.toggle('above',!below);
  }
  window.addEventListener('scroll',place,{passive:true,capture:true});window.addEventListener('resize',place);

  function openPicker(){
    const chosen=[...state.selected].map(photo).filter(Boolean);
    if(!chosen.length||!chosen.every(p=>isPortrait(p)&&!busy(p))){toast('Персону можно назначить только обработанным портретам');return;}
    picking=true;query='';hot=0;hints=new Map();dock();$('#pick-q')?.focus({preventScroll:true});
    // No room on either side of the photo: scroll so the search opens below it.
    const el=$('#selection-dock'),tile=boxes().find(b=>b.dataset.photo===last)?.closest('.photo-tile');
    if(tile){const r=tile.getBoundingClientRect(),bounds=dockBounds(),h=el.offsetHeight,need=r.bottom+10+h-bounds.bottom;
      if(need>0&&r.top-10-h<bounds.top){const distance=Math.min(need,Math.max(0,r.top-bounds.top));
        if(bounds.dialog)bounds.dialog.scrollBy({top:distance,behavior:'smooth'});
        else scrollBy({top:distance,behavior:'smooth'});}}
    const gen=++hintGen,orderId=state.order.id;
    api(`/orders/${orderId}/person-suggestions`,json('POST',{photo_ids:chosen.map(p=>p.id)})).then(result=>{
      if(gen!==hintGen||!picking)return;
      for(const item of result.photos)for(const c of item.candidates){if(c.similarity!==null&&c.similarity<.35&&c.reason==='face')continue;const rank=c.reason==='face_and_neighbors'?3:c.reason==='neighbors'?1:2;hints.set(c.person_id,Math.max(rank,hints.get(c.person_id)||0));}
      refreshPicker();
    }).catch(()=>{});
  }
  function closePicker(){if(!picking)return;picking=false;dock();}
  function candidates(){
    const o=state.order,q=query.trim().toLocaleLowerCase();
    return o.persons.map((person,i)=>{const own=o.photos.filter(p=>p.person_id===person.id);return {id:person.id,i,name:personName(person,i),cover:own.find(p=>!p.uncertain&&p.face&&!state.selected.has(p.id))||own.find(p=>!p.uncertain&&!state.selected.has(p.id))||own.find(p=>!state.selected.has(p.id))};})
      .filter(p=>!q||p.name.toLocaleLowerCase().includes(q)).sort((a,b)=>(hints.get(b.id)||0)-(hints.get(a.id)||0)||a.i-b.i);
  }
  function pickerRows(){
    const list=candidates(),current=[...new Set([...state.selected].map(id=>photo(id)?.person_id))];
    return list.map((p,j)=>`<button type="button" class="opt ${j===hot?'hot':''}" data-pick="${p.id}"><span class="ava">${p.cover?faceImg(p.cover):''}</span><span class="opt-name">${esc(p.name)}</span>${current.length===1&&current[0]===p.id?'<span class="tag">сейчас</span>':hints.has(p.id)?'<span class="tag like">похож</span>':''}</button>`).join('')
      +(list.length?'':'<div class="pp-empty">Никого не нашли</div>')
      +`<button type="button" class="opt new ${hot===list.length?'hot':''}" data-pick=""><span class="ava">${svgIcon('plus',12)}</span><span class="opt-name">Новая персона</span></button>`;
  }
  /* The thumbnail scaled and shifted so the stored face box fills the circle; no extra requests. */
  function faceImg(p){const f=p.face;if(!f)return `<img src="/media/${p.id}/thumb${p.retouch_version?'?v='+p.retouch_version:''}" alt="" loading="lazy">`;const zoom=Math.min(6,Math.max(1,.62/f[2]));
    return `<img class="face" src="/media/${p.id}/thumb${p.retouch_version?'?v='+p.retouch_version:''}" alt="" loading="lazy" style="width:${(zoom*100).toFixed(1)}%;transform:translate(${(-(f[0]+f[2]/2)*100).toFixed(1)}%,${(-(f[1]+f[3]/2)*100).toFixed(1)}%)">`;}
  function pickerHtml(){return `<div class="pp-head"><button type="button" class="ico-btn" data-photo-tools="pick-back" title="Назад · Esc" aria-label="Назад">${svgIcon('left',16)}</button><strong>Другой персоне <span>· ${state.selected.size} фото</span></strong></div><div class="pp-search">${svgIcon('search',15)}<input id="pick-q" type="text" placeholder="Найти по имени" autocomplete="off" aria-label="Найти персону" value="${esc(query)}"></div><div class="pp-list">${pickerRows()}</div><div class="pp-foot">↑↓ — выбрать · Enter — перенести · Esc — назад</div>`;}
  /* Only the list is redrawn so the search field keeps focus. */
  function refreshPicker(){const box=$('#selection-dock .pp-list');if(!box)return;box.innerHTML=pickerRows();place();box.querySelector('.opt.hot')?.scrollIntoView({block:'nearest'});}
  function pickerKey(e){
    const opts=[...document.querySelectorAll('#selection-dock .opt')];
    if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();hot=(hot+(e.key==='ArrowDown'?1:-1)+opts.length)%opts.length;opts.forEach((x,j)=>x.classList.toggle('hot',j===hot));opts[hot]?.scrollIntoView({block:'nearest'});return true;}
    if(e.key==='Enter'){e.preventDefault();opts[hot]?.click();return true;}
    if(e.key==='Escape'){e.preventDefault();closePicker();return true;}
    return false;
  }
  async function assign(pid){
    const list=[...state.selected],o=state.order,i=pid?personIndex(pid):-1;
    document.querySelectorAll('#selection-dock .opt').forEach(b=>{b.disabled=true;});
    try{await api(`/orders/${o.id}/move`,json('POST',{photo_ids:list,person_id:pid||null}));picking=false;$('#person-dialog')?.open&&$('#person-dialog').close();state.selected.clear();await refreshOrder();toast(pid?`${personName(o.persons[i],i)}: перенесено ${list.length}`:`Новая персона: ${list.length} фото`);}
    catch(error){toast(error.message);refreshPicker();}
  }
  document.addEventListener('click',e=>{if(picking&&!e.target.closest('#selection-dock,.photo-tile'))closePicker();});

  /* Review: suggested matches grouped by person next to a confirmed reference, then unrecognised frames, then errors. */
  function reviewTile(p,kind){
    const quick=kind==='match'?`<button type="button" class="quick ok" data-review="ok" data-id="${p.id}" title="Верно" aria-label="Верно">${svgIcon('ok',18)}</button><button type="button" class="quick no" data-review="wrong" data-id="${p.id}" title="Не он — выбрать персону" aria-label="Другая персона">${svgIcon('x',18)}</button>`
      :kind==='unknown'?`<button type="button" class="quick" data-review="assign" data-id="${p.id}" title="Кто это? Выбрать персону" aria-label="Выбрать персону">${svgIcon('user',17)}</button><button type="button" class="quick" data-review="general" data-id="${p.id}" title="Не портрет — в общую съёмку" aria-label="Перенести в общую съёмку">${svgIcon('scene',17)}</button>`:'';
    const note=kind==='unknown'?(p.status==='ready'?'Персона не определена':statuses[p.status]||'Проверить'):kind==='error'?p.error||statuses.error:'';
    // The checkbox goes first: a label activates its first labelable descendant, and buttons are labelable too.
    return `<label class="photo-tile review-tile" ${kind==='error'?'':'draggable="true"'}><input type="checkbox" data-photo="${p.id}" aria-label="Выбрать ${esc(p.filename)}" ${state.selected.has(p.id)?'checked':''}><span class="tile-media"><img src="/media/${p.id}/thumb${p.retouch_version?'?v='+p.retouch_version:''}" alt="${esc(p.filename)}" loading="lazy" decoding="async" draggable="false"><span class="tile-quick">${quick}</span></span><p title="${esc(p.filename)}">${esc(p.filename)}</p>${note?`<small>${esc(note)}</small>`:''}</label>`;
  }
  function reviewGroup(g){
    const o=state.order,i=personIndex(g.id),name=personName(o.persons[i],i);
    const confirmed=o.photos.filter(p=>p.person_id===g.id&&p.status==='ready'&&!p.uncertain);
    const ref=confirmed[0]||o.photos.find(p=>p.person_id===g.id&&p.status==='ready'&&!g.photos.includes(p));
    const note=confirmed.length?`Подтверждено ${confirmed.length} · сравните с эталоном`:ref?'Эталон тоже не подтверждён':'Других снимков нет — возможно, новый человек';
    return `<article class="review-group" data-drop-person="${g.id}"><header class="review-head"><div><strong>${esc(name)}</strong><small>${note}</small></div><button class="text-button" data-review="select-group" data-pid="${g.id}">Выбрать группу</button><button class="primary review-ok" data-review="confirm-group" data-pid="${g.id}">${svgIcon('ok',16)}${ref?'Всё верно':'Оставить отдельно'} · ${g.photos.length}</button></header><div class="photo-grid review-cands">${ref?`<div class="ref-tile"><img src="/media/${ref.id}/thumb${ref.retouch_version?'?v='+ref.retouch_version:''}" alt="Эталон: ${esc(name)}" loading="lazy" draggable="false"><span class="ref-label">Эталон</span><p>${esc(name)}</p></div>`:`<div class="ref-tile ref-empty">${svgIcon('user',34)}<p>Нет эталона</p></div>`}${g.photos.map(p=>reviewTile(p,'match')).join('')}</div></article>`;
  }
  function reviewBoard(photos){
    const o=state.order,matches=photos.filter(p=>p.status==='ready'&&p.person_id&&personIndex(p.person_id)>=0),errors=photos.filter(p=>p.status==='error'),unknown=photos.filter(p=>!matches.includes(p)&&!errors.includes(p));
    const groups=[...new Set(matches.map(p=>p.person_id))].sort((a,b)=>personIndex(a)-personIndex(b)).map(id=>({id,photos:matches.filter(p=>p.person_id===id)}));
    if(!photos.length)return `<div class="empty-state review-done">${svgIcon('check',40)}<h3>Всё проверено</h3><p>Все портреты распределены по персонам.</p>${o.stage==='photos'?'<button class="primary" data-v2="send-forms">Отправить на анкеты</button>':''}</div>`;
    return `<div class="review-board">${groups.length?`<section class="review-section"><header><h3>Проверьте совпадения <span>${matches.length}</span></h3><p>Слева эталон персоны. Нажмите «Всё верно» для группы или ✕ на лишнем снимке. Снимки можно перетащить в другую группу.</p></header><div class="review-groups">${groups.map(reviewGroup).join('')}</div></section>`:''}${unknown.length?`<section class="review-section"><header><h3>Не распознано <span>${unknown.length}</span></h3><p>Лицо не найдено, несколько лиц или персона не определена. Назначьте человека, перенесите в общую съёмку или удалите.</p></header><div class="photo-grid">${unknown.map(p=>reviewTile(p,'unknown')).join('')}</div></section>`:''}${errors.length?`<section class="review-section"><header><h3>Не удалось распознать <span>${errors.length}</span></h3><button class="secondary with-icon" data-action="retry">${svgIcon('retry',15)}Повторить</button></header><div class="photo-grid">${errors.map(p=>reviewTile(p,'error')).join('')}</div></section>`:''}</div>`;
  }
  async function confirm(photos,message){
    photos=photos.filter(p=>p.status==='ready'&&p.person_id);if(!photos.length)return;
    await api(`/orders/${state.order.id}/confirm-photos`,json('POST',{photo_ids:photos.map(p=>p.id),expected_persons:Object.fromEntries(photos.map(p=>[p.id,p.person_id]))}));
    photos.forEach(p=>state.selected.delete(p.id));await refreshOrder();if(message)toast(message);
  }
  function only(id,then){state.selected=new Set([id]);changed();then();}
  document.addEventListener('click',async e=>{
    const pick=e.target.closest('[data-pick]');if(pick){e.preventDefault();assign(pick.dataset.pick);return;}
    const t=e.target.closest('[data-review],[data-photo-tools]');if(!t)return;
    e.preventDefault();
    const action=t.dataset.review||t.dataset.photoTools,pid=t.dataset.pid,group=()=>state.order.photos.filter(p=>p.person_id===pid&&needsReview(p));
    try{
      if(action==='clear')clear();
      if(action==='select-all')selectAll();
      if(action==='to-general')toGeneral([...state.selected]);
      if(action==='move')openPicker();
      if(action==='pick-back')closePicker();
      if(action==='select-group'){const list=group().map(p=>p.id),all=list.every(id=>state.selected.has(id));select(list,!all);}
      if(action==='confirm-group'){t.disabled=true;const i=personIndex(pid);await confirm(group(),`${personName(state.order.persons[i],i)}: подтверждено ${group().length}`);}
      if(action==='ok'){t.disabled=true;await confirm([photo(t.dataset.id)].filter(Boolean));}
      if(action==='wrong'||action==='assign'){last=t.dataset.id;only(t.dataset.id,openPicker);}
      if(action==='general')toGeneral([t.dataset.id]);
    }catch(error){toast(error.message);t.disabled=false;}
  });

  /* Drag suggested or selected photos onto another person's group. */
  const dropTarget=e=>dragIds&&e.target.closest?.('[data-drop-person]');
  document.addEventListener('dragstart',e=>{const box=e.target.closest?.('.review-tile')?.querySelector('input[data-photo]');if(!box)return;const id=box.dataset.photo;dragIds=state.selected.has(id)?[...state.selected]:[id];e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',dragIds.length+' фото');});
  document.addEventListener('dragend',()=>{dragIds=null;document.querySelectorAll('.review-group.drop').forEach(g=>g.classList.remove('drop'));});
  document.addEventListener('dragover',e=>{const g=dropTarget(e);if(!g)return;e.preventDefault();document.querySelectorAll('.review-group.drop').forEach(x=>x!==g&&x.classList.remove('drop'));g.classList.add('drop');});
  document.addEventListener('drop',async e=>{const g=dropTarget(e);if(!g)return;e.preventDefault();const list=dragIds.filter(id=>isPortrait(photo(id))&&!busy(photo(id))),pid=g.dataset.dropPerson,i=personIndex(pid);dragIds=null;g.classList.remove('drop');if(!list.length)return;try{await api(`/orders/${state.order.id}/move`,json('POST',{photo_ids:list,person_id:pid}));list.forEach(id=>state.selected.delete(id));await refreshOrder();toast(`${personName(state.order.persons[i],i)}: добавлено ${list.length}`);}catch(error){toast(error.message);}});

  function toGeneral(list){
    list=list.filter(id=>isPortrait(photo(id))&&!busy(photo(id)));
    if(!list.length){toast('Выберите обработанные портреты');return;}
    const generals=(state.order.shoots||[]).filter(s=>s.kind==='general');
    $('#action-content').innerHTML=`<form id="to-general-form"><div class="dialog-heading"><h2>Перенести в общую съёмку?</h2><button type="button" class="close" data-close="action-dialog" aria-label="Закрыть">×</button></div><p class="muted">Выбрано снимков: ${list.length}. Они уйдут из групп персон, а в общей съёмке их заново проанализируют для подбора в макет.</p><label>Куда<select name="target">${generals.map(s=>`<option value="${s.id}">${esc(s.title)}</option>`).join('')}<option value="new">＋ Новая общая съёмка</option></select></label><p class="error" role="alert"></p><div class="dialog-actions"><button type="button" class="secondary" data-close="action-dialog">Отмена</button><button type="submit" class="primary">Перенести</button></div></form>`;
    const form=$('#to-general-form');
    form.onsubmit=async e=>{e.preventDefault();const b=form.querySelector('[type=submit]'),orderId=state.order.id;b.disabled=true;try{let id=form.elements.target.value;if(id==='new')id=(await api(`/orders/${orderId}/shoots`,json('POST',{kind:'general',title:'Общая съёмка'}))).id;await api(`/orders/${orderId}/shoots/${id}/move-photos`,json('POST',{photo_ids:list}));$('#action-dialog').close();$('#person-dialog').close();list.forEach(x=>state.selected.delete(x));await refreshOrder();toast(`Перенесено в общую съёмку: ${list.length}`);}catch(error){form.querySelector('.error').textContent=error.message;b.disabled=false;}};
    if(!$('#action-dialog').open)$('#action-dialog').showModal();
  }

  /* Page-wide drop, folders included. Without an open shoot the dialog asks where to put the photos. */
  const imageName=f=>!/^\./.test(f.name)&&(/\.(jpe?g|png)$/i.test(f.name)||['image/jpeg','image/png'].includes(f.type));
  const byName=new Intl.Collator('ru',{numeric:true});
  function onlyImages(files){const images=files.filter(imageName).sort((a,b)=>byName.compare(a.webkitRelativePath||a.name,b.webkitRelativePath||b.name));if(files.length>images.length)toast(`Пропущено файлов не JPG/PNG: ${files.length-images.length}`);return images;}
  async function filesFrom(dt){
    const entries=[...(dt.items||[])].map(i=>i.kind==='file'&&i.webkitGetAsEntry?.()).filter(Boolean);
    if(!entries.length)return [...dt.files];
    const out=[],walk=async entry=>{if(entry.isFile){out.push(await new Promise((ok,fail)=>entry.file(ok,fail)));return;}const reader=entry.createReader();for(;;){const batch=await new Promise((ok,fail)=>reader.readEntries(ok,fail));if(!batch.length)break;for(const child of batch)await walk(child);}};
    for(const entry of entries)await walk(entry);
    return out;
  }
  // Thumbnails dragged inside the page also report Files; only drags from outside upload.
  let internalDrag=false;
  document.addEventListener('dragstart',()=>{internalDrag=true;},true);
  document.addEventListener('dragend',()=>{internalDrag=false;},true);
  const fileDrag=e=>!internalDrag&&[...(e.dataTransfer?.types||[])].includes('Files');
  const canDrop=()=>!!state.order&&location.hash.startsWith('#order/')&&!document.querySelector('dialog[open]');
  function overlay(show){let el=$('#drop-overlay');if(!el){el=document.createElement('div');el.id='drop-overlay';el.className='drop-overlay';document.body.append(el);}const shoot=state.view==='photos'&&(state.shootId==='teachers'?{title:'Учителя'}:state.order?.shoots?.find(s=>s.id===state.shootId));el.innerHTML=`<div>${svgIcon('upload',40)}<strong>${shoot?`Загрузить в «${esc(shoot.title)}»`:'Отпустите, чтобы загрузить'}</strong><small>${shoot?'Файлы и папки целиком · JPG, PNG':'Затем выберите съёмку'}</small></div>`;el.classList.toggle('show',show);}
  document.addEventListener('dragenter',e=>{if(e.target.closest?.('[data-retouch-drop]'))return;if(!fileDrag(e)||!canDrop())return;dropDepth++;overlay(true);});
  document.addEventListener('dragleave',e=>{if(!fileDrag(e)||!dropDepth)return;if(!--dropDepth)overlay(false);});
  document.addEventListener('dragover',e=>{if(!fileDrag(e))return;e.preventDefault();e.dataTransfer.dropEffect=canDrop()||e.target.closest?.('.shoot-drop')?'copy':'none';});
  document.addEventListener('drop',async e=>{
    if(!fileDrag(e))return;e.preventDefault();dropDepth=0;overlay(false);if(!canDrop())return;
    const files=onlyImages(await filesFrom(e.dataTransfer));if(!files.length)return;
    if(state.view==='photos'&&(state.shootId==='teachers'||state.order.shoots?.some(s=>s.id===state.shootId)))uploadFiles(files);else openShootDialog(files);
  });

  /* Upload progress that follows the photographer across pages. */
  function renderPill(){
    let el=$('#upload-pill');if(!el){el=document.createElement('a');el.id='upload-pill';el.className='upload-pill';document.body.append(el);}
    const p=state.progress,inPlace=$('#upload-status')&&state.order?.id===p?.orderId;
    clearTimeout(pillTimer);
    if(!p||inPlace||!state.uploading&&Date.now()-(p.finishedAt||0)>6000){el.hidden=true;return;}
    el.hidden=false;el.href=`#order/${p.orderId}/photos`;
    const mode=state.uploading?'busy':'done';
    if(el.dataset.mode!==mode){el.dataset.mode=mode;el.innerHTML=`<span class="pill-icon ${mode}">${mode==='busy'?'<svg class="pill-spin" viewBox="0 0 34 34" aria-hidden="true"><circle cx="17" cy="17" r="15.5"/></svg>':''}${svgIcon(mode==='busy'?'upload':'check',18)}</span><span><strong></strong><progress></progress><small hidden></small></span>`;}
    el.querySelector('strong').textContent=state.uploading?`Загружаем ${p.done} из ${p.total}`:`Загружено ${p.done-p.duplicates-p.errors.length} из ${p.total}`;
    const bar=el.querySelector('progress');bar.max=p.total;bar.value=p.done;
    const err=el.querySelector('small');err.hidden=!p.errors.length;err.textContent=p.errors.length?`Ошибок: ${p.errors.length}`:'';
    if(!state.uploading)pillTimer=setTimeout(renderPill,6100);
  }
  window.addEventListener('hashchange',()=>setTimeout(renderPill));

  /* Shoot date from EXIF DateTimeOriginal of the first photos. */
  async function exifDate(file){
    try{
      const v=new DataView(await file.slice(0,262144).arrayBuffer());if(v.getUint16(0)!==0xFFD8)return null;
      for(let o=2;o+10<v.byteLength;){const marker=v.getUint16(o),len=v.getUint16(o+2);if((marker&0xFF00)!==0xFF00)return null;if(marker===0xFFE1&&v.getUint32(o+4)===0x45786966)return tiffDate(v,o+10);o+=2+len;}
    }catch{}
    return null;
  }
  function tiffDate(v,start){
    const le=v.getUint16(start)===0x4949,u16=p=>v.getUint16(p,le),u32=p=>v.getUint32(p,le);
    const ifd=off=>{const at=start+off,tags={};for(let i=0,n=u16(at);i<n;i++){const e=at+2+i*12;tags[u16(e)]={count:u32(e+4),at:e+8};}return tags;};
    const text=t=>{if(!t)return '';const at=t.count>4?start+u32(t.at):t.at;let s='';for(let i=0;i<t.count-1;i++)s+=String.fromCharCode(v.getUint8(at+i));return s;};
    const root=ifd(u32(start+4)),exif=root[0x8769]?ifd(u32(root[0x8769].at)):{};
    const m=/^(\d{4}):(\d{2}):(\d{2})/.exec(text(exif[0x9003])||text(exif[0x9004])||text(root[0x0132]));
    return m&&m[1]!=='0000'?`${m[1]}-${m[2]}-${m[3]}`:null;
  }
  async function guessDate(files){for(const f of files.slice(0,5)){const d=await exifDate(f);if(d)return d;}return null;}

  $('#person-dialog')?.addEventListener('close',()=>{state.selected.clear();anchor=null;changed();});
  return {changed,selectAll,rangeBetween,reviewBoard,onlyImages,filesFrom,guessDate,exifDate,renderPill};
})();
