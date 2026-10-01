// «Создать макет»: package, the class's teachers, general shoots going into the album and a build that waits for uploads.
// Uses the shared helpers from v2.js (state, api, json, esc, toast, count, svgIcon, packagePicker, uploadFiles, refreshOrder).
const LayoutStart=(()=>{
  let timer=null,teachers=null,teachersDirty=false,cancelled=null;
  const initials=t=>[t.last_name,t.first_name].map(x=>(x||'').charAt(0)).join('').toUpperCase()||'?';
  const avatar=t=>t.has_portrait?`<img src="/api/teachers/${encodeURIComponent(t.id)}/portrait/thumb?v=${encodeURIComponent(t.portrait_version)}" alt="" loading="lazy">`:`<span class="teacher-initials" aria-hidden="true">${esc(initials(t))}</span>`;
  const shortName=t=>[t.last_name,[t.first_name,t.patronymic].filter(Boolean).map(x=>x.charAt(0)+'.').join(' ')].filter(Boolean).join(' ');
  const generalShoots=()=>(state.order.shoots||[]).filter(s=>s.kind==='general');
  const shootPhotos=id=>state.order.photos.filter(p=>p.shoot_id===id);
  const queued=id=>(state.uploadQueue||[]).filter(x=>x.shootId===id).length;
  const uploadingHere=()=>state.uploading&&state.progress?.orderId===state.order.id;
  // Photos the build still waits for: files in the browser queue and unanalysed photos of included shoots.
  function waiting(){const o=state.order,off=new Set((o.shoots||[]).filter(s=>s.kind==='general'&&!s.in_layout).map(s=>s.id));
    const busy=o.photos.filter(p=>['pending','processing'].includes(p.status)&&!off.has(p.shoot_id)).length,files=(state.uploadQueue||[]).filter(x=>!off.has(x.shootId)).length;
    return {busy,files,any:busy+files>0||(uploadingHere()&&!(state.uploadQueue||[]).length&&state.progress.done<state.progress.total)};}

  function shootCard(s){const photos=shootPhotos(s.id),cover=photos.find(p=>p.status!=='error'),files=queued(s.id),busy=photos.filter(p=>['pending','processing'].includes(p.status)).length;
    const status=files?`Загрузка · ${files}`:busy?`Обработка · ${busy}`:'';
    return `<label class="ls-shoot${s.in_layout?'':' off'}"><input type="checkbox" data-ls-shoot="${esc(s.id)}" ${s.in_layout?'checked':''}><span class="ls-shoot-cover">${cover?`<img src="/media/${cover.id}/thumb" alt="" loading="lazy">`:svgIcon('upload',20)}</span><strong>${esc(s.title)}</strong><small>${status||count(photos.length,'фото','фото','фото')}</small></label>`;}
  function drawShoots(){const el=$('#ls-shoots');if(!el)return;const open=el.querySelector('.ls-add-drop');if(open)return;
    const html=`<div class="ls-shoot-row">${generalShoots().map(shootCard).join('')}<button type="button" class="ls-shoot ls-shoot-new" data-ls-add>${svgIcon('plus',20)}<strong>Добавить съёмку</strong></button></div>`;
    if(el.innerHTML!==html&&el.dataset.html!==html){el.innerHTML=html;el.dataset.html=html;}}
  function openDrop(){const el=$('#ls-shoots');el.innerHTML=`<div class="shoot-drop ls-add-drop"><input type="file" data-ls-files accept="image/jpeg,image/png,.jpg,.jpeg,.png" multiple hidden><input type="file" data-ls-folder webkitdirectory multiple hidden>${svgIcon('upload',24)}<p class="shoot-drop-text">Перетащите <button type="button" data-ls-pick="files">фото</button> или <button type="button" data-ls-pick="folder">папку</button> сюда</p><button type="button" class="text-button small" data-ls-cancel>Отмена</button></div>`;
    const drop=el.querySelector('.ls-add-drop');
    drop.ondragover=e=>{e.preventDefault();drop.classList.add('dragging');};
    drop.ondragleave=e=>{if(!drop.contains(e.relatedTarget))drop.classList.remove('dragging');};
    drop.ondrop=async e=>{e.preventDefault();drop.classList.remove('dragging');const dirs=[...(e.dataTransfer.items||[])].map(i=>i.webkitGetAsEntry?.()).filter(x=>x?.isDirectory);const files=PhotoTools.onlyImages(await PhotoTools.filesFrom(e.dataTransfer));addShoot(files,dirs.length===1?dirs[0].name:'');};
    for(const input of drop.querySelectorAll('input'))input.onchange=()=>{const files=[...input.files];input.value='';addShoot(PhotoTools.onlyImages(files),files[0]?.webkitRelativePath?.split('/')[0]||'');};}
  // A new general shoot is created at once and uploads in the background; its name and date can be changed later.
  async function addShoot(files,folder){if(!files.length)return;const o=state.order,n=generalShoots().length;
    try{const shotOn=await PhotoTools.guessDate(files).catch(()=>null)||'';const r=await api(`/orders/${o.id}/shoots`,json('POST',{kind:'general',title:(folder||(n?`Общая съёмка ${n+1}`:'Общая съёмка')).slice(0,100),shot_on:shotOn}));
      o.shoots.push({...r,in_layout:1});$('#ls-shoots').innerHTML='';delete $('#ls-shoots').dataset.html;drawShoots();uploadFiles(files,r.id);refreshOrder().catch(()=>{});}
    catch(error){$('#layout-master-error').textContent=error.message;drawShoots();}}

  function teacherSummary(d){if(!d)return '<p class="muted small">Загружаем учителей…</p>';
    if(!d.school)return '<p class="muted small">Школа не из каталога</p>';
    if(!d.teachers.length)return `<p class="muted small">В каталоге школы нет учителей · <a href="#order/${encodeURIComponent(state.order.id)}/teachers">загрузить фото</a></p>`;
    const picked=d.teachers.filter(t=>t.selected),lead=picked.find(t=>t.is_class_teacher);
    return `<div class="ls-teacher-sum"><span class="ls-avatars">${picked.slice(0,7).map(t=>`<span class="teacher-photo small" title="${esc(t.name)}">${avatar(t)}</span>`).join('')}${picked.length>7?`<span class="ls-more">+${picked.length-7}</span>`:''}</span><span><strong>${picked.length?count(picked.length,'учитель','учителя','учителей'):'Никто не выбран'}</strong><small>${[lead?'Классный руководитель: '+esc(shortName(lead)):''].filter(Boolean).join(' · ')}</small></span></div>${d.proposals?.length?`<p class="warn small">Класс предложил учителей: ${d.proposals.length} · <button type="button" class="text-button" data-teacher-proposals>Посмотреть</button></p>`:''}${d.unsigned_groups?`<p class="warn small">Не подписано на фото: ${d.unsigned_groups} · <a href="#order/${state.order.id}/teachers">подписать</a></p>`:''}`;}
  function teacherList(d){const rows=[...d.teachers].sort((a,b)=>b.selected-a.selected);
    return `<div class="ls-teacher-list">${rows.map(t=>`<div class="ls-teacher${t.selected?' on':''}"><label class="ls-teacher-main"><input type="checkbox" name="ls_teacher" value="${esc(t.id)}" ${t.selected?'checked':''}><span class="teacher-photo small">${avatar(t)}</span><span><strong>${esc(t.name)}</strong></span></label><input class="ls-subject" data-ls-subject="${esc(t.id)}" maxlength="100" value="${esc(t.subject)}" placeholder="Предмет" aria-label="Предмет в этом классе"><label class="ls-lead" title="Классный руководитель"><input type="radio" name="ls_lead" value="${esc(t.id)}" ${t.is_class_teacher?'checked':''}>кл. рук.</label></div>`).join('')}</div><button type="button" class="text-button" data-ls-clear-lead>Снять назначение классного руководителя</button>`;}
  function drawTeachers(expanded=false){const el=$('#ls-teachers');if(!el)return;el.innerHTML=teacherSummary(teachers)+(expanded&&teachers?.teachers.length?teacherList(teachers):'');}
  function syncTeachers(){
    const el=$('#ls-teachers');if(!el||!teachers||!el.querySelector('.ls-teacher-list'))return;
    const values=readTeachers(),picked=new Set(values.teacher_ids),data={...teachers,teachers:teachers.teachers.map(t=>({...t,selected:picked.has(t.id),is_class_teacher:t.id===values.class_teacher_id}))};
    el.querySelector('.ls-teacher-sum').outerHTML=teacherSummary(data).split('</div>')[0]+'</div>';
    el.querySelector('[data-ls-clear-lead]').hidden=!values.class_teacher_id;
  }
  function readTeachers(){const form=$('#layout-master-form'),ids=[...form.querySelectorAll('[name=ls_teacher]:checked')].map(x=>x.value);
    return {teacher_ids:ids,class_teacher_id:form.querySelector('[name=ls_lead]:checked')?.value||null,subjects:Object.fromEntries([...form.querySelectorAll('[data-ls-subject]')].filter(el=>ids.includes(el.dataset.lsSubject)).map(el=>[el.dataset.lsSubject,el.value]))};}

  function counters(){const o=state.order,c=o.client_progress,persons=o.persons.length,withPortrait=new Set(o.photos.filter(p=>p.shoot_type==='portrait'&&p.status==='ready'&&p.person_id).map(p=>p.person_id)).size;
    return `<div class="ls-counters"><span>Портреты <b>${withPortrait} из ${persons}</b></span>${c?.enabled?`<span>Анкеты <b>${c.completed} из ${c.total}</b>${c.total>c.completed?'<span class="help-dot" tabindex="0" data-help="Для незаполнивших возьмём первый готовый портрет">i</span>':''}</span>`:''}</div>`;}
  function syncButton(){const b=$('#layout-master-form [type=submit]');if(!b||b.disabled)return;const w=waiting();b.textContent=w.any?'Создать после загрузки':'Создать макет';$('#ls-wait').textContent=w.any?[w.files?`загружается ${w.files}`:'',w.busy?`обрабатывается ${w.busy}`:''].filter(Boolean).join(' · '):'';}

  // A proposal confirmed on top of this dialog changes the album's teachers: show the server's list again.
  document.addEventListener('teachers-changed',e=>{if(!$('#layout-master-form')||state.order?.id!==e.detail)return;
    api(`/orders/${encodeURIComponent(e.detail)}/teachers`).then(d=>{if(!$('#layout-master-form'))return;teachers=d;teachersDirty=false;drawTeachers(true);syncTeachers();}).catch(()=>{});});
  async function open(){const id=state.order.id,dialog=$('#action-dialog');teachers=null;teachersDirty=false;
    $('#action-content').innerHTML='<div class="dialog-heading"><h2>Создать макет</h2><button class="close" data-close="action-dialog" aria-label="Закрыть">×</button></div><p class="muted">Загружаем мастер-макеты…</p>';dialog.showModal();
    let designs;try{designs=await api('/designs');}catch(error){$('#action-content').innerHTML=`<p class="error">${esc(error.message)}</p><button class="secondary" data-close="action-dialog">Закрыть</button>`;return;}
    if(!dialog.open||state.order?.id!==id)return;dialog.classList.add('wide-dialog');
    const rebuild=state.order.stage==='layout'||state.view==='layout';
    $('#action-content').innerHTML=`<form id="layout-master-form" class="layout-start"><div class="dialog-heading"><h2>Создать макет</h2><button type="button" class="close" data-close="action-dialog" aria-label="Закрыть">×</button></div>
      <fieldset class="package-field"><legend>Дизайн и комплектация</legend>${packagePicker(designs,state.order.master_template_id,false)}</fieldset>${rebuild?'<p class="muted small">Другая комплектация соберёт макет заново, без прежних правок.</p>':''}
      <section class="ls-block"><h3>Учителя</h3><p class="muted small">Проверьте состав, предметы и классного руководителя перед созданием макета.</p><div id="ls-teachers"></div></section>
      <section class="ls-block"><h3>Общие съёмки</h3><div id="ls-shoots"></div></section>
      <section class="ls-block"><h3>Портреты в макете</h3><div class="ls-retouch-modes"><label><input type="radio" name="retouch_mode" value="asis" ${state.order.retouch?.mode!=='retouch'?'checked':''}> Как есть<small>Фото уже готовы — можно сразу на согласование</small></label><label><input type="radio" name="retouch_mode" value="retouch" ${state.order.retouch?.mode==='retouch'?'checked':''}> Буду ретушировать<small>Черновик соберётся сейчас. Готовые кадры займут те же места в макете</small></label></div></section>
      ${counters()}<p id="layout-master-error" class="error" role="alert"></p>
      <div class="ls-submit"><small id="ls-wait" class="muted"></small><button type="submit" class="primary">Создать макет</button></div></form>`;
    drawTeachers();drawShoots();syncButton();$('#layout-master-form [type=submit]').disabled=true;
    api(`/orders/${encodeURIComponent(id)}/teachers`).then(d=>{if(state.order?.id!==id)return;teachers=d;drawTeachers(true);syncTeachers();form.querySelector('[type=submit]').disabled=false;syncButton();}).catch(error=>{const el=$('#ls-teachers');if(el)el.innerHTML=`<p class="error small">${esc(error.message)}</p>`;});
    clearInterval(timer);timer=setInterval(()=>{if(!dialog.open||!$('#layout-master-form')){clearInterval(timer);return;}drawShoots();syncButton();},1500);
    const form=$('#layout-master-form');
    form.addEventListener('click',e=>{if(e.target.closest('[data-ls-clear-lead]')){form.querySelectorAll('[name=ls_lead]').forEach(el=>el.checked=false);teachersDirty=true;syncTeachers();return;}if(e.target.closest('[data-ls-teachers]')){drawTeachers(true);return;}if(e.target.closest('[data-ls-add]')){openDrop();return;}if(e.target.closest('[data-ls-cancel]')){$('#ls-shoots').innerHTML='';delete $('#ls-shoots').dataset.html;drawShoots();return;}const pick=e.target.closest('[data-ls-pick]');if(pick){form.querySelector(pick.dataset.lsPick==='folder'?'[data-ls-folder]':'[data-ls-files]').click();return;}if(e.target.closest('.ls-add-drop')&&!e.target.closest('button,input'))form.querySelector('[data-ls-files]').click();});
    form.addEventListener('change',async e=>{const box=e.target.closest('[data-ls-shoot]');if(box){const shoot=state.order.shoots.find(s=>s.id===box.dataset.lsShoot);try{await api(`/orders/${id}/shoots/${shoot.id}/in-layout`,json('PUT',{value:box.checked}));shoot.in_layout=box.checked?1:0;}catch(error){box.checked=!box.checked;$('#layout-master-error').textContent=error.message;}drawShoots();syncButton();return;}
      if(e.target.name==='ls_lead'&&e.target.checked){const t=form.querySelector(`[name=ls_teacher][value="${CSS.escape(e.target.value)}"]`);if(t)t.checked=true;}
      if(e.target.name==='ls_teacher'&&!e.target.checked){const lead=form.querySelector(`[name=ls_lead][value="${CSS.escape(e.target.value)}"]`);if(lead)lead.checked=false;}
      if(e.target.name==='ls_teacher'||e.target.name==='ls_lead'){teachersDirty=true;form.querySelectorAll('.ls-teacher').forEach(row=>row.classList.toggle('on',row.querySelector('[name=ls_teacher]').checked));syncTeachers();}});
    form.addEventListener('input',e=>{if(e.target.matches('[data-ls-subject]'))teachersDirty=true;});
    form.onsubmit=async e=>{e.preventDefault();const b=form.querySelector('[type=submit]'),error=$('#layout-master-error'),master=form.master_template_id.value;error.textContent='';
      if(!master){error.textContent='Выберите комплектацию.';return;}b.disabled=true;
      try{await api(`/orders/${id}/retouch`,json('PUT',{mode:form.retouch_mode.value}));if(teachersDirty&&form.querySelector('.ls-teacher-list')){await api(`/orders/${encodeURIComponent(id)}/teachers`,json('PUT',readTeachers()));teachersDirty=false;}
        const w=waiting();
        if(w.any){await api(`/orders/${id}/layout/queue`,json('POST',{master_template_id:master,uploading:uploadingHere()}));dialog.close();toast('Макет в очереди — соберём, когда фото загрузятся и обработаются');await refreshOrder();startOrderPolling();return;}
        await api('/orders/'+id+'/layout',json('POST',{master_template_id:master}));dialog.close();if(location.hash===`#order/${id}/layout`)await route();else location.hash=`order/${id}/layout`;toast('Макет создан');}
      catch(err){error.textContent=err.message;}finally{b.disabled=false;syncButton();}};}

  // The order head while a queued build waits, and the moment it lands.
  function stage(o){const q=o.layout_queue;if(!q)return null;
    if(q.error)return {title:'Макет не собран',text:q.error,actions:'<button class="secondary" data-v2="cancel-layout-queue">Убрать из очереди</button><button class="primary" data-v2="make-layout">Создать макет</button>',mine:true,turn:'alert'};
    const files=o.id===state.progress?.orderId&&state.uploading?(state.uploadQueue||[]).length:0,stalled=q.uploading&&!(o.id===state.progress?.orderId&&state.uploading);
    return {title:stalled?'Макет ждёт фото':'Макет соберётся сам',text:stalled?'Загрузка прервана. Догрузите фото или соберите без них.':files||q.pending?'Когда догрузятся и обработаются фото':'Собираем…',turn:stalled?'mine':'wait',
      actions:`<button class="secondary" data-v2="cancel-layout-queue">Отменить</button>${stalled?'<button class="primary" data-v2="build-queued-now">Собрать сейчас</button>':''}`,mine:stalled};}
  async function action(name){const id=state.order.id;
    if(name==='cancel-layout-queue'){cancelled=id;await api(`/orders/${id}/layout/queue`,{method:'DELETE'});await refreshOrder();toast('Сборка отменена');}
    if(name==='build-queued-now'){const r=await api(`/orders/${id}/layout/queue`,json('PATCH',{uploading:false}));await refreshOrder();if(r.built)location.hash=`order/${id}/layout`;}}
  function landed(previous,fresh){if(!previous?.layout_queue||fresh.layout_queue)return;if(cancelled===fresh.id){cancelled=null;return;}toast('Макет собран');}
  return {open,stage,action,landed};
})();
