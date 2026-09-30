const fs=require('fs'),vm=require('vm'),assert=require('assert');
const clicks=[],state={view:'photos',shootId:'one',selected:new Set(),order:{id:'o',stage:'layout',photos:[
  {id:'a',shoot_id:'one',shoot_type:'portrait',status:'ready',filename:'DSC1.jpg'},
  {id:'b',shoot_id:'one',shoot_type:'portrait',status:'ready',filename:'DSC2.jpg',retouch_version:'v2'},
  {id:'c',shoot_id:'two',shoot_type:'portrait',status:'ready',filename:'DSC3.jpg'},
  {id:'d',shoot_id:'one',shoot_type:'general',status:'ready'},
  {id:'bad',shoot_id:'one',shoot_type:'portrait',status:'error'}],persons:[
    {id:'p1',selected_photo_id:'a'},{id:'p2',selected_photo_id:'b'},{id:'p3',selected_photo_id:'c'},
    {id:'p4',selected_photo_id:'d'},{id:'p5',selected_photo_id:'bad'},{id:'p6'}],shoots:[]}};
const c=vm.createContext({state,document:{addEventListener:(event,handler)=>{if(event==='click')clicks.push(handler);}},
  esc:v=>String(v??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;'),
  svgIcon:n=>`<i>${n}</i>`,renderWorkspace(){},renderGroups(){},URLSearchParams});
vm.runInContext(fs.readFileSync('web/retouch.js','utf8'),c);
const ids=photos=>Array.from(photos,p=>p.id);
assert.deepEqual(ids(c.Retouch.chosen()),['a','b','c']);
assert.deepEqual(ids(c.Retouch.list()),['a','b']);
assert(c.Retouch.tools().includes('Обработано 1 из 2'));
assert(c.Retouch.tools().includes('Скачать оригиналы · 2'));
assert.equal(c.Retouch.url(state.order.photos[1]),'/media/b/thumb?v=v2');
assert(c.Retouch.badge(state.order.photos[1]).includes('обработано'));
clicks[0]({target:{closest:selector=>selector==='[data-retouch]'?{dataset:{retouch:'todo'}}:null}});
assert.deepEqual(ids(c.Retouch.list()),['a']);
assert(c.Retouch.tools().includes('Скачать оригиналы · 1'));
state.view='persons';
assert.deepEqual(ids(c.Retouch.list()),['a','c']);
assert(c.Retouch.personVisible(state.order.persons[0]));
assert(!c.Retouch.personVisible(state.order.persons[1]));
c.Retouch.reset();assert(c.Retouch.personVisible(state.order.persons[1]));
state.order.retouch={mode:'retouch',done:1,total:3,remaining:[]};
assert(c.Retouch.plate(state.order).includes('Обработка портретов · 1 из 3'));
state.order.stage='print';assert.equal(c.Retouch.plate(state.order),'');
assert(!c.Retouch.tools().includes('data-retouch-files'));
console.log('Retouch: scoped chosen portraits, unprocessed filters, versioned images, counts and print lock OK');
