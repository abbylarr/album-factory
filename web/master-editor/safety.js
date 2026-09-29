/* Master editor · Print safety zones dialog. */
'use strict';
/* Safety lines in mm on the whole spread (2w × h). Spreads and the cover are printed as one sheet, so bleed runs only along its outer edge and the fold has none. A book is printed page by page: bleed on the top, bottom and outer edge, and a glued spine strip on the inner edge that is only filled with background. */
const BOOK_SAFETY = { safe: 3, bleed: 7.5, outer: 3, spine: 10 };
function safetyKind(sec = section()) {
  return sec?.cover ? 'cover' : doc.layout === 'book' ? 'book' : 'spreads';
}
function safetyValues(kind) {
  return kind === 'cover'
    ? coverSection()?.safety || {}
    : kind === 'book'
      ? { ...BOOK_SAFETY, ...doc.safety?.book }
      : doc.safety || {};
}
function safetyGeometry(kind, w, h, g, spineWidth = kind === 'cover' ? Number(g.spine) || 0 : 0) {
  const n = key => Math.max(0, Number(g[key]) || 0),
    safe = n('safe'),
    bleed = n('bleed'),
    out = { bands: [], trims: [], safes: [], spines: [], gaps: [], folds: [] },
    ok = r => !!r && r[2] > 0.01 && r[3] > 0.01,
    inset = ([x, y, rw, rh], d) => [x + d, y + d, rw - 2 * d, rh - 2 * d];
  const add = (region, trim, safeBox) => {
    if (!ok(trim)) return;
    const [x, y, rw, rh] = region,
      [tx, ty, tw, th] = trim;
    out.bands.push(
      ...[
        [x, y, rw, ty - y],
        [x, ty + th, rw, y + rh - ty - th],
        [x, ty, tx - x, th],
        [tx + tw, ty, x + rw - tx - tw, th],
      ].filter(ok),
    );
    out.trims.push(trim);
    if (safe > 0 && ok(safeBox)) out.safes.push(safeBox);
  };
  if (kind === 'book') {
    const outer = n('outer'),
      spine = Math.min(n('spine'), w);
    for (const side of [0, 1]) {
      const x = side * w,
        trim = side
          ? [x + spine, bleed, w - spine - outer, h - 2 * bleed]
          : [x + outer, bleed, w - spine - outer, h - 2 * bleed];
      if (spine > 0) out.spines.push(side ? [x, 0, spine, h] : [x + w - spine, 0, spine, h]);
      add(side ? [x + spine, 0, w - spine, h] : [x, 0, w - spine, h], trim, inset(trim, safe));
    }
    return out;
  }
  const spine = kind === 'cover' ? Math.max(0, spineWidth) : 0,
    sheet = 2 * w + spine,
    trim = [bleed, bleed, sheet - 2 * bleed, h - 2 * bleed];
  if (kind === 'cover') {
    const gap = n('gap'),
      edge = bleed + safe;
    if (spine > 0) out.spines.push([w, 0, spine, h]);
    if (gap > 0) out.gaps.push(w - gap, w + spine + gap);
    add([0, 0, sheet, h], trim, null);
    if (safe > 0 && ok(trim))
      for (const box of [
        [edge, edge, w - gap - safe - edge, h - 2 * edge],
        [w + spine + gap + safe, edge, w - gap - safe - edge, h - 2 * edge],
      ])
        if (ok(box)) out.safes.push(box);
    return out;
  }
  out.folds.push(w);
  add([0, 0, 2 * w, h], trim, inset(trim, safe));
  return out;
}
function safetyFits(kind, w, h, g, spine) {
  const geo = safetyGeometry(kind, w, h, g, spine),
    sheets = kind === 'spreads' ? 1 : 2;
  return (
    geo.trims.length === (kind === 'book' ? 2 : 1) && (!(Number(g.safe) > 0) || geo.safes.length === sheets)
  );
}
/* Drawing of the lines: real proportions in the dialog, stylised ones on the album settings cards. */
function safetySvg(kind, w, h, g, spine) {
  const geo = safetyGeometry(kind, w, h, g, spine),
    sheet = 2 * w + (kind === 'cover' ? geo.spines[0]?.[2] || 0 : 0),
    rect = ([x, y, rw, rh], cls) => `<rect class="${cls}" x="${x}" y="${y}" width="${rw}" height="${rh}"/>`,
    line = (x, cls) => `<line class="${cls}" x1="${x}" y1="0" x2="${x}" y2="${h}"/>`,
    pages =
      kind === 'book'
        ? rect([0, 0, w, h], 'sk-page') + rect([w, 0, w, h], 'sk-page')
        : rect([0, 0, sheet, h], 'sk-page');
  return `<svg class="safety-svg" viewBox="0 0 ${sheet} ${h}" aria-hidden="true">${pages}${geo.bands.map(r => rect(r, 'sk-bleed')).join('')}${geo.spines.map(r => rect(r, 'sk-spine')).join('')}${geo.trims.map(r => rect(r, 'sk-trim')).join('')}${geo.safes.map(r => rect(r, 'sk-safe')).join('')}${geo.gaps.map(x => line(x, 'sk-gap')).join('')}${geo.folds.map(x => line(x, 'sk-fold')).join('')}</svg>`;
}
const safetySketchValues = {
  spreads: { bleed: 3.5, safe: 3.5 },
  book: { bleed: 4.5, outer: 3, spine: 5, safe: 3 },
  cover: { bleed: 3.5, safe: 3, spine: 7, gap: 1.5 },
};
function safetySketch(kind) {
  return safetySvg(kind, 34, 44, safetySketchValues[kind]);
}
function safetyNote(kind, g) {
  const mm = key => `${round(Number(g[key]) || 0)} мм`;
  return kind === 'book'
    ? `Вылет ${mm('bleed')} сверху и снизу, ${mm('outer')} снаружи · корешок ${mm('spine')} · зона ${mm('safe')}`
    : kind === 'cover'
      ? `Корешок ${doc.sheetThickness ? 'по толщине листа' : mm('spine')} · расстав ${mm('gap')} · вылет ${mm('bleed')}`
      : `Вылет ${mm('bleed')} по краю разворота · зона ${mm('safe')}`;
}
const safetyRows = {
  spreads: [
    ['safe', 'safe', 'Безопасная зона'],
    ['bleed', 'bleed', 'Вылет по краю разворота'],
  ],
  book: [
    ['safe', 'safe', 'Безопасная зона'],
    ['bleed', 'bleed', 'Вылет сверху и снизу'],
    ['bleed', 'outer', 'Вылет снаружи'],
    ['spine', 'spine', 'Корешок'],
  ],
  cover: [
    ['safe', 'safe', 'Безопасная зона'],
    ['bleed', 'bleed', 'Вылет'],
    ['spine', 'spine', 'Корешок'],
    ['gap', 'gap', 'Расстав'],
  ],
};
function safetyPanel(sec) {
  const kind = safetyKind(sec),
    guide = kind === 'cover' ? { ...safetyValues(kind), spine: coverSpine() } : safetyValues(kind);
  return `<section class="inspector-section"><div class="inspector-heading safety-heading"><h3>Линии безопасности</h3><button type="button" class="safety-edit" data-open-safety="${sec.cover ? 'cover' : 'pages'}">Настроить</button></div><div class="safety-summary">${safetyRows[kind].map(([cls, key, name]) => `<div><span class="safety-dot ${cls}"></span>${name}<strong>${round(Number(guide[key]) || 0)} мм</strong></div>`).join('')}</div></section>`;
}
let safetyScope = 'pages',
  safetyStart = null,
  safetyFrame = 0;
