// Regression: opening an automatic spine must render its controls, including after reload.
const fs = require('fs'), vm = require('vm'), assert = require('assert');
function readFunction(file, name, next) {
  const source = fs.readFileSync(file, 'utf8');
  return source.slice(source.indexOf(`function ${name}(`), source.indexOf(next, source.indexOf(`function ${name}(`)));
}
const cover = { cover: true, spineColor: '#000000', spreads: [{}] };
const context = vm.createContext({
  doc: { sheetThickness: .14, sections: [cover, { spreads: [{}, {}, {}] }], layout: 'spreads' },
  view: { coverSpreads: null },
  coverSection: () => cover,
  coverSpine: () => 8,
  infoTip: text => text,
  colorControl: () => 'colour control',
  block: (title, html) => `<h3>${title}</h3>${html}`,
});
vm.runInContext(readFunction('web/master-editor/scene.js', 'editorVolume', '\nconst SPINE_BOARD'), context);
vm.runInContext(readFunction('web/master-editor/controls.js', 'spinePanel', '\n/* A text along'), context);
let html = context.spinePanel();
assert(html.includes('<output>3</output>'));
assert(html.includes('Текст на корешке'));
assert(html.includes('colour control'));
context.view.coverSpreads = 20;
assert(context.spinePanel().includes('<output>20</output>'));
context.doc.sheetThickness = null;
html = context.spinePanel();
assert(!html.includes('<output>'));
assert(html.includes('Текст на корешке'));
// Reopening a saved automatic document computes the volume from its blocks again.
context.doc.sheetThickness = .2;
context.view.coverSpreads = null;
assert(context.spinePanel().includes('<output>3</output>'));
console.log('Spine panel: OK');
