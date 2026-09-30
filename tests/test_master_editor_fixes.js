const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = file => fs.readFileSync('web/' + file, 'utf8');
const slice = (s,a,b) => {const i=s.indexOf(a); assert(i>=0,a); const j=s.indexOf(b,i); assert(j>i,b);return s.slice(i,j);};
const clone = value => JSON.parse(JSON.stringify(value));
const round = value => Math.round(value*10)/10, clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const core=source('master-editor/core.js'), tools=source('master-editor/tools.js'), bindings=source('master-editor/bindings.js');
// A new edit must never replace the only copy of unsaved work, even if archiving fails.
for(const full of [false,true]) {
  const old=JSON.stringify({document:{name:'unsaved'},revision:1}), data=new Map([['af-package-test',old]]);
  const c=vm.createContext({serverId:'test',doc:{name:'server'},revision:2,recoveryPending:null,dirty:false,
    localStorage:{getItem:k=>data.get(k)||null,setItem:(k,v)=>{if(full&&k.startsWith('af-recovery'))throw Error('quota');data.set(k,v);}},
    updateSaveState(){},scheduleAutosave(){},notify(){}});
  vm.runInContext(slice(core,'function preserveRecovery(', 'function showRecovery('),c);
  vm.runInContext(slice(core,'function markDirty()', 'function ensureCover()'),c);
  c.recoveryPending=c.preserveRecovery('test',c.doc);c.markDirty();
  assert.equal(data.get('af-package-test'),old);assert.equal(c.recoveryPending.document.name,'unsaved');
  if(!full)assert.equal(data.get('af-recovery-test'),old);
}
// Downscaling must leave thin geometry valid.
const layer={box:{x:0,y:0,w:.4,h:.4}}, resize=vm.createContext({doc:{pageSize:[500,500],sections:[{spreads:[{pages:[{layers:[layer]}]}]}]},round,clamp});
vm.runInContext(slice(tools,'function resizeDesign(', 'function property('),resize);resize.resizeDesign(false,50,50);
assert.equal(layer.box.w,.1);assert.equal(layer.box.h,.1);
// Copying an anchored cover element into an inner page must strip cover-only properties.
for(const pin of ['spine','wrap']){
  const page={layers:[]}, c=vm.createContext({preview:false,clipboard:[{id:'old',type:'text',pin,spineContent:true,box:{x:-30,y:20,w:60,h:20}}],
    clipboardGeometry:[{cover:true,pageWidth:210,gap:16,x:190,w:60}],page:()=>page,section:()=>({cover:false}),
    view:{side:1},pageWidth:()=>210,pageHeight:()=>280,maxLayerSize:()=>560,clone,clamp,round,uid:()=>pin,
    commit:fn=>fn(),selected:[],notify(){}});
  vm.runInContext(slice(tools,'function pasteLayers()', 'const menuGlyphs'),c);c.pasteLayers();
  assert(!('pin' in page.layers[0]));assert(!('spineContent' in page.layers[0]));
  assert(page.layers[0].box.x+210>=0);
}
// Complete a delayed read after the selected cell changes, then after deletion.
const upload=slice(bindings,"  if (el.id === 'photo-upload'",'  if (!el.dataset.prop)');
for(const deleted of [false,true]){
  const cells={a:{id:'a'},b:{id:'b'}},target={id:'collage'}, doc={};let reader,commits=0;
  const c=vm.createContext({doc,preview:false,focusCell:'a',selectedLayer:()=>target,
    allLayers:()=>deleted?[]:[target],locateCell:(l,id)=>({cell:cells[id]}),notify(){},
    FileReader:class{constructor(){reader=this;}readAsDataURL(){}},commit:fn=>{commits++;fn();},
    CollageCore:{setSource:(item,src,data)=>{item.dataUrl=data.dataUrl;}}});
  vm.runInContext('function upload(el){'+upload+'}',c);c.upload({id:'cell-upload',files:[{size:100,type:'image/jpeg'}]});
  c.focusCell='b';reader.result='image';reader.onload();
  assert.equal(commits,deleted?0:1);assert.equal(cells.b.dataUrl,undefined);if(!deleted)assert.equal(cells.a.dataUrl,'image');
}
// Raster export uses the complete sheet, hides helpers, and restores state on failure.
for(const fail of [false,true]) {
  const active={}, transform=[1,0,0,1,10,20],helper={excludeFromExport:true,visible:true,set(k,v){this[k]=v;}};
  let width,handler;const canvas={getActiveObject:()=>active,viewportTransform:transform,getObjects:()=>[helper],discardActiveObject(){},
    setViewportTransform(t){this.viewportTransform=t;},toDataURL(options){assert.equal(helper.visible,false);width=options.width;if(fail)throw Error('export');return 'png';},
    setActiveObject(o){assert.equal(o,active);},requestRenderAll(){}};
  const button={};const c=vm.createContext({$:()=>button,canvas,changing:false,sheetWidth:()=>436,pageHeight:()=>280,download(){},notify(){}});
  vm.runInContext(slice(bindings,"$('#export-png').onclick", "document.addEventListener('keydown'"),c);button.onclick();
  assert.equal(width,872);assert.equal(helper.visible,true);assert.deepEqual(canvas.viewportTransform,transform);assert.equal(c.changing,false);
}
console.log('Master editor recovery, geometry, paste, upload and PNG: OK');
// The smallest vignette at the right/bottom edge remains inside its page after scaling.
const grid={type:'grid',box:{x:499.6,y:499.6,w:.4,h:.4}}, edge=vm.createContext({doc:{pageSize:[500,500],sections:[{spreads:[{pages:[{layers:[grid]}]}]}]},round,clamp});
vm.runInContext(slice(tools,'function resizeDesign(', 'function property('),edge);edge.resizeDesign(false,50,50);
assert(grid.box.x+grid.box.w<=50+.001);assert(grid.box.y+grid.box.h<=50+.001);
// The paint separates ordinary objects from spine contents, including ordering commands.
const stack=[{id:'art',type:'rect',pin:'spine',z:0},{id:'title',type:'text',pin:'spine',angle:-90,z:1}],sec={cover:true,spineColor:'#000',spreads:[{pages:[{layers:stack}]}]};
const order=vm.createContext({section:()=>sec,selected:['art']});
vm.runInContext(slice(core,'function spreadStack(', '/* Number the spread'),order);
vm.runInContext(slice(tools,'function orderEnabled(', 'function closeObjectMenu('),order);
assert.equal(order.orderEnabled('up'),false);assert.equal(order.orderEnabled('down'),false);
(async()=>{
  for(const action of ['restore','server']) for(const serverRevision of [1,2]) {
    const backup={document:{name:'local',sections:[{id:'cover'}]},revision:1};
    const data=new Map([['af-recovery-test',JSON.stringify(backup)],['af-package-test',JSON.stringify(backup)]]);
    const message={textContent:''},modal={setAttribute(){},addEventListener(type,fn){this[type]=fn;},querySelector:()=>message,showModal(){},close(){this.closed=true;}};
    const c=vm.createContext({$:()=>null,document:{createElement:()=>modal,body:{append(){}}},recoveryPending:backup,
      serverId:'test',doc:{name:'server'},revision:serverRevision,view:{},selected:[],clone,
      localStorage:{removeItem:k=>data.delete(k)},api:async()=>{},commit(fn){fn();},notify(){},scheduleAutosave(){}});
    vm.runInContext(core.slice(core.indexOf('function showRecovery(')),c);c.showRecovery();
    await modal.click({target:{closest:()=>({dataset:{recovery:action}})}});
    assert.equal(c.recoveryPending,null);assert.equal(modal.closed,true);
    assert.equal(c.doc.name,action==='restore'?'local':'server');
    if(action==='restore')assert.equal(c.revision,1,'stale backup must not overwrite a newer revision');
  }
  console.log('Recovery choices, grid boundaries and spine ordering: OK');
})().catch(error=>{console.error(error);process.exitCode=1;});
// A wrap pasted onto the front of the same cover cannot retain a back-only pin.
const front={layers:[]},coverPaste=vm.createContext({preview:false,clipboard:[{id:'wrap',type:'rect',pin:'wrap',box:{x:0,y:0,w:420,h:280}}],
 clipboardGeometry:[{cover:true,pageWidth:210,gap:16,x:0,w:436}],page:()=>front,section:()=>({cover:true}),view:{side:1},
 pageWidth:()=>210,pageHeight:()=>280,sideX:()=>226,maxLayerSize:()=>560,clone,round,clamp,uid:()=> 'front-copy',commit:fn=>fn(),notify(){},selected:[]});
vm.runInContext(slice(tools,'function pasteLayers()', 'const menuGlyphs'),coverPaste);coverPaste.pasteLayers();assert(!front.layers[0].pin);