function safetyDialogKind() {
  return safetyScope === 'cover' ? 'cover' : doc.layout === 'book' ? 'book' : 'spreads';
}
function safetySize() {
  return safetyScope === 'cover'
    ? coverSection()?.pageSize || doc.pageSize || [210, 280]
    : doc.pageSize || [210, 280];
}
/* The book lines live apart from the spread ones, so switching the layout back and forth keeps both. */
function safetySettings() {
  const kind = safetyDialogKind();
  if (kind === 'cover') return (coverSection().safety ??= {});
  const g = (doc.safety ??= {});
  return kind === 'book' ? (g.book ??= { ...BOOK_SAFETY }) : g;
}
function safetyControl(key, title, help, max) {
  const value = round(Number(safetyValues(safetyDialogKind())[key]) || 0);
  return `<div class="safety-control"><div class="safety-control-heading"><strong>${title}</strong><small>${help}</small></div><div class="safety-control-inputs"><input type="range" data-safety-key="${key}" min="0" max="${max}" step="0.5" value="${value}" aria-label="${title}"><label><input type="number" data-safety-key="${key}" min="0" max="${max}" step="0.5" value="${value}" aria-label="${title}, мм"><span>мм</span></label></div></div>`;
}
const safetyControls = {
  spreads: [
    [
      'bleed',
      'Вылет',
      'Запас под обрезку по внешнему краю разворота. На сгибе вылета нет — разворот печатается одним листом.',
      30,
    ],
    ['safe', 'Безопасная зона', 'Отступ от линии реза для текста, лиц и важных деталей.', 60],
  ],
  book: [
    ['bleed', 'Вылет сверху и снизу', 'Запас под обрезку по верхнему и нижнему краю страницы.', 30],
    [
      'outer',
      'Вылет снаружи',
      'Запас под обрезку по внешнему краю: слева у левой страницы, справа у правой.',
      30,
    ],
    ['spine', 'Корешок', 'Полоса у внутреннего края уходит в переплёт — её заполняют фоном.', 40],
    ['safe', 'Безопасная зона', 'Отступ от линии реза для текста, лиц и важных деталей.', 60],
  ],
  cover: [
    ['bleed', 'Вылет', 'Запас под обрезку по внешнему краю развёртки обложки.', 30],
    ['safe', 'Безопасная зона', 'Отступ от линии реза и от корешка для текста и важных деталей.', 60],
    ['spine', 'Корешок', 'Центральная часть переплёта.', 100],
    ['gap', 'Расстав', 'Зазор по краям корешка для сгиба и склейки.', 50],
  ],
};
const safetyLegend = {
  spreads: [
    ['bleed', 'Вылет по краю разворота'],
    ['safe', 'Безопасная зона'],
    ['fold', 'Сгиб — без вылета'],
  ],
  book: [
    ['bleed', 'Вылет сверху, снизу и снаружи'],
    ['spine', 'Корешок — заполнить фоном'],
    ['safe', 'Безопасная зона'],
  ],
  cover: [
    ['bleed', 'Вылет'],
    ['safe', 'Безопасная зона'],
    ['spine', 'Корешок и расстав'],
  ],
};
function renderSafetyPreview() {
  const kind = safetyDialogKind(),
    [w, h] = safetySize(),
    title = {
      spreads: ['Разворот печатается одним листом', `${round(2 * w)} × ${round(h)} мм`],
      book: ['Каждая страница печатается отдельно', `2 × ${round(w)} × ${round(h)} мм`],
      cover: ['Развёртка обложки', `${round(2 * w + coverSpine())} × ${round(h)} мм`],
    }[kind];
  $('#safety-preview').innerHTML =
    `<div class="safety-preview-title">${title[0]} <span>${title[1]}</span></div><div class="safety-sheet${kind === 'book' ? ' book' : ''}">${safetySvg(kind, w, h, safetyValues(kind), kind === 'cover' ? coverSpine() : undefined)}</div><p>${safetyScope === 'cover' ? (doc.sheetThickness ? `Корешок ${round(coverSpine())} мм — по толщине листа для ${plural(editorVolume().spreads, 'разворота', 'разворотов', 'разворотов')}. В заказе он пересчитается по объёму книги.` : 'Схема показывает расположение линий.') : `Вёрстка «${kind === 'book' ? 'Как книга' : 'Развороты'}» — её можно сменить в настройках макета, линии для каждой хранятся отдельно.`} На холсте линии обновляются при изменении значения.</p>`;
  $('#safety-legend').innerHTML = safetyLegend[kind]
    .map(([cls, name]) => `<span><i class="safety-dot ${cls}"></i>${name}</span>`)
    .join('');
}
function renderSafetyDialog() {
  $$('#safety-dialog [data-safety-scope]').forEach(b => {
    const active = b.dataset.safetyScope === safetyScope;
    b.classList.toggle('active', active);
    b.setAttribute('aria-selected', String(active));
  });
  $('#safety-controls').innerHTML = safetyControls[safetyDialogKind()]
    .filter(([key]) => !(safetyScope === 'cover' && key === 'spine' && doc.sheetThickness))
    .map(args => safetyControl(...args))
    .join('');
  renderSafetyPreview();
}
function selectSafetyScope(scope) {
  safetyScope = scope;
  const target = scope === 'cover' ? coverSection() : doc.sections.find(s => !s.cover);
  if (target) {
    view.section = target.id;
    view.spread = 0;
    view.side = scope === 'cover' ? 1 : 0;
    selected = [];
    render();
  }
  renderSafetyDialog();
}
function openSafety(scope) {
  if (preview) return;
  safetyStart = clone(doc);
  $('#safety-dialog').showModal();
  selectSafetyScope(scope);
}
function scheduleSafetyScene() {
  if (safetyFrame) return;
  safetyFrame = requestAnimationFrame(() => {
    safetyFrame = 0;
    renderScene();
  });
}
/* A value that would leave no room between the lines is lowered to the largest one that still fits. */
$('#safety-dialog').addEventListener('input', e => {
  const key = e.target.dataset.safetyKey;
  if (!key) return;
  const raw = Number(e.target.value);
  if (!Number.isFinite(raw)) return;
  const kind = safetyDialogKind(),
    g = safetySettings(),
    [w, h] = safetySize(),
    max = safetyControls[kind].find(c => c[0] === key)[3];
  let value = round(clamp(raw, 0, max));
  while (
    value > 0 &&
    !safetyFits(
      kind,
      w,
      h,
      { ...safetyValues(kind), [key]: value },
      kind === 'cover' && doc.sheetThickness ? coverSpine() : undefined,
    )
  )
    value = Math.max(0, round(value - 0.5));
  g[key] = value;
  $$(`#safety-dialog [data-safety-key="${key}"]`).forEach(input => {
    if (input !== e.target || input.type === 'range') input.value = g[key];
  });
  renderSafetyPreview();
  scheduleSafetyScene();
});
$('#safety-dialog').addEventListener('click', e => {
  const tab = e.target.closest('[data-safety-scope]');
  if (tab) selectSafetyScope(tab.dataset.safetyScope);
});
for (const id of ['safety-close', 'safety-done']) $('#' + id).onclick = () => $('#safety-dialog').close();
$('#safety-dialog').addEventListener('close', () => {
  if (safetyFrame) {
    cancelAnimationFrame(safetyFrame);
    safetyFrame = 0;
  }
  if (safetyStart && JSON.stringify(safetyStart) !== JSON.stringify(doc)) {
    history.push(safetyStart);
    if (history.length > 60) history.shift();
    future = [];
    markDirty();
    render();
  }
  safetyStart = null;
});
