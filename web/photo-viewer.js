/* Large view of one frame. ←/→ walk the frames shown on the page (or in the open dialog), Esc or a click outside closes.
   Opens by a click on a view-only tile, or a double click on any tile while sorting is still open.
   Uses the V2 globals (state, esc, svgIcon, personName). */
window.PhotoViewer=(()=>{
  let list=[],at=0,dialog=null;

  function ensure(){
    if(dialog)return dialog;
    dialog=document.createElement('dialog');dialog.className='photo-viewer';dialog.setAttribute('aria-label','Просмотр кадра');
    dialog.addEventListener('click',e=>{
      const b=e.target.closest('[data-pv]');
      if(b){step(b.dataset.pv==='next'?1:b.dataset.pv==='prev'?-1:0);if(b.dataset.pv==='close')dialog.close();return;}
      if(!e.target.closest('img,.pv-caption'))dialog.close();
    });
    dialog.addEventListener('keydown',e=>{
      if(e.key==='ArrowRight'){e.preventDefault();step(1);}
      if(e.key==='ArrowLeft'){e.preventDefault();step(-1);}
    });
    document.body.append(dialog);
    return dialog;
  }

  function step(d){if(!d||list.length<2)return;at=(at+d+list.length)%list.length;draw();}

  function draw(){
    const o=state.order,p=o?.photos.find(x=>x.id===list[at]);
    if(!p){dialog.close();return;}
    const index=o.persons.findIndex(x=>x.id===p.person_id),person=o.persons[index],chosen=person?.selected_photo_id===p.id;
    const v=p.retouch_version?'?v='+p.retouch_version:'';
    const mark=chosen?`<span class="pv-mark">${svgIcon(p.retouch_version?'check':'star',12)}${p.retouch_version?'ретушь':'выбор'}</span>`:'';
    const nav=list.length>1?`<button type="button" class="pv-nav prev" data-pv="prev" aria-label="Предыдущий кадр">${svgIcon('left',28)}</button><button type="button" class="pv-nav next" data-pv="next" aria-label="Следующий кадр">${svgIcon('right',28)}</button>`:'';
    dialog.innerHTML=`<img src="/media/${p.id}/full${v}" alt="${esc(p.filename)}">${nav}<button type="button" class="pv-close" data-pv="close" aria-label="Закрыть">${svgIcon('x',22)}</button><div class="pv-caption"><b>${esc(p.filename)}</b>${person?`<span>${esc(personName(person,index))}</span>`:''}${mark}<span class="pv-small" hidden>миниатюра</span>${list.length>1?`<span class="pv-count">${at+1} из ${list.length}</span>`:''}</div>`;
    // Unchosen portraits keep only a thumbnail once the student has chosen.
    const img=dialog.querySelector('img');
    img.onerror=()=>{img.onerror=null;img.src=`/media/${p.id}/thumb${v}`;dialog.querySelector('.pv-small').hidden=false;};
  }

  function open(id,from){
    const scope=from?.closest('dialog')||document.getElementById('workspace')||document;
    list=[...scope.querySelectorAll('.photo-tile[data-id]')].map(t=>t.dataset.id);
    at=Math.max(0,list.indexOf(id));if(!list.length)list=[id];
    ensure();draw();if(!dialog.open)dialog.showModal();
  }

  const viewable=e=>!state.personPick&&e.target.closest?.('.photo-tile[data-view]');
  document.addEventListener('click',e=>{const tile=viewable(e);if(!tile||e.target.closest('button,a'))return;e.preventDefault();open(tile.dataset.id,tile);});
  document.addEventListener('keydown',e=>{if(e.key!=='Enter'&&e.key!==' ')return;const tile=viewable(e);if(!tile)return;e.preventDefault();open(tile.dataset.id,tile);});
  document.addEventListener('dblclick',e=>{const tile=!state.personPick&&e.target.closest('.photo-tile[data-id]');if(!tile||e.target.closest('button,a'))return;e.preventDefault();open(tile.dataset.id,tile);});

  return {open};
})();
