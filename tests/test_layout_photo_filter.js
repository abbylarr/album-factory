const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('web/layout.js','utf8');
const from=source.indexOf('function layoutElementPerson('),to=source.indexOf('function renderLayoutPanel(',from);
const context=vm.createContext({state:{order:{photos:[]}}});
vm.runInContext(source.split('\n')[0]+'\n'+source.slice(from,to),context);
const photos=[
  {id:'a1',person_id:'a',shoot_type:'portrait'},
  {id:'a2',person_id:'a',shoot_type:'portrait'},
  {id:'b1',person_id:'b',shoot_type:'portrait'},
  {id:'g',person_id:null,shoot_type:'general'}
];
context.data={photos};
context.state.order.photos=photos;
vm.runInContext("layoutUI.owner='student:a';layoutUI.photoTab='portrait'",context);
context.element={key:'students/cell[student:b]/portrait',photo:'a1'};
assert.deepStrictEqual(Array.from(vm.runInContext('layoutVisiblePhotos(data,element)',context),p=>p.id),['b1']);
context.element={key:'personal[student:a]/portrait',photo:'a1'};
assert.deepStrictEqual(Array.from(vm.runInContext('layoutVisiblePhotos(data,element)',context),p=>p.id),['a1','a2']);
context.data={photos:photos.map(({person_id,...photo})=>photo)};
assert.deepStrictEqual(Array.from(vm.runInContext('layoutVisiblePhotos(data,element)',context),p=>p.id),['a1','a2']);
vm.runInContext("layoutUI.photoTab='general'",context);
assert.deepStrictEqual(Array.from(vm.runInContext('layoutVisiblePhotos(data,element)',context),p=>p.id),['g']);
const general=[{id:'g1',shoot_type:'general',bucket:'pair',quality:.9},{id:'g2',shoot_type:'general',bucket:'group',style:'candid',quality:.4},{id:'g3',shoot_type:'general',bucket:'class',quality:.8}];
context.data={photos:general,document:{photo_report:{slots:{slot:{ranked:['g2']}}}}};
context.element={key:'shared/x',photo:'g1',slot:'slot'};
assert.deepStrictEqual(Array.from(vm.runInContext('layoutVisiblePhotos(data,element)',context),p=>p.id),['g2','g1','g3']);
vm.runInContext("layoutUI.photoTab='group'",context);
assert.deepStrictEqual(Array.from(vm.runInContext('layoutVisiblePhotos(data,element)',context),p=>p.id),['g2','g3']);
vm.runInContext("layoutUI.photoTab='pair'",context);
assert.deepStrictEqual(Array.from(vm.runInContext('layoutVisiblePhotos(data,element)',context),p=>p.id),['g1']);
vm.runInContext("layoutUI.photoTab='report'",context);
assert.deepStrictEqual(Array.from(vm.runInContext('layoutVisiblePhotos(data,element)',context),p=>p.id),['g2']);
console.log('Layout photo filter uses the selected frame person: OK');
console.log('General photo categories and slot ranking: OK');
