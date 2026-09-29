/* Categories of automatic general-photo slots (built-in and the master's own), album photo rules and the server preview on a test shoot.
   Built-ins mirror CATEGORIES in album_factory/photo_pick.py; a master may edit them or add its own in doc.photoCategories. */
window.MasterPhotos=(()=>{
  const BUILTIN=[
    ['any','Любое','Лучший из свободных снимков.',{}],
    ['class','Весь класс','Постановочное фото всего класса.',{people:['class'],style:'posed'}],
    ['subgroup','Подгруппа','Постановочная группа — часть класса.',{people:['subgroup'],style:'posed'}],
    ['few','Вдвоём-втроём','Два-три человека рядом.',{people:['few']}],
    ['solo','Один','Один человек в кадре.',{people:['solo']}],
    ['candid','Репортаж','Живые, непостановочные кадры.',{style:'candid'}],
    ['wide','Общий план','Люди видны мелко, много пространства.',{scale:['wide']}],
    ['empty','Без людей','Детали, место, атмосфера.',{people:['none']}]];
  /* What a slot with the hero takes when its category has nothing — mirrors FALLBACKS in photo_pick.py. */
  const HERO_FALLBACK={few:'Если с героем таких нет — репортаж с ним, затем дубль групповой фотографии.',solo:'Если нет — репортаж, где он крупно, затем вдвоём-втроём, затем дубль групповой.',candid:'Сначала кадры, где героя хорошо видно, затем где он мелко, затем дубль групповой.'};
  const LEGACY={any:['any'],hero:['any'],class_photo:['class'],life:['candid'],friends:['few','owner'],me_in_class:['subgroup','owner'],with_item:['any','hero'],close_up:['solo'],atmosphere:['empty']};
  const FILTERS=['people','scale','style','quality','tags'];
  const PEOPLE=[['none','Никого'],['solo','Один'],['few','2–3'],['subgroup','Подгруппа'],['class','Весь класс']];
  const SCALES=[['close','Крупный'],['medium','Средний'],['full','В рост'],['wide','Общий'],['detail','Детали']];
  const STYLES=[['','Любой'],['posed','Постановка'],['candid','Репортаж']],QUALITY=[['','Любое'],['good','Без брака'],['best','Лучшее']];
  const TAGS=[['classroom','Класс'],['library','Библиотека'],['hall','Коридор'],['gym','Спортзал'],['stage','Сцена'],['ceremony','Праздник'],['studio','Студия'],['nature','Природа'],['beach','Море'],['city','Город'],['picnic','Пикник'],['winter','Зима']];
  const RELAX={quality:'качество',scale:'крупность',people:'число людей',style:'стиль',tags:'сцена',include:'кто на фото',any:'категория',cut:'обрезка людей',reuse:'повтор',fallback:'похожий кадр с героем',dup:'дубль групповой',small:'герой мелко'};
  const RULES={reuse:'album',rhythm:true,chronology:true,mixShoots:true,posedFirst:true};
  let hooks=null,data=null,sent='',timer=null,version=0,failed='',openCategory=null,menuOpen=false;
  const tick='<svg class="mark" viewBox="0 0 16 16" aria-hidden="true"><path d="M3.2 8.4 6.3 11.5 12.8 4.6" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',caret='<svg class="caret" viewBox="0 0 10 10" aria-hidden="true"><path d="M2.5 4 5 6.5 7.5 4" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const clean=f=>Object.fromEntries(FILTERS.filter(k=>Array.isArray(f[k])?f[k].length:f[k]).map(k=>[k,f[k]]));
  /* Built-in categories with the master's edits and without its removed ones, then its own: {id,name,note,filters,builtin,edited}. */
  function categories(doc){const own=doc?.photoCategories||[],removed=doc?.removedCategories||[],list=BUILTIN.filter(([id])=>!removed.includes(id)).map(([id,name,note,filters])=>{const edit=own.find(c=>c.id===id);return {id,name:edit?.name||name,note,filters:edit?clean(edit):filters,builtin:true,edited:!!edit};});for(const c of own)if(!BUILTIN.some(([id])=>id===c.id))list.push({id:c.id,name:c.name,note:'',filters:clean(c),builtin:false,edited:false});return list;}
  function category(doc,id){const list=categories(doc);return list.find(c=>c.id===id)||list[0];}
  /* Slots saved with the first role presets become category + who. */
  function upgrade(pick){if(!pick||'category' in pick)return pick;const [category,who]=LEGACY[pick.role]||LEGACY.any,include=pick.include==='item'?'hero':pick.include==='owner'?'owner':null;return {category,...((include||who)?{who:include||who}:{})};}
  function migrate(doc){let changed=false;const fix=item=>{if(item?.pick&&!('category' in item.pick)){item.pick=upgrade(item.pick);changed=true;}};const walk=c=>{if(c.split)c.cells.forEach(walk);else fix(c);};for(const s of doc.sections||[])for(const sp of s.spreads||[])for(const p of sp.pages||[])for(const l of p.layers||[]){if(l.type==='photo')fix(l);if(l.type==='collage'){fix(l);(l.rows||[]).forEach(r=>r.forEach(walk));}}return changed;}
  const label=(options,id)=>options.find(([k])=>k===id)?.[1]||id;
  /* One line such as «2–3 · Репортаж · Без брака». */
  function describe(f){const parts=[];if(f.people?.length)parts.push(f.people.map(p=>label(PEOPLE,p)).join(', '));if(f.scale?.length)parts.push(f.scale.map(p=>label(SCALES,p)).join(', ').toLowerCase()+' план');if(f.style)parts.push(label(STYLES,f.style));if(f.quality)parts.push(f.quality==='best'?'лучшее качество':'без брака');if(f.tags?.length)parts.push(f.tags.map(t=>label(TAGS,t)).join(', '));const text=parts.join(' · ');return text?text[0].toUpperCase()+text.slice(1):'Без ограничений';}
  function chips(attr,key,options,values){return `<div class="pick-chips" role="group">${options.map(([id,text])=>{const on=!!values?.includes(id);return `<button type="button" ${attr}="${key}" data-value="${id}" class="${on?'active':''}" aria-pressed="${on}">${text}</button>`;}).join('')}</div>`;}
  function segmented(attr,key,options,value){return `<div class="pick-chips pick-segmented" role="group">${options.map(([id,text])=>{const on=(value??'')===id;return `<button type="button" ${attr}="${key}" data-value="${id}" class="${on?'active':''}" aria-pressed="${on}">${text}</button>`;}).join('')}</div>`;}
  function stats(key){if(failed)return `<p class="pick-stats warning">${esc(failed)}</p>`;const slot=data?.slots?.[key];if(!slot)return `<p class="pick-stats">${data?'На этой странице слот не участвует в примере.':'Подбираем фото на тестовой съёмке…'}</p>`;const relaxed=slot.relaxed.filter(r=>RELAX[r]);return `<p class="pick-stats${relaxed.length?' warning':''}"><strong>${slot.candidates}</strong> из ${data.photos} тестовых фото подходят без уступок.${relaxed.length?`<br>Для примера взято: ${relaxed.map(r=>RELAX[r]).join(', ')}.`:''}</p>`;}
  /* Who must be on the photo: the hero exists only on personal spreads; elsewhere the album owner may be asked for. */
  /* Category rows of both frame menus (canvas and inspector): name, what it takes, and «new category» at the end. */
  function categoryRows(doc,current,attr){return categories(doc).map(c=>{const on=c.id===current;return `<button type="button" class="menu-row${on?' on':''}" role="menuitemradio" aria-checked="${on}" title="${esc(describe(c.filters))}" ${attr}="${esc(c.id)}"><span>${esc(c.name)}</span>${on?tick:''}</button>`;}).join('')+`<button type="button" class="menu-row menu-add" data-new-category><i aria-hidden="true">+</i><span>Новая категория</span></button>`;}
  /* A new category for the selected slot: it is chosen right away and opened for editing in the album settings. */
  function newCategory(){const t=target(),id='c-'+Math.random().toString(36).slice(2,8);openCategory=id;menuOpen=false;hooks.commit(()=>{const doc=hooks.doc();doc.photoCategories=[...(doc.photoCategories||[]),{id,name:'Новая категория'}];if(t){t.obj.source='class';t.obj.pick={...(upgrade(t.obj.pick)||{}),category:id};}});hooks.rules();requestAnimationFrame(()=>{const input=document.querySelector('.category-item.open [data-cat-name]');input?.scrollIntoView({block:'nearest'});input?.select();});}
  function whoOptions(section){return section.kind==='repeat'?[['hero','С героем разворота'],['','Любой']]:[['','Любой'],['owner','С владельцем альбома']];}
  /* Body of «what is in the frame» for an automatic general-photo slot (layer or collage cell): category, who, test-shoot stats. */
  function panel(pick,key,section){const doc=hooks.doc(),p=upgrade(pick)||{category:'any'},c=category(doc,p.category),note=p.who==='hero'&&HERO_FALLBACK[c.id]?`<p class="section-note">${HERO_FALLBACK[c.id]}</p>`:'';
    return `<div class="pick-section"><div class="pick-field pick-picker"><span>Категория</span><button type="button" class="pick-trigger" data-pick-menu aria-haspopup="menu" aria-expanded="${menuOpen}"><span>${esc(c.name)}</span>${caret}</button>${menuOpen?`<div class="cell-sources pick-menu" role="menu">${categoryRows(doc,c.id,'data-pick-choice')}</div>`:''}</div>
    <div class="pick-summary"><span>${esc(c.note&&!c.edited?c.note:describe(c.filters))}</span><button type="button" class="link-button" data-edit-category="${esc(c.id)}">Настроить</button></div>
    <div class="pick-field"><span>Кто на снимке</span>${segmented('data-pick-who','who',whoOptions(section),p.who||'')}</div>${note}${stats(key)}</div>`;}
  /* Editor of one category inside the album settings. */
  function categoryEditor(c){const f=c.filters,reset=c.builtin&&c.edited?`<button type="button" data-cat-reset="${esc(c.id)}">Вернуть как было</button>`:'';
    return `<div class="category-editor"><label>Название<input data-cat-name="${esc(c.id)}" maxlength="40" value="${esc(c.name)}"></label>
    <div class="pick-field"><span>Сколько людей</span>${chips('data-cat-chip','people',PEOPLE,f.people)}</div>
    <div class="pick-field"><span>Крупность</span>${chips('data-cat-chip','scale',SCALES,f.scale)}</div>
    <div class="pick-field"><span>Стиль</span>${segmented('data-cat-set','style',STYLES,f.style)}</div>
    <div class="pick-field"><span>Качество</span>${segmented('data-cat-set','quality',QUALITY,f.quality)}</div>
    <div class="pick-field"><span>Сцена</span>${chips('data-cat-chip','tags',TAGS,f.tags)}</div>
    <p class="section-note">Пустая группа — без ограничения. Если подходящих снимков нет, фильтры ослабляются по очереди, а в макете появляется предупреждение.</p>${reset?`<div class="category-actions">${reset}</div>`:''}</div>`;}
  /* Album-settings sketches drawn like the «Формат» tab: pages, photo tiles, figures. */
  const svg=(w,h,body,cls='rule-svg')=>`<svg class="${cls}" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true">${body}</svg>`;
  const TINT={photo:'#e6dbef',hot:'#b27fd2',a:'#e6dbef',b:'#cfe4ec',c:'#f1e2c6'};
  /* A spread at x with tiles given in page units [x,y,w,h,fill] of a 30×20 spread. */
  function spread(x,tiles,w=30,h=20){return `<g transform="translate(${x} 1)"><rect x=".5" y=".5" width="${w}" height="${h}" rx="1.5" fill="#fff" stroke="#cdb8dc"/><path d="M${w/2+.5} .5v${h}" stroke="#e3d6ec"/>${tiles.map(([tx,ty,tw,th,f])=>`<rect x="${tx+.5}" y="${ty+.5}" width="${tw}" height="${th}" rx="1" fill="${TINT[f]||f}"/>`).join('')}</g>`;}
  const PAIR=hot=>[[3,4,10,12,hot===0?'hot':'photo'],[18,3,9,7,hot===1?'hot':'photo'],[18,11,9,6,'photo']];
  const REUSE=[['album','Не повторять','Каждый снимок — один раз на весь альбом.',svg(102,23,spread(0,PAIR(0))+spread(35,PAIR(-1))+spread(70,PAIR(-1)))],
    ['section','Не повторять в блоке','В следующем блоке снимок может встретиться снова.',svg(106,23,spread(0,PAIR(0))+spread(33,PAIR(-1))+'<path d="M69 0v23" stroke="#b27fd2" stroke-dasharray="2 2"/>'+spread(74,PAIR(1)))],
    ['allow','Разрешить повторы','Сильный кадр можно поставить несколько раз.',svg(102,23,spread(0,PAIR(0))+spread(35,PAIR(1))+spread(70,PAIR(0)))]];
  function figure(x,base,size,fill='#b9a2cb'){const r=size*.26;return `<circle cx="${x}" cy="${base-size+r}" r="${r}" fill="${fill}"/><rect x="${x-size*.34}" y="${base-size+r*2.15}" width="${size*.68}" height="${size-r*2.15}" rx="${size*.2}" fill="${fill}"/>`;}
  const row=(n,x0,x1,base,size,jitter=0)=>Array.from({length:n},(_,i)=>figure(x0+(n===1?(x1-x0)/2:i*(x1-x0)/(n-1)),base+(jitter&&i%2?jitter:0),size)).join('');
  const SHOOTS='<g font-size="5" fill="#8f7aa0"><circle cx="46" cy="6" r="2.2" fill="#e6dbef"/><text x="50.5" y="7.7">осень</text><circle cx="46" cy="12" r="2.2" fill="#cfe4ec"/><text x="50.5" y="13.7">спорт</text><circle cx="46" cy="18" r="2.2" fill="#f1e2c6"/><text x="50.5" y="19.7">выпуск</text></g>';
  const TOGGLES=[['posedFirst','Сначала постановочные','Класс и подгруппы в начале, живые кадры — после.',svg(74,23,spread(0,[[3,4,24,13,'photo']])+`<g transform="translate(0 1)">${row(5,7,24,15.5,6)}</g>`+'<path d="M35 11.5h5m-2-2 2 2-2 2" fill="none" stroke="#b27fd2" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>'+spread(43,[[3,4,24,13,'photo']])+`<g transform="translate(43 1)">${figure(8,14,7)+figure(15,17,5)+figure(22,15,7)}</g>`)],
    ['mixShoots','Личные развороты вперемешку','На развороте ученика — кадры с разных съёмок.',svg(74,23,spread(0,[[3,3,10,15,'a'],[18,3,9,7,'b'],[18,11,9,7,'c']])+`<g transform="translate(0 1)">${figure(8.5,17,10)}</g>`+SHOOTS)],
    ['rhythm','Чередовать крупность','Крупный кадр рядом с общими, а не все одинаковые.',svg(74,23,spread(0,[[3,3,11,15,'photo'],[17,3,5,5,'photo'],[23,3,5,5,'photo'],[17,9,11,9,'photo']])+`<g transform="translate(0 1)">${figure(8.5,19,12)}${figure(19.5,8,3)}${figure(25.5,8,3)}${row(3,19.5,26.5,18,3.5)}</g>`)],
    ['chronology','Общие развороты по съёмкам','Съёмки идут друг за другом, кадры разворота — из одной.',svg(74,23,['a','b','c'].map((f,i)=>spread(i*25,[[2,3,7,14,f],[12,3,6,6,f],[12,11,6,6,f]],20,20)).join(''))]];
  /* A category pictured: how many people, how large and whether they stand in a row or freely. */
  function categoryIcon(f){const people=f.people?.[0],scale=f.scale?.[0],candid=f.style==='candid',j=candid?1.6:0;let body;
    if(people==='none'||scale==='detail')body='<path d="M3 19l7-7 5 4 4-3 8 6z" fill="#cbb4dc"/><circle cx="22" cy="7" r="2.6" fill="#e2cdb0"/>';
    else if(scale==='close')body=figure(15,26,22);
    else if(scale==='wide')body=`<path d="M1 15.5h28" stroke="#ddd0e7"/>${row(people==='solo'?1:people==='few'?2:4,people==='solo'?15:9,21,18,4,j*.5)}`;
    else{const n={solo:1,few:3,subgroup:5,class:7}[people]||3,size=scale==='medium'?{1:15,3:11}[n]||8:{1:13,3:9,5:7}[n]||5.5;
      body=people==='class'?row(7,5,25,13,5.2,j)+row(6,7,23,20,5.4,j):people?row(n,n===1?15:5,n===1?15:25,people==='solo'&&scale==='medium'?24:20,size,j):row(3,8,22,20,8,1.6).replace(/#b9a2cb/g,'#d6c8e1');}
    return svg(30,22,`<rect x=".5" y=".5" width="29" height="21" rx="3" fill="#f7f2fb" stroke="#e6dbef"/>${body}`,'category-icon');}
  function categoriesPanel(doc){const list=categories(doc);if(openCategory&&!list.some(c=>c.id===openCategory))openCategory=null;
    return `<section class="album-section" id="photo-categories"><h3>Категории снимков</h3><p class="section-note category-lead">Из них выбирают, что поставить в кадр. Изменения действуют во всём макете.</p><div class="category-list">${list.map(c=>{const open=openCategory===c.id;return `<div class="category-item${open?' open':''}"><button type="button" class="category-row" data-cat-open="${esc(c.id)}" aria-expanded="${open}">${categoryIcon(c.filters)}<span><strong>${esc(c.name)}${c.edited?' <i>изменена</i>':''}${c.builtin?'':' <i>своя</i>'}</strong>${describe(c.filters).toLowerCase()===c.name.toLowerCase()?'':`<small>${esc(describe(c.filters))}</small>`}</span>${caret}</button>${c.id==='any'?'':`<button type="button" class="category-delete" data-cat-delete="${esc(c.id)}" title="Удалить категорию «${esc(c.name)}»" aria-label="Удалить категорию «${esc(c.name)}»"><img src="/static/assets/editor/trash.svg" alt=""></button>`}${open?categoryEditor(c):''}</div>`;}).join('')}</div><button type="button" class="wide" data-cat-add>+ Новая категория</button>${doc.removedCategories?.length?`<button type="button" class="link-button" data-cat-restore>Вернуть удалённые встроенные (${doc.removedCategories.length})</button>`:''}</section>`;}
  function rulesPanel(doc){const r={...RULES,...(doc.photoRules||{})};
    return `<section class="album-section"><h3>Повторы снимков</h3><div class="rule-choices">${REUSE.map(([id,title,help,sketch])=>{const on=r.reuse===id;return `<button type="button" class="layout-choice${on?' active':''}" data-photo-set="reuse" data-value="${id}" aria-pressed="${on}"><span class="rule-sketch">${sketch}</span><strong>${title}</strong><small>${help}</small></button>`;}).join('')}</div></section>
    <section class="album-section"><h3>Расстановка снимков</h3><div class="rule-toggles">${TOGGLES.map(([key,title,help,sketch])=>{const on=!!r[key];return `<button type="button" class="rule-toggle" role="switch" data-photo-toggle="${key}" aria-checked="${on}"><span class="rule-sketch">${sketch}</span><span class="rule-toggle-text"><strong>${title}</strong><small>${help}</small></span><i class="switch" aria-hidden="true"></i></button>`;}).join('')}</div></section>`;}
  function target(){const t=hooks.target();return t&&t.obj?t:null;}
  function setPick(mutator){const t=target();if(!t)return;hooks.commit(()=>{const pick={...(upgrade(t.obj.pick)||{category:'any'})};mutator(pick);if(!pick.who)delete pick.who;t.obj.pick=pick;});}
  /* Change a category: built-ins are stored as edits in doc.photoCategories, the master's own are edited in place. */
  function editCategory(id,mutator){hooks.commit(()=>{const doc=hooks.doc(),own=doc.photoCategories=[...(doc.photoCategories||[])];let item=own.find(c=>c.id===id);if(!item){const base=categories(doc).find(c=>c.id===id);if(!base)return;item={id,name:base.name,...JSON.parse(JSON.stringify(base.filters))};own.push(item);}mutator(item);for(const k of FILTERS)if(item[k]==null||(Array.isArray(item[k])&&!item[k].length))delete item[k];});}
  /* Slots still pointing at a removed category take any photo. */
  /* A removed built-in is remembered in doc.removedCategories so it can be brought back. */
  function dropCategory(id){hooks.commit(()=>{const doc=hooks.doc();doc.photoCategories=(doc.photoCategories||[]).filter(c=>c.id!==id);if(!doc.photoCategories.length)delete doc.photoCategories;if(BUILTIN.some(([b])=>b===id))doc.removedCategories=[...(doc.removedCategories||[]),id];const fix=item=>{if(item?.pick?.category===id)item.pick={...item.pick,category:'any'};},walk=c=>c.split?c.cells.forEach(walk):fix(c);for(const s of doc.sections||[])for(const sp of s.spreads||[])for(const p of sp.pages||[])for(const l of p.layers||[]){if(l.type==='photo')fix(l);if(l.type==='collage'){fix(l);(l.rows||[]).forEach(r=>r.forEach(walk));}}});}
  function setRule(key,value){hooks.commit(()=>{const doc=hooks.doc(),rules={...RULES,...(doc.photoRules||{}),[key]:value};doc.photoRules=rules;});}
  function click(e){const ruleSet=e.target.closest('[data-photo-set]');if(ruleSet){setRule(ruleSet.dataset.photoSet,ruleSet.dataset.value);return true;}const toggle=e.target.closest('[data-photo-toggle]');if(toggle){const key=toggle.dataset.photoToggle;setRule(key,!{...RULES,...(hooks.doc().photoRules||{})}[key]);return true;}if(e.target.closest('[data-pick-menu]')){menuOpen=!menuOpen;hooks.inspector();return true;}const choice=e.target.closest('[data-pick-choice]');if(choice){menuOpen=false;setPick(pick=>{pick.category=choice.dataset.pickChoice;});return true;}if(e.target.closest('[data-new-category]')){newCategory();return true;}const who=e.target.closest('[data-pick-who]');if(who){setPick(pick=>{pick.who=who.dataset.value||undefined;});return true;}
    const edit=e.target.closest('[data-edit-category]');if(edit){openCategory=edit.dataset.editCategory;hooks.rules();requestAnimationFrame(()=>document.querySelector('.category-item.open')?.scrollIntoView({block:'nearest'}));return true;}
    const open=e.target.closest('[data-cat-open]');if(open){openCategory=openCategory===open.dataset.catOpen?null:open.dataset.catOpen;hooks.inspector();return true;}
    const chip=e.target.closest('[data-cat-chip]');if(chip){const key=chip.dataset.catChip,value=chip.dataset.value;editCategory(openCategory,item=>{const list=new Set(item[key]||[]);list.has(value)?list.delete(value):list.add(value);item[key]=[...list];});return true;}
    const set=e.target.closest('[data-cat-set]');if(set){editCategory(openCategory,item=>{item[set.dataset.catSet]=set.dataset.value||null;});return true;}
    const reset=e.target.closest('[data-cat-reset]');if(reset){const id=reset.dataset.catReset;hooks.commit(()=>{const doc=hooks.doc();doc.photoCategories=(doc.photoCategories||[]).filter(c=>c.id!==id);if(!doc.photoCategories.length)delete doc.photoCategories;});return true;}
    const del=e.target.closest('[data-cat-delete]');if(del){dropCategory(del.dataset.catDelete);openCategory=null;return true;}
    if(e.target.closest('[data-cat-restore]')){hooks.commit(()=>{delete hooks.doc().removedCategories;});return true;}
    if(e.target.closest('[data-cat-add]')){const id='c-'+Math.random().toString(36).slice(2,8);openCategory=id;hooks.commit(()=>{const doc=hooks.doc();doc.photoCategories=[...(doc.photoCategories||[]),{id,name:'Новая категория'}];});return true;}
    return false;}
  function change(e){const el=e.target;if(el.matches('[data-pick-category]')){setPick(pick=>{pick.category=el.value;});return true;}
    if(el.dataset.catName){const name=el.value.trim().slice(0,40);if(name)editCategory(el.dataset.catName,item=>{item.name=name;});else el.value=category(hooks.doc(),el.dataset.catName).name;return true;}
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
  /* What the test shoot gave one slot (with or without a photo), or null when the slot is not in the preview. */
  function slot(sectionId,pageIndex,slotId){return data?.slots?.[`${sectionId}:${pageIndex}/${slotId}`]||null;}
  const ready=()=>!!data&&!failed;
  function image(sectionId,pageIndex,slotId){const slot=data?.slots?.[`${sectionId}:${pageIndex}/${slotId}`];if(!slot?.photo)return null;return {src:scene(slot),crop:slot.crop};}
  function bind(value){hooks=value;}
  document.addEventListener('pointerdown',e=>{if(menuOpen&&!e.target.closest('.pick-picker')){menuOpen=false;hooks?.inspector();}},true);
  document.addEventListener('keydown',e=>{if(menuOpen&&e.key==='Escape'){e.stopImmediatePropagation();menuOpen=false;hooks?.inspector();}},true);
  return {bind,panel,rulesPanel,categoriesPanel,click,change,refresh,image,slot,ready,categories,category,describe,migrate,upgrade,categoryRows,newCategory};
})();
