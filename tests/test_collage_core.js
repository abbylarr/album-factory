const fs=require('fs'),vm=require('vm'),assert=require('assert');
const c=vm.createContext({window:{}});
vm.runInContext(fs.readFileSync('web/collage-core.js','utf8'),c);
const C=c.window.CollageCore;
let n=0;const uid=()=>'n'+(++n);
const grid=(rows,cols)=>({box:{x:0,y:0,w:100,h:80},gapX:4,gapY:4,rows:Array.from({length:rows},()=>Array.from({length:cols},()=>C.leaf(uid)))});
const ids=l=>C.leaves(l).map(c=>c.id);

let l=grid(2,2);
assert.equal(C.frames(l).length,4);
assert.deepEqual(JSON.parse(JSON.stringify(C.frames(l)[1])),{cell:JSON.parse(JSON.stringify(l.rows[0][1])),x:52,y:0,w:48,h:38,depth:0});
assert.equal(C.layout(l).gutters.length,3,'two vertical gutters in rows and one between rows');
assert.equal(l.rows[0][0].source,'class','new frames take a general photo');
console.log('Geometry: OK');

l=grid(1,2);const first=l.rows[0][0];first.source='custom';first.dataUrl='data:x';first.cropX=10;
const keep=C.split(l,first.id,'v',uid);
assert.notEqual(keep,first.id,'the kept half gets a new id');
const kept=C.locate(l,keep).cell;
assert.equal(kept.dataUrl,'data:x','photo stays in the first half');assert.equal(kept.cropX,10);
assert.equal(first.split,'v');assert(!('dataUrl' in first),'split node holds no content');
assert.equal(C.frames(l).length,3);
console.log('Split keeps the photo: OK');

let next=C.remove(l,first.cells[1].id);
assert.equal(next,keep);assert.equal(l.rows[0][0].id,keep,'a split with one child collapses into it');
assert.equal(l.rows[0][0].dataUrl,'data:x');
console.log('Remove collapses splits: OK');

l=grid(2,1);next=C.remove(l,l.rows[0][0].id);
assert.equal(l.rows.length,1,'an empty row disappears');assert.equal(next,l.rows[0][0].id);
assert.equal(C.remove(l,l.rows[0][0].id),null,'the last frame cannot be removed');
assert.equal(C.can(l,l.rows[0][0].id).remove,false);
console.log('Last frame stays: OK');

l=grid(1,1);let deep=l.rows[0][0].id;
for(let i=0;i<4;i++)deep=C.split(l,deep,i%2?'h':'v',uid);
assert.equal(C.locate(l,deep).depth,4);
assert.equal(C.split(l,deep,'h',uid),null,'no deeper than four levels');
console.log('Depth limit: OK');

l=grid(8,1);assert.equal(C.addRow(l,uid),null,'eight rows at most');
l=grid(1,8);assert.equal(C.addColumn(l,uid),null,'eight frames per row at most');
l=grid(2,3);C.addRow(l,uid);assert.equal(l.rows[2].length,3,'a new row is as wide as the widest');
C.addColumn(l,uid);assert(l.rows.every(r=>r.length===4));
const row=l.rows[1][0].id;assert(C.removeRow(l,row));assert.equal(l.rows.length,2);
console.log('Rows and columns: OK');

const cell=C.leaf(uid);
C.setSource(cell,'custom',{dataUrl:'data:y'});assert.equal(cell.dataUrl,'data:y');assert(!cell.pick,'a file frame has no pick rule');
cell.cropX=20;cell.cropZoom=2;
C.setSource(cell,'owner');assert.equal(cell.dataUrl,'data:y','the upload survives switching away');assert.equal(cell.cropX,50,'a new kind resets the crop');assert(!('cropZoom' in cell));
cell.cropX=30;C.setSource(cell,'lead');assert.equal(cell.cropX,30,'portrait to portrait keeps the crop');
C.setSource(cell,'class',{pick:{role:'life'}});assert.equal(cell.pick.role,'life');
assert.equal(C.kind('item'),'portrait');assert.equal(C.kind('custom'),'custom');assert.equal(C.kind(undefined),'class');
console.log('Sources: OK');

l=grid(2,2);assert.equal(C.gapsLinked(l),true);l.gapY=6;assert.equal(C.gapsLinked(l),false);l.gapLinked=true;assert.equal(C.gapsLinked(l),true);
assert.equal(C.maxGap(grid(1,1)),40);const wide=grid(1,5);assert.equal(C.maxGap(wide,'x'),17.5,'frames keep at least 6 mm');assert.equal(C.maxGap(wide,'y'),40);assert.equal(C.maxGap(wide),17.5);
const before=ids(l);C.reidentify(l,uid);assert(ids(l).every(id=>!before.includes(id)));
console.log('Gaps and ids: OK');

l=grid(1,1);l.rows[0][0].pick={category:'few',who:'hero'};
C.addColumn(l,uid);assert.equal(l.rows[0][1].pick.who,'hero','a new frame beside a hero frame shows the hero too');
C.addRow(l,uid);assert.equal(l.rows[1][0].pick.who,'hero');
const plain=C.split(l,l.rows[0][0].id,'h',uid);assert.equal(C.locate(l,plain).cell.pick.category,'few','the kept half keeps its category');
assert.equal(l.rows[0][0].cells[1].pick.who,'hero');
assert.equal(C.leaf(uid).pick.who,undefined,'without a neighbour a frame takes anyone');
console.log('New frames follow their neighbours: OK');
