const fs=require('fs'),vm=require('vm'),assert=require('assert');
const elements={'#photo-results':{innerHTML:''}};
const photos=[
  {id:'best',shoot_id:'g',status:'ready',filename:'best.jpg'},
  {id:'twin',shoot_id:'g',status:'ready',filename:'twin.jpg'},
  {id:'blur',shoot_id:'g',status:'ready',filename:'blur.jpg'},
  {id:'off',shoot_id:'g',status:'ready',filename:'off.jpg'},
  {id:'wait',shoot_id:'g',status:'processing',filename:'wait.jpg'}];
const analysed=(id,extra={})=>({id,analyzed:true,alternate:false,defect:null,defects:[],series:null,bucket:'pair',count:2,scale:'medium',subjects:['a'],tags:[],quality:.7,flags:{excluded:false,must_use:false,hero:false,best:false},...extra});
const data={photos:[analysed('best',{series:'best'}),analysed('twin',{series:'best',alternate:true}),analysed('blur',{defect:'reject',defects:['blur']}),analysed('off',{flags:{excluded:true,must_use:false,hero:false,best:false}})],
  persons:[{id:'a',name:'Анна',count:2,portrait:'pa'},{id:'b',name:'Борис',count:0,portrait:null}],clusters:[{id:1,faces:[{id:'f1',photo_id:'best'},{id:'f2',photo_id:'twin'}]},{id:2,faces:[{id:'f3',photo_id:'off'}]}],uncertain:[],
  labels:{scale:{medium:'Средний'},bucket:{pair:'Пара'},defect:{blur:'Нерезко'},tags:{}}};
const context=vm.createContext({window:{},document:{addEventListener(){},querySelector:s=>elements[s]||null},globalThis:{},
  state:{order:{id:'o',shoots:[{id:'g',kind:'general',title:'День'}],photos,persons:[{id:'a',name:'Анна'},{id:'b',name:'Борис'}]},shootId:'g',photoFilter:'all',selected:new Set()},
  api:async()=>data,json:()=>({}),toast(){},refreshOrder:async()=>{},$:s=>elements[s]||null,esc:s=>String(s??''),personName:p=>p.name,
  count:(n,one,few,many)=>`${n} ${n===1?one:n<5?few:many}`});
vm.runInContext(fs.readFileSync('web/general-review.js','utf8'),context);
const review=context.window.GeneralReview;
(async()=>{
  const shown=async filter=>{context.state.photoFilter=filter;await review.render();return (elements['#photo-results'].innerHTML.match(/data-photo="([^"]+)"/g)||[]).map(x=>x.slice(12,-1));};
  assert.deepStrictEqual(await shown('all'),['best','twin','blur','off','wait']);
  assert.deepStrictEqual(await shown('best'),['best']);
  assert.deepStrictEqual(await shown('defects'),['blur','off']);
  assert.deepStrictEqual(await shown('series'),['best','twin']);
  assert(elements['#photo-results'].innerHTML.includes('data-general="best" data-id="twin"'));
  assert.deepStrictEqual(Array.from(review.visiblePhotos(),p=>p.id),['best','twin']);
  context.state.photoFilter='people';await review.render();
  const people=elements['#photo-results'].innerHTML;
  assert(people.includes('coverage-item missing'));
  assert(people.includes('data-faces="f1,f2"'));
  assert(people.includes('1 лицо встречается'));
  assert(!review.filters().some(([key])=>key==='pending'),'analysis in progress is a status line, not a filter');
  console.log('General shoot filters, series and people review: OK');
})().catch(error=>{console.error(error);process.exit(1);});
