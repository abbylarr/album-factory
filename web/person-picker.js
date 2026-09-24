// Shared photo-based selector in both interfaces. Suggestions never submit a move.
let pickerGeneration=0;
function showPersonPicker({order,selected,api,esc,personName}){
  const generation=++pickerGeneration;
  const root=document.querySelector('#person-picker'),form=document.querySelector('#move-form');
  const submit=form.querySelector('[type=submit]');submit.disabled=true;submit.textContent='Назначить персону';
  const chosen=order.photos.filter(p=>selected.includes(p.id));
  let target=null,query='',hints=new Map();
  const cards=order.persons.map((person,i)=>{
    const photos=order.photos.filter(p=>p.person_id===person.id);
    const cover=photos.find(p=>!p.uncertain&&!selected.includes(p.id))||photos.find(p=>!selected.includes(p.id))||photos[0];
    return {id:person.id,name:personName(person,i),count:photos.length,cover};
  });
  root.innerHTML=`<p class="muted small picker-instruction">Выбрано: ${chosen.length}. Найдите человека по фотографии и подтвердите назначение.</p><div class="picker-selected">${chosen.slice(0,8).map(p=>`<img src="/media/${p.id}/thumb" alt="${esc(p.filename)}" title="${esc(p.filename)}">`).join('')}${chosen.length>8?`<span>+${chosen.length-8}</span>`:''}</div><p id="picker-help" class="muted small" role="status">Подбираем подсказки по лицу и соседним кадрам…</p><label class="picker-search-label">Поиск по имени<input type="search" id="picker-search" placeholder="Имя или номер персоны" autocomplete="off"></label><fieldset class="picker-fieldset"><legend>Кому назначить фотографии</legend><div id="picker-cards" class="picker-cards"></div></fieldset><p class="muted small">Подсказка не гарантирует совпадение. Сходство — оценка модели, не процент вероятности.</p>`;
  function draw(){
    const shown=cards.filter(p=>p.name.toLocaleLowerCase().includes(query.toLocaleLowerCase())).sort((a,b)=>(hints.get(b.id)?.priority||0)-(hints.get(a.id)?.priority||0));
    submit.disabled=target===null||(target!==''&&!shown.some(p=>p.id===target));
    document.querySelector('#picker-cards').innerHTML=shown.map(p=>{
      const hint=hints.get(p.id);
      return `<label class="picker-card"><input type="radio" name="target" value="${p.id}" required ${target===p.id?'checked':''}><span class="picker-portrait">${p.cover?`<img src="/media/${p.cover.id}/thumb" alt="${esc(p.name)}" loading="lazy">`:'<span>Нет фото</span>'}</span><strong>${esc(p.name)}</strong><span class="picker-count">${p.count} фото</span>${hint?`<span class="picker-hint">${esc(hint.label)}</span>`:''}</label>`;
    }).join('')+`<label class="picker-card picker-new"><input type="radio" name="target" value="" required ${target===''?'checked':''}><span class="picker-portrait">＋</span><strong>Новая персона</strong><span class="picker-count">Создать отдельную группу</span></label>`;
  }
  document.querySelector('#picker-search').oninput=e=>{query=e.target.value;draw();};
  root.onchange=e=>{if(e.target.name==='target'){target=e.target.value;submit.disabled=false;}};
  draw();
  api(`/orders/${order.id}/person-suggestions`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({photo_ids:selected})}).then(result=>{
    if(generation!==pickerGeneration)return;
    for(const photo of result.photos){
      for(const c of photo.candidates){
        if(c.similarity!==null&&c.similarity<.35&&c.reason==='face')continue;
        const priority=c.reason==='face_and_neighbors'?3:c.reason==='neighbors'?1:2;
        const label=c.reason==='face_and_neighbors'?'Лицо и соседние кадры':c.reason==='neighbors'?'По соседним кадрам':`Сходство лица: ${c.similarity.toFixed(2)}`;
        const previous=hints.get(c.person_id);
        if(!previous||priority>previous.priority)hints.set(c.person_id,{priority,label});
      }
    }
    const noVector=result.photos.filter(p=>!p.has_embedding).length;
    document.querySelector('#picker-help').textContent=(hints.size?'Подходящие варианты показаны первыми. ':'Уверенных подсказок нет — выберите по фотографии. ')+(chosen.length>1?'Подсказки могут относиться к разным выбранным снимкам. ':'')+(noVector?`Для ${noVector} снимков нет вектора лица; оценки сходства для них нет.`:'');
    draw();
  }).catch(()=>{if(generation===pickerGeneration)document.querySelector('#picker-help').textContent='Подсказки недоступны. Можно выбрать человека по фотографии.';});
}
