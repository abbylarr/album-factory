/* Master editor · Album settings dialog: format, spine, safety card. */
'use strict';
/* Album settings: layout of the book, page and cover size, safety lines and the rules and categories of general photos. */
let albumTab = 'format';
function albumSummary() {
  const [w, h] = doc.pageSize || [210, 280],
    book = doc.layout === 'book';
  return `${round(book ? w : 2 * w)} × ${round(h)} мм · ${book ? 'как книга' : 'развороты'}`;
}
/* Size fields drag like the rest of the editor; a spread width is twice the stored page width. */
/* The icon sketches the pages like the layout choice above and brackets the measured side. */
/* A shown value is stored × factor + offset: a spread is two pages, a whole cover is two sides and the spine. */
function albumNumber(label, key, value, factor = 1, offset = 0) {
  const axis = key.endsWith('width') ? 'width' : 'height',
    title = `${label}, мм`,
    cover = key.startsWith('cover.'),
    pages = cover ? '<i></i><b></b><i></i>' : doc.layout === 'book' ? '<i></i>' : '<i></i><i></i>',
    min = 50 * factor + offset,
    max = 500 * factor + offset;
  return `<div class="type-field"><div class="type-value" data-scrub="album" data-min="${min}" data-max="${max}" data-step="1" title="${title}: потяните влево или вправо"><span class="type-inline-scrub size-sketch ${axis}" aria-hidden="true">${pages}</span><input aria-label="${title}" data-album-size="${key}" data-factor="${factor}" data-offset="${offset}" type="number" value="${round((value || 0) * factor + offset)}" min="${min}" max="${max}" step="0.1"></div></div>`;
}
/* Printers give the whole cover for the thinnest book: its sides are that width less the thinnest spine. */
/* A short hint behind an «i» next to a label: shown on hover and on focus. */
function infoTip(text) {
  return `<span class="info-tip" tabindex="0" role="img" aria-label="${esc(text)}" data-tip="${esc(text)}">i</span>`;
}
function baseSpine() {
  return doc.sheetThickness ? SPINE_MIN : Number(coverSection()?.safety?.spine) || 0;
}
function safetyCard(scope, kind, title) {
  return `<button type="button" class="safety-card" data-album-safety="${scope}"><span class="safety-sketch">${safetySketch(kind)}</span><strong>${title}</strong><small>${safetyNote(kind, safetyValues(kind))}</small></button>`;
}
function layoutChoice(id, title, help, sheets) {
  const on = (doc.layout || 'spreads') === id;
  return `<button type="button" class="layout-choice${on ? ' active' : ''}" data-album-layout="${id}" aria-pressed="${on}"><span class="layout-sketch" aria-hidden="true">${sheets.map(([a, b]) => `<span><i class="${a}"></i><i class="${b}"></i></span>`).join('')}</span><strong>${title}</strong><small>${help}</small></button>`;
}
/* Cover spine: fixed, or counted from the thickness of one inner sheet — a layflat spread, or two pages of a book. */
/* Ready thicknesses by kind of book, or your own: a layflat or photo paper spread is one sheet; a book printed page by page has two pages to a sheet. */
const SHEET_PRESETS = {
  spreads: [
    [
      'Лайфлат',
      [
        ['На бумаге', 0.48],
        ['На картоне', 0.62],
        ['Картон с прослойкой 1 мм', 1.09],
      ],
    ],
    [
      'Фотобумага',
      [
        ['Без прослойки', 0.52],
        ['С прослойкой 1 мм', 0.99],
        ['С прослойкой 2 мм', 1.84],
      ],
    ],
    ['Мелованная', [['280 г/м² без ламинации', 0.39]]],
  ],
  book: [['Мелованная', [['170 г/м²', 0.14]]]],
};
let sheetMenu = false;
/* The paper menu stays inside the dialog: it opens up when there is more room above and scrolls on its own. */
function placeSheetMenu() {
  const menu = $('.sheet-picker .pick-menu');
  if (!menu) return;
  const box = $('#album-dialog').getBoundingClientRect(),
    trigger = menu.previousElementSibling.getBoundingClientRect(),
    below = box.bottom - trigger.bottom - 18,
    above = trigger.top - box.top - 18,
    up = below < menu.scrollHeight && above > below;
  menu.classList.toggle('up', up);
  menu.style.maxHeight = Math.max(120, Math.min(340, up ? above : below)) + 'px';
}
const SHEET_CARET =
    '<svg class="caret" viewBox="0 0 10 10" aria-hidden="true"><path d="M2.5 4 5 6.5 7.5 4" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  SHEET_TICK =
    '<svg class="mark" viewBox="0 0 16 16" aria-hidden="true"><path d="M3.2 8.4 6.3 11.5 12.8 4.6" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>';
