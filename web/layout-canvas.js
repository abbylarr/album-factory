// Shared read-only spread renderer: the order layout editor and the master class preview draw albums the same way.
function layoutSpread(doc,owner,index){
  const variant=doc.variants.find(v=>v.owner===owner)||doc.variants[0];if(!variant)return null;
  const key=variant.sequence[index];return key?.startsWith('cover[')?doc.covers[variant.owner]:doc.shared_spreads[key]||doc.variant_spreads[variant.owner]?.[key];
}
function layoutCanvas(spread,doc,photos,interactive=true,full=interactive){
  const [width,height]=spread.section==='cover'?doc.cover_size_mm:doc.spread_size_mm;
  const markup=spread.elements.filter(e=>!e.hidden).map(e=>{
    const [rawX,rawY,rawW,rawH]=e.box,stroke=e.type==='frame'?(e.strokeWidth||0):0,pad=e.type==='frame'?(e.strokeAlign==='outside'?stroke:e.strokeAlign==='center'?stroke/2:0):0,[x,y,w,h]=[rawX-pad,rawY-pad,rawW+2*pad,rawH+2*pad],center=e.rotation_center||[rawX+rawW/2,rawY+rawH/2],shadow=e.shadow?`box-shadow:${(e.shadow.offsetX||0)/width*100}cqw ${(e.shadow.offsetY||0)/width*100}cqw ${(e.shadow.blur||0)/width*100}cqw ${esc(e.shadow.color||'#000000')}${Math.round((e.shadow.opacity??35)/100*255).toString(16).padStart(2,'0')};`:'',appearance=`${shadow}transform:rotate(${e.angle||0}deg);transform-origin:${(center[0]-x)/w*100}% ${(center[1]-y)/h*100}%;border:${(e.strokeWidth||0)/width*100}cqw solid ${esc(e.stroke||'#333333')};border-radius:${(e.radius||0)/width*100}cqw;`,box=`left:${x/width*100}%;top:${y/height*100}%;width:${w/width*100}%;height:${h/height*100}%;opacity:${(e.opacity??100)/100};${appearance}`,selected=interactive&&layoutUI.element===e.key?' selected':'';
    if(e.type==='svg')return `<div class="layout-layer" style="${box};border:0"><img alt="" src="data:image/svg+xml;charset=utf-8,${encodeURIComponent(e.svg||'')}" style="width:100%;height:100%;object-fit:fill;transform:scale(${e.flipX?-1:1},${e.flipY?-1:1})"></div>`;if(['rect','ellipse','line','frame'].includes(e.type))return `<div class="layout-layer" style="${box};background:${e.type==='frame'?'transparent':esc(e.fill)};${e.type==='ellipse'?'border-radius:50%':''}"></div>`;
    const tag=interactive?'button':'div',attribute=interactive?` data-layout-element="${esc(e.key)}"`:'';
    if(e.type==='photo'){
      const meta=photos.find(p=>p.id===e.photo),crop=e.crop;
      const image=meta&&crop?`<img src="${esc(meta.url||('/media/'+encodeURIComponent(e.photo)+'/'+(full?'full':'thumb')))}" alt="" style="width:${meta.width/crop[2]*100}%;height:${meta.height/crop[3]*100}%;left:${-crop[0]/crop[2]*100}%;top:${-crop[1]/crop[3]*100}%">`:'';
      const placeholder=interactive?'<img class="layout-add-icon" src="/static/assets/layout-add.svg" alt=""><span class="sr-only">Выбрать фотографию</span>':'';
      return `<${tag} class="layout-layer layout-photo${selected}${image?'':' empty'}"${attribute} style="${box};${e.mask==='ellipse'?'border-radius:50%;':''}" ${interactive?'title="Заменить фотографию" aria-label="Заменить фотографию"':''}>${image||placeholder}</${tag}>`;
    }
    return `<${tag} class="layout-layer layout-text${selected}${e.text?'':' empty'}"${attribute} style="${box};font-size:${e.size*(doc.master_template?.3528:1)/width*100}cqw;color:${esc(e.color)};font-family:${e.font==='display'?'Georgia,serif':e.font==='times'?'Times New Roman,serif':'Arial,sans-serif'};text-align:${e.align};${e.valign==='middle'?'display:flex;align-items:center;justify-content:'+({left:'flex-start',center:'center',right:'flex-end'}[e.align])+';':''}">${e.text?esc(e.text).replace(/\n/g,'<br>'):interactive?'Добавить подпись':''}</${tag}>`;
  }).join('');
  const pages=interactive&&spread.section==='custom'?['left','right'].map(side=>{
    const blank=(spread.page_templates?.[side]||'blank')==='blank';
    const label=side==='left'?'левой':'правой';
    return `<button type="button" class="layout-page-hit${blank?' is-blank':''}" data-layout-page="${side}" aria-label="Выбрать шаблон ${label} страницы" style="left:${side==='right'?'50%':'0'}">${blank?'<img class="layout-add-icon" src="/static/assets/layout-add.svg" alt="">':''}</button>${blank?'':`<button type="button" class="layout-page-change" data-layout-page="${side}" aria-label="Сменить шаблон ${label} страницы"></button>`}`;
  }).join(''):'';
  return `<div class="layout-canvas${spread.section==='custom'?' is-custom':''}" style="aspect-ratio:${width}/${height}">${pages}${markup}${interactive&&spread.section!=='cover'?'<img class="layout-divider" src="/static/assets/layout-divider.svg" alt="">':''}</div>`;
}
