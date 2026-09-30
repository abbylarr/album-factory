const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('web/v2.js','utf8'),groups={innerHTML:''};
const person={id:'p',name:'Анна',selected_photo_id:'chosen',quote:'<script> & привет\nВторая строка'};
const photos=[{id:'first',person_id:'p',status:'ready',filename:'first.jpg'},
  {id:'chosen',person_id:'p',status:'ready',filename:'chosen.jpg'}];
const state={tab:'persons',selected:new Set(),order:{persons:[person],photos,shoots:[]}};
const context=vm.createContext({state,$:s=>s==='#groups'?groups:null,
  esc:s=>String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'),
  photoLabel:n=>`${n} фото`,personName:p=>p.name,needsReview:()=>false,
  PhotoTools:{changed(){}},statuses:{},svgIcon:n=>`<i class="${n}"></i>`});
for(const name of ['photoTile','orderSignature','renderGroups']){
  const line=source.split('\n').find(l=>l.startsWith(`function ${name}(`));vm.runInContext(line,context);
}
vm.runInContext(source.slice(source.indexOf('function personPortrait('),source.indexOf('function renderGroups(')),context);
context.renderGroups();assert(groups.innerHTML.includes('/media/chosen/thumb'));assert(!groups.innerHTML.includes('/media/first/thumb'));
assert(groups.innerHTML.includes('pw-card-badge')&&groups.innerHTML.includes('«&lt;script&gt; &amp; привет'),'chosen cover is marked and shows the quote');
let html=context.personPhotosHtml(person,photos);
assert(html.indexOf('/media/chosen/thumb')<html.indexOf('/media/first/thumb'));
assert(html.includes('pw-choice')&&html.includes('Заменить выбор'),'big chosen portrait and a deliberate re-pick link');
assert.equal((html.match(/data-photo="chosen"/g)||[]).length,1);
assert(html.includes('pw-tile-badge'));assert(html.includes('&lt;script&gt; &amp; привет\nВторая строка'));assert(!html.includes('<script>'));
const before=context.orderSignature(state.order);person.quote='Новая цитата';assert.notEqual(context.orderSignature(state.order),before);
state.selected.add('first');context.personPhotosHtml(person,photos);assert(state.selected.has('first'));
person.quote='';assert(context.personPhotosHtml(person,photos).includes('Цитаты нет'));
state.personPick={candidate:'first'};html=context.personPhotosHtml(person,photos);assert(html.includes('pw-picking')&&html.includes('pw-candidate')&&!html.includes('data-person-pick="start"'));state.personPick=null;
person.selected_photo_id='gone';context.renderGroups();assert(groups.innerHTML.includes('/media/first/thumb'));assert(!groups.innerHTML.includes('pw-card-badge'));
html=context.personPhotosHtml(person,photos);assert(!html.includes('pw-tile-badge'));assert(!html.includes('pw-quote')&&html.includes('Ещё не выбрал')&&html.includes('Выбрать за ученика'));
person.selected_photo_id='chosen';photos[1].status='error';assert.equal(context.personPortrait(person,photos),null);
console.log('Person choices: cover, chosen portrait first, escaped quote, missing choice and refresh signature OK');