const mmText = v => String(v).replace('.', ',');
function spineSection() {
  if (!coverSection()) return '';
  const t = doc.sheetThickness,
    book = doc.layout === 'book',
    chip = (attr, value, body, on) =>
      `<button type="button" class="${on ? 'active' : ''}" data-${attr}="${value}" aria-pressed="${on}">${body}</button>`;
  const groups = SHEET_PRESETS[book ? 'book' : 'spreads'],
    known = groups.flatMap(([name, items]) =>
      items.filter(([, mm]) => mm === t).map(([label]) => `${name} · ${label.toLowerCase()}`),
    )[0],
    current = known || 'Своя толщина',
    row = (mm, label, on) =>
      `<button type="button" class="menu-row${on ? ' on' : ''}" role="menuitemradio" aria-checked="${on}" data-sheet-preset="${mm}"><span>${label}</span>${on ? SHEET_TICK : ''}</button>`;
  const detail = t
    ? `<div class="album-sizes spine-fields"><div class="type-field"><span class="type-label">Бумага</span><div class="pick-picker sheet-picker"><button type="button" class="pick-trigger" data-sheet-menu aria-haspopup="menu" aria-expanded="${sheetMenu}"><span>${esc(current)}</span>${SHEET_CARET}</button>${sheetMenu ? `<div class="cell-sources pick-menu" role="menu">${groups.map(([name, items]) => `<p class="menu-label">${name}</p>${items.map(([label, mm]) => row(mm, label, mm === t)).join('')}`).join('')}<p class="menu-label">Другая</p>${row('', 'Своя толщина', !known)}</div>` : ''}</div></div><div class="type-field"><span class="type-label">Толщина листа</span><div class="type-value" data-scrub="sheet" data-min="0.02" data-max="5" data-step="0.01" title="Толщина листа, мм: потяните влево или вправо"><span class="type-inline-scrub sheet-sketch" aria-hidden="true"><i></i><i></i><i></i></span><input aria-label="Толщина листа, мм" data-sheet-thickness type="number" value="${t}" min="0.02" max="5" step="0.01"><span class="unit">мм</span></div></div></div>`
    : '<p class="section-note">Ширина корешка задаётся в линиях безопасности обложки и не зависит от объёма книги.</p>';
  return `<section class="album-section"><h3>Корешок обложки</h3><div class="segments spine-mode">${chip('spine-mode', 'auto', 'По толщине листа', !!t)}${chip('spine-mode', 'fixed', 'Фиксированный', !t)}</div>${detail}</section>`;
}
function renderAlbumDialog() {
  const dialog = $('#album-dialog');
  if (!dialog?.open) return;
  const body = $('#album-body'),
    scroll = body.scrollTop;
  $$('#album-dialog [data-album-tab]').forEach(b => {
    const on = b.dataset.albumTab === albumTab;
    b.classList.toggle('active', on);
    b.setAttribute('aria-selected', String(on));
  });
  let html = '';
  if (albumTab === 'format') {
    const cover = coverSection(),
      coverSize = cover?.pageSize || doc.pageSize || [210, 280],
      [w, h] = doc.pageSize || [210, 280],
      book = doc.layout === 'book';
    html =
      `<section class="album-section"><h3>Вёрстка</h3><div class="layout-choices">${layoutChoice(
        'spreads',
        'Развороты',
        'Все страницы — полные развороты, от первого до последнего.',
        [
          ['p', 'p'],
          ['p', 'p'],
          ['p', 'p'],
        ],
      )}${layoutChoice('book', 'Как книга', 'Первая страница стоит одна справа, последняя — одна слева.', [
        ['x', 'p'],
        ['p', 'p'],
        ['p', 'x'],
      ])}</div>${doc.layout === 'book' ? '<p class="section-note">Левая страница первого разворота и правая страница последнего не печатаются — на холсте они затенены.</p>' : ''}</section>` +
      `<section class="album-section"><h3>Размер, мм</h3><div class="album-sizes"><div><span>${book ? 'Страница' : 'Разворот'}${infoTip(book ? 'Как в шаблоне типографии, вместе с вылетом.' : 'Весь разворот, как в шаблоне типографии, вместе с вылетом.')}</span><div class="field-grid">${albumNumber('Ширина', 'document.width', w, book ? 1 : 2)}${albumNumber('Высота', 'document.height', h)}</div></div>${cover ? `<div><span>Обложка${infoTip('Как в шаблоне типографии для самой тонкой книги. Под объём альбома обложка подстроится сама.')}</span><div class="field-grid">${albumNumber('Ширина', 'cover.width', coverSize[0], 2, baseSpine())}${albumNumber('Высота', 'cover.height', coverSize[1])}</div></div>` : ''}</div></section>` +
      `${spineSection()}<section class="album-section"><h3>Линии безопасности</h3><div class="album-safety">${safetyCard('pages', book ? 'book' : 'spreads', book ? 'Страницы книги' : 'Развороты')}${cover ? safetyCard('cover', 'cover', 'Обложка') : ''}</div></section>`;
  } else html = MasterPhotos.rulesPanel(doc) + MasterPhotos.categoriesPanel(doc);
  body.innerHTML = html;
  body.scrollTop = scroll;
  placeSheetMenu();
}
function openAlbum(tab = 'format') {
  if (preview) return;
  albumTab = tab;
  sheetMenu = false;
  const dialog = $('#album-dialog');
  if (!dialog.open) dialog.showModal();
  renderAlbumDialog();
}
$('#album-dialog').addEventListener('click', e => {
  if (MasterPhotos.click(e)) return;
  const tab = e.target.closest('[data-album-tab]');
  if (tab) {
    albumTab = tab.dataset.albumTab;
    renderAlbumDialog();
    return;
  }
  const layout = e.target.closest('[data-album-layout]');
  if (layout) {
    const value = layout.dataset.albumLayout;
    if ((doc.layout || 'spreads') !== value)
      commit(() => {
        doc.layout = value;
      });
    return;
  }
  const safety = e.target.closest('[data-album-safety]');
  if (safety) {
    openSafety(safety.dataset.albumSafety);
    return;
  }
  if (e.target.closest('[data-sheet-menu]')) {
    sheetMenu = !sheetMenu;
    renderAlbumDialog();
    return;
  }
  const preset = e.target.closest('[data-sheet-preset]');
  if (preset) {
    sheetMenu = false;
    const mm = Number(preset.dataset.sheetPreset);
    if (mm && doc.sheetThickness !== mm)
      commit(() => {
        doc.sheetThickness = mm;
      });
    else {
      renderAlbumDialog();
      if (!mm) $('#album-dialog [data-sheet-thickness]')?.focus();
    }
    return;
  }
  const mode = e.target.closest('[data-spine-mode]');
  if (mode) {
    const auto = mode.dataset.spineMode === 'auto';
    if (auto !== !!doc.sheetThickness)
      commit(() => {
        if (auto) doc.sheetThickness = doc.layout === 'book' ? 0.14 : 0.48;
        else delete doc.sheetThickness;
      });
    return;
  }
});
document.addEventListener(
  'pointerdown',
  e => {
    if (sheetMenu && !e.target.closest('.sheet-picker')) {
      sheetMenu = false;
      $('.sheet-picker .pick-menu')?.remove();
      $('.sheet-picker [data-sheet-menu]')?.setAttribute('aria-expanded', 'false');
    }
  },
  true,
);
$('#album-dialog').addEventListener('change', e => {
  if (MasterPhotos.change(e)) return;
  const el = e.target;
  if (el.hasAttribute('data-sheet-thickness')) {
    if (el.value === '' || !el.validity.valid) {
      el.reportValidity();
      return;
    }
    commit(() => {
      doc.sheetThickness = Math.round(Number(el.value) * 100) / 100;
    });
    return;
  }
  if (el.dataset.albumSize) {
    if (el.value === '' || !el.validity.valid) {
      el.reportValidity();
      return;
    }
    const value = Number(el.value);
    property(
      el.dataset.albumSize,
      round((value - (Number(el.dataset.offset) || 0)) / (Number(el.dataset.factor) || 1)),
    );
  }
});
