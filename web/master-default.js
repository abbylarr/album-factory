window.MasterDefaults=(()=>{const id=()=>crypto.randomUUID();
  const page = (layers = [], background = '#ffffff') => ({id:id(), background, layers});
  const spread = (left, right) => ({id:id(), pages:[left,right]});
  const box = (x,y,w,h) => ({x,y,w,h});
  const layer = (type, placement, other = {}) => ({id:id(),type,box:placement,opacity:100,...other});
  const text = (x,y,w,h,value,size = 24,extra = {}) => layer('text',box(x,y,w,h),{name:'Текст',text:value,binding:'static',font:'Georgia',fontSize:size,color:'#282a26',align:'left',...extra});
  const photo = (x,y,w,h,source,name) => layer('photo',box(x,y,w,h),{name,source,cropX:50,cropY:50});
  const grid = source => layer('grid',box(16,33,178,224),{name:source==='teachers'?'Виньетки учителей':'Виньетки учеников',source,min:4,max:12,gap:5,minPhotoWidth:32,font:'Georgia',fontSize:12,minFontSize:10,color:'#34332f',strictMin:false,excludeLead:source==='teachers',styleGroup:source});
  function defaultDocument(){
    const studentPages=Array.from({length:4},()=>page([grid('students')]));
    const shared=Array.from({length:4},(_,i)=>spread(
      page([photo(14,18,182,230,'class',`Общее фото ${i*2+1}`)]),
      page([photo(14,18,182,230,'class',`Общее фото ${i*2+2}`)])));
    return {schemaVersion:1,name:'Выпускной альбом · Классика',personalMode:'all',sections:[
      {id:'intro',name:'Начало',kind:'fixed',spreads:[spread(page([]),page([photo(14,18,182,230,'owner','Портрет владельца')]))]},
      {id:'teachers',name:'Наши учителя',kind:'flow',target:1,spreads:[spread(page([photo(16,26,178,210,'lead','Классный руководитель'),text(16,240,178,24,'Классный руководитель',20,{align:'center'})]),page([grid('teachers')]))]},
      {id:'students',name:'Наш класс',kind:'flow',target:2,spreads:[spread(studentPages[0],studentPages[1]),spread(studentPages[2],studentPages[3])]},
      {id:'shared',name:'Общие фотографии',kind:'fixed',spreads:shared},
      {id:'personal',name:'Личные развороты',kind:'repeat',spreads:[spread(page([photo(16,22,178,210,'item','Портрет этого ученика'),text(16,239,178,24,'Имя ученика',23,{binding:'item.name',align:'center'})]),page([photo(16,22,178,210,'class','Общая фотография')]))]}
    ]};
  }

return {create:defaultDocument};})();
