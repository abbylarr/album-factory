window.MasterPlanner=function(documentModel,view){
let planning=[];
  const TEACHERS = ['Елена Александровна Морозова','Андрей Сергеевич Волков','Ольга Викторовна Соколова','Ирина Павловна Белова','Михаил Юрьевич Орлов','Наталья Олеговна Миронова','Анна Игоревна Крылова','Сергей Петрович Зайцев','Мария Андреевна Лебедева','Дмитрий Алексеевич Попов'];
  const STUDENTS = ['Анна Соколова','Михаил Волков','София Миронова','Александр Орлов','Мария Белова','Иван Лебедев','Полина Крылова','Артём Зайцев','Дарья Попова','Даниил Морозов','Елизавета Иванова','Максим Петров'];
  const SUBJECTS = ['Классный руководитель','Математика','Русский язык','История','Физика','Биология','Литература','География','Английский язык','Информатика'];
  const getSection = key => documentModel.sections.find(section=>section.id===key);
  const getTemplatePage = pageId => documentModel.sections.flatMap(section=>section.spreads.flatMap(item=>item.pages)).find(item=>item.id===pageId);
  const getLayer = layerId => documentModel.sections.flatMap(section=>section.spreads.flatMap(item=>item.pages.flatMap(p=>p.layers))).find(item=>item.id===layerId);
  function people(source){const count=source==='teachers'?view.teachers:view.students,names=source==='teachers'?TEACHERS:STUDENTS;return Array.from({length:count},(_,i)=>({id:(source==='teachers'?'t':'s')+i,name:view.long&&i===1?'Александра Константиновна Рождественская-Воскресенская':names[i%names.length]+(i>=names.length?` ${Math.floor(i/names.length)+1}`:''),role:source==='teachers'?(i===0?SUBJECTS[0]:SUBJECTS[1+(i-1)%9]):'11 «А»',detail:source==='teachers'?(i===0?SUBJECTS[0]:SUBJECTS[1+(i-1)%9]):'Наши лучшие моменты впереди',missing:view.missing&&i===1}));}
  function templatePages(section){return section.spreads.flatMap(item=>item.pages);}
  /* A vignette card: the photo and its captions. Each caption sits in a zone around the photo (above, below, left, right) or over it; captions of one zone stack name first. Mirrors master_layout.card_frame. */
  const CARD_ZONES=['above','below','left','right','over'];
  function cardFrame(settings){
    const ratio=Number(settings.photoRatio)||.75,gap=Number(settings.photoNameGap??3),inset=Number(settings.overInset??3),between=Number(settings.nameDetailGap??2),side=Number(settings.captionWidth)||40,sideAlign=Math.min(1,Math.max(0,Number(settings.sideAlign??.5)||0)),
      nameH=settings.fontSize*.3528*(settings.lineHeight||1.25)*2,
      detailH=settings.showDetail?(settings.detailFontSize||9)*.3528*(settings.detailLineHeight||1.25)*2:0,
      texts=[{key:'name',zone:CARD_ZONES.includes(settings.nameAt)?settings.nameAt:'below',h:nameH}].concat(settings.showDetail?[{key:'detail',zone:CARD_ZONES.includes(settings.detailAt)?settings.detailAt:'below',h:detailH}]:[]),
      stack=zone=>{const items=texts.filter(t=>t.zone===zone);return items.length?items.reduce((sum,t)=>sum+t.h,0)+between*(items.length-1):0;},
      zones=Object.fromEntries(CARD_ZONES.map(zone=>[zone,stack(zone)]));
    return {ratio,gap,inset,between,side,sideAlign,nameH,detailH,texts,zones,
      top:zones.above?zones.above+gap:0,bottom:zones.below?zones.below+gap:0,
      left:zones.left?side+gap:0,right:zones.right?side+gap:0,sideH:Math.max(zones.left,zones.right)};
  }
  /* Boxes of the photo and captions in card coordinates for a photo width. Caption boxes reserve two lines. */
  function cardParts(photoW,frame){
    const f=frame,photoH=photoW/f.ratio,body=Math.max(photoH,f.sideH),parts={photo:{x:f.left,y:f.top,w:photoW,h:photoH}},pad=Math.min(f.inset,photoW/4);
    for(const zone of CARD_ZONES){
      const items=f.texts.filter(t=>t.zone===zone);if(!items.length)continue;
      const h=f.zones[zone];let x=f.left,w=photoW,y;
      if(zone==='above')y=0;
      else if(zone==='below')y=f.top+body+f.gap;
      else if(zone==='over'){x=f.left+pad;w=Math.max(1,photoW-2*pad);y=f.top+photoH-pad-h;}
      else{x=zone==='left'?0:f.left+photoW+f.gap;w=f.side;y=f.top+Math.max(0,(photoH-h)*f.sideAlign);}
      for(const t of items){parts[t.key]={x,y,w,h:t.h,zone};y+=t.h+f.between;}
    }
    return {w:f.left+photoW+f.right,h:f.top+body+f.bottom,photoW,photoH,parts};
  }
  const CARD_ANCHORS=['top-left','top','top-right','left','center','right','bottom-left','bottom','bottom-right'];
  function cardAnchor(anchor){const i=CARD_ANCHORS.indexOf(anchor),at=i<0?4:i;return [(at%3)/2,Math.floor(at/3)/2];}
  /* The narrowest caption a name still reads in at its smallest size: a teacher's first name and patronymic on one line
     (about 22 letters), a student's longest word (about 15); capitals are wider. Beside the photo a name may take more
     lines, so there only its longest word must fit. Mirrors master_layout.caption_floor. */
  function captionFloor(settings){const side=settings.nameAt==='left'||settings.nameAt==='right',letters=settings.source==='teachers'&&!side?22:15,em=settings.textCase==='upper'?.62:.52;return letters*em*(Number(settings.minFontSize)||Number(settings.fontSize)||10)*.3528;}
  /* The size every name of a vignette page is set in: the set size, reduced block-wide until the longest name fits two lines. */
  /* Beside the photo a name may take as many lines as the photo height leaves (less the caption under it); elsewhere two. Mirrors master_layout.name_room. */
  function nameRoom(layout){const zone=layout.parts.name.zone,detail=layout.parts.detail;if(zone!=='left'&&zone!=='right')return 0;return layout.photoH-(detail&&detail.zone===zone?layout.nameDetailGap+layout.detailH:0);}
  function nameFont(settings,layout,people){layout=narrowest(layout);const room=nameRoom(layout),lineH=(settings.lineHeight||1.25)*.3528;const fits=size=>people.every(person=>{const lines=nameLines(AutoText.applyCase(person.name,settings.textCase),layout.parts.name.w*.97,size,settings.font,settings);return lines&&(lines.length<=2||lines.length*size*lineH<=room+.1);});let size=settings.fontSize;while(size>settings.minFontSize&&!fits(size))size=Math.max(settings.minFontSize,size-.5);return {size,fits:fits(size)};}
  /* Cards per row for n cards in cols columns and at most rows rows. Rows fill in turn, fuller rows first; when n needs
     more rows than there are, the first rows take one card more each (narrower, «squeezed»), never two; a last row
     shorter than half a row borrows a card from each row above it in turn. Mirrors master_layout.row_counts. */
  function rowCounts(n,cols,rows){
    if(n<=0)return [];
    const need=Math.ceil(n/cols);
    if(need>rows){const counts=Array(rows).fill(cols);for(let i=0;i<n-cols*rows;i++)counts[i]++;return counts;}
    const counts=Array(need).fill(cols),half=Math.ceil(cols/2);counts[need-1]=n-cols*(need-1);
    for(let k=need-2;need>1&&counts[need-1]<half;k--){if(k<0)k=need-2;counts[k]--;counts[need-1]++;}
    return counts;
  }
  /* The grid for count cards: columns, rows, the card size and, when rows are squeezed, the narrower card. Rows are
     squeezed only when the cards do not fit otherwise — within the photo width «от» and the page's «до» (settings.max,
     counting full rows). Mirrors master_layout.geometry. */
  function gridGeometry(count,settings){if(count<=0)return null;const {w,h}=settings.box,gap=Number(settings.gap)||0,frame=cardFrame(settings),floor=captionFloor(settings),least=Number(settings.minPhotoWidth)||5,most=Number(settings.photoWidth)||85,cap=Number(settings.max)||Infinity;let best=null,squeezed=null;
    const widest=(slotW,room)=>Math.min(slotW-frame.left-frame.right,room*frame.ratio,most);
    for(let cols=1;cols<=Math.min(6,count);cols++)for(let rows=Math.ceil(count/(cols+1));rows<=Math.ceil(count/cols);rows++){
      const extra=Math.max(0,count-cols*rows);
      /* Squeezed rows stay the exception: when every row would take one more, that is simply a wider grid. */
      if(extra&&extra>=rows||count-extra>cap)continue;
      const slotH=(h-(rows-1)*gap)/rows,room=slotH-frame.top-frame.bottom;
      if(room<frame.sideH)continue;
      const photoW=widest((w-(cols-1)*gap)/cols,room);if(photoW<least)continue;
      /* A name must still read in two lines at the smallest size names may shrink to. */
      const card=cardParts(photoW,frame);if(card.parts.name.w<floor)continue;
      let tight=null;
      if(extra){const tightW=Math.min(photoW,widest((w-cols*gap)/(cols+1),room));if(tightW<least)continue;const t=cardParts(tightW,frame);if(t.parts.name.w<floor)continue;tight={cellW:t.w,photoW:tightW,photoH:t.photoH,parts:t.parts};}
      /* Where the cards sit when they do not fill the area: one of nine anchors, as in Figma auto layout. */
      const fullW=cols*card.w+(cols-1)*gap,blockW=Math.max(fullW,tight?(cols+1)*tight.cellW+cols*gap:0),[ax,ay]=cardAnchor(settings.anchor),offsetX=(w-blockW)*ax,offsetY=(h-rows*card.h-(rows-1)*gap)*ay,
        score=(count-extra)*photoW*photoW+(tight?extra*tight.photoW*tight.photoW:0)-Math.max(0,cols*rows-count)*photoW*.01-extra*photoW*.001-(settings.fewRows?rows*photoW*photoW*.05:0);
      const found={cols,rows,cellW:card.w,cellH:card.h,photoW,photoH:card.photoH,parts:card.parts,tight,fullW,blockW,nameH:frame.nameH,detailH:frame.detailH,photoNameGap:frame.gap,overInset:frame.inset,nameDetailGap:frame.between,offsetX,offsetY,score};
      if(extra){if(!squeezed||score>squeezed.score)squeezed=found;}else if(!best||score>best.score)best=found;}
    return best||squeezed;}
  /* Where each of n cards stands in a grid made for at least n: rows by rowCounts; a squeezed row takes the narrower card;
     a short row keeps the left edge of the full rows, or stands in the middle with centerLastRow. Mirrors master_layout.card_slots. */
  function cardSlots(n,geo,settings){
    const gap=Number(settings.gap)||0,out=[];
    rowCounts(n,geo.cols,geo.rows).forEach((k,r)=>{
      const tight=k>geo.cols,cw=tight?geo.tight.cellW:geo.cellW,rowW=k*cw+(k-1)*gap,
        x=geo.offsetX+(k>=geo.cols||settings.centerLastRow?(geo.blockW-rowW)/2:(geo.blockW-geo.fullW)/2),y=geo.offsetY+(Number(settings.pushY)||0)+r*(geo.cellH+gap);
      for(let i=0;i<k;i++)out.push({x:x+i*(cw+gap),y,photoW:tight?geo.tight.photoW:geo.photoW,tight});
    });
    return out;
  }
  /* The narrowest card of a grid: names and quotes are sized for it so they read in every card. */
  function narrowest(geo){return geo&&geo.tight?{...geo,cellW:geo.tight.cellW,photoW:geo.tight.photoW,photoH:geo.tight.photoH,parts:geo.tight.parts}:geo;}
  /* A block kept to its own spreads («только эти развороты»): every vignette page is used once and the list is shared
     between them so that all cards are one size, as large as the pages allow; a page holds at most max cards (plus the
     squeezed ones). With leadBig the class teacher is not a card of the list but takes the free space of one page —
     a whole page left empty, or the room under the cards — when that makes the portrait clearly larger than a card;
     otherwise the class teacher is the first card. Mirrors master_layout.fill_pages.
     grids — the vignette of each page in order; count — people including the class teacher.
     Result: {pages:[{count,cap,lead}], leadCard, fits}; lead = {x,y,photoW} in vignette coordinates. */
  const TOP_OF={'top-left':'top-left',top:'top','top-right':'top-right',left:'top-left',center:'top',right:'top-right','bottom-left':'top-left',bottom:'top','bottom-right':'top-right'};
  /* The class teacher's portrait keeps its own proportions, whatever the cards have. */
  const leadFrame=settings=>cardFrame({...settings,photoRatio:Number(settings.leadRatio)||.75});
  function leadRoom(settings,used,geo,m){
    /* The class teacher opens the page: his card on top, the cards of the page under it; together they stand where the
       vignette's anchor puts them. Without cards he has the whole page. */
    const {w,h}=settings.box,gap=Number(settings.gap)||0,frame=leadFrame(settings),floor=captionFloor(settings);
    let below=0;if(m){const rows=rowCounts(m,geo.cols,geo.rows).length;below=rows*geo.cellH+(rows-1)*gap+gap;}
    const room=h-below;if(room<=0)return null;
    const photoW=Math.min(w-frame.left-frame.right,(room-frame.top-frame.bottom)*frame.ratio);
    if(photoW<=0||(frame.sideH&&(room-frame.top-frame.bottom)<frame.sideH))return null;
    const card=cardParts(photoW,frame);if(card.parts.name.w<floor)return null;
    const y=(room-card.h)*cardAnchor(settings.anchor)[1];
    return {x:(w-card.w)/2,y,photoW,push:y+card.h+gap,used};
  }
  /* Lexicographic comparison of two score lists. */
  function ahead(a,b){for(let i=0;i<a.length;i++)if(a[i]!==b[i])return a[i]>b[i];return false;}
  function fillPages(grids,count,leadBig,least=1){
    const most=g=>Math.max(1,Math.round(Number(g.max)||100)),pages=grids.length;
    const tryFill=(m,big)=>{
      if(m<0)return null;
      const splits=pages===1?[[m]]:pages===2?Array.from({length:m+1},(_,a)=>[a,m-a]):[MasterPlan.distribute(m,pages)];
      let best=null;
      for(const split of splits){
        /* A page with cards keeps at least «от» of them, unless the whole list is shorter. */
        if(split.some(k=>k&&k<Math.min(least,Math.floor(m/pages))))continue;
        if(!big&&split.some(k=>!k)&&m>=pages)continue;
        const natural=split.map((k,i)=>k?gridGeometry(k,grids[i]):null);
        if(split.some((k,i)=>k&&!natural[i]))continue;
        /* «до» counts the cards of full rows; a squeezed row may add one card to each row. */
        if(split.some((k,i)=>k&&k-Math.max(0,k-natural[i].cols*natural[i].rows)>most(grids[i])))continue;
        const widths=natural.filter(Boolean).map(g=>g.photoW),common=widths.length?Math.min(...widths):0;
        const settings=split.map((k,i)=>({...grids[i],photoWidth:Math.min(Number(grids[i].photoWidth)||85,common)})),
          capped=split.map((k,i)=>k?gridGeometry(k,settings[i]):null);
        if(split.some((k,i)=>k&&!capped[i]))continue;
        let lead=null;
        if(big){
          /* Beside the class teacher the cards take as few rows as they can, to leave the portrait the most room. */
          for(let i=0;i<pages;i++){const few={...settings[i],fewRows:true},geo=split[i]?gridGeometry(split[i],few):null,room=leadRoom(few,i,geo,split[i]);if(room&&(!lead||room.photoW>lead.photoW))lead=room;}
          if(!lead||(common&&lead.photoW<common*1.4))continue;
        }
        const squeezed=split.reduce((sum,k,i)=>sum+(k?Math.max(0,k-capped[i].cols*capped[i].rows):0),0),
          /* A whole page for the class teacher first (the teachers fit the other pages), then larger cards, then a larger portrait. */
          score=[lead&&!split[lead.used]?1:0,Math.round(common*2)/2,lead?Math.round(lead.photoW*2)/2:0,-squeezed,-Math.abs(split[0]-(split[1]??split[0]))];
        if(!best||ahead(score,best.score))best={score,split,common,lead,big};
      }
      return best;
    };
    const found=(leadBig&&count>0&&tryFill(count-1,true))||tryFill(count,false);
    if(!found)return {pages:grids.map(()=>({count:0,cap:0,top:false,push:0,lead:null})),leadCard:true,fits:false};
    return {pages:found.split.map((k,i)=>({count:k,cap:found.common,max:grids[i].max,top:!!found.lead&&found.lead.used===i,push:found.lead&&found.lead.used===i?found.lead.push:0,lead:found.lead&&found.lead.used===i?{x:found.lead.x,y:found.lead.y,photoW:found.lead.photoW}:null})),leadCard:!found.big,fits:true};
  }
  /* The most people a block kept to its own spreads takes. */
  function fillCapacity(grids,leadBig,least){let n=0;for(let k=1;k<=100&&k-n<=6;k++)if(fillPages(grids,k,leadBig,least).fits)n=k;return n;}
  function capacity(settings){let result=0;for(let n=1;n<=settings.max;n++)if(gridGeometry(n,settings))result=n;return result;}
  function distribute(count,max,preferred,min){if(count===0)return [];const slots=Math.max(Math.ceil(count/max),Math.min(preferred,Math.max(1,Math.floor(count/min)))),base=Math.floor(count/slots),extra=count%slots;return Array.from({length:slots},(_,i)=>base+(i<extra?1:0));}
  const measure=document.createElement('canvas').getContext('2d');
  /* Lines a caption wraps into, or null when a word is wider than the caption. Letter spacing counts, as in print. */
  function nameLines(name,width,fontSize,font,style){const px=fontSize*96/72,spacing=px*(Number(style?.letterSpacing)||0)/100;measure.font=`${style?.italic?'italic ':''}${style?.bold?'700 ':''}${px}px "${font||'Arial'}"`;const wide=text=>measure.measureText(text).width+text.length*spacing,widthPx=width*96/25.4,lines=[];let current='';for(const word of name.split(/\s+/).filter(Boolean)){if(wide(word)>widthPx)return null;const next=current?current+' '+word:word;if(wide(next)>widthPx){lines.push(current);current=word}else current=next;}if(current)lines.push(current);return lines;}
  /* The size of one card's subject or quote: each shrinks on its own, down to «от», within the two lines kept for it. Mirrors the detail sizing in master_layout. */
  function detailFont(settings,layout,text){const max=Number(settings.detailFontSize)||9,min=Math.min(max,Number(settings.detailMinFontSize??max)||max),lineH=(settings.detailLineHeight||1.25)*.3528,style={bold:settings.detailBold,italic:settings.detailItalic,letterSpacing:settings.detailLetterSpacing};const fits=size=>{const lines=nameLines(text,layout.parts.detail.w*.97,size,settings.detailFont||settings.font,style);return !!lines&&lines.length*size*lineH<=layout.detailH+.1;};let size=max;while(size>min&&!fits(size))size=Math.max(min,size-.5);return {size,fits:fits(size)};}
  /* Cards that fit on the tightest vignette of a list block. */
  function listCapacity(section){const list={...MasterPlan.LIST_DEFAULT,...(section.list||{})},grids=templatePages(section).flatMap(p=>p.layers.filter(l=>l.type==='grid'));return grids.length?Math.min(...grids.map(l=>capacity({...l,max:list.max}))):0;}
  const PLAN_TEXT={'no-grid':['warning','В блоке «по списку» нет виньетки — развороты выводятся по одному разу.'],'no-fit':['error','Карточки не помещаются при заданной ширине фото и отступах.'],'no-repeat':['error','Список не помещается: добавьте разворот с ролью «Повторяемый».'],'half':['warning','Список закончился на середине разворота — добавьте шаблон «Последний неполный».'],'below-min':['warning','На странице меньше карточек, чем минимум блока.'],'overflow':['error','Карточки не помещаются на страницу.'],'parts-order':['error','Продолжение списка стоит выше его начала — перетащите его ниже.']};
  /* Pages of a list block on the sample class. lists carries split blocks from part to part: block id → {everyone, end}. */
  function listPages(section,lists,issues){
    const original=templatePages(section),list={...MasterPlan.LIST_DEFAULT,...(section.list||{})},source=list.source,grids=original.flatMap(p=>p.layers.filter(l=>l.type==='grid')),settings={...(grids[0]||{}),...list},generated=[];
    let everyone,start=0;
    if(section.continues){
      if(!lists[section.continues]){issues.push({severity:'error',text:PLAN_TEXT['parts-order'][1]});return generated;}
      ({everyone,end:start}=lists[section.continues]);
    }else everyone=people(source).filter(person=>!(source==='teachers'&&list.excludeLead&&original.some(p=>p.layers.some(item=>item.type==='photo'&&!item.hidden&&item.source==='lead'))&&person.id==='t0'));
    const rest=everyone.slice(start);
    if(section.continues&&!rest.length){lists[section.id]={everyone,end:start};return generated;}
    if(list.fill==='spreads'&&!section.continues){lists[section.id]={everyone,end:everyone.length};return spreadPages(section,list,source,everyone,rest,issues);}
    if(list.min>list.max)issues.push({severity:'error',text:'Минимум карточек больше максимума.'});
    if(grids[0]&&settings.minFontSize>settings.fontSize)issues.push({severity:'error',text:'Минимальный кегль больше основного.'});
    const cap=listCapacity(section),result=MasterPlan.listPlan(section,rest.length,cap),counts=result.counts,layoutCount=Math.max(0,...counts);
    lists[section.id]={everyone,end:start+result.taken};
    if(cap&&list.max<100&&cap<list.max)issues.push({severity:'warning',text:`По размерам фото на страницу помещается ${cap} вместо максимума ${list.max}.`});
    for(const code of result.issues){const [level,text]=PLAN_TEXT[code];issues.push({severity:code==='below-min'&&list.strictMin?'error':level,text});}
    if(rest.some(person=>person.missing))issues.push({severity:'error',text:'У участника отсутствует обязательный портрет.'});
    const chunks=[];let offset=0;for(const count of counts){chunks.push(rest.slice(offset,offset+count));offset+=count;}
    const layout=layoutCount&&grids[0]?gridGeometry(layoutCount,settings):null;let actualFont=settings.fontSize;
    if(layout){const fit=nameFont(settings,layout,everyone);actualFont=fit.size;if(!fit.fits)issues.push({severity:'error',text:'Длинное имя не помещается при минимальном кегле.'});else if(actualFont<settings.fontSize)issues.push({severity:'warning',text:`Имена всего блока уменьшены до ${actualFont} pt.`});}
    for(const spread of result.spreads)for(const item of spread.pages){const template=getTemplatePage(item.page),grid=template.layers.some(l=>l.type==='grid');generated.push(item.part==null?{templateId:item.page,records:grid?[]:null,source:grid?source:'fixed',role:spread.role,actualFont,layoutCount}:{templateId:item.page,records:chunks[item.part],source,actualFont,layoutCount,part:item.part+1,parts:counts.length,role:spread.role});}
    return generated;
  }
  /* The vignette of a page as a block kept to its own spreads lays it out: cards no wider than the common width, and on
     the class teacher's page as few rows as fit, standing at the top. Mirrors master_layout.page_settings. */
  function pageSettings(layer,g){
    if(!g||!g.cap)return layer;
    return {...layer,max:g.max,photoWidth:Math.min(Number(layer.photoWidth)||85,g.cap),...(g.top?{anchor:TOP_OF[layer.anchor]||'top',fewRows:true,pushY:g.push||0}:{})};
  }
  /* A list kept to the block's own spreads: each spread once, the list shared by fillPages. */
  function spreadPages(section,list,source,everyone,rest,issues){
    const generated=[],templates=section.spreads.flatMap(spread=>spread.pages.map(page=>({spread,page,grid:page.layers.find(l=>l.type==='grid')}))),
      grids=templates.filter(t=>t.grid).map(t=>({...t.grid,max:list.max})),
      lead=source==='teachers'&&grids[0]?.lead==='big'?rest.find(person=>person.id==='t0')||null:null,
      fill=fillPages(grids,rest.length,!!lead,list.min);
    if(!fill.fits){const most=fillCapacity(grids,!!lead,list.min);issues.push({severity:'error',text:most?`Не помещаются все: эти развороты принимают до ${most}.`:PLAN_TEXT['no-fit'][1]});}
    /* The class teacher without room of his own is the first card. */
    const others=lead?(fill.leadCard?[lead]:[]).concat(rest.filter(person=>person!==lead)):rest,
      layouts=fill.pages.map((f,i)=>f.count?gridGeometry(f.count,pageSettings(grids[i],f)):null).filter(Boolean),
      narrow=layouts.map(narrowest).sort((a,b)=>a.parts.name.w-b.parts.name.w)[0];
    let actualFont=grids[0]?.fontSize;
    if(narrow){const fit=nameFont({...grids[0]},narrow,everyone);actualFont=fit.size;if(!fit.fits)issues.push({severity:'error',text:'Длинное имя не помещается при минимальном кегле.'});}
    let offset=0,at=0;
    for(const t of templates){
      if(!t.grid){generated.push({templateId:t.page.id,records:null,source:'fixed',role:t.spread.role});continue;}
      const f=fill.pages[at++],records=others.slice(offset,offset+f.count);offset+=f.count;
      generated.push({templateId:t.page.id,records,source,actualFont,layoutCount:records.length,cap:f.cap,max:f.max,top:f.top,push:f.push,lead:f.lead&&lead?{...f.lead,record:lead}:null,role:t.spread.role});
    }
    return generated;
  }
  function planSection(section,lists={}){const original=templatePages(section),issues=[];let generated=[];
    if(section.cover||section.kind==='fixed')generated=original.map(template=>({templateId:template.id,records:null,source:'fixed'}));
    else if(section.kind==='repeat'){
      const from=section.continues?lists[section.continues]:null;
      if(section.continues&&!from)issues.push({severity:'error',text:PLAN_TEXT['parts-order'][1]});
      const everyone=from?from.everyone:section.continues?[]:MasterPlan.people(section,people('students').map(person=>person.id),view.owner),start=from?from.end:0;
      const ids=everyone.slice(start,start+MasterPlan.personalTake(section,everyone.length-start));
      lists[section.id]={everyone,end:start+ids.length};
      ids.forEach(personId=>original.forEach(template=>generated.push({templateId:template.id,personId,records:null,source:'repeat'})));
    }else generated=listPages(section,lists,issues);
    const checked=new Set();for(const generatedPage of generated){const template=getTemplatePage(generatedPage.templateId);for(const item of template?.layers||[]){const checkKey=item.id+(item.source==='item'?':'+generatedPage.personId:'');if(item.type!=='photo'||item.hidden||checked.has(checkKey))continue;checked.add(checkKey);if(item.source==='custom'&&!item.dataUrl)issues.push({severity:'error',text:`«${item.name}»: загруженная фотография не выбрана.`});if(['lead','owner','item'].includes(item.source)&&(!photoPerson(item.source,generatedPage.personId)||photoPerson(item.source,generatedPage.personId).missing))issues.push({severity:'error',text:`«${item.name}»: источник фотографии пуст.`});}}
    if(generated.length%2)generated.push({templateId:null,records:null,source:'padding'});
    return {sectionId:section.id,pages:generated,spreads:generated.length/2,issues};
  }
  /* What needs fixing in the block itself, whatever class it is built for: only this shows in the block list and settings. */
  function designIssues(section){
    const issues=[],add=(severity,text)=>issues.push({severity,text}),pages=templatePages(section);
    if(!section.cover&&section.kind==='flow'){
      const list={...MasterPlan.LIST_DEFAULT,...(section.list||{})},grids=pages.flatMap(p=>p.layers.filter(l=>l.type==='grid'));
      if(list.min>list.max)add('error','Минимум карточек больше максимума.');
      if(!grids.length)add(...PLAN_TEXT['no-grid']);
      else{const cap=listCapacity(section);if(!cap)add(...PLAN_TEXT['no-fit']);else if(list.min>cap)add(list.strictMin?'error':'warning',`На страницу помещается ${cap}, а минимум — ${list.min}.`);else if(list.max<100&&cap<list.max)add('warning',`На страницу помещается ${cap}, а не ${list.max}. Уменьшите фото или отступы.`);if(grids.some(g=>g.minFontSize>g.fontSize))add('error','Минимальный кегль больше основного.');}
    }
    if(section.continues&&documentModel.sections.findIndex(s=>s.id===section.continues)>documentModel.sections.indexOf(section))add(...PLAN_TEXT['parts-order']);
    for(const item of pages.flatMap(p=>p.layers))if(item.type==='photo'&&!item.hidden&&item.source==='custom'&&!item.dataUrl)add('error',`«${item.name}»: загруженная фотография не выбрана.`);
    return issues;
  }
  /* In a book the first inner page stands alone on the right and the last one on the left: those pages are not printed. */
  function markBook(planning){if(documentModel.layout!=='book')return;const inner=planning.filter(p=>!getSection(p.sectionId)?.cover&&p.pages.length);if(!inner.length)return;inner[0].pages[0].blank=true;inner.at(-1).pages.at(-1).blank=true;}
  function plan(){const lists={};planning=documentModel.sections.map(section=>planSection(section,lists));markBook(planning);return planning;}
  function sectionPlan(key){return planning.find(p=>p.sectionId===key);}
  function currentPagePlan(){return sectionPlan(view.section)?.pages[view.spread*2+view.side];}
  function currentTemplatePage(){return getTemplatePage(currentPagePlan()?.templateId);}
  function selectedLayer(){return currentTemplatePage()?.layers.find(item=>item.id===view.layer);}
  function photoPerson(source,personId){if(source==='lead')return people('teachers')[0];if(source==='owner')return [...people('students'),...people('teachers')].find(p=>p.id===view.owner);if(source==='item')return people('students').find(p=>p.id===personId);return null;}
  function placeholderSvg(person,group=false){const colors=['#a3aaa4','#b6aaa0','#a7a8b2','#b5ada0'],color=colors[Number(person?.id?.slice(1)||0)%4];let circles='';if(group){for(let i=0;i<12;i++){const x=13+i%6*15,y=31+Math.floor(i/6)*43;circles+=`<circle cx="${x}" cy="${y}" r="4" fill="#b6b3ad"/><rect x="${x-6}" y="${y+6}" width="12" height="17" rx="3" fill="#b9b7b1"/>`;}}else circles=`<ellipse cx="50" cy="112" rx="44" ry="42" fill="${color}"/><rect x="42" y="60" width="16" height="30" fill="#d4c2b5"/><ellipse cx="50" cy="45" rx="23" ry="30" fill="#d7c5b8"/><path d="M27 43 Q22 11 50 13 Q78 10 73 46 Q64 27 42 34 Z" fill="#80766e"/>`;
    return 'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="100" height="133" viewBox="0 0 100 133"><rect width="100" height="133" fill="#e7e5e0"/>${circles}</svg>`);
  }
  function resolvedPhoto(item,generated){if(item.source==='custom')return item.dataUrl||null;if(item.source==='class')return placeholderSvg(null,true);const person=photoPerson(item.source,generated.personId);return person&&!person.missing?placeholderSvg(person):null;}
  const TEXT_SAMPLES={'owner.quote':'Цитата владельца альбома','item.quote':'Цитата героя разворота','lead.subject':'Русский язык','class':'11 «А»','year':'2026','school':{full:'МБОУ «Средняя общеобразовательная школа № 5»',short:'Школа № 5'},'city':'Казань','shoot.title':'Никольская сопка','shoot.date':'27.09.2020'};
  function resolvedText(item,generated){return AutoText.resolve(item.text,field=>{if(field.endsWith('.name')){const person=photoPerson(field.split('.')[0],generated.personId);if(!person)return 'Нет данных';const words=person.name.split(' ');return words.length>2?{first:words[0],middle:words[1],last:words.slice(2).join(' ')}:{first:words[0],middle:'',last:words.slice(1).join(' ')};}return TEXT_SAMPLES[field];});}

return {plan,designIssues,people,gridGeometry,leadFrame,pageSettings,fillPages,fillCapacity,cardSlots,narrowest,rowCounts,nameFont,detailFont,cardFrame,cardParts,placeholderSvg,resolvedPhoto,resolvedText,getTemplatePage,listCapacity};
};
