// Exercise report switching without a browser or access to live photographs.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const elements=new Map();
const get=s=>{if(!elements.has(s))elements.set(s,{value:'',checked:false,textContent:'',innerHTML:''});return elements.get(s);};
const context=vm.createContext({document:{querySelector:get},fetch:()=>new Promise(()=>{}),URL:{createObjectURL:()=> 'blob:test',revokeObjectURL(){}},Blob,console,setTimeout,clearTimeout,localStorage:{},history:{},location:{hash:''}});
vm.runInContext(fs.readFileSync('web/sorting-lab.js','utf8'),context);
const photo={id:'photo',filename:'<unsafe>.jpg',person_id:'p1',status:'ready',source:'sequence',uncertain:true};
const entry={seconds:10,photos_per_minute:6,persons:1,inferred:1,errors:0,timings:{decode:1,recognition:8,matching:0,previews:1},photos:[photo]};
const report={id:'trial',total:1,result:{variants:{v2_series:entry,v3:{...entry,seconds:5}},comparisons:{},versus_v2_series:{speedup:2,changed_photos:1,changed_ids:['photo'],split_pairs:0,merged_pairs:1},note:'Test'}};
vm.runInContext(`report=${JSON.stringify(report)};variant='v3';render();`,context);
assert(get('#comparison').textContent.includes('Относительно V2 серии: 2.00'));
assert(get('#groups').innerHTML.includes('Расхождение с V2 серии'));
assert(get('#groups').innerHTML.includes('&lt;unsafe&gt;'));
vm.runInContext("variant='v2_series';render();",context);
assert(get('#comparison').textContent.includes('База для сравнения с V3'));
const legacy={...report,result:{variants:{v1:entry,v2_series:entry},comparisons:{v2_series:{speedup:1,changed_ids:[],changed_photos:0,merged_pairs:0,split_pairs:0}},note:'Old'}};
vm.runInContext(`report=${JSON.stringify(legacy)};variant='v2_series';render();`,context);
assert(get('#comparison').textContent.includes('Относительно V1'));
console.log('UI report switching, comparison labels and legacy reports: OK');
