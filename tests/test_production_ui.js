const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('printed layout summary presents viewing and disables regeneration', () => {
  const source = fs.readFileSync('web/layout.js', 'utf8');
  const context = {state:{order:{id:'order'}},count:(n,s)=>`${n} ${s}`,document:{addEventListener(){}},esc:String};
  vm.createContext(context);
  vm.runInContext(source, context);
  const data = {document:{variants:[{owner:'student:one',sequence:['cover','page']}],issues:[]},status:{locked:true,reviews:{}}};
  context.data=data;
  const frozen=vm.runInContext('layoutSummary(data)',context);
  assert.match(frozen,/Зафиксирован для печати/);
  assert.match(frozen,/Просмотреть макет/);
  assert.match(frozen,/data-layout="generate" disabled/);
  assert.doesNotMatch(frozen,/заменить фото, поправить/);
  data.status.locked=false;
  const draft=vm.runInContext('layoutSummary(data)',context);
  assert.match(draft,/Открыть редактор макета/);
  assert.doesNotMatch(draft,/data-layout="generate" disabled/);
});
