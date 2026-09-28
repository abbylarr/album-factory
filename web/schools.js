// School catalogue: the studio's schools, their teachers with portraits, and teachers chosen for an order.
// Uses the shared helpers from v2.js (api, json, esc, toast, count, svgIcon, searchKey, routeVersion).
const SchoolCatalog=(()=>{
  let query='';
  const teacherLabel=n=>count(n,'учитель','учителя','учителей');
  const orderLabel=n=>count(n,'заказ','заказа','заказов');
  const initials=t=>[t.last_name,t.first_name].map(x=>(x||'').charAt(0)).join('').toUpperCase()||'?';
  const portraitUrl=t=>`/api/teachers/${encodeURIComponent(t.id)}/portrait/thumb?v=${encodeURIComponent(t.portrait_version)}`;
  const avatar=t=>t.has_portrait?`<img src="${portraitUrl(t)}" alt="" loading="lazy">`:`<span class="teacher-initials" aria-hidden="true">${esc(initials(t))}</span>`;
  const place=s=>s.city?esc(s.city):'<span class="muted">Город не указан</span>';

  function schoolForm(school){
    $('#action-dialog').classList.remove('wide-dialog');
    $('#action-content').innerHTML=`<form id="school-form"><div class="dialog-heading"><h2>${school?'Изменить школу':'Новая школа'}</h2><button type="button" class="close" data-close="action-dialog" aria-label="Закрыть">×</button></div><label>Полное название<textarea name="name" rows="3" maxlength="300" required placeholder="МБОУ «Средняя общеобразовательная школа № 5»">${esc(school?.name||'')}</textarea></label><label>Город<input name="city" maxlength="100" required placeholder="Казань" value="${esc(school?.city||'')}" autocomplete="address-level2"></label><p class="error" role="alert"></p><button class="primary wide" type="submit">${school?'Сохранить':'Добавить школу'}</button></form>`;
    $('#action-dialog').showModal();
    const form=$('#school-form');form.elements.name.focus();
    form.onsubmit=async e=>{e.preventDefault();const button=form.querySelector('[type=submit]'),values=Object.fromEntries(new FormData(form));button.disabled=true;try{const saved=await api('/schools'+(school?'/'+school.id:''),json(school?'PATCH':'POST',values));$('#action-dialog').close();toast(school?'Школа сохранена':'Школа добавлена');if(school)await schoolPage(school.id);else location.hash='schools/'+saved.id;}catch(error){form.querySelector('.error').textContent=error.message;button.disabled=false;}};
  }

  function drawList(schools){
    const el=$('#school-list');if(!el)return;const q=searchKey(query);
    const rows=schools.filter(s=>!q||searchKey(s.name+' '+s.city).includes(q));
    el.innerHTML=rows.map(s=>`<a class="school-card" href="#schools/${encodeURIComponent(s.id)}"><span class="school-card-icon">${svgIcon('school',20)}</span><span class="school-card-text"><strong>${esc(s.name)}</strong><small>${place(s)}</small></span><span class="school-card-meta">${teacherLabel(s.teacher_count)}<small>${orderLabel(s.order_count)}</small></span></a>`).join('')||`<div class="empty-state"><h3>${schools.length?'Школы не найдены':'Школ пока нет'}</h3><p>${schools.length?'Измените поиск.':'Добавьте школу, затем её учителей. Учителя сохраняются и подходят для всех заказов этой школы.'}</p></div>`;
  }

  async function listPage(){
    const version=routeVersion;
    $('#main').innerHTML=`<div class="page schools-page"><div class="page-heading"><div><h1>Каталог школ</h1><p class="muted">Ваши школы и учителя. Их видит только ваша студия; класс выбирает учителей для своего альбома.</p></div><button class="primary" data-school="new">＋ Добавить школу</button></div><label class="queue-search open school-search-box">${svgIcon('search',16)}<input id="school-query" type="search" aria-label="Поиск школы" placeholder="Название или город" value="${esc(query)}"></label><div id="school-list" class="school-list" aria-live="polite"><p class="muted">Загружаем школы…</p></div></div>`;
    let schools;try{schools=await api('/schools');}catch(error){if(version===routeVersion)$('#school-list').innerHTML=`<p class="error">${esc(error.message)}</p>`;return;}
    if(version!==routeVersion)return;
    drawList(schools);$('#school-query').oninput=e=>{query=e.target.value;drawList(schools);};
  }

  function teacherFields(t={}){
    return `<label>Фамилия<input name="last_name" maxlength="60" required value="${esc(t.last_name||'')}" autocomplete="off"></label><label>Имя<input name="first_name" maxlength="60" value="${esc(t.first_name||'')}" autocomplete="off"></label><label>Отчество<input name="patronymic" maxlength="60" value="${esc(t.patronymic||'')}" autocomplete="off"></label><label>Предмет или должность<input name="subject" maxlength="100" value="${esc(t.subject||'')}" placeholder="Математика" autocomplete="off"></label>`;
  }

  function teacherCard(t){
    return `<article class="teacher-card" data-teacher="${esc(t.id)}"><div class="teacher-photo">${avatar(t)}</div><div class="teacher-text"><strong>${esc(t.name)}</strong><small>${esc(t.subject)||'&nbsp;'}</small></div><div class="teacher-actions"><label class="text-button teacher-upload">${t.has_portrait?'Заменить фото':'Загрузить фото'}<input type="file" accept="image/jpeg,image/png" data-teacher-photo="${esc(t.id)}" hidden></label><button type="button" class="text-button" data-teacher-edit="${esc(t.id)}">Изменить</button><button type="button" class="text-button danger-text" data-teacher-delete="${esc(t.id)}">Удалить</button></div></article>`;
  }

  async function schoolPage(id){
    const version=routeVersion;
    $('#main').innerHTML='<div class="page"><p class="muted">Загружаем школу…</p></div>';
    let school;try{school=await api('/schools/'+encodeURIComponent(id));}catch(error){if(version===routeVersion)$('#main').innerHTML=`<div class="page"><h1>Школа не найдена</h1><p class="error">${esc(error.message)}</p><a class="secondary" href="#schools">К каталогу школ</a></div>`;return;}
    if(version!==routeVersion)return;
    const teachers=school.teachers;
    $('#main').innerHTML=`<div class="page schools-page"><div class="eyebrow"><a href="#schools">Каталог школ</a> / ${esc(school.city||'Школа')}</div><div class="page-heading"><div><h1 class="school-title">${esc(school.name)}</h1><p class="muted">${place(school)} · ${teacherLabel(school.teacher_count)} · ${orderLabel(school.order_count)}</p></div><div class="school-heading-actions"><button class="secondary" data-school="edit">Изменить</button>${school.order_count?'':'<button class="danger-button" data-school="delete">Удалить</button>'}</div></div><section class="forms-block teacher-add"><div class="forms-block-head"><h3>Добавить учителя</h3><small>Фото можно загрузить после добавления</small></div><form id="teacher-form" class="teacher-form">${teacherFields()}<button class="primary" type="submit">Добавить</button><p class="error" role="alert"></p></form></section><div class="forms-block-head teacher-list-head"><h2>Учителя <span class="heading-count">${teachers.length}</span></h2></div><div class="teacher-grid">${teachers.map(teacherCard).join('')||'<div class="empty-state"><h3>Учителей пока нет</h3><p>Добавьте учителей школы. Класс отметит нужных в личном кабинете и выберет классного руководителя.</p></div>'}</div></div>`;
    const main=$('#main .schools-page');
    main.querySelector('[data-school="edit"]').onclick=()=>schoolForm(school);
    const remove=main.querySelector('[data-school="delete"]');
    if(remove)remove.onclick=async()=>{if(!confirm(`Удалить школу «${school.name}» вместе с учителями?`))return;try{await api('/schools/'+school.id,{method:'DELETE'});toast('Школа удалена');location.hash='schools';}catch(error){toast(error.message);}};
    const form=$('#teacher-form');
    form.onsubmit=async e=>{e.preventDefault();const button=form.querySelector('[type=submit]');button.disabled=true;try{await api(`/schools/${school.id}/teachers`,json('POST',Object.fromEntries(new FormData(form))));await schoolPage(school.id);toast('Учитель добавлен');$('#teacher-form')?.elements.last_name.focus();}catch(error){form.querySelector('.error').textContent=error.message;button.disabled=false;}};
    main.onchange=async e=>{const input=e.target.closest('[data-teacher-photo]');if(!input||!input.files[0])return;const file=input.files[0];input.value='';const card=input.closest('.teacher-card');card.classList.add('busy');try{await api(`/teachers/${encodeURIComponent(input.dataset.teacherPhoto)}/portrait`,{method:'PUT',headers:{'Content-Type':file.type||'application/octet-stream'},body:file});await schoolPage(school.id);toast('Портрет сохранён');}catch(error){card.classList.remove('busy');toast(error.message);}};
    main.onclick=async e=>{
      const edit=e.target.closest('[data-teacher-edit]'),del=e.target.closest('[data-teacher-delete]');
      if(edit){const t=teachers.find(x=>x.id===edit.dataset.teacherEdit);$('#action-dialog').classList.remove('wide-dialog');$('#action-content').innerHTML=`<form id="teacher-edit"><div class="dialog-heading"><h2>Изменить учителя</h2><button type="button" class="close" data-close="action-dialog" aria-label="Закрыть">×</button></div>${teacherFields(t)}${t.has_portrait?'<button type="button" class="text-button danger-text" id="teacher-photo-remove">Удалить портрет</button>':''}<p class="error" role="alert"></p><button class="primary wide" type="submit">Сохранить</button></form>`;$('#action-dialog').showModal();const f=$('#teacher-edit');f.onsubmit=async ev=>{ev.preventDefault();try{await api('/teachers/'+t.id,json('PATCH',Object.fromEntries(new FormData(f))));$('#action-dialog').close();await schoolPage(school.id);toast('Учитель сохранён');}catch(error){f.querySelector('.error').textContent=error.message;}};const drop=$('#teacher-photo-remove');if(drop)drop.onclick=async()=>{try{await api(`/teachers/${t.id}/portrait`,{method:'DELETE'});$('#action-dialog').close();await schoolPage(school.id);toast('Портрет удалён');}catch(error){f.querySelector('.error').textContent=error.message;}};return;}
      if(del){const t=teachers.find(x=>x.id===del.dataset.teacherDelete);if(!confirm(`Удалить учителя ${t.name}? В уже выбранных альбомах он останется.`))return;try{await api('/teachers/'+t.id,{method:'DELETE'});await schoolPage(school.id);toast('Учитель удалён');}catch(error){toast(error.message);}}
    };
  }

  function page(id){if(id)schoolPage(id);else listPage();}

  // Order page (Анкеты tab): teachers chosen for this class album.
  async function orderBlock(order){
    const el=$('#order-teachers');if(!el)return;const id=order.id;
    let data;try{data=await api(`/orders/${encodeURIComponent(id)}/teachers`);}catch(error){el.innerHTML=`<p class="error">${esc(error.message)}</p>`;return;}
    if(state.order?.id!==id||!$('#order-teachers'))return;
    if(!data.school){el.innerHTML='<p class="muted small">Школа заказа не выбрана из каталога. Откройте «⋯ → Изменить заказ» и выберите школу, чтобы класс мог отметить учителей.</p>';return;}
    if(!data.teachers.length){el.innerHTML=`<p class="muted small">В каталоге у школы «${esc(data.school.name)}» пока нет учителей. <a href="#schools/${encodeURIComponent(data.school.id)}">Добавить учителей →</a></p>`;return;}
    const picked=data.teachers.filter(t=>t.selected).length;
    const who=data.updated_by==='client'?'Выбрал класс':data.updated_by==='photographer'?'Выбрал фотограф':'Класс ещё не выбрал учителей';
    el.innerHTML=`<p class="muted small">${who}${data.chosen?` · ${teacherLabel(picked)} в альбоме`:''}${data.class_teacher_id?'':' · классный руководитель не выбран'}</p>${data.layout_outdated?'<p class="warn small">Состав учителей изменился после сборки макета. Пересоберите макет.</p>':''}<form id="order-teachers-form"><div class="teacher-choice-list">${data.teachers.map(t=>`<div class="teacher-choice"><label class="teacher-choice-main"><input type="checkbox" name="teacher" value="${esc(t.id)}" ${t.selected?'checked':''} ${data.locked?'disabled':''}><span class="teacher-photo small">${avatar(t)}</span><span><strong>${esc(t.name)}</strong><small>${esc(t.subject)}</small></span></label><label class="teacher-lead"><input type="radio" name="lead" value="${esc(t.id)}" ${t.is_class_teacher?'checked':''} ${data.locked?'disabled':''}>Кл. руководитель</label></div>`).join('')}</div>${data.locked?'<p class="muted small">Заказ в печати — состав учителей зафиксирован.</p>':'<p class="error" role="alert"></p><button class="secondary" type="submit">Сохранить учителей</button>'}</form>`;
    const form=$('#order-teachers-form');
    form.onchange=e=>{if(e.target.name==='lead'&&e.target.checked){const box=form.querySelector(`[name=teacher][value="${CSS.escape(e.target.value)}"]`);if(box)box.checked=true;}if(e.target.name==='teacher'&&!e.target.checked){const lead=form.querySelector(`[name=lead][value="${CSS.escape(e.target.value)}"]`);if(lead)lead.checked=false;}};
    form.onsubmit=async e=>{e.preventDefault();const ids=[...form.querySelectorAll('[name=teacher]:checked')].map(x=>x.value),lead=form.querySelector('[name=lead]:checked')?.value||null;try{await api(`/orders/${encodeURIComponent(id)}/teachers`,json('PUT',{teacher_ids:ids,class_teacher_id:lead}));toast('Учителя сохранены');orderBlock(order);}catch(error){form.querySelector('.error').textContent=error.message;}};
  }

  document.addEventListener('click',e=>{if(e.target.closest('[data-school="new"]'))schoolForm(null);});
  return {page,orderBlock};
})();
