const layoutUI={orderId:null,data:null,owner:null,spread:0,element:null,panel:null,photoTab:'general',loading:false,saving:false,error:null};
const layoutSections={cover:'Обложка',intro:'Наш выпуск',personal:'Портрет',teachers:'Наши учителя',students:'Наш класс',moments:'Вместе',story:'В деталях',final:'Финал',custom:'Новый разворот'};
const layoutPhotoTabs=[['general','Общие'],['group','Групповые'],['pair','Парные'],['report','Репортажные'],['portrait','Персональные']];
const layoutPageTemplates=[['blank','Пустая'],['full','Во всю страницу'],['editorial','Фото и подпись'],['diptych','Два фото'],['grid','Сетка 2×2']];
async function loadLayout(){
  const id=state.order?.id;if(!id)return;
  if(layoutUI.orderId!==id){layoutUI.orderId=id;layoutUI.data=null;layoutUI.owner=null;layoutUI.spread=0;layoutUI.element=null;layoutUI.panel=null;}
  layoutUI.error=null;layoutUI.loading=true;renderLayout();
  try{const data=await api(`/orders/${id}/layout`);if(layoutUI.orderId===id)layoutUI.data=data;}catch(error){if(layoutUI.orderId===id){if(error.message==='Макет ещё не создан')layoutUI.data=null;else layoutUI.error=error.message;}}
  if(layoutUI.orderId===id&&state.order?.id===id&&state.view==='layout'){layoutUI.loading=false;renderLayout();}
}
function layoutSpread(doc,owner,index){
  const variant=doc.variants.find(v=>v.owner===owner)||doc.variants[0];if(!variant)return null;
  const key=variant.sequence[index];return key?.startsWith('cover[')?doc.covers[variant.owner]:doc.shared_spreads[key]||doc.variant_spreads[variant.owner]?.[key];
}
function layoutCanvas(spread,doc,photos,interactive=true){
  const [width,height]=spread.section==='cover'?doc.cover_size_mm:doc.spread_size_mm;
  const markup=spread.elements.filter(e=>!e.hidden).map(e=>{
    const [x,y,w,h]=e.box,box=`left:${x/width*100}%;top:${y/height*100}%;width:${w/width*100}%;height:${h/height*100}%`,selected=interactive&&layoutUI.element===e.key?' selected':'';
    if(e.type==='rect')return `<div class="layout-layer" style="${box};background:${esc(e.fill)}"></div>`;
    const tag=interactive?'button':'div',attribute=interactive?` data-layout-element="${esc(e.key)}"`:'';
    if(e.type==='photo'){
      const meta=photos.find(p=>p.id===e.photo),crop=e.crop;
      const image=meta&&crop?`<img src="/media/${encodeURIComponent(e.photo)}/${interactive?'full':'thumb'}" alt="" style="width:${meta.width/crop[2]*100}%;height:${meta.height/crop[3]*100}%;left:${-crop[0]/crop[2]*100}%;top:${-crop[1]/crop[3]*100}%">`:'';
      const placeholder=interactive?'<img class="layout-add-icon" src="/static/assets/layout-add.svg" alt=""><span class="sr-only">Выбрать фотографию</span>':'';
      return `<${tag} class="layout-layer layout-photo${selected}${image?'':' empty'}"${attribute} style="${box};${e.mask==='ellipse'?'border-radius:50%;':''}" ${interactive?'title="Заменить фотографию" aria-label="Заменить фотографию"':''}>${image||placeholder}</${tag}>`;
    }
    return `<${tag} class="layout-layer layout-text${selected}${e.text?'':' empty'}"${attribute} style="${box};font-size:${e.size/width*100}cqw;color:${esc(e.color)};font-family:${e.font==='display'?'Georgia,serif':'Arial,sans-serif'};text-align:${e.align};">${e.text?esc(e.text).replace(/\n/g,'<br>'):interactive?'Добавить подпись':''}</${tag}>`;
  }).join('');
  return `<div class="layout-canvas" style="aspect-ratio:${width}/${height}">${markup}${interactive&&spread.section!=='cover'?'<img class="layout-divider" src="/static/assets/layout-divider.svg" alt="">':''}</div>`;
}
function layoutElementPerson(data,element){
  const match=element?.key.match(/\[student:([^\]]+)\]/);
  if(match)return match[1];
  const current=data.photos.find(p=>p.id===element?.photo);
  if(current?.person_id)return current.person_id;
  return layoutUI.owner?.startsWith('student:')?layoutUI.owner.slice('student:'.length):null;
}
function layoutVisiblePhotos(data,element){
  if(layoutUI.photoTab==='general')return data.photos.filter(p=>p.shoot_type==='general');
  if(layoutUI.photoTab==='portrait'){
    const personId=layoutElementPerson(data,element);
    if(!personId)return [];
    const orderPhotos=new Map((state.order?.photos||[]).map(p=>[p.id,p]));
    return data.photos.filter(p=>{
      const current=orderPhotos.get(p.id);
      return (current?.shoot_type??p.shoot_type)==='portrait'&&(current?.person_id??p.person_id)===personId;
    });
  }
  return [];
}
function renderLayoutPanel(){
  const el=$('#layout-drawer');if(!el)return;
  if(!layoutUI.panel){el.hidden=true;el.innerHTML='';return;}
  const data=layoutUI.data,spread=layoutSpread(data.document,layoutUI.owner,layoutUI.spread),element=spread?.elements.find(e=>e.key===layoutUI.element);
  if(!element){layoutUI.panel=null;el.hidden=true;return;}
  el.hidden=false;
  if(layoutUI.panel==='photo'){
    const photos=layoutVisiblePhotos(data,element),personId=layoutElementPerson(data,element),person=data.document.variants.find(v=>v.owner==='student:'+personId)?.name;
    el.innerHTML=`<div class="layout-drawer-head"><div><h2>Фотографии</h2><p class="muted small">${layoutUI.photoTab==='portrait'?(person?`Снимки: ${esc(person)}`:'Снимки выбранной персоны'):'Выберите снимок для замены в рамке'}</p></div><div class="layout-drawer-actions"><a href="#order/${state.order.id}/photos" class="secondary">Добавить</a><button data-layout="close-panel" class="layout-close" aria-label="Закрыть выбор фотографий">×</button></div></div>
      <div class="layout-photo-tabs" role="tablist" aria-label="Категории фотографий">${layoutPhotoTabs.map(([key,label])=>`<button role="tab" aria-selected="${layoutUI.photoTab===key}" class="${layoutUI.photoTab===key?'active':''}" data-layout-tab="${key}">${label}</button>`).join('')}</div>
      ${photos.length?`<div class="layout-photo-grid">${photos.map(p=>`<button data-layout-photo="${p.id}" class="${p.id===element.photo?'selected':''}" title="${esc(p.filename)}" aria-label="Поставить ${esc(p.filename)} в рамку"><img src="/media/${p.id}/thumb" alt="" loading="lazy"><span>${esc(p.filename)}</span></button>`).join('')}</div>`:`<div class="layout-photo-empty"><h3>Фотографий пока нет</h3><p>${layoutUI.photoTab==='general'?'Загрузите общую съёмку, затем выберите снимок здесь.':layoutUI.photoTab==='portrait'?(person?`У ${esc(person)} пока нет доступных портретов.`:'Для этой рамки нет доступных портретов.'):'Общие снимки пока не распределяются по этой категории. Все они доступны на вкладке «Общие».'}</p><a href="#order/${state.order.id}/photos" class="secondary">Открыть загрузку</a></div>`}
      <p class="layout-panel-error error" role="alert"></p>`;
  }else{
    el.innerHTML=`<div class="layout-drawer-head"><h2>Текст</h2><button data-layout="close-panel" class="layout-close" aria-label="Закрыть редактор текста">×</button></div><p class="muted small">${esc(element.key)}</p><form id="layout-text-edit"><label>Содержание<textarea name="value" maxlength="300" rows="7">${esc(element.text)}</textarea></label><button class="primary" type="submit">Сохранить текст</button><p class="error" role="alert"></p></form>`;
    $('#layout-text-edit').onsubmit=async event=>{event.preventDefault();const form=event.target,button=form.querySelector('[type=submit]');button.disabled=true;try{layoutUI.data=await api(`/orders/${state.order.id}/layout/element`,json('PUT',{key:element.key,type:'text',value:new FormData(form).get('value'),revision:data.document.revision}));layoutUI.panel=null;renderLayout();toast('Текст сохранён');}catch(error){form.querySelector('.error').textContent=error.message;}finally{button.disabled=false;}};
  }
}
function renderLayout(){
  const el=$('#workspace');if(!el||state.view!=='layout')return;
  if(layoutUI.orderId!==state.order?.id){el.innerHTML='<div class="future-state"><h2>Открываем макет…</h2></div>';return;}
  if(layoutUI.loading){el.innerHTML='<div class="future-state"><h2>Открываем макет…</h2></div>';return;}
  if(layoutUI.error){el.innerHTML=`<div class="future-state"><h2>Не удалось открыть макет</h2><p>${esc(layoutUI.error)}</p><button class="secondary" data-layout="reload">Повторить</button></div>`;return;}
  const data=layoutUI.data;
  if(!data){const portraits=state.order.photos.filter(p=>p.shoot_type==='portrait'&&p.status==='ready'&&p.person_id).length;el.innerHTML=`<div class="future-state"><span class="status-badge neutral">Шаг 03</span><h2>Создать макет</h2><p>Генератор соберёт персональные варианты из портретов и сохранённых подписей. Общие фотографии вы добавите вручную в редакторе.</p><p class="muted small">Для старта нужны портреты минимум трёх персон. Сейчас готово снимков: ${portraits}.</p><button class="primary" data-layout="generate">Создать макет</button><p id="layout-error" class="error" role="alert"></p></div>`;return;}
  document.body.classList.add('layout-mode');
  const doc=data.document,variants=doc.variants;
  if(!variants.some(v=>v.owner===layoutUI.owner)){layoutUI.owner=variants[0]?.owner;layoutUI.spread=0;}
  const variant=variants.find(v=>v.owner===layoutUI.owner),sequence=variant?.sequence||[];
  layoutUI.spread=Math.max(0,Math.min(layoutUI.spread,sequence.length-1));
  const spread=layoutSpread(doc,layoutUI.owner,layoutUI.spread);
  const errors=doc.issues.filter(i=>i.level==='error'),warnings=doc.issues.filter(i=>i.level==='warning'),conflicts=doc.overrides?.conflicts||[];
  const issueCount=errors.length+warnings.length+conflicts.length;
  el.innerHTML=`<div class="layout-toolbar"><div class="layout-toolbar-start"><a class="layout-back" href="#orders" aria-label="Сохранить и выйти">← <span>К заказам</span></a><span class="layout-toolbar-divider" aria-hidden="true"></span><strong>Редактор макета</strong><span class="layout-order-name">${esc(orderName(state.order))}</span></div><div class="layout-toolbar-actions"><label class="layout-variant-control"><span>Вариант</span><select id="layout-variant" aria-label="Вариант альбома">${variants.map(v=>`<option value="${esc(v.owner)}" ${v.owner===layoutUI.owner?'selected':''}>${esc(v.name||'Общий вариант')}</option>`).join('')}</select></label><details class="layout-check"><summary class="${errors.length||conflicts.length?'has-errors':''}" title="Замечания к макету">${issueCount?`● ${issueCount}`:'✓'}<span class="sr-only">Замечания к макету</span></summary><div class="layout-check-popover"><h3>Замечания</h3>${conflicts.map(c=>`<p class="error">Правка ${esc(c.key)} не применена: ${esc(c.reason)}</p>`).join('')}${doc.issues.length?doc.issues.map(i=>`<button data-layout-issue="${esc(i.key)}" class="${i.level==='error'?'error':''}"><strong>${i.level==='error'?'Ошибка':'Предупреждение'}</strong> ${esc(i.message)}</button>`).join(''):'<p class="muted">Замечаний нет.</p>'}</div></details><button class="secondary layout-refresh" data-layout="generate" title="Обновить из данных заказа">Обновить</button>${errors.length?'':`<a class="primary layout-pdf" href="/api/orders/${state.order.id}/layout/pdf/${encodeURIComponent(layoutUI.owner)}" target="_blank" rel="noopener">Открыть PDF ↗</a>`}</div></div>
    <div class="layout-editor"><aside class="layout-spreads" aria-label="Страницы альбома"><div class="layout-spreads-head"><h2>Развороты <span>${sequence.length}</span></h2><button data-layout="add-spread" class="layout-add-spread" title="Добавить разворот после текущего" aria-label="Добавить разворот">＋</button></div><div class="layout-spread-list">${sequence.map((key,index)=>{const thumb=layoutSpread(doc,layoutUI.owner,index);return `<button class="layout-spread-thumb ${index===layoutUI.spread?'active':''}" data-layout-spread="${index}" aria-label="Открыть ${index+1} разворот: ${esc(layoutSections[thumb.section]||thumb.section)}" aria-current="${index===layoutUI.spread?'page':'false'}">${layoutCanvas(thumb,doc,data.photos,false)}<small>${index+1} · ${esc(layoutSections[thumb.section]||thumb.section)}</small></button>`;}).join('')}</div></aside>
    <div class="layout-stage"><div class="layout-preview">${spread?layoutCanvas(spread,doc,data.photos):''}</div><div class="layout-stage-footer"><span>${layoutUI.spread+1} / ${sequence.length} · ${esc(layoutSections[spread?.section]||spread?.section||'')}</span>${spread?.section==='custom'?`<div class="layout-template-controls">${['left','right'].map(side=>`<label>${side==='left'?'Левая':'Правая'}<select data-layout-page-template="${side}" aria-label="Шаблон: ${side==='left'?'левая':'правая'} страница">${layoutPageTemplates.map(([key,name])=>`<option value="${key}" ${spread.page_templates?.[side]===key?'selected':''}>${name}</option>`).join('')}</select></label>`).join('')}<button data-layout="delete-spread" class="layout-remove-spread" title="Удалить разворот" aria-label="Удалить разворот">×</button></div>`:''}<div class="layout-page-nav"><button class="secondary" data-layout="prev" aria-label="Предыдущий разворот" ${layoutUI.spread===0?'disabled':''}>←</button><button class="secondary" data-layout="next" aria-label="Следующий разворот" ${layoutUI.spread===sequence.length-1?'disabled':''}>→</button></div></div></div>
    <aside class="layout-drawer" id="layout-drawer" aria-label="Редактор элемента" hidden></aside></div>`;
  renderLayoutPanel();
  requestAnimationFrame(fitLayoutCanvas);
}
function fitLayoutCanvas(){
  const preview=document.querySelector('.layout-preview'),canvas=preview?.querySelector('.layout-canvas');
  if(!preview||!canvas)return;
  const ratio=Number(canvas.style.aspectRatio.split('/')[0])/Number(canvas.style.aspectRatio.split('/')[1]);
  if(!Number.isFinite(ratio)||ratio<=0)return;
  const width=Math.min(preview.clientWidth,preview.clientHeight*ratio);
  canvas.style.width=`${width}px`;canvas.style.height=`${width/ratio}px`;
}
window.addEventListener('resize',fitLayoutCanvas);
document.addEventListener('click',async event=>{
  const item=event.target.closest('[data-layout],[data-layout-element],[data-layout-issue],[data-layout-spread],[data-layout-tab],[data-layout-photo]');if(!item)return;
  if(item.dataset.layoutElement){layoutUI.element=item.dataset.layoutElement;const spread=layoutSpread(layoutUI.data.document,layoutUI.owner,layoutUI.spread),element=spread.elements.find(e=>e.key===layoutUI.element);layoutUI.panel=element?.type;layoutUI.photoTab=element?.source?.includes('.photo:')||layoutUI.data.photos.find(p=>p.id===element?.photo)?.shoot_type==='portrait'?'portrait':'general';renderLayout();return;}
  if(item.dataset.layoutSpread!==undefined){layoutUI.spread=Number(item.dataset.layoutSpread);layoutUI.element=null;layoutUI.panel=null;renderLayout();return;}
  if(item.dataset.layoutTab){layoutUI.photoTab=item.dataset.layoutTab;renderLayoutPanel();return;}
  if(item.dataset.layoutPhoto){if(layoutUI.saving)return;layoutUI.saving=true;item.disabled=true;try{layoutUI.data=await api(`/orders/${state.order.id}/layout/element`,json('PUT',{key:layoutUI.element,type:'photo',value:item.dataset.layoutPhoto,revision:layoutUI.data.document.revision}));layoutUI.panel=null;renderLayout();toast('Фотография заменена');}catch(error){const message=$('.layout-panel-error');if(message)message.textContent=error.message;item.disabled=false;}finally{layoutUI.saving=false;}return;}
  if(item.dataset.layoutIssue){const key=item.dataset.layoutIssue,doc=layoutUI.data.document,variant=doc.variants.find(v=>v.owner===layoutUI.owner);const index=variant.sequence.findIndex((_,i)=>layoutSpread(doc,layoutUI.owner,i)?.elements.some(e=>e.key===key));if(index>=0){layoutUI.spread=index;layoutUI.element=key;layoutUI.panel=layoutSpread(doc,layoutUI.owner,index).elements.find(e=>e.key===key)?.type;layoutUI.photoTab='general';renderLayout();}return;}
  const action=item.dataset.layout;
  if(action==='close-panel'){layoutUI.panel=null;layoutUI.element=null;renderLayout();}
  if(action==='prev'||action==='next'){layoutUI.spread+=action==='next'?1:-1;layoutUI.element=null;layoutUI.panel=null;renderLayout();}
  if(action==='reload'){layoutUI.error=null;await loadLayout();}
  if(action==='add-spread'){item.disabled=true;try{layoutUI.data=await api(`/orders/${state.order.id}/layout/spreads`,json('POST',{revision:layoutUI.data.document.revision,after_index:layoutUI.spread}));layoutUI.spread=layoutUI.data.document.variants.find(v=>v.owner===layoutUI.owner).sequence.indexOf(layoutUI.data.added_spread);layoutUI.element=null;layoutUI.panel=null;renderLayout();toast('Разворот добавлен');}catch(error){toast(error.message);item.disabled=false;}return;}
  if(action==='delete-spread'){if(!confirm('Удалить этот разворот и все его фотографии и подписи из макета?'))return;const key=layoutUI.data.document.variants.find(v=>v.owner===layoutUI.owner).sequence[layoutUI.spread];item.disabled=true;try{layoutUI.data=await api(`/orders/${state.order.id}/layout/spreads/${encodeURIComponent(key)}`,json('DELETE',{revision:layoutUI.data.document.revision}));layoutUI.spread=Math.max(0,layoutUI.spread-1);layoutUI.element=null;layoutUI.panel=null;renderLayout();toast('Разворот удалён');}catch(error){toast(error.message);item.disabled=false;}return;}
  if(action==='generate'){item.disabled=true;try{layoutUI.data=await api(`/orders/${state.order.id}/layout`,json('POST',{}));layoutUI.error=null;layoutUI.element=null;layoutUI.panel=null;await refreshOrder();state.orders=state.orders.map(o=>o.id===state.order.id?{...o,stage:'layout'}:o);nav();renderLayout();toast('Макет собран');}catch(error){const place=$('#layout-error');if(place)place.textContent=error.message;else toast(error.message);}finally{item.disabled=false;}}
});
document.addEventListener('change',async event=>{
  if(event.target.id==='layout-variant'){layoutUI.owner=event.target.value;layoutUI.spread=0;layoutUI.element=null;layoutUI.panel=null;renderLayout();return;}
  const side=event.target.dataset.layoutPageTemplate;if(!side)return;
  const key=layoutUI.data.document.variants.find(v=>v.owner===layoutUI.owner).sequence[layoutUI.spread];
  event.target.disabled=true;
  try{layoutUI.data=await api(`/orders/${state.order.id}/layout/spreads/${encodeURIComponent(key)}/pages/${side}`,json('PUT',{revision:layoutUI.data.document.revision,template:event.target.value}));layoutUI.element=null;layoutUI.panel=null;renderLayout();}
  catch(error){toast(error.message);renderLayout();}
});
document.addEventListener('keydown',event=>{
  if(state.view!=='layout'||!layoutUI.data)return;
  if(event.key==='Escape'&&layoutUI.panel){layoutUI.panel=null;layoutUI.element=null;renderLayout();return;}
  if(!['ArrowLeft','ArrowRight'].includes(event.key)||event.target.closest('input,textarea,select,[contenteditable]'))return;
  const sequence=layoutUI.data.document.variants.find(v=>v.owner===layoutUI.owner)?.sequence||[];
  const next=layoutUI.spread+(event.key==='ArrowRight'?1:-1);
  if(next<0||next>=sequence.length)return;
  event.preventDefault();layoutUI.spread=next;layoutUI.element=null;layoutUI.panel=null;renderLayout();
});
