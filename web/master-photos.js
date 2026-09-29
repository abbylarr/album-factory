/* Categories of automatic general-photo slots (built-in and the photographer's own), album photo rules and the server preview on a test shoot.
   Built-ins mirror CATEGORIES in album_factory/photo_pick.py. Categories belong to the studio, not to a design: one list behind
   /api/photo-categories ({items: edits of built-ins and own ones, removed: built-in ids}), shared by every design and package. */
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
  const RULES={reuse:'album',rhythm:true,chronology:true,mixShoots:true,posedFirst:true};
  let hooks=null,data=null,sent='',timer=null,version=0,failed='',openCategory=null,menuOpen=false,lastView=null;
  let studio={items:[],removed:[]},saving=Promise.resolve();
  const tick='<svg class="mark" viewBox="0 0 16 16" aria-hidden="true"><path d="M3.2 8.4 6.3 11.5 12.8 4.6" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',caret='<svg class="caret" viewBox="0 0 10 10" aria-hidden="true"><path d="M2.5 4 5 6.5 7.5 4" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const clean=f=>Object.fromEntries(FILTERS.filter(k=>Array.isArray(f[k])?f[k].length:f[k]).map(k=>[k,f[k]]));
  /* Built-in categories with the studio's edits and without its removed ones, then its own: {id,name,note,filters,builtin,edited}.
     The document argument callers pass is ignored: categories are the same in every design. */
  function categories(){const own=studio.items,removed=studio.removed,list=BUILTIN.filter(([id])=>!removed.includes(id)).map(([id,name,note,filters])=>{const edit=own.find(c=>c.id===id);return {id,name:edit?.name||name,note,filters:edit?clean(edit):filters,builtin:true,edited:!!edit};});for(const c of own)if(!BUILTIN.some(([id])=>id===c.id))list.push({id:c.id,name:c.name,note:'',filters:clean(c),builtin:false,edited:false});return list;}
  function category(doc,id){const list=categories();return list.find(c=>c.id===id)||list[0];}
  /* The studio list: loaded once, saved in order after every change; a failed save reloads what the server has. */
  function loadStudio(){return fetch('/api/photo-categories').then(r=>r.ok?r.json():null).then(value=>{if(value){studio={items:value.items||[],removed:value.removed||[]};changed();}}).catch(()=>{});}
  function changed(){sent='';if(lastView&&hooks)refresh(hooks.doc(),lastView);keepFocus(()=>hooks?.updated());}
  function saveStudio(mutator){const next=JSON.parse(JSON.stringify(studio));mutator(next);for(const item of next.items)for(const k of FILTERS)if(item[k]==null||(Array.isArray(item[k])&&!item[k].length))delete item[k];studio=next;changed();const body=JSON.stringify(next);
    saving=saving.then(()=>fetch('/api/photo-categories',{method:'PUT',headers:{'Content-Type':'application/json'},body})).then(r=>{if(!r.ok)throw Error();}).catch(()=>loadStudio());}
  /* Slots saved with the first role presets become category + who. */
  function upgrade(pick){if(!pick||'category' in pick)return pick;const [category,who]=LEGACY[pick.role]||LEGACY.any,include=pick.include==='item'?'hero':pick.include==='owner'?'owner':null;return {category,...((include||who)?{who:include||who}:{})};}
  function migrate(doc){let changed=false;const fix=item=>{if(item?.pick&&!('category' in item.pick)){item.pick=upgrade(item.pick);changed=true;}};const walk=c=>{if(c.split)c.cells.forEach(walk);else fix(c);};for(const s of doc.sections||[])for(const sp of s.spreads||[])for(const p of sp.pages||[])for(const l of p.layers||[]){if(l.type==='photo')fix(l);if(l.type==='collage'){fix(l);(l.rows||[]).forEach(r=>r.forEach(walk));}}return changed;}
  const label=(options,id)=>options.find(([k])=>k===id)?.[1]||id;
  /* One line such as «2–3 · Репортаж · Без брака». */
  function describe(f){const parts=[];if(f.people?.length)parts.push(f.people.map(p=>label(PEOPLE,p)).join(', '));if(f.scale?.length)parts.push(f.scale.map(p=>label(SCALES,p)).join(', ').toLowerCase()+' план');if(f.style)parts.push(label(STYLES,f.style));if(f.quality)parts.push(f.quality==='best'?'лучшее качество':'без брака');if(f.tags?.length)parts.push(f.tags.map(t=>label(TAGS,t)).join(', '));const text=parts.join(' · ');return text?text[0].toUpperCase()+text.slice(1):'Без ограничений';}
  function chips(attr,key,options,values){return `<div class="pick-chips" role="group">${options.map(([id,text])=>{const on=!!values?.includes(id);return `<button type="button" ${attr}="${key}" data-value="${id}" class="${on?'active':''}" aria-pressed="${on}">${text}</button>`;}).join('')}</div>`;}
  function segmented(attr,key,options,value){return `<div class="pick-chips pick-segmented" role="group">${options.map(([id,text])=>{const on=(value??'')===id;return `<button type="button" ${attr}="${key}" data-value="${id}" class="${on?'active':''}" aria-pressed="${on}">${text}</button>`;}).join('')}</div>`;}
  /* Category rows of both frame menus (canvas and inspector): pictogram and name, built-ins first, then the photographer's own
     after a thin divider (with small captions when `captions`), and «new category» at the end. */
  function categoryRows(doc,current,attr,captions=false){const list=categories(),row=c=>{const on=c.id===current;return `<button type="button" class="menu-row cat-row${on?' on':''}" role="menuitemradio" aria-checked="${on}" title="${esc(describe(c.filters))}" ${attr}="${esc(c.id)}">${pictogram(c)}<span>${esc(c.name)}</span>${on?tick:''}</button>`;},
      own=list.filter(c=>!c.builtin);
    return (captions?'<p class="menu-label">Стандартные</p>':'')+list.filter(c=>c.builtin).map(row).join('')+(own.length?`<hr class="menu-divider">${captions?'<p class="menu-label">Мои</p>':''}${own.map(row).join('')}`:'')
      +`<hr class="menu-divider"><button type="button" class="menu-row menu-add" data-new-category><i aria-hidden="true">+</i><span>Новая категория</span></button>`;}
  /* A new category for the selected slot: it is chosen right away and opened for editing in the album settings. */
  function newCategory(){const t=target(),id='c-'+Math.random().toString(36).slice(2,8);openCategory=id;menuOpen=false;saveStudio(s=>{s.items.push({id,name:'Новая категория'});});if(t)hooks.commit(()=>{t.obj.source='class';t.obj.pick={...(upgrade(t.obj.pick)||{}),category:id};});hooks.rules();requestAnimationFrame(()=>{const input=document.querySelector('.category-item.open [data-cat-name]');input?.scrollIntoView({block:'nearest'});input?.select();});}
  /* Who must be on the photo: the hero exists only on personal spreads; elsewhere the album owner may be asked for. [id, label, full name] */
  function whoOptions(section){return section.kind==='repeat'?[['hero','Герой','С героем разворота'],['','Любой','Любой']]:[['','Любой','Любой'],['owner','Владелец','С владельцем альбома']];}
  const pencil='<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M10.6 2.9 13.1 5.4M3 13l.6-3.1 7.9-7.9a1.1 1.1 0 0 1 1.6 0l.9.9a1.1 1.1 0 0 1 0 1.6L6.1 12.4z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  /* Body of «what is in the frame» for an automatic general-photo slot (layer or collage cell): label → control rows like the
     other inspector sections — category (pictogram dropdown with an edit button beside it) and who is on the photo. */
  function panel(pick,key,section){const doc=hooks.doc(),p=upgrade(pick)||{category:'any'},c=category(doc,p.category),tip=p.who==='hero'&&HERO_FALLBACK[c.id]?infoTip(HERO_FALLBACK[c.id]):'';
    if(menuOpen)requestAnimationFrame(placeMenu);
    return `<div class="pick-section pick-rows"><div class="pick-row"><span class="pick-label">Категория</span><div class="pick-picker"><button type="button" class="pick-trigger" data-pick-menu aria-haspopup="menu" aria-expanded="${menuOpen}" title="${esc(describe(c.filters))}">${pictogram(c)}<span>${esc(c.name)}</span>${caret}</button>${menuOpen?`<div class="cell-sources pick-menu" role="menu">${categoryRows(doc,c.id,'data-pick-choice',true)}</div>`:''}</div><button type="button" class="icon-toggle pick-edit" data-edit-category="${esc(c.id)}" title="Настроить категорию «${esc(c.name)}»" aria-label="Настроить категорию «${esc(c.name)}»">${pencil}</button></div>
    <div class="pick-row"><span class="pick-label">Кто в кадре${tip}</span><div class="segments pick-who" role="group" aria-label="Кто в кадре">${whoOptions(section).map(([id,text,full])=>{const on=(p.who||'')===id;return `<button type="button" data-pick-who="who" data-value="${id}" class="${on?'active':''}" aria-pressed="${on}" title="${full}">${text}</button>`;}).join('')}</div></div></div>`;}
  const infoTip=text=>`<span class="info-tip" tabindex="0" role="img" aria-label="${esc(text)}" data-tip="${esc(text)}">i</span>`;
  /* The inspector menu stays in view: it opens up when there is more room above and scrolls on its own. */
  function placeMenu(){const menu=document.querySelector('#inspector .pick-rows .pick-menu');if(!menu)return;const box=document.getElementById('inspector').getBoundingClientRect(),trigger=menu.previousElementSibling.getBoundingClientRect(),
      below=Math.min(box.bottom,innerHeight)-trigger.bottom-12,above=trigger.top-Math.max(box.top,0)-12,up=below<Math.min(menu.scrollHeight,360)&&above>below;
    menu.classList.toggle('up',up);menu.style.maxHeight=Math.max(140,Math.min(360,up?above:below))+'px';
    const on=menu.querySelector('.on');if(on)menu.scrollTop=on.offsetTop-(menu.clientHeight-on.offsetHeight)/2;}
  /* A category pictured for menus and the category list: built-ins by what they show, the photographer's own as a tag. */
  const PIC='#b58fd0',PIC_SOFT='#d9c6e8',n1=v=>+v.toFixed(1);
  function bust(x,base,s,fill=PIC){const r=s*.28,w=s*.42;return `<circle cx="${n1(x)}" cy="${n1(base-s+r)}" r="${n1(r)}" fill="${fill}"/><path d="M${n1(x-w)} ${n1(base)}a${n1(w)} ${n1(s*.4)} 0 0 1 ${n1(2*w)} 0z" fill="${fill}"/>`;}
  const busts=(n,x0,x1,base,s,fill)=>Array.from({length:n},(_,i)=>bust(n===1?(x0+x1)/2:x0+i*(x1-x0)/(n-1),base,s,fill)).join('');
  const PICTOGRAMS={
    any:busts(3,8,22,19,9,PIC_SOFT)+bust(15,20,11,PIC_SOFT),
    class:busts(5,6,24,13.5,6)+busts(6,4.5,25.5,20.5,6.5),
    subgroup:busts(4,6,24,19.5,8),
    few:busts(2,10.5,19.5,20.5,11),
    solo:bust(15,21.5,16),
    candid:bust(10,21,11)+bust(19.5,18.5,8)+`<path d="M23.5 5.5l3-1.8M24.5 9h3" stroke="${PIC}" stroke-width="1.2" stroke-linecap="round"/>`,
    wide:`<circle cx="23" cy="6" r="2.2" fill="${PIC_SOFT}"/><path d="M2 15.5h26" stroke="${PIC_SOFT}" stroke-width="1.2"/>`+busts(3,10,18,18.5,4),
    empty:`<circle cx="22" cy="6.5" r="2.4" fill="${PIC_SOFT}"/><path d="M2.5 19.5l7-8 4.5 4.5 3.5-3 10 6.5z" fill="${PIC}"/>`,
  };
  const TAG=`<path d="M8 6.5h8l5.5 4.5-5.5 4.5H8z" fill="none" stroke="${PIC}" stroke-width="1.4" stroke-linejoin="round"/><circle cx="11" cy="11" r="1.3" fill="${PIC}"/>`;
  function pictogram(c,cls='cat-pic'){return `<svg class="${cls}" viewBox="0 0 30 22" aria-hidden="true"><rect x=".5" y=".5" width="29" height="21" rx="4" fill="#f5effa"/>${c.builtin?PICTOGRAMS[c.id]||'':TAG}</svg>`;}
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
  /* Each arrangement is drawn the same way: two spreads in album order, the rule seen in how they differ. */
  const NEXT='<path d="M35 11.5h5m-2-2 2 2-2 2" fill="none" stroke="#b27fd2" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>';
  const pair=(a,b,people='')=>svg(74,23,spread(0,a)+NEXT+spread(43,b)+(people?`<g transform="translate(0 1)">${people}</g>`:''));
  const shift=(x,body)=>`<g transform="translate(${x} 0)">${body}</g>`;
  const MOSAIC=f=>[[3,3,10,15,f[0]],[18,3,9,7,f[1]],[18,11,9,7,f[2]]];
  const TOGGLES=[['posedFirst','Сначала постановочные','Класс и подгруппы в начале, живые кадры — после.',pair([[3,4,24,13,'photo']],[[3,4,24,13,'photo']],row(5,7,24,15.5,6)+shift(43,figure(8,14,7)+figure(15,17,5)+figure(22,15,7)))],
    ['mixShoots','Личные развороты вперемешку','На развороте ученика — кадры с разных съёмок.',pair(MOSAIC(['a','b','c']),[[3,3,10,7,'c'],[3,11,10,7,'a'],[18,3,9,15,'b']],figure(8.5,17,10)+shift(43,figure(23,17,8)))],
    ['rhythm','Чередовать крупность','Крупный кадр рядом с общими, а не все одинаковые.',pair([[3,3,10,15,'photo'],[18,3,4,7,'photo'],[23,3,4,7,'photo'],[18,11,4,7,'photo'],[23,11,4,7,'photo']],[[3,3,4,7,'photo'],[8,3,4,7,'photo'],[3,11,9,7,'photo'],[18,3,9,15,'photo']],figure(8.5,17,10)+figure(20.5,9.5,4)+figure(25.5,9.5,4)+row(2,20.5,25.5,17.5,3.5)+shift(43,figure(5.5,9.5,4)+figure(10.5,9.5,4)+row(3,5,11,17.5,3.5)+figure(23,17,10)))],
    ['chronology','Общие развороты по съёмкам','Съёмки идут друг за другом, кадры разворота — из одной.',pair(MOSAIC(['a','a','a']),MOSAIC(['b','b','b']))]];
  /* The studio's categories in the album settings: built-ins, then the photographer's own under a small caption. */
  function categoriesPanel(){const list=categories();if(openCategory&&!list.some(c=>c.id===openCategory))openCategory=null;
    const item=c=>{const open=openCategory===c.id;return `<div class="category-item${open?' open':''}"><button type="button" class="category-row" data-cat-open="${esc(c.id)}" aria-expanded="${open}">${pictogram(c,'category-icon')}<span><strong>${esc(c.name)}${c.edited?' <i>изменена</i>':''}</strong>${describe(c.filters).toLowerCase()===c.name.toLowerCase()?'':`<small>${esc(describe(c.filters))}</small>`}</span>${caret}</button>${c.id==='any'?'':`<button type="button" class="category-delete" data-cat-delete="${esc(c.id)}" title="Удалить категорию «${esc(c.name)}»" aria-label="Удалить категорию «${esc(c.name)}»"><img src="/static/assets/editor/trash.svg" alt=""></button>`}${open?categoryEditor(c):''}</div>`;},
      own=list.filter(c=>!c.builtin);
    return `<section class="album-section" id="photo-categories"><h3>Категории снимков ${infoTip('Общие для всех дизайнов и комплектаций.')}</h3><div class="category-list">${list.filter(c=>c.builtin).map(item).join('')}</div>${own.length?`<p class="category-group">Мои</p><div class="category-list">${own.map(item).join('')}</div>`:''}<button type="button" class="wide" data-cat-add>+ Новая категория</button>${studio.removed.length?`<button type="button" class="link-button" data-cat-restore>Вернуть удалённые стандартные (${studio.removed.length})</button>`:''}</section>`;}
  function rulesPanel(doc){const r={...RULES,...(doc.photoRules||{})};
    return `<section class="album-section"><h3>Повторы снимков</h3><div class="rule-choices">${REUSE.map(([id,title,help,sketch])=>{const on=r.reuse===id;return `<button type="button" class="layout-choice${on?' active':''}" data-photo-set="reuse" data-value="${id}" aria-pressed="${on}"><span class="rule-sketch">${sketch}</span><strong>${title}</strong><small>${help}</small></button>`;}).join('')}</div></section>
    <section class="album-section"><h3>Расстановка снимков</h3><div class="rule-toggles">${TOGGLES.map(([key,title,help,sketch])=>{const on=!!r[key];return `<button type="button" class="rule-toggle" role="switch" data-photo-toggle="${key}" aria-checked="${on}"><span class="rule-sketch">${sketch}</span><span class="rule-toggle-text"><strong>${title}</strong><small>${help}</small></span><i class="switch" aria-hidden="true"></i></button>`;}).join('')}</div></section>`;}
  function target(){const t=hooks.target();return t&&t.obj?t:null;}
  function setPick(mutator){const t=target();if(!t)return;hooks.commit(()=>{const pick={...(upgrade(t.obj.pick)||{category:'any'})};mutator(pick);if(!pick.who)delete pick.who;t.obj.pick=pick;});}
  /* Change a category: built-ins are stored as edits in the studio list, own ones are edited in place. */
  function editCategory(id,mutator){saveStudio(s=>{let item=s.items.find(c=>c.id===id);if(!item){const base=categories().find(c=>c.id===id);if(!base)return;item={id,name:base.name,...JSON.parse(JSON.stringify(base.filters))};s.items.push(item);}mutator(item);});}
  /* Slots in any design still pointing at a removed category take any photo; a removed built-in can be brought back. */
  function dropCategory(id){saveStudio(s=>{s.items=s.items.filter(c=>c.id!==id);if(BUILTIN.some(([b])=>b===id))s.removed=[...s.removed,id];});}
  function setRule(key,value){hooks.commit(()=>{const doc=hooks.doc(),rules={...RULES,...(doc.photoRules||{}),[key]:value};doc.photoRules=rules;});}
  function click(e){const ruleSet=e.target.closest('[data-photo-set]');if(ruleSet){setRule(ruleSet.dataset.photoSet,ruleSet.dataset.value);return true;}const toggle=e.target.closest('[data-photo-toggle]');if(toggle){const key=toggle.dataset.photoToggle;setRule(key,!{...RULES,...(hooks.doc().photoRules||{})}[key]);return true;}if(e.target.closest('[data-pick-menu]')){menuOpen=!menuOpen;hooks.inspector();placeMenu();return true;}const choice=e.target.closest('[data-pick-choice]');if(choice){menuOpen=false;setPick(pick=>{pick.category=choice.dataset.pickChoice;});return true;}if(e.target.closest('[data-new-category]')){newCategory();return true;}const who=e.target.closest('[data-pick-who]');if(who){setPick(pick=>{pick.who=who.dataset.value||undefined;});return true;}
    const edit=e.target.closest('[data-edit-category]');if(edit){openCategory=edit.dataset.editCategory;hooks.rules();requestAnimationFrame(()=>document.querySelector('.category-item.open')?.scrollIntoView({block:'nearest'}));return true;}
    const open=e.target.closest('[data-cat-open]');if(open){openCategory=openCategory===open.dataset.catOpen?null:open.dataset.catOpen;hooks.inspector();return true;}
    const chip=e.target.closest('[data-cat-chip]');if(chip){const key=chip.dataset.catChip,value=chip.dataset.value;editCategory(openCategory,item=>{const list=new Set(item[key]||[]);list.has(value)?list.delete(value):list.add(value);item[key]=[...list];});return true;}
    const set=e.target.closest('[data-cat-set]');if(set){editCategory(openCategory,item=>{item[set.dataset.catSet]=set.dataset.value||null;});return true;}
    const reset=e.target.closest('[data-cat-reset]');if(reset){const id=reset.dataset.catReset;saveStudio(s=>{s.items=s.items.filter(c=>c.id!==id);});return true;}
    const del=e.target.closest('[data-cat-delete]');if(del){openCategory=null;dropCategory(del.dataset.catDelete);return true;}
    if(e.target.closest('[data-cat-restore]')){saveStudio(s=>{s.removed=[];});return true;}
    if(e.target.closest('[data-cat-add]')){const id='c-'+Math.random().toString(36).slice(2,8);openCategory=id;saveStudio(s=>{s.items.push({id,name:'Новая категория'});});requestAnimationFrame(()=>{const input=document.querySelector('.category-item.open [data-cat-name]');input?.scrollIntoView({block:'nearest'});input?.select();});return true;}
    return false;}
  function change(e){const el=e.target;if(el.matches('[data-pick-category]')){setPick(pick=>{pick.category=el.value;});return true;}
    if(el.dataset.catName){const name=el.value.trim().slice(0,40);if(name)editCategory(el.dataset.catName,item=>{item.name=name;});else el.value=category(hooks.doc(),el.dataset.catName).name;return true;}
    return false;}
  function strip(doc){return JSON.parse(JSON.stringify(doc,(k,v)=>k==='dataUrl'?undefined:v));}
  /* Ask the server what the draft would pick on the test shoot; re-render when it answers. */
  function refresh(doc,view){lastView=view;const payload=JSON.stringify({document:strip(doc),students:view.students,teachers:view.teachers,owner:view.owner});if(payload===sent)return;sent=payload;clearTimeout(timer);const mine=++version;timer=setTimeout(async()=>{try{const r=await fetch('/api/master-templates/photo-preview',{method:'POST',headers:{'Content-Type':'application/json'},body:payload});const value=await r.json();if(mine!==version)return;if(!r.ok)throw Error(typeof value.detail==='string'?value.detail:'Превью подбора недоступно');data=value;failed='';}catch(error){if(mine!==version)return;failed=error.message||'Превью подбора недоступно';}keepFocus(()=>hooks?.updated());},350);}
  /* Re-rendering the album settings must not take the caret out of a category name being typed. */
  function keepFocus(render){const el=document.activeElement,id=el?.dataset?.catName,start=el?.selectionStart,end=el?.selectionEnd,value=el?.value;render();
    if(!id)return;const input=document.querySelector(`[data-cat-name="${CSS.escape(id)}"]`);if(!input||input===el)return;input.value=value;input.focus();input.setSelectionRange(start,end);}
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
  function bind(value){hooks=value;loadStudio();}
  document.addEventListener('pointerdown',e=>{if(menuOpen&&!e.target.closest('.pick-picker')){menuOpen=false;hooks?.inspector();}},true);
  document.addEventListener('keydown',e=>{if(menuOpen&&e.key==='Escape'){e.stopImmediatePropagation();menuOpen=false;hooks?.inspector();}},true);
  return {bind,panel,rulesPanel,categoriesPanel,click,change,refresh,image,slot,ready,categories,category,describe,migrate,upgrade,categoryRows,newCategory};
})();
