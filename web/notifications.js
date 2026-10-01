// Notifications on «Все заказы»: a bell next to the search opens the news from classes and finished processing.
// An item leads straight to the part of the order it is about; the badge counts what has not been opened yet.
(()=>{
  const bell='<svg class="ico" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg>';
  const KINDS={
    forms_complete:()=>({stage:'forms',tab:'client',text:'Все заполнили анкеты'}),
    approved:()=>({stage:'approval',tab:'layout',text:'Класс согласовал макет'}),
    corrections:n=>({stage:'approval',icon:'approve-alert',tab:'layout',text:n.count>1?`Правки от класса: ${n.count}`:'Класс прислал правку'}),
    teacher_proposals:n=>({stage:'forms',icon:'users',tab:'teachers',text:n.count>1?`Класс предложил учителей: ${n.count}`:'Класс предложил учителя'}),
    photos_ready:n=>n.review_count?{stage:'photos',tab:'review',text:`Лица распознаны · ${n.review_count} на проверку`}:{stage:'photos',icon:'photo-done',tab:'photos',text:'Фото обработаны'},
  };
  let feed={items:[],unread:0},request=null;

  const ago=iso=>{const m=Math.round((Date.now()-Date.parse(iso))/6e4);if(m<1)return 'только что';if(m<60)return `${m} мин назад`;const h=Math.round(m/60);if(h<24)return `${h} ч назад`;const d=Math.round(h/24);return d===1?'вчера':`${count(d,'день','дня','дней')} назад`;};
  const root=()=>document.querySelector('.registry .notify');

  function item(n){
    const k=(KINDS[n.kind]||KINDS.approved)(n);
    return `<a class="notify-item${n.read?'':' unread'}" href="#order/${encodeURIComponent(n.order_id)}/${k.tab}" data-id="${esc(n.id)}"><span class="notify-ico" style="--stage:${stageOf(k.stage)[2]}">${svgIcon(k.icon||STAGE_ICONS[k.stage],16)}</span><span class="notify-text"><strong>${esc(n.school)} · ${esc(n.class_name)}</strong><span>${esc(k.text)}</span></span><time datetime="${esc(n.created_at)}">${ago(n.created_at)}</time></a>`;
  }

  function draw(){
    const el=root();if(!el)return;
    const badge=el.querySelector('.notify-badge');
    badge.hidden=!feed.unread;badge.textContent=feed.unread>9?'9+':feed.unread;
    el.querySelector('.notify-toggle').setAttribute('aria-label',feed.unread?`Уведомления: ${feed.unread} новых`:'Уведомления');
    const panel=el.querySelector('.notify-panel');
    if(panel.hidden)return;
    panel.innerHTML=`<div class="notify-head"><strong>Уведомления</strong>${feed.unread?'<button type="button" class="notify-read-all">Прочитать все</button>':''}</div><div class="notify-list">${feed.items.map(item).join('')||'<p class="notify-empty">Пока ничего нового</p>'}</div>`;
  }

  async function load(){
    if(request)return request;
    request=api('/notifications').then(data=>{feed=data;draw();}).catch(()=>{}).finally(()=>{request=null;});
    return request;
  }

  function toggle(open){
    const el=root();if(!el)return;
    const panel=el.querySelector('.notify-panel'),button=el.querySelector('.notify-toggle');
    open??=panel.hidden;
    panel.hidden=!open;button.setAttribute('aria-expanded',String(open));el.classList.toggle('open',open);
    if(open){draw();load();}
  }

  function mount(){
    const tools=document.querySelector('#orders-search-toggle')?.closest('.queue-tools');
    if(!tools||tools.querySelector('.notify'))return;
    tools.insertAdjacentHTML('afterbegin',`<div class="notify"><button type="button" class="notify-toggle" aria-haspopup="true" aria-expanded="false" aria-label="Уведомления" title="Уведомления">${bell}<span class="notify-badge" hidden></span></button><div class="notify-panel" hidden></div></div>`);
    const el=root();
    el.querySelector('.notify-toggle').onclick=()=>toggle();
    el.querySelector('.notify-panel').onclick=e=>{
      if(e.target.closest('.notify-read-all')){
        feed={items:feed.items.map(n=>({...n,read:true})),unread:0};draw();
        api('/notifications/read',{method:'POST'}).catch(()=>{}).then(load);
        return;
      }
      const link=e.target.closest('.notify-item');
      if(!link)return;
      if(link.classList.contains('unread'))api(`/notifications/${encodeURIComponent(link.dataset.id)}/read`,{method:'POST'}).catch(()=>{});
      toggle(false);
    };
    draw();load();
  }

  new MutationObserver(mount).observe(document.getElementById('main'),{childList:true});
  mount();
  document.addEventListener('mousedown',e=>{const el=root();if(el&&el.classList.contains('open')&&!el.contains(e.target))toggle(false);});
  document.addEventListener('keydown',e=>{const el=root();if(e.key==='Escape'&&el?.classList.contains('open')){toggle(false);el.querySelector('.notify-toggle').focus();}});
  setInterval(()=>{if(!document.hidden&&root())load();},15000);
})();
