/* Order tab «Макет»: generation and a proofing summary. Editing lives in proof-editor.html. */
const layoutUI={orderId:null,data:null,loading:false,error:null};
const editorUrl=(id,owner)=>`/static/proof-editor.html?order=${encodeURIComponent(id)}${owner?`&owner=${encodeURIComponent(owner)}`:''}`;
async function loadLayout(){
  const id=state.order?.id;if(!id)return;
  if(layoutUI.orderId!==id){layoutUI.orderId=id;layoutUI.data=null;}
  layoutUI.error=null;layoutUI.loading=true;renderLayout();
  try{const data=await api(`/orders/${id}/layout`);if(layoutUI.orderId===id)layoutUI.data=data;}
  catch(error){if(layoutUI.orderId===id){if(error.message==='Макет ещё не создан')layoutUI.data=null;else layoutUI.error=error.message;}}
  if(layoutUI.orderId===id&&state.order?.id===id&&state.view==='layout'){layoutUI.loading=false;renderLayout();}
}
function spreadRange(variants){const lengths=variants.map(v=>v.sequence.length),min=Math.min(...lengths),max=Math.max(...lengths);return min===max?`${count(min,'разворот','разворота','разворотов')} в каждом`:`от ${min} до ${max} разворотов`;}
function layoutSummary(data){
  const doc=data.document,variants=doc.variants||[],status=data.status||{},reviews=status.reviews||{};
  const errors=(doc.issues||[]).filter(i=>i.level==='error').length,warnings=(doc.issues||[]).length-errors;
  const done=variants.filter(v=>reviews[v.owner]?.current).length,publication=status.publication;
  const publishState=!publication?'Не опубликован':publication.current?'Опубликован':`Есть неопубликованные правки (${publication.changed.length})`;
  const next=variants.find(v=>!reviews[v.owner]?.current)?.owner;
  return `<div class="layout-summary">
    <div class="layout-summary-head"><div><span class="status-badge ${errors?'attention':done===variants.length?'ready':'neutral'}">${errors?'Есть ошибки':done===variants.length?'Проверен':'Идёт проверка'}</span><h2>Макет альбома</h2><p class="muted">${count(variants.length,'вариант','варианта','вариантов')} · ${spreadRange(variants)}</p></div>
      <a class="primary" href="${editorUrl(state.order.id,next)}">${done?'Продолжить проверку →':'Открыть редактор макета →'}</a></div>
    <div class="layout-stats">
      <div><strong>${done} / ${variants.length}</strong><span>проверено</span><progress max="${variants.length||1}" value="${done}"></progress></div>
      <div><strong class="${errors?'error':''}">${errors}</strong><span>${errors?'ошибок блокируют публикацию':'ошибок нет'}</span></div>
      <div><strong>${warnings}</strong><span>предупреждений</span></div>
      <div><strong>${publishState}</strong><span>${publication?'Класс видит опубликованную редакцию':'Класс пока не видит макет'}</span></div>
    </div>
    <p class="muted small">В редакторе можно пролистать альбом каждого человека, заменить фото, поправить кадр и подписи, отметить вариант проверенным и опубликовать редакцию классу.</p>
    <div class="layout-summary-actions"><button class="secondary" data-layout="generate" title="Подставить новые фото и подписи из заказа">Обновить из данных заказа</button><p id="layout-error" class="error" role="alert"></p></div>
  </div>`;
}
function renderLayout(){
  const el=$('#workspace');if(!el||state.view!=='layout')return;
  if(layoutUI.orderId!==state.order?.id||layoutUI.loading){el.innerHTML='<div class="future-state"><h2>Открываем макет…</h2></div>';return;}
  if(layoutUI.error){el.innerHTML=`<div class="future-state"><h2>Не удалось открыть макет</h2><p>${esc(layoutUI.error)}</p><button class="secondary" data-layout="reload">Повторить</button></div>`;return;}
  const data=layoutUI.data;
  if(!data){const portraits=state.order.photos.filter(p=>p.shoot_type==='portrait'&&p.status==='ready'&&p.person_id).length;el.innerHTML=`<div class="future-state"><span class="status-badge neutral">Шаг 03</span><h2>Создать макет</h2><p>Генератор соберёт альбом каждого ученика из комплектации заказа, портретов и анкет. Проверка и правки — в редакторе макета.</p><p class="muted small">Готово портретов: ${portraits}.</p><button class="primary" data-layout="generate">Создать макет</button><p id="layout-error" class="error" role="alert"></p></div>`;return;}
  el.innerHTML=layoutSummary(data);
}
document.addEventListener('click',async event=>{
  if(state.view!=='layout')return;
  const item=event.target.closest('[data-layout]');if(!item)return;
  const action=item.dataset.layout;
  if(action==='reload'){layoutUI.error=null;await loadLayout();}
  if(action==='generate'){
    item.disabled=true;
    try{layoutUI.data=await api(`/orders/${state.order.id}/layout`,json('POST',{}));layoutUI.error=null;await refreshOrder();state.orders=state.orders.map(o=>o.id===state.order.id?{...o,stage:'layout'}:o);nav();renderLayout();toast('Макет собран');}
    catch(error){const place=$('#layout-error');if(place)place.textContent=error.message;else toast(error.message);}
    finally{item.disabled=false;}
  }
});
