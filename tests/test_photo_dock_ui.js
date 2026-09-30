const fs=require('fs'),vm=require('vm'),assert=require('assert');
const noop=()=>{},events=[];
function classes(){const set=new Set();return {contains:v=>set.has(v),add(...vs){vs.forEach(v=>set.add(v))},remove(...vs){vs.forEach(v=>set.delete(v))},toggle(v,on){if(on===undefined)on=!set.has(v);on?set.add(v):set.delete(v);return on}};}
const style={setProperty(k,v){this[k]=v}},dock={hidden:true,classList:classes(),style,offsetWidth:420,scrollWidth:420,offsetHeight:60,querySelector:()=>null,setAttribute:noop};
const rects={first:{left:140,top:160,bottom:360,width:150},last:{left:580,top:390,bottom:590,width:150}};
const boxes=Object.keys(rects).map(id=>{const tile={getBoundingClientRect:()=>rects[id],querySelector:()=>box};const box={dataset:{photo:id},closest:()=>tile};return box});
const dialog={open:true,getBoundingClientRect:()=>({left:100,right:900,top:80,bottom:720}),querySelectorAll:()=>boxes,append(el){el.parentElement=this},addEventListener:noop};
const row={remove:noop},tools={querySelector:()=>row,prepend:noop},bar={classList:classes(),querySelector:s=>s==='.shoot-tools'?tools:row,getBoundingClientRect:()=>({bottom:60})};
const body={classList:classes(),append(el){el.parentElement=this},getBoundingClientRect:()=>({left:0,right:1000,top:0,bottom:800})};
const workspace={getBoundingClientRect:()=>({left:20,right:980,top:0,bottom:800}),querySelectorAll:()=>boxes};
const state={selected:new Set(['first','last']),view:'persons',order:{photos:boxes.map(b=>({id:b.dataset.photo,status:'ready'})),persons:[]}};
const ctx=vm.createContext({state,ICONS:{},window:{addEventListener:(type,fn,options)=>events.push({surface:'window',type,fn,options})},
 document:{body,addEventListener:(type,fn,options)=>events.push({surface:'document',type,fn,options}),querySelectorAll:()=>boxes,createElement:()=>dock},
 $:s=>({'#selection-dock':dock,'#person-dialog':dialog,'#workspace':workspace,'.shoot-head':bar}[s]||null),
 innerWidth:1000,innerHeight:800,svgIcon:()=>'',esc:String,canConfirmMatch:()=>false,syncConfirmation:noop});
vm.runInContext(fs.readFileSync('web/photo-tools.js','utf8'),ctx);
const captureClick=events.find(e=>e.surface==='document'&&e.type==='click'&&e.options===true);
function click(box){captureClick.fn({target:{closest:selector=>selector==='.photo-tile'?box.closest():null},shiftKey:false});ctx.window.PhotoTools.changed();}
click(boxes[1]);assert.equal(dock.parentElement,dialog);assert(dock.classList.contains('in-dialog'));
assert.equal(style.top,'600px');assert.equal(style.left,'445px');assert(dock.classList.contains('below'));
const scroll=events.find(e=>e.surface==='window'&&e.type==='scroll');assert.equal(scroll.options.capture,true,'dialog scroll events must be captured');
rects.last={...rects.last,top:350,bottom:550};scroll.fn();assert.equal(style.top,'560px','panel follows last selected tile during dialog scroll');
rects.last={...rects.last,top:480,bottom:680};scroll.fn();assert.equal(style.top,'410px');assert(dock.classList.contains('above'));
// The toolbar stays within the dialog when the anchor scrolls out of view.
rects.last={...rects.last,top:900,bottom:1100};scroll.fn();assert.equal(style.top,'648px');assert.equal(style['--arrow'],'0');
// Deselecting the last anchor uses a selected photo; clicking moves the anchor again.
state.selected.delete('last');ctx.window.PhotoTools.changed();assert.equal(style.top,'370px');assert.equal(style.left,'112px');
state.selected.add('last');rects.last={...rects.last,top:200,bottom:400};click(boxes[1]);assert.equal(style.top,'410px');
// Switching back to the page restores the original workspace and sticky-bar bounds.
dialog.open=false;state.view='photos';ctx.window.PhotoTools.changed();assert.equal(dock.parentElement,body);assert(!dock.classList.contains('in-dialog'));assert.equal(style.top,'410px');
rects.last={...rects.last,top:-200,bottom:0};scroll.fn();assert.equal(style.top,'68px');
state.selected.clear();ctx.window.PhotoTools.changed();assert(dock.hidden);
console.log('Photo action panel: last anchor, dialog scroll, above/below, bounds and page fallback OK');
