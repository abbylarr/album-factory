/* Roles of automatic general-photo slots, album photo rules and the server preview on a test shoot. */
window.MasterPhotos=(()=>{
  const ROLES=[
    ['any','Любое общее фото','Лучший из свободных снимков по хронологии.'],
    ['hero','Главное фото разворота','Самый выразительный кадр: средний, в рост или общий план.'],
    ['class_photo','Весь класс','Постановочное фото всего класса.'],
    ['life','Жизнь класса','Репортаж: группы от 3 до 12 человек.'],
    ['friends','Владелец с друзьями','Владелец альбома и 1–5 человек рядом, крупно или средне.'],
    ['me_in_class','Владелец в классе','Владелец альбома в большой группе.'],
    ['with_item','С учеником разворота','Общее фото, где есть ученик этого личного разворота.'],
    ['close_up','Крупный план','Один-два человека крупно — для небольших кадров.'],
    ['atmosphere','Атмосфера','Кадры без людей, детали и общие планы.']];
  const DEFAULTS={any:{},hero:{scale:['medium','full','wide'],quality:'best'},class_photo:{buckets:['class'],style:'posed'},life:{buckets:['small_group','group'],style:'candid'},friends:{include:'owner',buckets:['pair','small_group'],scale:['close','medium']},me_in_class:{include:'owner',buckets:['group','class']},with_item:{include:'item'},close_up:{buckets:['solo','pair'],scale:['close']},atmosphere:{buckets:['none'],scale:['detail','wide']}};
  const BUCKETS=[['solo','Один'],['pair','Двое'],['small_group','3–6'],['group','7 и больше'],['class','Весь класс'],['none','Без людей']];
  const SCALES=[['close','Крупный'],['medium','Средний'],['full','В рост'],['wide','Общий'],['detail','Детали']];
  const TAGS=[['classroom','Класс'],['library','Библиотека'],['hall','Коридор'],['gym','Спортзал'],['stage','Сцена'],['ceremony','Праздник'],['studio','Студия'],['nature','Природа'],['beach','Море'],['city','Город'],['picnic','Пикник'],['winter','Зима']];
  const RELAX={quality:'качество',scale:'крупность',buckets:'число людей',style:'стиль',tags:'сцена',include:'кто на фото',any:'роль',cut:'обрезка людей',reuse:'повтор'};
  const RULES={reuse:'album',coverageMin:1,coverageMax:0,rhythm:true,chronology:true};
  let hooks=null,data=null,sent='',timer=null,version=0,failed='';
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const role=pick=>DEFAULTS[pick?.role]?pick.role:'any';
  function effective(pick){const base=DEFAULTS[role(pick)],result={};for(const key of ['buckets','scale','tags','include','style','quality'])result[key]=pick&&key in pick?pick[key]:base[key]??null;return result;}
  function chips(key,options,values){return `<div class="pick-chips" role="group">${options.map(([id,label])=>{const on=!!values?.includes(id);return `<button type="button" data-pick-chip="${key}" data-value="${id}" class="${on?'active':''}" aria-pressed="${on}">${label}</button>`;}).join('')}</div>`;}
  function segmented(key,options,value){return `<div class="pick-chips pick-segmented" role="group">${options.map(([id,label])=>{const on=(value??'')===id;return `<button type="button" data-pick-set="${key}" data-value="${id}" class="${on?'active':''}" aria-pressed="${on}">${label}</button>`;}).join('')}</div>`;}
  function stats(key){if(failed)return `<p class="pick-stats warning">${esc(failed)}</p>`;const slot=data?.slots?.[key];if(!slot)return `<p class="pick-stats">${data?'На этой странице слот не участвует в примере.':'Подбираем фото на тестовой съёмке…'}</p>`;const relaxed=slot.relaxed.filter(r=>RELAX[r]);return `<p class="pick-stats${relaxed.length?' warning':''}"><strong>${slot.candidates}</strong> из ${data.photos} тестовых фото подходят без уступок.${relaxed.length?`<br>Для примера ослаблено: ${relaxed.map(r=>RELAX[r]).join(', ')}.`:''}</p>`;}
  /* Inspector block for an automatic general-photo slot (layer or collage cell). */
  function panel(pick,key,section){const r=role(pick),e=effective(pick),custom=pick&&Object.keys(pick).some(k=>k!=='role');const roles=ROLES.filter(([id])=>id!=='with_item'||section.kind==='repeat');
    const include=[['','Не важно'],['owner','Владелец альбома'],...(section.kind==='repeat'?[['item','Ученик разворота']]:[])];
    return `<section class="inspector-section pick-section"><h3>Подбор общего фото</h3><label>Роль слота<select data-pick-role>${roles.map(([id,label])=>`<option value="${id}" ${r===id?'selected':''}>${label}</option>`).join('')}</select></label><p class="section-note">${esc(ROLES.find(x=>x[0]===r)[2])}</p>${stats(key)}
    <details class="pick-more" ${custom?'open':''}><summary>Уточнить фильтры${custom?' · изменены':''}</summary>
    <div class="pick-field"><span>Сколько людей</span>${chips('buckets',BUCKETS,e.buckets)}</div>
    <div class="pick-field"><span>Крупность</span>${chips('scale',SCALES,e.scale)}</div>
    <div class="pick-field"><span>Кто на фото</span>${segmented('include',include,e.include)}</div>
    <div class="pick-field"><span>Стиль</span>${segmented('style',[['','Любой'],['posed','Постановка'],['candid','Репортаж']],e.style)}</div>
    <div class="pick-field"><span>Качество</span>${segmented('quality',[['','Любое'],['good','Без брака'],['best','Лучшее']],e.quality)}</div>
    <div class="pick-field"><span>Сцена</span>${chips('tags',TAGS,e.tags)}</div>
    <p class="section-note">Пустая группа — без ограничения. Если подходящих снимков нет, фильтры ослабляются по очереди, а в макете появляется предупреждение.</p>
    ${custom?'<button type="button" class="wide" data-pick-reset>Вернуть фильтры роли</button>':''}</details></section>`;}
  function rulesPanel(doc){const r={...RULES,...(doc.photoRules||{})},low=data&&Object.entries(data.coverage||{}).filter(([,n])=>n<r.coverageMin);
    return `<section class="inspector-section pick-section"><h3>Общие фото альбома</h3><label>Повторы снимков<select data-photo-rule="reuse"><option value="album" ${r.reuse==='album'?'selected':''}>Не повторять в альбоме</option><option value="section" ${r.reuse==='section'?'selected':''}>Не повторять в разделе</option><option value="allow" ${r.reuse==='allow'?'selected':''}>Разрешить повторы</option></select></label>
    <div class="field-grid"><label>Минимум появлений ученика<input type="number" min="0" max="10" step="1" data-photo-rule="coverageMin" value="${r.coverageMin}"></label><label>Максимум, 0 — без предела<input type="number" min="0" max="50" step="1" data-photo-rule="coverageMax" value="${r.coverageMax}"></label></div>
    <label class="check"><input type="checkbox" data-photo-rule="rhythm" ${r.rhythm?'checked':''}>Чередовать крупность на развороте</label><label class="check"><input type="checkbox" data-photo-rule="chronology" ${r.chronology?'checked':''}>Ставить снимки по времени съёмки</label>
    ${data?`<p class="pick-stats${low.length?' warning':''}">${low.length?`На тестовом классе ${low.length} из ${Object.keys(data.coverage).length} учеников появляются реже ${r.coverageMin} раз.`:`На тестовом классе каждый ученик появляется не реже ${r.coverageMin} раз.`}</p>`:''}</section>`;}
  function target(){const t=hooks.target();return t&&t.obj?t:null;}
  function setPick(mutator){const t=target();if(!t)return;hooks.commit(()=>{const pick={...(t.obj.pick||{role:'any'})};mutator(pick,effective(t.obj.pick));for(const k of Object.keys(pick))if(pick[k]===undefined)delete pick[k];t.obj.pick=pick;});}
  function click(e){const chip=e.target.closest('[data-pick-chip]');if(chip){const key=chip.dataset.pickChip,value=chip.dataset.value;setPick((pick,current)=>{const list=new Set(current[key]||[]);list.has(value)?list.delete(value):list.add(value);pick[key]=list.size?[...list]:null;});return true;}
    const set=e.target.closest('[data-pick-set]');if(set){setPick(pick=>{pick[set.dataset.pickSet]=set.dataset.value||null;});return true;}
    if(e.target.closest('[data-pick-reset]')){setPick(pick=>{for(const k of Object.keys(pick))if(k!=='role')pick[k]=undefined;});return true;}
    return false;}
  function change(e){const el=e.target;if(el.matches('[data-pick-role]')){setPick(pick=>{for(const k of Object.keys(pick))pick[k]=undefined;pick.role=el.value;});return true;}
    if(el.dataset.photoRule){const key=el.dataset.photoRule;let value=el.type==='checkbox'?el.checked:el.type==='number'?Math.round(Number(el.value)):el.value;if(el.type==='number'&&(!Number.isFinite(value)||!el.validity.valid))return true;hooks.commit(()=>{const doc=hooks.doc(),rules={...RULES,...(doc.photoRules||{}),[key]:value};if(rules.coverageMax&&rules.coverageMax<rules.coverageMin)rules.coverageMax=rules.coverageMin;doc.photoRules=rules;});return true;}
    return false;}
  function strip(doc){return JSON.parse(JSON.stringify(doc,(k,v)=>k==='dataUrl'?undefined:v));}
  /* Ask the server what the draft would pick on the test shoot; re-render when it answers. */
  function refresh(doc,view){const payload=JSON.stringify({document:strip(doc),students:view.students,teachers:view.teachers,owner:view.owner});if(payload===sent)return;sent=payload;clearTimeout(timer);const mine=++version;timer=setTimeout(async()=>{try{const r=await fetch('/api/master-templates/photo-preview',{method:'POST',headers:{'Content-Type':'application/json'},body:payload});const value=await r.json();if(mine!==version)return;if(!r.ok)throw Error(typeof value.detail==='string'?value.detail:'Превью подбора недоступно');data=value;failed='';}catch(error){if(mine!==version)return;failed=error.message||'Превью подбора недоступно';}hooks?.updated();},350);}
  const svgCache=new Map();
  function scene(slot){const key=slot.photo+':'+slot.persons.map(p=>p.owner?1:0).join('');if(svgCache.has(key))return svgCache.get(key);const [w,h]=slot.size.map(v=>v/10),people=[...slot.persons].sort((a,b)=>(a.box[1]+a.box[3])-(b.box[1]+b.box[3]));
    let body='';const n=v=>v.toFixed(1);for(const p of people){const [x,y,bw,bh]=p.box,fill=p.owner?'#a77cc4':'#b7b3ab',skin=p.owner?'#dcc6e8':'#d8cfc5',f=p.face;
      if(f){const fx=f[0]*w,fy=f[1]*h,fw=f[2]*w,fh=f[3]*h,cx=fx+fw/2,torso=Math.min(bw*w,fw*2.5),top=fy+fh*.8,edge=fw*.14;body+=`<rect x="${n(cx-torso/2)}" y="${n(top)}" width="${n(torso)}" height="${n(Math.max(1,(y+bh)*h-top))}" rx="${n(fw*.7)}" fill="${fill}" stroke="#ebe8e2" stroke-width="${n(edge)}"/><ellipse cx="${n(cx)}" cy="${n(fy+fh/2)}" rx="${n(fw*.52)}" ry="${n(fh*.58)}" fill="${skin}" stroke="#ebe8e2" stroke-width="${n(edge)}"/>`;}
      else{const cx=(x+bw/2)*w,tw=Math.min(bw*w,bh*h*.3);body+=`<rect x="${n(cx-tw/2)}" y="${n(y*h)}" width="${n(tw)}" height="${n(bh*h)}" rx="${n(tw*.4)}" fill="${fill}"/>`;}}
    if(!people.length)body=`<circle cx="${w*.5}" cy="${h*.45}" r="${Math.min(w,h)*.16}" fill="#d9d4cb"/><rect x="${w*.3}" y="${h*.62}" width="${w*.4}" height="${h*.05}" rx="${h*.02}" fill="#cdc7bd"/>`;
    const src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><rect width="${w}" height="${h}" fill="#ebe8e2"/><rect y="${h*.72}" width="${w}" height="${h*.28}" fill="#e1ddd5"/>${body}</svg>`);svgCache.set(key,src);return src;}
  /* The test photo a slot received in the preview: {src, crop} with crop normalised to the photo. */
  function image(sectionId,pageIndex,slotId){const slot=data?.slots?.[`${sectionId}:${pageIndex}/${slotId}`];if(!slot?.photo)return null;return {src:scene(slot),crop:slot.crop};}
  function bind(value){hooks=value;}
  return {bind,panel,rulesPanel,click,change,refresh,image,effective,ROLES};
})();
