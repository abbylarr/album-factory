const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const names={v1:'V1 · исходный',v2:'V2 · быстрое чтение',v2_series:'V2 · чтение + серии',v3:'V3 · основной алгоритм',v4:'V4 · уменьшенный поиск лица',v5:'V5 · адаптивный шаг серии'};
let report,variant='v1',timer,blobURL;
async function api(path,options={}){const r=await fetch('/api'+path,options),v=await r.json();if(!r.ok)throw Error(typeof v.detail==='string'?v.detail:'Не удалось выполнить запрос');return v;}
function render(){
  const result=report.result,v=result.variants[variant],relative=result.relative?.[variant],c=relative||(variant==='v3'&&result.versus_v2_series?result.versus_v2_series:result.comparisons?.[variant]),reference=relative?names[relative.baseline]:result.versus_v2_series&&(variant==='v3'||!result.variants.v1)?'V2 серии':'V1',changed=new Set(c?.changed_ids||[]);
  $('#results').hidden=false;
  $('#result-title').textContent=report.order_name||'Результат пробы';
  $('#sample').textContent=`${report.total} снимков · начало с ${(report.offset||0)+1} · пробные результаты`;
  $('#variants').innerHTML=Object.keys(result.variants).map(m=>`<button data-mode="${m}" class="${m===variant?'active':''}" aria-pressed="${m===variant}">${names[m]}</button>`).join('');
  $('#metrics').innerHTML=[['Время обработки',v.seconds.toFixed(1)+' с'],['Снимков в минуту',Math.round(v.photos_per_minute)],['Пробных персон',v.persons],['Назначено по серии',v.inferred]].map(([label,value])=>`<div><span>${label}</span><strong>${value}</strong></div>`).join('');
  $('#comparison').textContent=(c?`Относительно ${reference}: ${c.speedup.toFixed(2)}× по скорости. Расхождения в составе групп или статусе: ${c.changed_photos} снимков. Разделённых пар: ${c.split_pairs}; объединённых пар: ${c.merged_pairs}. `:'Распознаны все фотографии текущим алгоритмом.' )+` Ошибок чтения/обработки: ${v.errors}.`;
  if(variant!=='v1'&&!c)$('#comparison').textContent=`Одиночный запуск: для сравнения скорости и групп выберите «Сравнить все версии». Ошибок: ${v.errors}.`;
  if(variant==='v2_series'&&result.versus_v2_series&&!c)$('#comparison').textContent=`База для сравнения с V3. Назначено по серии: ${v.inferred}; ошибок: ${v.errors}.`;
  if(!c&&Object.keys(result.variants).length>1&&Object.values(result.relative||{}).some(r=>r.baseline===variant))$('#comparison').textContent=`Базовый результат для сравнения. Назначено по серии: ${v.inferred}; ошибок: ${v.errors}.`;
  $('#method').textContent=result.note+` Этапы: чтение ${v.timings.decode.toFixed(1)} с; лица ${v.timings.recognition.toFixed(1)} с; сопоставление ${v.timings.matching.toFixed(1)} с; превью ${v.timings.previews.toFixed(1)} с.`;
  if(v.pipeline)$('#method').textContent+=` В этом режиме время чтения в этапах — ожидание готовых кадров и повторные чтения. Подготовка (${v.pipeline.workers} потоков) перекрывается с распознаванием: чтение ${v.pipeline.decode_work_seconds.toFixed(1)} с, уменьшение ${v.pipeline.resize_work_seconds.toFixed(1)} с (суммарно по потокам; не складывать с общим временем).`;
  if(v.settings)$('#method').textContent+=` Настройки: поиск ${v.settings.detection_size} px; подготовка ${v.settings.decode_workers} поток(а); вычисления ${v.settings.opencv_threads} поток(а); максимальный шаг ${v.settings.max_step}. Полных проходов: ${v.cascade?.full_passes??0}.`;
  if(variant==='v5'&&v.adaptive_steps)$('#method').textContent+=` Интервалы по шагам: ${Object.entries(v.adaptive_steps).map(([step,n])=>step+' → '+n).join(', ')}.`;
  $('#review-label').textContent=` Только предположения и расхождения с ${reference}`;
  const groups=new Map();
  for(const p of v.photos){if($('#review-only').checked&&p.source!=='sequence'&&!changed.has(p.id))continue;const key=p.person_id||'unassigned';if(!groups.has(key))groups.set(key,[]);groups.get(key).push(p);}
  $('#groups').innerHTML=[...groups].map(([id,photos])=>`<section class="trial-group"><h3>${id==='unassigned'?'Без персоны':'Группа '+esc(id.slice(1))} <span class="muted">· ${photos.length}</span></h3><div class="trial-photos">${photos.map(p=>`<figure class="trial-photo ${changed.has(p.id)?'changed':''}"><a href="/media/${p.id}/full" target="_blank" rel="noopener"><img src="/media/${p.id}/thumb" alt="${esc(p.filename)}" loading="lazy"></a><figcaption>${esc(p.filename)}${p.source==='sequence'?'<small>По серии · проверить</small>':p.uncertain?'<small>Неуверенное совпадение</small>':''}${changed.has(p.id)?`<small>Расхождение с ${reference}</small>`:''}${p.status!=='ready'?`<small>${esc({no_face:'Лицо не найдено',multiple_faces:'Несколько лиц',small_face:'Маленькое лицо',error:'Ошибка'}[p.status]||p.status)}</small>`:''}</figcaption></figure>`).join('')}</div></section>`).join('')||'<p class="muted">По этому фильтру снимков нет.</p>';
  if(blobURL)URL.revokeObjectURL(blobURL);blobURL=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));$('#download').href=blobURL;$('#download').download='sorting-trial-'+report.id+'.json';
}
async function poll(id){
  clearTimeout(timer);
  try{const job=await api('/sorting-trials/'+encodeURIComponent(id));
    if(job.status==='complete'){report=job;variant=['v5','v4','v3','v2_series','v2','v1'].find(m=>job.result.variants[m]);$('#progress').textContent='Проба завершена. Рабочие группы не изменены.';$('#start').disabled=false;render();return;}
    if(job.status==='error')throw Error(job.error);
    $('#start').disabled=true;$('#progress').textContent=job.status==='queued'?'Ожидаем свободный обработчик…':`${names[job.mode]||'Подготовка'}: ${job.done} из ${job.total}`;
    timer=setTimeout(()=>poll(id),1500);
  }catch(e){$('#error').textContent=e.message;$('#start').disabled=false;$('#progress').textContent='';}
}
$('#trial-form').onsubmit=async e=>{e.preventDefault();$('#error').textContent='';$('#start').disabled=true;$('#results').hidden=true;
try{const job=await api(`/orders/${$('#order').value}/sorting-trials`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({limit:Number($('#limit').value),offset:Number($('#offset').value)-1,mode:$('#mode').value,detection_size:Number($('#detection-size').value),decode_workers:Number($('#decode-workers').value),opencv_threads:Number($('#opencv-threads').value),max_step:Number($('#max-step').value)})});localStorage.setItem('sorting-trial-id',job.id);history.replaceState(null,'','#'+job.id);poll(job.id);}catch(e){$('#error').textContent=e.message;$('#start').disabled=false;}};
$('#variants').onclick=e=>{const b=e.target.closest('[data-mode]');if(b){variant=b.dataset.mode;render();}};
$('#review-only').onchange=()=>{if(report)render();};
(async()=>{try{const orders=await api('/orders');$('#order').innerHTML=orders.filter(o=>o.photo_count).map(o=>`<option value="${o.id}">${esc(o.school+' / '+o.class_name)} · ${o.photo_count} фото</option>`).join('');if(!$('#order').value){$('#start').disabled=true;$('#progress').textContent='Сначала загрузите фотографии в заказ.';}const id=location.hash.slice(1)||localStorage.getItem('sorting-trial-id');if(id&&/^[a-f0-9]{32}$/.test(id))poll(id);}catch(e){$('#error').textContent=e.message;}})();
