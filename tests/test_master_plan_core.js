/* Upgrading masters saved before block rules: list settings move from vignettes to the block, the personal mode to each personal block. */
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const c=vm.createContext({window:{}});
vm.runInContext(fs.readFileSync('web/master-plan-core.js','utf8'),c);
const P=c.window.MasterPlan;
let n=0;const uid=()=>'u'+(++n);
const page=(id,layers=[])=>({id,background:'#fff',layers});
const grid=(id,source='students',extra={})=>({id,type:'grid',source,min:3,max:9,strictMin:true,excludeLead:source==='teachers',...extra});
const old=()=>({schemaVersion:1,personalMode:'owner',sections:[
  {id:'cover',cover:true,kind:'fixed',spreads:[{id:'c',pages:[page('cl'),page('cr')]}]},
  {id:'teachers',kind:'flow',spreads:[{id:'t',pages:[page('tl',[{id:'lead',type:'photo',source:'lead'}]),page('tr',[grid('tg','teachers')])]}]},
  {id:'students',kind:'flow',spreads:[{id:'a',pages:[page('al',[{id:'title',type:'text'}]),page('ar')]},{id:'s',pages:[page('sl',[grid('g1')]),page('sr',[grid('g2')])]},{id:'z',pages:[page('zl'),page('zr')]}]},
  {id:'personal',kind:'repeat',spreads:[{id:'p',pages:[page('pl'),page('pr')]}]}]});

let doc=old();
assert.equal(P.upgrade(doc,uid),true);
assert.equal(doc.rulesVersion,2);assert.equal(doc.layout,'spreads');assert(!('personalMode' in doc));
const [,teachers,students,personal]=doc.sections;
assert.deepEqual(JSON.parse(JSON.stringify(students.list)),{source:'students',min:3,max:9,strictMin:true,excludeLead:false});
assert.deepEqual(students.spreads.map(s=>s.role),['intro','repeat','outro'],'vignette spreads repeat, the rest keep their place');
assert(students.spreads[1].pages.every(p=>p.layers.every(l=>!('min' in l)&&!('max' in l)&&!('strictMin' in l))),'list settings leave the vignettes');
assert.equal(personal.people,'owner');
console.log('Block settings move to blocks: OK');

assert.equal(teachers.list.excludeLead,true);
assert.deepEqual(teachers.spreads.map(s=>s.role),['intro','repeat'],'a lead page next to the vignette stays once; overflow gets a repeat spread');
assert(teachers.spreads[1].pages.every(p=>p.layers[0].type==='grid'&&p.layers[0].source==='teachers'));
assert.notEqual(teachers.spreads[1].pages[0].layers[0].id,'tg','copied vignettes get new ids');
console.log('Old overflow keeps working: OK');

assert.equal(P.upgrade(doc,uid),false,'an upgraded document stays as it is');
console.log('Upgrade runs once: OK');

/* The teachers block after the upgrade: 20 teachers, 9 per page — the intro page takes the first part, then full spreads. */
const plan=P.listPlan(teachers,20,9);
assert.deepEqual(plan.spreads.map(s=>s.role),['intro','repeat']);
assert.deepEqual(plan.counts,[7,7,6]);
assert.deepEqual(plan.spreads.flatMap(s=>s.pages.map(p=>p.part)),[null,0,1,2]);
console.log('Upgraded teachers flow: OK');

/* Split blocks: a continuation follows a block of the same kind and people; a limit stays only on a continued block. */
const split={sections:[
  {id:'cover',cover:true,kind:'fixed',spreads:[]},
  {id:'a',kind:'flow',limit:3,list:{source:'students',min:4,max:12},spreads:[]},
  {id:'g',kind:'fixed',spreads:[]},
  {id:'b',kind:'flow',continues:'a',list:{source:'teachers',min:4,max:12},spreads:[]},
  {id:'c',kind:'flow',continues:'a',list:{source:'students',min:4,max:12},spreads:[]},
  {id:'d',kind:'flow',limit:2,list:{source:'students',min:4,max:12},spreads:[]},
  {id:'p',kind:'repeat',people:'others',limit:4,spreads:[{id:'x'},{id:'y'}]},
  {id:'q',kind:'repeat',people:'all',continues:'p',spreads:[]},
  {id:'r',kind:'repeat',people:'owner',continues:'q',spreads:[]}]};
assert.equal(P.linkParts(split),true);
assert.equal(split.sections[3].list.source,'students','the continuation lists the same people');
assert(!('continues' in split.sections[4]),'one continuation per block');
assert.equal(split.sections[1].limit,3);
assert(!('limit' in split.sections[5]),'no limit without a continuation');
assert.equal(split.sections[7].people,'others','a personal continuation is for the same people');
assert(!('continues' in split.sections[8]),'the owner\'s own spread is not split');
assert.equal(P.linkParts(split),false);
assert.equal(P.personalTake(split.sections[6],10),2,'four spreads of two-spread people: two people');
assert.equal(P.personalTake(split.sections[6],1),1);
split.sections.splice(1,1);
assert.equal(P.linkParts(split),true);
assert(!('continues' in split.sections[2]),'a continuation of a removed block becomes a whole list');
console.log('Split blocks: OK');
