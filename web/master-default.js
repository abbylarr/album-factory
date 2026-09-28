window.MasterDefaults=(()=>{const id=()=>crypto.randomUUID();
  const page = (layers = [], background = '#ffffff') => ({id:id(), background, layers});
  const spread = (left, right) => ({id:id(), pages:[left,right]});
  const box = (x,y,w,h) => ({x,y,w,h});
  const layer = (type, placement, other = {}) => ({id:id(),type,box:placement,opacity:100,...other});
  const text = (x,y,w,h,value,size = 24,extra = {}) => layer('text',box(x,y,w,h),{name:'Текст',text:value,binding:'static',font:'Georgia',fontSize:size,color:'#282a26',align:'left',...extra});
  const textStyles = () => [
    {id:'text-title',name:'Заголовок',font:'Georgia',fontSize:32,color:'#282a26',align:'center',bold:true,italic:false,underline:false,strike:false,lineHeight:1.15,letterSpacing:0},
    {id:'text-name',name:'Имя',font:'Georgia',fontSize:23,color:'#282a26',align:'center',bold:false,italic:false,underline:false,strike:false,lineHeight:1.25,letterSpacing:0},
    {id:'text-caption',name:'Подпись',font:'Georgia',fontSize:12,color:'#34332f',align:'center',bold:false,italic:false,underline:false,strike:false,lineHeight:1.25,letterSpacing:0},
    {id:'text-quote',name:'Цитата',font:'Georgia',fontSize:18,color:'#282a26',align:'left',bold:false,italic:true,underline:false,strike:false,lineHeight:1.4,letterSpacing:0},
    {id:'text-body',name:'Основной текст',font:'Arial',fontSize:14,color:'#333333',align:'left',bold:false,italic:false,underline:false,strike:false,lineHeight:1.3,letterSpacing:0}
  ];
  const photo = (x,y,w,h,source,name,extra={}) => layer('photo',box(x,y,w,h),{name,source,cropX:50,cropY:50,...extra});
  const grid = source => layer('grid',box(16,33,178,224),{name:source==='teachers'?'Виньетки учителей':'Виньетки учеников',source,gap:5,minPhotoWidth:32,photoWidth:85,photoNameGap:3,nameDetailGap:2,font:'Georgia',fontSize:12,minFontSize:10,color:'#34332f',styleGroup:source});
  /* A collage that takes as many photos of the person as the shoot has: from `min` to `max`. */
  const flexCollage = (x,y,w,h,min=1,max=4) => layer('collage',box(x,y,w,h),{name:'Гибкий коллаж',fill:'#e6e1ea',gapX:4,gapY:4,gapLinked:true,rows:[[{id:id(),source:'class',pick:{category:'any',who:'hero'},cropX:50,cropY:50}]],flex:{min,max},pick:{category:'any',who:'hero'}});
  const cover = (pageSize=[210,280]) => ({id:id(),name:'Обложка',cover:true,kind:'fixed',pageSize:[Math.min(pageSize[0]+6,500),Math.min(pageSize[1]+6,500)],safety:{safe:8,bleed:3,spine:8,gap:2},spreads:[spread(page([]),page([]))]});
  const listDefaults = source => ({source,min:4,max:12,strictMin:false,excludeLead:source==='teachers'});
  const withRole = (value, role) => ({...value, role});
  /* Starter blocks for the «new block» dialog and the default document.
     fixed: {spreads}; flow: {source, min, max, intro, last}; repeat: {people}. */
  function block(kind, options={}){
    if(kind==='flow'){
      const source=options.source==='teachers'?'teachers':'students',teachers=source==='teachers',spreads=[];
      if(options.intro)spreads.push(withRole(teachers?spread(page([photo(16,26,178,210,'lead','Классный руководитель'),text(16,240,178,24,'Классный руководитель',23,{styleId:'text-name',align:'center'})]),page([grid(source)])):spread(page([text(16,120,178,40,'Наш класс',32,{styleId:'text-title',align:'center',bold:true,lineHeight:1.15})]),page([grid(source)])),'intro'));
      spreads.push(withRole(spread(page([grid(source)]),page([grid(source)])),'repeat'));
      if(options.last)spreads.push(withRole(spread(page([grid(source)]),page([photo(14,18,182,230,'class','Общее фото',{pick:{category:'class'}})])),'last'));
      return {id:id(),name:options.name||(teachers?'Наши учителя':'Наш класс'),kind:'flow',target:options.target||1,list:{...listDefaults(source),min:options.min??4,max:options.max??12},spreads};
    }
    if(kind==='repeat')return {id:id(),name:options.name||'Личные развороты',kind:'repeat',people:options.people||'all',spreads:[spread(page([photo(16,22,178,210,'item','Портрет ученика'),text(16,239,178,24,'Имя ученика',23,{styleId:'text-name',binding:'item.name',align:'center'})]),page([flexCollage(14,18,182,244)]))]};
    const count=Math.max(1,Math.min(10,Number(options.spreads)||1));
    return {id:id(),name:options.name||'Общие фотографии',kind:'fixed',spreads:Array.from({length:count},(_,i)=>options.empty?spread(page([]),page([])):spread(page([photo(14,18,182,230,'class',`Общее фото ${i*2+1}`)]),page([photo(14,18,182,230,'class',`Общее фото ${i*2+2}`)])))};
  }
  function defaultDocument(){
    return {schemaVersion:1,rulesVersion:2,layout:'spreads',name:'Выпускной альбом · Классика',pageSize:[210,280],safety:{safe:5,bleed:3,spine:0,gap:0},textStyles:textStyles(),sections:[
      cover(),
      {id:'intro',name:'Начало',kind:'fixed',spreads:[spread(page([]),page([photo(14,18,182,230,'owner','Портрет владельца')]))]},
      {...block('flow',{source:'teachers',intro:true}),id:'teachers'},
      {...block('flow',{source:'students',last:true,target:2}),id:'students'},
      {...block('fixed',{spreads:4}),id:'shared'},
      {...block('repeat',{people:'all'}),id:'personal'}
    ]};
  }

return {create:defaultDocument,createCover:cover,textStyles,block};})();
