/* Master editor · Vignette dialog, photo content and collage panels. */
'use strict';
const vignetteDialog = $('#vignette-dialog');
function vignetteLive(key, value, input) {
  const l = selectedLayer();
  if (!l || l.type !== 'grid' || !Number.isFinite(value)) return;
  if (!slide) slide = { start: clone(doc) };
  const grids = section()
    .spreads.flatMap(sp => sp.pages.flatMap(p => p.layers))
    .filter(item => item.type === 'grid');
  if (key === 'minFontSize') value = Math.min(value, l.fontSize);
  for (const item of grids) {
    item[key] = value;
    if (key === 'min' && item.max < value) item.max = value;
    if (key === 'max' && item.min > value) item.min = value;
    if (key === 'fontSize' && item.minFontSize > value) item.minFontSize = value;
    if (key === 'minPhotoWidth' && (item.photoWidth ?? 85) < value) item.photoWidth = value;
    if (key === 'photoWidth' && item.minPhotoWidth > value) item.minPhotoWidth = value;
  }
  if (input && Number(input.value) !== value) input.value = String(value);
  const paired =
    key === 'min'
      ? 'max'
      : key === 'max'
        ? 'min'
        : key === 'fontSize'
          ? 'minFontSize'
          : key === 'photoWidth'
            ? 'minPhotoWidth'
            : key === 'minPhotoWidth'
              ? 'photoWidth'
              : null;
  if (paired) {
    const other = $(`#vignette-controls [data-prop="${paired}"],#vignette-controls [data-live="${paired}"]`);
    if (other) other.value = l[paired];
  }
  planner = MasterPlanner(doc, view);
  plans = planner.plan();
  vignettePreview();
  renderScene();
}
async function uploadVignetteFont(el) {
  const file = el.files?.[0];
  el.value = '';
  if (!file) return;
  if (file.size > 1500000) return notify('Шрифт больше 1,5 МБ', true);
  if ((doc.fonts || []).length >= 12) return notify('В макете уже 12 шрифтов', true);
  const bytes = new Uint8Array(await file.arrayBuffer()),
    format = fontKind(bytes);
  if (!format) return notify('Нужен файл TTF или OTF', true);
  const name = (file.name.replace(/\.(ttf|otf)$/i, '').trim() || 'Шрифт').slice(0, 60),
    id = 'font-' + uid(),
    dataUrl = 'data:font/' + format + ';base64,' + bytesToBase64(bytes),
    key = el.dataset.fontTarget || 'font';
  commit(() => {
    doc.fonts = [...(doc.fonts || []), { id, name, dataUrl }];
    section()
      .spreads.flatMap(sp => sp.pages.flatMap(p => p.layers))
      .filter(item => item.type === 'grid')
      .forEach(item => (item[key] = id));
  });
  renderVignetteDialog();
}
vignetteDialog.addEventListener('click', e => {
  if (e.target.closest('#vignette-close,#vignette-done')) {
    vignetteDialog.close();
    return;
  }
  if (e.target.closest('[data-vignette-block]')) {
    vignetteDialog.close();
    openBlockSettings();
    return;
  }
  const pageStep = e.target.closest('[data-vignette-page]');
  if (pageStep) {
    vignettePage += Number(pageStep.dataset.vignettePage);
    vignettePreview();
    return;
  }
  const tab = e.target.closest('[data-vignette-dialog-tab]');
  if (tab) {
    vignetteDialogTab = tab.dataset.vignetteDialogTab;
    renderVignetteDialog();
    return;
  }
  const type = e.target.closest('[data-vignette-type]');
  if (type) {
    vignetteTextTab = type.dataset.vignetteType;
    renderVignetteDialog();
    return;
  }
  const color = e.target.closest('[data-color-key]');
  if (color) {
    openColor(color);
    return;
  }
  const remove = e.target.closest('[data-font-remove]');
  if (remove) {
    const id = remove.dataset.fontRemove;
    loadedFonts.delete(id);
    commit(() => {
      doc.fonts = (doc.fonts || []).filter(font => font.id !== id);
      allLayers().forEach(layer => {
        if (layer.font === id) layer.font = 'Arial';
        if (layer.detailFont === id) layer.detailFont = 'Arial';
      });
      (doc.textStyles || []).forEach(style => {
        if (style.font === id) style.font = 'Arial';
      });
    });
    renderVignetteDialog();
    return;
  }
  const choice = e.target.closest('[data-choice]');
  if (!choice) return;
  const l = selectedLayer(),
    key = choice.dataset.choice;
  if (!l) return;
  if (key === 'showDetail') {
    vignetteTextTab = l.showDetail ? 'name' : 'detail';
    property(key, !l.showDetail);
  } else if (
    [
      'bold',
      'italic',
      'underline',
      'strike',
      'detailBold',
      'detailItalic',
      'detailUnderline',
      'detailStrike',
      'strictMin',
      'excludeLead',
    ].includes(key)
  )
    property(key, !l[key]);
  else property(key, choice.dataset.value);
  renderVignetteDialog();
});
vignetteDialog.addEventListener('input', e => {
  const el = e.target;
  if (el.dataset.vignetteTestCount) {
    if (el.value !== '' && el.validity.valid) {
      view[el.dataset.vignetteTestCount] = Number(el.value);
      planner = MasterPlanner(doc, view);
      plans = planner.plan();
      vignettePreview();
      renderScene();
    }
    return;
  }
  const key = el.dataset.live || (el.type === 'number' ? el.dataset.prop : null);
  if (!key || el.value === '' || !el.validity.valid) return;
  vignetteLive(key, Number(el.value), el);
});
vignetteDialog.addEventListener('change', e => {
  const el = e.target;
  if (el.dataset.vignetteTestCount) return;
  if (el.dataset.vignetteTestFlag) {
    view[el.dataset.vignetteTestFlag] = el.checked;
    planner = MasterPlanner(doc, view);
    plans = planner.plan();
    vignettePreview();
    renderScene();
    return;
  }
  if (el.id === 'font-upload') {
    uploadVignetteFont(el);
    return;
  }
  if (el.dataset.live || (el.type === 'number' && el.dataset.prop)) {
    finishSlide();
    vignettePreview();
    return;
  }
  const key = el.dataset.prop;
  if (!key) return;
  const value = ['bold', 'detailBold'].includes(key)
    ? el.value === 'true'
    : el.type === 'checkbox'
      ? el.checked
      : el.value;
  property(key, value);
  renderVignetteDialog();
});
vignetteDialog.addEventListener('close', () => {
  if (slide) finishSlide();
  if (colorPop) closeColor(false);
  document.body.append($('#color-pop'));
});
const staticPhotoIcon = '<span class="static-photo-icon" aria-hidden="true"></span>';
/* What fills a photo layer or a collage frame. One panel for both, so they are set up the same way. */
function photoContentPanel(item, { title, key, cell }) {
  const source = item.source || 'class',
    kind = CollageCore.kind(source),
    modes = `<div class="photo-mode-switch" data-mode="${kind}" role="group" aria-label="Что в кадре">${contentKinds.map(([id, label]) => `<button type="button" data-content-kind="${id}" class="${kind === id ? 'active' : ''}" aria-pressed="${kind === id}">${label}</button>`).join('')}</div>`;
  let body = '';
  if (kind === 'portrait') {
    const rows = portraitChoices(source)
      .map(
        ([id, label, note]) =>
          `<button type="button" class="photo-choice${source === id ? ' active' : ''}" data-content-source="${id}" aria-pressed="${source === id}"><span class="photo-radio" aria-hidden="true"></span><span class="photo-choice-copy"><strong>${label}</strong><small>${note}</small></span></button>`,
      )
      .join('');
    body = `<div class="photo-choice-list" role="group" aria-label="Чей портрет">${rows}</div>`;
  } else if (kind === 'custom') {
    const action = item.dataUrl ? 'Заменить файл' : 'Загрузить файл',
      id = cell ? 'cell-upload' : 'photo-upload';
    body = `<div class="photo-file-row">${item.dataUrl ? `<img src="${esc(item.dataUrl)}" alt="Загруженное изображение">` : `<span class="photo-file-empty" aria-hidden="true">${staticPhotoIcon}</span>`}<span class="photo-file-copy">${item.dataUrl ? 'Одинаково во всех альбомах' : 'PNG, JPEG или WebP до 1 МБ'}</span><label class="photo-upload" title="${action}" aria-label="${action}">${cellGlyph.upload}<input id="${id}" type="file" accept="image/jpeg,image/png,image/webp" aria-label="${action}"></label></div>${item.dataUrl ? `<button type="button" class="wide crop-button" data-content-crop>${cellGlyph.crop}<span>Кадрировать</span></button>` : ''}`;
  } else body = MasterPhotos.panel(item.pick, pickKey(key), section());
  return block(title, modes + body);
}
/* Collage settings: gaps in mm (one value unless unlinked) and rows/columns. */
/* Collage settings: gaps in mm as draggable values (like text metrics), rows and columns. One gap unless unlinked. */
const collageIcons = {
  gap: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2.5" y="2.5" width="6" height="6" rx="1"/><rect x="11.5" y="2.5" width="6" height="6" rx="1"/><rect x="2.5" y="11.5" width="6" height="6" rx="1"/><rect x="11.5" y="11.5" width="6" height="6" rx="1"/></svg>',
  gapX: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 3v14M17 3v14M7 10h6M7 10l2-2M7 10l2 2M13 10l-2-2M13 10l-2 2"/></svg>',
  gapY: '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 3h14M3 17h14M10 7v6M10 7l-2 2M10 7l2 2M10 13l-2-2M10 13l2-2"/></svg>',
  addRow:
    '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="2.5" width="14" height="8" rx="1.5"/><path d="M3 6.5h14M10 2.5v8M10 13.5v5M7.5 16h5"/></svg>',
  addCol:
    '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2.5" y="3" width="8" height="14" rx="1.5"/><path d="M6.5 3v14M2.5 10h8M13.5 10h5M16 7.5v5"/></svg>',
  removeRow:
    '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="2.5" width="14" height="8" rx="1.5"/><path d="M3 6.5h14M10 2.5v8M7.5 16h5"/></svg>',
};
function collagePanel(l) {
  const flex = !!l.flex,
    linked = CollageCore.gapsLinked(l),
    allowed = CollageCore.can(l, focusCell),
    mm = (label, key, value, max, icon) =>
      scrubField(label, key, round(value), 0, round(max), 0.5, icon, 'мм'),
    gapMax = axis => (flex ? 20 : CollageCore.maxGap(l, axis)),
    gaps = linked
      ? mm('Зазор', 'gap', l.gapX ?? 4, gapMax(), collageIcons.gap)
      : mm('По ширине', 'gapX', l.gapX ?? 4, gapMax('x'), collageIcons.gapX) +
        mm('По высоте', 'gapY', l.gapY ?? 4, gapMax('y'), collageIcons.gapY),
    tool = (act, label, icon, on) =>
      `<button type="button" data-collage="${act}" title="${label}" aria-label="${label}"${on ? '' : ' disabled'}>${icon}</button>`,
    mode = `<div class="segments collage-mode" role="group" aria-label="Раскладка коллажа">${[
      ['fixed', 'Фиксированная', 'Кадры нарезаны вручную и заполняются всегда'],
      ['flex', 'Гибкая', 'Столько кадров, сколько нашлось хороших фото'],
    ]
      .map(([id, name, title]) => {
        const on = (flex ? 'flex' : 'fixed') === id;
        return `<button type="button" data-collage-mode="${id}" class="${on ? 'active' : ''}" aria-pressed="${on}" title="${title}">${name}</button>`;
      })
      .join('')}</div>`,
    gapRow = `<div class="collage-gaps${linked ? '' : ' split'}">${gaps}<button type="button" class="icon-toggle${linked ? ' active' : ''}" data-gap-link title="${linked ? 'Разные зазоры по ширине и высоте' : 'Одинаковый зазор'}" aria-label="Одинаковый зазор" aria-pressed="${linked}">${glyph.link}</button></div>`;
  if (flex) {
    const f = l.flex,
      show = flexShow[l.id] || 0;
    return `<section class="inspector-section collage-section"><h3>Коллаж</h3>${mode}<div class="block-pair"><span>Сколько фото</span><label>от<input type="number" data-flex="min" min="1" max="${CollageCore.FLEX_MAX}" value="${f.min}" aria-label="Сколько фото: от"></label><label>до<input type="number" data-flex="max" min="1" max="${CollageCore.FLEX_MAX}" value="${f.max}" aria-label="Сколько фото: до"></label></div><p class="section-note">Берёт столько снимков, сколько нашлось без уступок, но не меньше минимума. Кадры раскладываются по форме снимков.</p>${gapRow}<p class="visual-label">Показать на холсте</p><div class="segments flex-show" role="group" aria-label="Сколько фото показать на холсте">${[
      [0, 'Тест'],
    ]
      .concat(Array.from({ length: f.max }, (_, i) => [i + 1, String(i + 1)]))
      .map(
        ([n, name]) =>
          `<button type="button" data-flex-show="${n}" class="${show === n ? 'active' : ''}" aria-pressed="${show === n}" title="${n ? `Как будет при ${n} фото` : 'Как подберётся на тестовой съёмке'}">${name}</button>`,
      )
      .join('')}</div></section>`;
  }
  return `<section class="inspector-section collage-section"><h3>Коллаж</h3>${mode}${gapRow}<div class="collage-tools" role="group" aria-label="Ряды и колонки">${tool('add-row', 'Добавить ряд', collageIcons.addRow, allowed.addRow)}${tool('add-col', 'Добавить колонку', collageIcons.addCol, allowed.addColumn)}${tool('remove-row', focusCell ? 'Удалить ряд с выбранным кадром' : 'Удалить ряд — сначала выберите кадр в нём', collageIcons.removeRow, focusCell && allowed.removeRow)}</div></section>`;
}
/* Frames of a flexible collage on the canvas: as many as the test shoot found, or as many as the designer asked to see. */
const flexShow = {};
function flexLayout(l, sectionId, pageIndex) {
  const high = clamp(Number(l.flex?.max) || 4, 1, CollageCore.FLEX_MAX),
    forced = flexShow[l.id];
  let aspects;
  if (forced) aspects = Array(clamp(forced, 1, high)).fill(1.5);
  else if (MasterPhotos.ready()) {
    aspects = [];
    for (let i = 0; i < high; i++) {
      const slot = MasterPhotos.slot(sectionId, pageIndex, l.id + '/flex' + i);
      if (slot) aspects.push(slot.size ? slot.size[0] / slot.size[1] : 1.5);
    }
    if (!aspects.length) aspects = Array(clamp(Number(l.flex?.min) || 1, 1, high)).fill(1.5);
  } else aspects = Array(high).fill(1.5);
  return CollageCore.flexFrames(l.box.w, l.box.h, aspects, Number(l.gapX ?? 4), Number(l.gapY ?? 4)).map(
    (f, i) => ({ ...f, cell: { id: 'flex' + i, source: 'class', pick: l.pick, forced: !!forced } }),
  );
}
/* Preview key of an automatic slot: section, first generated page of its template, layer[/cell]. */
function pickKey(id) {
  const sec = section(),
    plan = plans.find(p => p.sectionId === sec.id),
    layerId = id.split('/')[0];
  if (!plan) return '';
  const template = sec.spreads.flatMap(sp => sp.pages).find(p => p.layers.some(x => x.id === layerId));
  const index = plan.pages.findIndex(g => g.templateId === template?.id);
  return index < 0 ? '' : `${sec.id}:${index}/${id}`;
}
