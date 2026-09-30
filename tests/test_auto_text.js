// Chip modifiers in the editor resolve exactly as album_factory/auto_text.py does on the server.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const c=vm.createContext({window:{}});
vm.runInContext(fs.readFileSync('web/auto-text.js','utf8'),c);
const A=c.window.AutoText;

const values={'lead.name':{first:'Анна',middle:'Петровна',last:'Иванова'},school:{full:'МБОУ «Средняя школа № 5»',short:'Школа № 5'},class:'11 «б»',city:'томск'};
const cases={
  '{{lead.name}}':'Анна Петровна Иванова',
  '{{lead.name|first}}':'Анна',
  '{{lead.name|last|upper}}':'ИВАНОВА',
  '{{lead.name|initials}}':'Иванова А. П.',
  '{{school}}':'МБОУ «Средняя школа № 5»',
  '{{school|short}}':'Школа № 5',
  '{{class}}':'11 «б»',
  '{{class|bare}}':'11 б',
  '{{class|bare|upper}}':'11 Б',
  '{{class|letter|upper}}':'Б',
  '{{class|number}}':'11',
  '{{city|title}}':'Томск',
};
for(const [token,expected] of Object.entries(cases))assert.equal(A.resolve(token,f=>values[f]),expected,token);
assert.equal(A.resolve('{{school|short}}',()=>({full:'Лицей 46',short:''})),'Лицей 46','no short name falls back to the full one');
assert.equal(A.resolve('{{class}}\n{{city}}\n',f=>({class:'11 А',city:''})[f]),'11 А','no empty last line: a trailing break or an empty chip on the last line takes no height');
assert.equal(A.format('class','9А',['quotes']),'9 «А»');
assert.equal(A.applyCase('анна-мария «звезда» петрова','title'),'Анна-Мария «Звезда» Петрова');
console.log('Modifiers: OK');

const parts=A.parts('Класс {{class|bare|upper}}\n{{owner.name}}');
assert.deepEqual(JSON.parse(JSON.stringify(parts)),[{text:'Класс '},{field:'class',mods:['bare','upper']},{text:'\n'},{field:'owner.name',mods:[]}]);
assert.equal(A.token('class',['bare','','upper']),'{{class|bare|upper}}');
assert.equal(A.token('school'),'{{school}}');
assert.equal(A.label('class',['bare','upper']),'Класс · 11 Б · AG');
assert.equal(A.label('owner.name',['last']),'Имя владельца · фамилия');
assert.equal(A.label('school',['short']),'Школа · краткое название');
assert.deepEqual([...A.fields('{{school|short}} {{unknown}}')],['school']);
console.log('Chip editor parts: OK');

// Master frames expose one case control, including legacy chip-only formatting.
for (const [text,current,expectedText,expectedCase] of [
  ['{{school|short|upper}}',undefined,'{{school|short}}','upper'],
  ['{{school|short|upper}}','lower','{{school|short}}','lower'],
  ['{{school|short|upper}}','','{{school|short}}',''],
  ['{{owner.name|last|lower}} {{school|short|upper}}',undefined,'{{owner.name|last}} {{school|short}}',''],
  ['Школа: {{school|short|upper}}',undefined,'Школа: {{school|short}}',''],
  ['{{unknown|upper}}',undefined,'{{unknown|upper}}',''],
]) {
  const unified=A.unifyCase(text,current);
  assert.equal(unified.text,expectedText);assert.equal(unified.textCase,expectedCase);
  assert.equal(JSON.stringify(A.unifyCase(unified.text,unified.textCase)),JSON.stringify(unified),'idempotent migration');
}
const migrated=A.unifyCase('{{school|short|upper}}','');
assert.equal(A.applyCase(A.resolve(migrated.text,f=>values[f]),migrated.textCase),'Школа № 5','As-is restores the original data case');
const editorSource=fs.readFileSync('web/master-editor/text.js','utf8');
const pop=vm.createContext({AutoText:A,esc:s=>s});
vm.runInContext(editorSource.slice(editorSource.indexOf('function chipPopHtml('),editorSource.indexOf('function openChipPop(')),pop);
const html=pop.chipPopHtml('school',['short','upper']);
assert(html.includes('Краткое название'));assert(!html.includes('Регистр'));assert(!html.includes('data-chip-case'));
assert(!editorSource.includes('data-chip-case'));
console.log('Unified frame case and chip menu: OK');
