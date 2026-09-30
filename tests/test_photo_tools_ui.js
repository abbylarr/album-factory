const fs=require('fs'),vm=require('vm'),assert=require('assert');
const noop=()=>{};
const state={selected:new Set(),view:'photos',order:{id:'o',stage:'photos',persons:[{id:'a',name:'Анна'},{id:'b',name:''}],photos:[
  {id:'r',person_id:'a',status:'ready',uncertain:0,filename:'r.jpg'},
  {id:'1',person_id:'a',status:'ready',uncertain:1,filename:'1.jpg'},
  {id:'2',person_id:'b',status:'ready',uncertain:1,filename:'2.jpg'},
  {id:'3',person_id:null,status:'no_face',uncertain:0,filename:'3.jpg'},
  {id:'4',person_id:null,status:'error',uncertain:0,error:'Сломан файл',filename:'4.jpg'}]}};
const c=vm.createContext({state,ICONS:{},window:{addEventListener:noop},document:{addEventListener:noop,querySelectorAll:()=>[],querySelector:()=>null},location:{hash:''},
  $:()=>null,esc:s=>String(s),svgIcon:n=>`[${n}]`,personName:(p,i)=>p.name||`Персона ${i+1}`,statuses:{no_face:'Лицо не найдено',error:'Ошибка обработки'},toast:m=>{c.toasted=m;},
  count:(n,a,b,d)=>`${n} ${d}`,DataView,Uint8Array});
vm.runInContext(fs.readFileSync('web/photo-tools.js','utf8'),c);
const T=c.window.PhotoTools;

assert.deepEqual(T.rangeBetween(['a','b','c','d','e'],'b','d'),['b','c','d']);
assert.deepEqual(T.rangeBetween(['a','b','c','d','e'],'e','c'),['c','d','e'],'range works backwards');
assert.deepEqual(T.rangeBetween(['a','b'],'gone','b'),['b'],'a stale anchor selects only the clicked photo');
console.log('Shift range selection: OK');

const board=T.reviewBoard(state.order.photos.filter(p=>p.id!=='r'));
assert(board.includes('Проверьте совпадения <span>2</span>'));
assert.equal((board.match(/class="review-group"/g)||[]).length,2,'one group per suggested person');
assert(board.indexOf('Анна')<board.indexOf('Персона 2'),'groups follow the person order');
assert(board.includes('/media/r/thumb')&&board.includes('Эталон'),'confirmed photo is the reference');
assert(board.includes('Оставить отдельно · 1'),'a person without other photos can be kept as new');
assert(board.includes('Не распознано <span>1</span>')&&board.includes('Лицо не найдено'));
assert(board.includes('Не удалось распознать <span>1</span>')&&board.includes('Сломан файл')&&board.includes('data-action="retry"'));
assert(!board.includes('data-person='),'group buttons must not trigger the person dialog handler');
assert(T.reviewBoard([]).includes('Всё проверено')&&T.reviewBoard([]).includes('data-v2="send-forms"'));
console.log('Review grouped by person, unrecognised and errors: OK');

const files=[{name:'DSC10.jpg',type:'image/jpeg'},{name:'.DS_Store',type:''},{name:'DSC9.JPG',type:''},{name:'notes.txt',type:'text/plain'},{name:'a.png',type:'image/png'}];
assert.deepEqual(T.onlyImages(files).map(f=>f.name),['a.png','DSC9.JPG','DSC10.jpg'],'images only, natural order');
assert(c.toasted.includes('2'));
console.log('Folder filtering: OK');

// Minimal JPEG with an Exif APP1 carrying DateTimeOriginal in the Exif sub-IFD (little-endian TIFF).
function jpeg(date){
  const t=[],u16=v=>t.push(v&255,v>>8),u32=v=>t.push(v&255,v>>8&255,v>>16&255,v>>>24);
  t.push(0x49,0x49);u16(42);u32(8);                      // TIFF header, IFD0 at 8
  u16(1);u16(0x8769);u16(4);u32(1);u32(26);u32(0);        // IFD0: ExifIFD pointer -> 26
  u16(1);u16(0x9003);u16(2);u32(20);u32(44);u32(0);       // Exif IFD: DateTimeOriginal at 44
  for(const ch of date+'\0')t.push(ch.charCodeAt(0));
  const app=[0x45,0x78,0x69,0x66,0,0,...t],len=app.length+2;
  const bytes=new Uint8Array([0xFF,0xD8,0xFF,0xE1,len>>8,len&255,...app,0xFF,0xD9]);
  return {name:'x.jpg',slice:()=>({arrayBuffer:async()=>bytes.buffer})};
}
(async()=>{
  assert.equal(await T.exifDate(jpeg('2026:05:21 10:11:12')),'2026-05-21');
  assert.equal(await T.exifDate(jpeg('0000:00:00 00:00:00')),null);
  assert.equal(await T.exifDate({slice:()=>({arrayBuffer:async()=>new Uint8Array([1,2,3,4]).buffer})}),null);
  assert.equal(await T.guessDate([{slice:()=>({arrayBuffer:async()=>new ArrayBuffer(4)})},jpeg('2025:12:01 09:00:00')]),'2025-12-01');
  console.log('Shoot date from EXIF: OK');
})().catch(e=>{console.error(e);process.exit(1);});
for(const tile of board.match(/<label class="photo-tile[\s\S]*?<\/label>/g)){
  const first=tile.match(/<(input|button|select|textarea)\b/);
  assert.equal(first[1],'input','clicking a tile must toggle its checkbox, not a quick action');
}
console.log('Tile click targets the checkbox: OK');
