/* Photo selection, the floating action bar, review by person, the large viewer and page-wide upload.
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
  let anchor=null,hovered=null,lasso=null,dragIds=null,dropDepth=0,pillTimer=null,viewer={ids:[],index:0};
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
    const id=box.dataset.photo;
    if(e.shiftKey&&anchor&&anchor!==id&&ids().includes(anchor)){e.preventDefault();select(rangeBetween(ids(),anchor,id),state.selected.has(anchor));anchor=id;return;}
    anchor=id;
  },true);
  document.addEventListener('mouseover',e=>{hovered=e.target.closest?.('.photo-tile')?.querySelector('input[data-photo]')?.dataset.photo||null;});

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
    lasso.frame=requestAnimationFrame(()=>{if(!lasso)return;const next=new Set(lasso.base);for(const box of boxes()){const t=box.closest('.photo-tile').getBoundingClientRect();if(t.right>r.left&&t.left<r.right&&t.bottom>r.top&&t.top<r.bottom)next.add(box.dataset.photo);}state.selected=next;changed();});
  });
  const endLasso=e=>{if(!lasso||e.pointerId!==lasso.id)return;lasso.el?.remove();document.body.classList.remove('lassoing');lasso=null;};
  document.addEventListener('pointerup',endLasso);document.addEventListener('pointercancel',endLasso);

  document.addEventListener('keydown',e=>{
    if($('#photo-viewer')?.open){viewerKey(e);return;}
    if(typing(e.target)||[...document.querySelectorAll('dialog[open]')].some(d=>d.id!=='person-dialog'))return;
    if(!boxes().length)return;
    const mod=e.metaKey||e.ctrlKey;
    if(mod&&e.code==='KeyA'){e.preventDefault();select(ids(),true);return;}
    if(e.key==='Escape'&&state.selected.size){e.preventDefault();clear();return;}
    if(mod||e.altKey||e.target.closest?.('button,a'))return;
    if(e.code==='Space'){e.preventDefault();const list=ids();openViewer(list.includes(hovered)?hovered:[...state.selected].find(id=>list.includes(id))||list[0]);return;}
    if((e.key==='Delete'||e.key==='Backspace')&&state.selected.size){e.preventDefault();confirmRemoval('photos');return;}
    if(e.key==='Enter'&&state.selected.size){const b=$('#selection-dock [data-v2="confirm-photos"]');if(b&&!b.disabled){e.preventDefault();b.click();}}
  });

  /* Floating bar: shown only while something is selected; its buttons depend on what is selected. */
  const button=(attrs,icon,label,title,cls='')=>`<button class="dock-btn ${cls}" ${attrs} title="${esc(title)}">${svgIcon(icon,17)}<span>${esc(label)}</span></button>`;
  function actions(){
    const chosen=state.order.photos.filter(p=>state.selected.has(p.id)),one=chosen.length===1;
    const cover=one?button('data-v2="set-cover"','star','На обложку','Сделать обложкой заказа'):'';
    const del=button('data-v2="delete-photos"','trash','Удалить','Удалить выбранные · Delete','danger');
    if(state.view==='photos'&&globalThis.GeneralReview?.isGeneral())return GeneralReview.dockActions(button)+cover+del;
    const portrait=chosen.length&&chosen.every(p=>isPortrait(p)&&!busy(p));
    return (chosen.some(p=>p.uncertain&&canConfirmMatch(p))?`<button class="dock-btn primary-dock" data-v2="confirm-photos"></button>`:'')
      +(portrait?button('data-action="move"','swap','Другой персоне','Назначить другую или новую персону'):'')
      +(portrait?button('data-photo-tools="to-general"','scene','Не портрет','Перенести в общую съёмку'):'')+cover+del;
  }
  function dock(){
    let el=$('#selection-dock');
    if(!el){el=document.createElement('div');el.id='selection-dock';el.className='selection-dock';el.setAttribute('role','toolbar');el.setAttribute('aria-label','Действия с выбранными фото');}
    const host=$('#person-dialog')?.open?$('#person-dialog'):document.body;
    if(el.parentElement!==host)host.append(el);
    el.classList.toggle('in-dialog',host!==document.body);
    const n=state.selected.size;
    document.body.classList.toggle('has-dock',!!n&&host===document.body);
    if(!n||!state.order){el.hidden=true;el.innerHTML='';return;}
    const list=ids(),all=list.every(id=>state.selected.has(id));
    el.hidden=false;
    el.innerHTML=`<button class="dock-icon" data-photo-tools="clear" title="Снять выделение · Esc" aria-label="Снять выделение">${svgIcon('x',18)}</button><span class="dock-count">Выбрано ${n}</span>${all||!list.length?'':`<button class="dock-link" data-photo-tools="select-all">Выбрать все ${list.length}</button>`}<span class="dock-sep"></span>${actions()}`;
    syncConfirmation();
  }

  /* Review: suggested matches grouped by person next to a confirmed reference, then unrecognised frames, then errors. */
  function reviewTile(p,kind){
    const quick=kind==='match'?`<button type="button" class="quick ok" data-review="ok" data-id="${p.id}" title="Верно" aria-label="Верно">${svgIcon('ok',18)}</button><button type="button" class="quick no" data-review="wrong" data-id="${p.id}" title="Не он — выбрать персону" aria-label="Другая персона">${svgIcon('x',18)}</button>`
      :kind==='unknown'?`<button type="button" class="quick" data-review="assign" data-id="${p.id}" title="Кто это? Выбрать персону" aria-label="Выбрать персону">${svgIcon('user',17)}</button><button type="button" class="quick" data-review="general" data-id="${p.id}" title="Не портрет — в общую съёмку" aria-label="Перенести в общую съёмку">${svgIcon('scene',17)}</button>`:'';
    const note=kind==='unknown'?(p.status==='ready'?'Персона не определена':statuses[p.status]||'Проверить'):kind==='error'?p.error||statuses.error:'';
    // The checkbox goes first: a label activates its first labelable descendant, and buttons are labelable too.
    return `<label class="photo-tile review-tile" ${kind==='error'?'':'draggable="true"'}><input type="checkbox" data-photo="${p.id}" aria-label="Выбрать ${esc(p.filename)}" ${state.selected.has(p.id)?'checked':''}><span class="tile-media"><img src="/media/${p.id}/thumb" alt="${esc(p.filename)}" loading="lazy" decoding="async" draggable="false"><span class="tile-quick">${quick}</span></span><button type="button" class="quick-view" data-review="view" data-id="${p.id}" title="Открыть крупно · Пробел" aria-label="Открыть крупно">${svgIcon('eye',15)}</button><p title="${esc(p.filename)}">${esc(p.filename)}</p>${note?`<small>${esc(note)}</small>`:''}</label>`;
  }
  function reviewGroup(g){
    const o=state.order,i=personIndex(g.id),name=personName(o.persons[i],i);
    const confirmed=o.photos.filter(p=>p.person_id===g.id&&p.status==='ready'&&!p.uncertain);
    const ref=confirmed[0]||o.photos.find(p=>p.person_id===g.id&&p.status==='ready'&&!g.photos.includes(p));
    const note=confirmed.length?`Подтверждено ${confirmed.length} · сравните с эталоном`:ref?'Эталон тоже не подтверждён':'Других снимков нет — возможно, новый человек';
    return `<article class="review-group" data-drop-person="${g.id}"><header class="review-head"><div><strong>${esc(name)}</strong><small>${note}</small></div><button class="text-button" data-review="select-group" data-pid="${g.id}">Выбрать группу</button><button class="primary review-ok" data-review="confirm-group" data-pid="${g.id}">${svgIcon('ok',16)}${ref?'Всё верно':'Оставить отдельно'} · ${g.photos.length}</button></header><div class="photo-grid review-cands">${ref?`<div class="ref-tile"><img src="/media/${ref.id}/thumb" alt="Эталон: ${esc(name)}" loading="lazy" draggable="false"><span class="ref-label">Эталон</span><p>${esc(name)}</p></div>`:`<div class="ref-tile ref-empty">${svgIcon('user',34)}<p>Нет эталона</p></div>`}${g.photos.map(p=>reviewTile(p,'match')).join('')}</div></article>`;
  }
  function reviewBoard(photos){
    const o=state.order,matches=photos.filter(p=>p.status==='ready'&&p.person_id&&personIndex(p.person_id)>=0),errors=photos.filter(p=>p.status==='error'),unknown=photos.filter(p=>!matches.includes(p)&&!errors.includes(p));
    const groups=[...new Set(matches.map(p=>p.person_id))].sort((a,b)=>personIndex(a)-personIndex(b)).map(id=>({id,photos:matches.filter(p=>p.person_id===id)}));
    if(!photos.length)return `<div class="empty-state review-done">${svgIcon('check',40)}<h3>Всё проверено</h3><p>Все портреты распределены по персонам.</p>${o.stage==='photos'?'<button class="primary" data-v2="send-forms">Отправить на анкеты</button>':''}</div>`;
    return `<div class="review-board">${groups.length?`<section class="review-section"><header><h3>Проверьте совпадения <span>${matches.length}</span></h3><p>Слева эталон персоны. Нажмите «Всё верно» для группы или ✕ на лишнем снимке. Снимки можно перетащить в другую группу.</p></header><div class="review-groups">${groups.map(reviewGroup).join('')}</div></section>`:''}${unknown.length?`<section class="review-section"><header><h3>Не распознано <span>${unknown.length}</span></h3><p>Лицо не найдено, несколько лиц или персона не определена. Назначьте человека, перенесите в общую съёмку или удалите.</p></header><div class="photo-grid">${unknown.map(p=>reviewTile(p,'unknown')).join('')}</div></section>`:''}${errors.length?`<section class="review-section"><header><h3>Ошибки обработки <span>${errors.length}</span></h3><button class="secondary with-icon" data-action="retry">${svgIcon('retry',15)}Повторить обработку</button></header><div class="photo-grid">${errors.map(p=>reviewTile(p,'error')).join('')}</div></section>`:''}</div>`;
  }
  async function confirm(photos,message){
    photos=photos.filter(p=>p.status==='ready'&&p.person_id);if(!photos.length)return;
    await api(`/orders/${state.order.id}/confirm-photos`,json('POST',{photo_ids:photos.map(p=>p.id),expected_persons:Object.fromEntries(photos.map(p=>[p.id,p.person_id]))}));
    photos.forEach(p=>state.selected.delete(p.id));await refreshOrder();if(message)toast(message);
  }
  function only(id,then){state.selected=new Set([id]);changed();then();}
  document.addEventListener('click',async e=>{
    const t=e.target.closest('[data-review],[data-photo-tools]');if(!t)return;
    e.preventDefault();
    const action=t.dataset.review||t.dataset.photoTools,pid=t.dataset.pid,group=()=>state.order.photos.filter(p=>p.person_id===pid&&needsReview(p));
    try{
      if(action==='clear')clear();
      if(action==='select-all')selectAll();
      if(action==='to-general')toGeneral([...state.selected]);
      if(action==='view')openViewer(t.dataset.id);
      if(action==='select-group'){const list=group().map(p=>p.id),all=list.every(id=>state.selected.has(id));select(list,!all);}
      if(action==='confirm-group'){t.disabled=true;const i=personIndex(pid);await confirm(group(),`${personName(state.order.persons[i],i)}: подтверждено ${group().length}`);}
      if(action==='ok'){t.disabled=true;await confirm([photo(t.dataset.id)].filter(Boolean));}
      if(action==='wrong'||action==='assign')only(t.dataset.id,openMove);
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

  /* Large viewer: the photo next to the person's reference, with the same actions as the bar. */
  function viewerDialog(){let d=$('#photo-viewer');if(!d){d=document.createElement('dialog');d.id='photo-viewer';d.className='photo-viewer';d.setAttribute('aria-label','Просмотр фотографии');document.body.append(d);d.addEventListener('click',viewerClick);}return d;}
  function openViewer(id){const list=ids();if(!list.length)return;viewer={ids:list,index:Math.max(0,list.indexOf(id))};drawViewer();const d=viewerDialog();if(!d.open)d.showModal();}
  function drawViewer(){
    const d=viewerDialog(),id=viewer.ids[viewer.index],p=photo(id);
    if(!p){if(d.open)d.close();return;}
    const i=p.person_id?personIndex(p.person_id):-1,name=i>=0?personName(state.order.persons[i],i):'',ref=i>=0&&isPortrait(p)?matchReference(p):null,sel=state.selected.has(id),can=p.uncertain&&canConfirmMatch(p);
    d.innerHTML=`<div class="viewer-top"><span>${viewer.index+1} из ${viewer.ids.length} · ${esc(p.filename)}${name?` · ${esc(name)}`:''}</span><button class="viewer-close" data-viewer="close" aria-label="Закрыть · Esc">${svgIcon('x',20)}</button></div><div class="viewer-stage"><figure><img src="/media/${p.id}/full" alt="${esc(p.filename)}" style="background-image:url('/media/${p.id}/thumb')"><figcaption>${p.status!=='ready'?esc(statuses[p.status]||''):p.uncertain?`Предположительно: ${esc(name)}`:name?esc(name):''}</figcaption></figure>${ref?`<figure class="viewer-ref"><img src="/media/${ref.id}/full" alt="Эталон: ${esc(name)}" style="background-image:url('/media/${ref.id}/thumb')"><figcaption>Эталон: ${esc(name)}</figcaption></figure>`:''}</div><button class="viewer-nav prev" data-viewer="prev" aria-label="Предыдущее фото" ${viewer.index?'':'disabled'}>${svgIcon('left',28)}</button><button class="viewer-nav next" data-viewer="next" aria-label="Следующее фото" ${viewer.index<viewer.ids.length-1?'':'disabled'}>${svgIcon('right',28)}</button><div class="viewer-bar"><button class="dock-btn ${sel?'on':''}" data-viewer="toggle">${svgIcon('selectAll',17)}<span>${sel?'Выбрано':'Выбрать'}</span><kbd>X</kbd></button>${can?`<button class="dock-btn primary-dock" data-viewer="ok">${svgIcon('ok',17)}<span>Верно: ${esc(name)}</span><kbd>Enter</kbd></button>`:''}${isPortrait(p)&&!busy(p)?`<button class="dock-btn" data-viewer="move">${svgIcon('swap',17)}<span>Другой персоне</span><kbd>P</kbd></button>`:''}<button class="dock-btn danger" data-viewer="delete">${svgIcon('trash',17)}<span>Удалить</span><kbd>Del</kbd></button></div>`;
  }
  async function viewerAction(action){
    const d=viewerDialog(),id=viewer.ids[viewer.index];
    if(action==='close')d.close();
    if(action==='prev'&&viewer.index>0){viewer.index--;drawViewer();}
    if(action==='next'&&viewer.index<viewer.ids.length-1){viewer.index++;drawViewer();}
    if(action==='toggle'){select([id],!state.selected.has(id));drawViewer();}
    if(action==='move'){d.close();only(id,openMove);}
    if(action==='delete'){d.close();only(id,()=>confirmRemoval('photos'));}
    if(action==='ok'){const p=photo(id);if(!(p?.uncertain&&canConfirmMatch(p)))return;try{await confirm([p]);}catch(error){toast(error.message);return;}const list=ids();if(!list.length){d.close();return;}viewer={ids:list,index:Math.min(list.includes(id)?list.indexOf(id)+1:viewer.index,list.length-1)};drawViewer();}
  }
  function viewerClick(e){const t=e.target.closest('[data-viewer]');if(t)viewerAction(t.dataset.viewer);}
  function viewerKey(e){
    const map={ArrowLeft:'prev',ArrowRight:'next',Space:'close',KeyX:'toggle',Enter:'ok',KeyP:'move',Delete:'delete',Backspace:'delete'},action=map[e.code]||map[e.key];
    if(!action||e.metaKey||e.ctrlKey||e.altKey)return;
    e.preventDefault();viewerAction(action);
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
  function overlay(show){let el=$('#drop-overlay');if(!el){el=document.createElement('div');el.id='drop-overlay';el.className='drop-overlay';document.body.append(el);}const shoot=state.view==='photos'&&state.order?.shoots?.find(s=>s.id===state.shootId);el.innerHTML=`<div>${svgIcon('upload',40)}<strong>${shoot?`Загрузить в «${esc(shoot.title)}»`:'Отпустите, чтобы загрузить'}</strong><small>${shoot?'Файлы и папки целиком · JPG, PNG':'Затем выберите съёмку'}</small></div>`;el.classList.toggle('show',show);}
  document.addEventListener('dragenter',e=>{if(!fileDrag(e)||!canDrop())return;dropDepth++;overlay(true);});
  document.addEventListener('dragleave',e=>{if(!fileDrag(e)||!dropDepth)return;if(!--dropDepth)overlay(false);});
  document.addEventListener('dragover',e=>{if(!fileDrag(e))return;e.preventDefault();e.dataTransfer.dropEffect=canDrop()?'copy':'none';});
  document.addEventListener('drop',async e=>{
    if(!fileDrag(e))return;e.preventDefault();dropDepth=0;overlay(false);if(!canDrop())return;
    const files=onlyImages(await filesFrom(e.dataTransfer));if(!files.length)return;
    if(state.view==='photos'&&state.order.shoots?.some(s=>s.id===state.shootId))uploadFiles(files);else openShootDialog(files);
  });

  /* Upload progress that follows the photographer across pages. */
  function renderPill(){
    let el=$('#upload-pill');if(!el){el=document.createElement('a');el.id='upload-pill';el.className='upload-pill';document.body.append(el);}
    const p=state.progress,inPlace=$('#upload-status')&&state.order?.id===p?.orderId;
    clearTimeout(pillTimer);
    if(!p||inPlace||!state.uploading&&Date.now()-(p.finishedAt||0)>6000){el.hidden=true;return;}
    el.hidden=false;el.href=`#order/${p.orderId}/photos`;
    el.innerHTML=`<span class="pill-icon ${state.uploading?'busy':''}">${svgIcon(state.uploading?'upload':'check',18)}</span><span><strong>${state.uploading?`Загружаем ${p.done} из ${p.total}`:`Загружено ${p.done-p.duplicates-p.errors.length} из ${p.total}`}</strong><progress max="${p.total}" value="${p.done}"></progress>${p.errors.length?`<small>Ошибок: ${p.errors.length}</small>`:''}</span>`;
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
  return {changed,selectAll,rangeBetween,reviewBoard,onlyImages,guessDate,exifDate,renderPill,openViewer};
})();
