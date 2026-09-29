const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('web/v2.js','utf8');
const ctx=vm.createContext({state:{orders:[]},cardStatus:o=>({kind:o.kind}),isMine:st=>st.kind==='todo',daysIn:o=>o.days||0});
for(const prefix of ['const orderFilters=','const searchKey=','function schoolLabel(','function schoolFilterKey(','const orderSort=','function registryOrders('])vm.runInContext(source.split('\n').find(l=>l.startsWith(prefix)),ctx);
ctx.state.orders=[{school:'Школа 1',class_name:'9 б',stage:'photos',kind:'todo',customer_name:'Анна',days:7},{school:'Школа 2',class_name:'9 Б',stage:'forms',kind:'waiting'},{school:'Школа 1',class_name:'11 А',stage:'archive',kind:'done'}];
const run=s=>vm.runInContext(s,ctx);
assert.equal(run('registryOrders().length'),2);
assert.equal(run("orderFilters.query='9б';registryOrders().length"),2);
assert.equal(run("orderFilters.school='Школа 1';registryOrders().length"),1);
assert.equal(run("orderFilters.school='';orderFilters.attention=true;registryOrders().length"),1);
assert.equal(run("orderFilters.query='';orderFilters.attention=false;orderFilters.scope='waiting';registryOrders().length"),1);
assert.equal(run("orderFilters.scope='archive';registryOrders()[0].class_name"),'11 А');
assert.equal(run("orderFilters.scope='all';orderFilters.className='9 Б';registryOrders().length"),2);
assert.equal(run("orderFilters.className='';orderFilters.query='анна';registryOrders().length"),1);
assert.equal(run("orderFilters.query='нет такого заказа';registryOrders().length"),0);
console.log('Order registry: combined filters, normalized class search, waiting and archive scopes OK');

ctx.state.orders=[{school_id:'kazan',school:'Школа № 1',school_city:'Казань',class_name:'11А',stage:'new',kind:'todo'},{school_id:'ufa',school:'Школа № 1',school_city:'Уфа',class_name:'11А',stage:'new',kind:'todo'}];
assert.equal(run("orderFilters.query='';orderFilters.school='kazan';registryOrders().length"),1);
assert.equal(run("registryOrders()[0].school_city"),'Казань');
assert.equal(run("orderFilters.school='';orderFilters.query='уфа';registryOrders().length"),1);
console.log('School city search and distinct school IDs: OK');

ctx.state.orders=[{school:'Школа № 20',class_name:'10 А',stage:'photos',kind:'waiting'},{school:'Школа № 5',class_name:'9 Б',stage:'forms',kind:'waiting'},{school:'Школа № 20',class_name:'9 Б',stage:'layout',kind:'todo'},{school:'Школа № 5',class_name:'11 А',stage:'new',kind:'todo'}];
run("Object.assign(orderFilters,{query:'',school:'',className:'',stage:'',scope:'all',attention:false})");
assert.deepEqual(JSON.parse(run("JSON.stringify(registryOrders().map(o=>o.school+' '+o.class_name))")),['Школа № 5 11 А','Школа № 20 9 Б','Школа № 5 9 Б','Школа № 20 10 А']);
console.log('Sorting: orders needing action first, then school and class in natural order OK');

assert.equal(run("orderFilters.stage='forms';registryOrders().length"),1);
assert.equal(run("registryOrders({ignoreStage:true}).length"),4);
console.log('Kanban ignores the stage filter OK');
