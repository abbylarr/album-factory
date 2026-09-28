// Shared read-only spread renderer: the order layout editor and the master class preview draw albums the same way.
// Own escaping: the master editor keeps its helpers private, so a page-level esc() is not guaranteed.
const layoutEscape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function layoutSpread(doc,owner,index){
  const variant=doc.variants.find(v=>v.owner===owner)||doc.variants[0];if(!variant)return null;
  const key=variant.sequence[index];return key?.startsWith('cover[')?doc.covers[variant.owner]:doc.shared_spreads[key]||doc.variant_spreads[variant.owner]?.[key];
}
function layoutCanvas(spread,doc,photos,interactive=true,full=interactive){
  const [width,height]=spread.section==='cover'?doc.cover_size_mm:doc.spread_size_mm;
  const cqw=mm=>mm/width*100+'cqw',visible=spread.elements.filter(e=>!e.hidden),cast=new Set();
  const shadowOf=(e,prop='box-shadow')=>e.shadow?`${prop}:${cqw(e.shadow.offsetX||0)} ${cqw(e.shadow.offsetY||0)} ${cqw(e.shadow.blur||0)} ${layoutEscape(e.shadow.color||'#000000')}${Math.round((e.shadow.opacity??35)/100*255).toString(16).padStart(2,'0')};`:'';
  // Photo strokes are drawn only over a real photo, as in the PDF; the shadow is cast by the stroke's outer edge.
  const photoStroke=e=>e.type==='photo'&&e.photo&&(e.strokeWidth||0)>0,reach=e=>{const sw=e.strokeWidth||0;return !sw||(e.type==='photo'&&!e.photo)?0:e.strokeAlign==='outside'?sw:e.strokeAlign==='inside'?0:sw/2;};
  const place=(e,pad)=>{const [rawX,rawY,rawW,rawH]=e.box,[x,y,w,h]=[rawX-pad,rawY-pad,rawW+2*pad,rawH+2*pad],center=e.rotation_center||[rawX+rawW/2,rawY+rawH/2];return `left:${x/width*100}%;top:${y/height*100}%;width:${w/width*100}%;height:${h/height*100}%;opacity:${(e.opacity??100)/100};transform:rotate(${e.angle||0}deg);transform-origin:${(center[0]-x)/w*100}% ${(center[1]-y)/h*100}%;border-radius:${e.mask==='ellipse'?'50%':cqw(e.radius?e.radius+pad:0)};`;};
  // Vignette cards share one shadow layer below all of them, so a card's shadow never falls on its neighbour.
  const shadowLayer=e=>{const group=e.shadowGroup;if(!group||cast.has(group))return '';cast.add(group);return visible.filter(m=>m.shadowGroup===group).map(m=>`<div class="layout-layer" style="${place(m,reach(m))}${shadowOf(m)}pointer-events:none"></div>`).join('');};
  const strokeLayer=e=>photoStroke(e)?`<div class="layout-layer" style="${place(e,reach(e))}${e.shadowGroup?'':shadowOf(e)}border:${cqw(e.strokeWidth)} solid ${layoutEscape(e.stroke||'#333333')};pointer-events:none"></div>`:'';
  const markup=visible.map(e=>shadowLayer(e)+element(e)+strokeLayer(e)).join('');
  function element(e){
    const stroke=e.type==='frame'?(e.strokeWidth||0):0,pad=e.type==='frame'?(e.strokeAlign==='outside'?stroke:e.strokeAlign==='center'?stroke/2:0):0,shape=['rect','ellipse','line','frame'].includes(e.type),shadow=e.shadowGroup||photoStroke(e)?'':shadowOf(e,e.type==='text'?'text-shadow':'box-shadow'),box=`${place(e,pad)}${shadow}border:${shape?cqw(e.strokeWidth||0):0} solid ${layoutEscape(e.stroke||'#333333')};`,selected=interactive&&layoutUI.element===e.key?' selected':'';
    if(e.type==='svg')return `<div class="layout-layer" style="${box};border:0"><img alt="" src="data:image/svg+xml;charset=utf-8,${encodeURIComponent(e.svg||'')}" style="width:100%;height:100%;object-fit:fill;transform:scale(${e.flipX?-1:1},${e.flipY?-1:1})"></div>`;if(['rect','ellipse','line','frame'].includes(e.type))return `<div class="layout-layer" style="${box};background:${e.type==='frame'?'transparent':layoutEscape(e.fill)};${e.type==='ellipse'?'border-radius:50%':''}"></div>`;
    const tag=interactive?'button':'div',attribute=interactive?` data-layout-element="${layoutEscape(e.key)}"`:'';
    if(e.type==='photo'){
      const meta=photos.find(p=>p.id===e.photo),crop=e.crop;
      const image=meta&&crop?`<img src="${layoutEscape(meta.url||('/media/'+encodeURIComponent(e.photo)+'/'+(full?'full':'thumb')))}" alt="" style="width:${meta.width/crop[2]*100}%;height:${meta.height/crop[3]*100}%;left:${-crop[0]/crop[2]*100}%;top:${-crop[1]/crop[3]*100}%">`:'';
      const placeholder=interactive?'<img class="layout-add-icon" src="/static/assets/layout-add.svg" alt=""><span class="sr-only">Выбрать фотографию</span>':'';
      return `<${tag} class="layout-layer layout-photo${selected}${image?'':' empty'}"${attribute} style="${box};${e.mask==='ellipse'?'border-radius:50%;':''}" ${interactive?'title="Заменить фотографию" aria-label="Заменить фотографию"':''}>${image||placeholder}</${tag}>`;
    }
    return `<${tag} class="layout-layer layout-text${selected}${e.text?'':' empty'}"${attribute} style="${box};font-size:${e.size*(doc.master_template?.3528:1)/width*100}cqw;color:${layoutEscape(e.color)};font-family:${e.font==='display'?'Georgia,serif':e.font==='times'?'Times New Roman,serif':'Arial,sans-serif'};text-align:${e.align};${e.valign==='middle'?'display:flex;align-items:center;justify-content:'+({left:'flex-start',center:'center',right:'flex-end'}[e.align])+';':''}">${e.text?layoutEscape(e.text).replace(/\n/g,'<br>'):interactive?'Добавить подпись':''}</${tag}>`;
  }
  const pages=interactive&&spread.section==='custom'?['left','right'].map(side=>{
    const blank=(spread.page_templates?.[side]||'blank')==='blank';
    const label=side==='left'?'левой':'правой';
    return `<button type="button" class="layout-page-hit${blank?' is-blank':''}" data-layout-page="${side}" aria-label="Выбрать шаблон ${label} страницы" style="left:${side==='right'?'50%':'0'}">${blank?'<img class="layout-add-icon" src="/static/assets/layout-add.svg" alt="">':''}</button>${blank?'':`<button type="button" class="layout-page-change" data-layout-page="${side}" aria-label="Сменить шаблон ${label} страницы"></button>`}`;
  }).join(''):'';
  return `<div class="layout-canvas${spread.section==='custom'?' is-custom':''}" style="aspect-ratio:${width}/${height}">${pages}${markup}${interactive&&spread.section!=='cover'?'<img class="layout-divider" src="/static/assets/layout-divider.svg" alt="">':''}</div>`;
}
