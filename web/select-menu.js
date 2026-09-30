// One dropdown look for the whole service: every native <select> keeps its value, form and change events,
// but opens our menu instead of the system list. Filter chips anchor the menu to the chip itself.
// Touch screens keep the native picker, which is the better one there.
(()=>{
  const coarse=matchMedia('(pointer: coarse)');
  const norm=v=>String(v||'').toLocaleLowerCase('ru').replace(/ё/g,'е').trim();
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const check='<svg class="sm-check" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>';
  const SEARCH_FROM=12;
  let current=null;

  const skip=s=>s.multiple||s.size>1||s.disabled||coarse.matches||s.closest('[data-native-select]');
  const anchorOf=s=>s.closest('.filter-chip')||s;

  function items(s){
    let html='';
    for(const node of s.children){
      if(node.tagName==='OPTGROUP'){
        const inner=[...node.children].filter(o=>!o.hidden).map(item).join('');
        if(inner)html+=`<div class="sm-group" role="group" aria-label="${esc(node.label)}"><div class="sm-group-label">${esc(node.label)}</div>${inner}</div>`;
      }else if(node.tagName==='OPTION'&&!node.hidden)html+=item(node);
    }
    return html;
  }
  function item(o){
    const text=o.dataset.menuLabel||o.textContent,color=o.dataset.color;
    return `<div class="sm-item${o.value===''?' sm-any':''}" role="option" id="sm-opt-${o.index}" data-i="${o.index}" aria-selected="${o.selected}"${o.disabled?' aria-disabled="true"':''} data-key="${esc(norm(text))}">${color?`<i class="sm-dot" style="--dot:${esc(color)}"></i>`:''}<span>${esc(text)}</span>${check}</div>`;
  }

  function place(){
    if(!current)return;
    if(!current.select.isConnected){close();return;}
    const {menu,anchor}=current,box=anchor.getBoundingClientRect(),gap=6,margin=12;
    const width=Math.max(box.width,anchor===current.select?0:220);
    const below=innerHeight-box.bottom-margin,above=box.top-margin;
    const natural=menu.scrollHeight,up=below<Math.min(natural,280)&&above>below;
    menu.style.maxHeight=Math.max(120,Math.min(360,up?above-gap:below-gap))+'px';
    menu.style.minWidth=width+'px';
    const left=Math.min(box.left,innerWidth-Math.max(width,menu.offsetWidth)-margin);
    menu.style.left=Math.max(margin,left)+'px';
    menu.style.top=up?'':box.bottom+gap+'px';
    menu.style.bottom=up?innerHeight-box.top+gap+'px':'';
    menu.classList.toggle('sm-up',up);
  }

  function visible(){return [...current.list.querySelectorAll('.sm-item:not([hidden]):not([aria-disabled])')];}
  function activate(el,scroll=true){
    current.list.querySelector('.sm-active')?.classList.remove('sm-active');
    if(!el){current.focus.removeAttribute('aria-activedescendant');return;}
    el.classList.add('sm-active');current.focus.setAttribute('aria-activedescendant',el.id);
    if(scroll)el.scrollIntoView({block:'nearest'});
  }
  function move(step){
    const all=visible();if(!all.length)return;
    const at=all.indexOf(current.list.querySelector('.sm-active'));
    activate(all[at<0?(step>0?0:all.length-1):Math.max(0,Math.min(all.length-1,at+step))]);
  }

  function open(s){
    close();
    const anchor=anchorOf(s),host=s.closest('dialog[open]')||document.body,many=s.options.length>=SEARCH_FROM;
    const menu=document.createElement('div');
    menu.className='sm-menu';
    menu.innerHTML=`${many?'<div class="sm-search-row"><input class="sm-search" type="search" placeholder="Найти" aria-label="Найти в списке" autocomplete="off"></div>':''}<div class="sm-list" role="listbox" tabindex="-1" aria-label="${esc(s.getAttribute('aria-label')||'')}">${items(s)}</div>`;
    host.appendChild(menu);
    const list=menu.querySelector('.sm-list'),search=menu.querySelector('.sm-search');
    current={select:s,anchor,menu,list,search,focus:search||list};
    anchor.classList.add('sm-open');s.setAttribute('aria-expanded','true');
    place();
    current.focus.focus({preventScroll:true});
    activate(list.querySelector('[aria-selected="true"]:not(.sm-any)')||visible()[0]);
    menu.addEventListener('mousedown',e=>{if(e.target!==search)e.preventDefault();});
    list.addEventListener('mousemove',e=>{const el=e.target.closest('.sm-item:not([aria-disabled])');if(el&&!el.classList.contains('sm-active'))activate(el,false);});
    list.addEventListener('click',e=>{const el=e.target.closest('.sm-item:not([aria-disabled])');if(el)choose(el);});
    menu.addEventListener('keydown',keys);
    if(search)search.addEventListener('input',()=>{
      const q=norm(search.value);let any=false;
      for(const el of list.querySelectorAll('.sm-item')){const hit=!q||el.dataset.key.includes(q);el.hidden=!hit;any||=hit;}
      for(const g of list.querySelectorAll('.sm-group'))g.hidden=!g.querySelector('.sm-item:not([hidden])');
      list.querySelector('.sm-empty')?.remove();
      if(!any)list.insertAdjacentHTML('beforeend','<div class="sm-empty">Ничего не найдено</div>');
      activate(visible()[0]);
    });
  }

  function close(refocus=false){
    if(!current)return;
    const {select,anchor,menu}=current;
    current=null;menu.remove();anchor.classList.remove('sm-open');select.setAttribute('aria-expanded','false');
    if(refocus)select.focus({preventScroll:true});
  }

  function choose(el){
    const s=current.select,o=s.options[+el.dataset.i];
    close(true);
    if(!o||o.selected)return;
    s.value=o.value;
    s.dispatchEvent(new Event('input',{bubbles:true}));
    s.dispatchEvent(new Event('change',{bubbles:true}));
  }

  function keys(e){
    if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();move(e.key==='ArrowDown'?1:-1);}
    else if(e.key==='Home'||e.key==='End'){if(e.target===current.search)return;e.preventDefault();const all=visible();activate(e.key==='Home'?all[0]:all[all.length-1]);}
    else if(e.key==='Enter'||(e.key===' '&&e.target!==current.search)){e.preventDefault();const el=current.list.querySelector('.sm-active');if(el)choose(el);}
    else if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close(true);}
    else if(e.key==='Tab')close(true);
  }

  document.addEventListener('mousedown',e=>{
    const s=e.target.closest?.('select');
    if(current&&!current.menu.contains(e.target)&&s!==current.select)close();
    if(!s||e.button!==0||skip(s))return;
    e.preventDefault();
    if(current?.select===s){close(true);return;}
    s.focus({preventScroll:true});open(s);
  },true);
  document.addEventListener('keydown',e=>{
    const s=e.target;
    if(s?.tagName!=='SELECT'||skip(s)||current)return;
    if(['ArrowDown','ArrowUp','Enter',' '].includes(e.key)&&!e.altKey&&!e.metaKey){e.preventDefault();open(s);}
  },true);
  addEventListener('resize',()=>close());
  document.addEventListener('scroll',e=>{if(current&&!current.menu.contains(e.target))place();},true);
  document.addEventListener('close',()=>close(),true);
})();
