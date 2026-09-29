/* Master editor · Auto text, text panels, vignette panel and text style menu. */
'use strict';
/* Opacity and corner radius as drag-to-change fields, shown next to the layer's size. */
function layerMetrics(l) {
  const rounded = !['ellipse', 'line', 'svg'].includes(l.type),
    opacity = scrubField(
      'Непрозрачность',
      'opacity',
      l.opacity ?? 100,
      0,
      100,
      1,
      '<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="6.5" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M10 3.5a6.5 6.5 0 0 1 0 13Z" fill="currentColor"/></svg>',
      '%',
    ),
    radius = rounded
      ? scrubField(
          l.type === 'collage' ? 'Скругление кадров' : l.type === 'grid' ? 'Скругление фото' : 'Скругление',
          'radius',
          l.radius || 0,
          0,
          100,
          0.5,
          '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><path d="M4 16V10a6 6 0 0 1 6-6h6"/></svg>',
          'мм',
        )
      : '';
  return `<div class="type-metrics layer-metrics">${opacity}${radius}</div>`;
}
/* Auto text: static text with data chips. The layer keeps one string with {{field}} tokens. */
let chipRange = null,
  autoTextTimer = 0;
function chipHtml(field, mods = []) {
  return `<span class="text-chip" contenteditable="false" data-field="${esc(field)}" data-mods="${esc(mods.join('|'))}">${esc(AutoText.label(field, mods))}</span>`;
}
function autoTextField(l) {
  const groups = AutoText.GROUPS.map(
    ([title, rows]) =>
      `<p class="menu-label">${esc(title)}</p>${rows.map(([field, label]) => `<button type="button" class="chip-row" role="menuitem" data-insert-chip="${esc(field)}"><span class="text-chip">${esc(label)}</span></button>`).join('')}`,
  ).join('');
  return `<div class="auto-text-field"><div class="auto-text" contenteditable="true" role="textbox" aria-multiline="true" aria-label="Текст" spellcheck="false" data-auto-text>${AutoText.parts(
    l.text,
  )
    .map(part => (part.field ? chipHtml(part.field, part.mods) : esc(part.text)))
    .join(
      '',
    )}</div><button type="button" class="auto-text-add" data-chip-menu aria-haspopup="menu" aria-expanded="false" title="Вставить данные заказа">＋ Данные</button><div class="chip-menu" role="menu" aria-label="Данные заказа" hidden>${groups}</div></div><p class="section-note">Чипы заменяются данными каждого альбома; пустое значение не печатается.</p>`;
}
function autoTextValue(box) {
  let out = '';
  const walk = node => {
    for (const n of node.childNodes) {
      if (n.nodeType === 3) out += n.nodeValue;
      else if (n.dataset?.field) out += AutoText.token(n.dataset.field, (n.dataset.mods || '').split('|'));
      else if (n.nodeName === 'BR') out += '\n';
      else {
        if (/^(DIV|P)$/.test(n.nodeName) && out && !out.endsWith('\n')) out += '\n';
        walk(n);
      }
    }
  };
  walk(box);
  return out.replace(/\u200b/g, '').slice(0, 2000);
}
function autoTextInput(box) {
  const layer = selectedLayer();
  if (!layer || layer.type !== 'text') return;
  if (!slide) slide = { start: clone(doc) };
  layer.text = autoTextValue(box);
  clearTimeout(autoTextTimer);
  autoTextTimer = setTimeout(renderScene, 200);
}
function insertChip(field) {
  const box = $('#inspector [data-auto-text]');
  if (!box || !(field in AutoText.FIELDS)) return;
  const range =
    chipRange && box.contains(chipRange.startContainer)
      ? chipRange
      : (() => {
          const r = document.createRange();
          r.selectNodeContents(box);
          r.collapse(false);
          return r;
        })();
  const holder = document.createElement('span');
  holder.innerHTML = chipHtml(field);
  const chip = holder.firstChild;
  range.deleteContents();
  range.insertNode(chip);
  const after = document.createRange();
  after.setStartAfter(chip);
  after.collapse(true);
  const sel = getSelection();
  sel.removeAllRanges();
  sel.addRange(after);
  chipRange = after.cloneRange();
  autoTextInput(box);
  box.focus();
}
function bindAutoText() {
  const host = $('#inspector');
  document.addEventListener('selectionchange', () => {
    const sel = getSelection();
    if (!sel.rangeCount) return;
    const node = sel.anchorNode,
      el = node?.nodeType === 1 ? node : node?.parentElement;
    if (el?.closest('[data-auto-text]')) chipRange = sel.getRangeAt(0).cloneRange();
  });
  const closeChips = () =>
    host.querySelectorAll('.chip-menu:not([hidden])').forEach(menu => {
      menu.hidden = true;
      menu.parentElement.querySelector('[data-chip-menu]')?.setAttribute('aria-expanded', 'false');
    });
  document.addEventListener(
    'pointerdown',
    e => {
      if (!e.target.closest?.('.auto-text-field')) closeChips();
      if (chipPop && !chipPop.element.contains(e.target) && !e.target.closest?.('[data-auto-text] .text-chip'))
        closeChipPop();
    },
    true,
  );
  document.addEventListener(
    'keydown',
    e => {
      if (e.key === 'Escape' && chipPop) {
        e.preventDefault();
        e.stopImmediatePropagation();
        closeChipPop();
      }
    },
    true,
  );
  host.addEventListener('keydown', e => {
    if (e.key === 'Escape' && e.target.closest?.('.auto-text-field')) {
      closeChips();
      return;
    }
    if (e.target.closest?.('[data-auto-text]') && e.key === 'Enter') {
      e.preventDefault();
      document.execCommand('insertText', false, '\n');
    }
  });
  host.addEventListener('paste', e => {
    if (!e.target.closest?.('[data-auto-text]')) return;
    e.preventDefault();
    document.execCommand('insertText', false, e.clipboardData.getData('text/plain'));
  });
  host.addEventListener('input', e => {
    const box = e.target.closest?.('[data-auto-text]');
    if (box) autoTextInput(box);
  });
  host.addEventListener('focusout', e => {
    if (!e.target.closest?.('[data-auto-text]') || e.relatedTarget?.closest?.('.auto-text-field')) return;
    clearTimeout(autoTextTimer);
    if (slide) finishSlide();
  });
  host.addEventListener('pointerdown', e => {
    if (e.target.closest('[data-insert-chip],[data-chip-menu]')) e.preventDefault();
  });
  host.addEventListener(
    'click',
    e => {
      const toggle = e.target.closest('[data-chip-menu]');
      if (toggle) {
        e.stopPropagation();
        const menu = toggle.parentElement.querySelector('.chip-menu'),
          open = menu.hidden;
        menu.hidden = !open;
        toggle.setAttribute('aria-expanded', String(open));
        return;
      }
      const item = e.target.closest('[data-insert-chip]');
      if (item) {
        e.stopPropagation();
        item.closest('.chip-menu').hidden = true;
        insertChip(item.dataset.insertChip);
        return;
      }
      const chip = e.target.closest('[data-auto-text] .text-chip');
      if (chip) {
        e.stopPropagation();
        const box = chip.closest('[data-auto-text]'),
          index = [...box.querySelectorAll('.text-chip')].indexOf(chip);
        if (chipPop?.index === index) closeChipPop();
        else openChipPop(index);
      }
    },
    true,
  );
}
/* Chip settings: click a chip in the text field to pick the form of its value and the letter case. */
let chipPop = null;
function closeChipPop() {
  if (!chipPop) return;
  chipPop.element.remove();
  document.querySelectorAll('[data-auto-text] .text-chip.open').forEach(c => c.classList.remove('open'));
  chipPop = null;
}
function chipAt(index) {
  return $$('#inspector [data-auto-text] .text-chip')[index] || null;
}
function chipPopHtml(field, mods) {
  const forms = AutoText.FORMS[AutoText.kind(field)] || [],
    form = forms.find(([id]) => id && mods.includes(id))?.[0] || '',
    mode = AutoText.CASES.find(([id]) => id && mods.includes(id))?.[0] || '',
    row = (attr, id, name, note, on, icon = '') =>
      `<button type="button" class="menu-row${on ? ' on' : ''}" ${attr}="${id}" role="menuitemradio" aria-checked="${on}">${icon}<span>${esc(name)}</span>${note ? `<small>${esc(note)}</small>` : ''}</button>`;
  return (
    (forms.length
      ? `<p class="menu-label">${esc(AutoText.FIELDS[field])}</p>${forms.map(([id, name, note]) => row('data-chip-form', id, name, note, id === form)).join('')}`
      : '') +
    `<p class="menu-label">Регистр</p>${AutoText.CASES.map(([id, name, icon]) => row('data-chip-case', id, name, '', id === mode, `<b class="case-glyph" aria-hidden="true">${icon}</b>`)).join('')}`
  );
}
function openChipPop(index) {
  closeChipPop();
  const l = selectedLayer(),
    chip = chipAt(index);
  if (!l || l.type !== 'text' || !chip) return;
  const element = document.createElement('div');
  element.className = 'cell-sources chip-pop';
  element.setAttribute('role', 'menu');
  element.setAttribute('aria-label', 'Настройка данных');
  document.body.append(element);
  element.addEventListener('pointerdown', e => e.preventDefault());
  element.addEventListener('click', e => {
    const form = e.target.closest('[data-chip-form]'),
      mode = e.target.closest('[data-chip-case]');
    if (form) setChipMods(chipPop.index, 'form', form.dataset.chipForm);
    else if (mode) setChipMods(chipPop.index, 'case', mode.dataset.chipCase);
  });
  chipPop = { element, index, layerId: l.id };
  drawChipPop();
}
function drawChipPop() {
  const chip = chipPop && chipAt(chipPop.index);
  if (!chip || selectedLayer()?.id !== chipPop.layerId) return closeChipPop();
  const mods = (chip.dataset.mods || '').split('|').filter(Boolean),
    element = chipPop.element;
  document.querySelectorAll('[data-auto-text] .text-chip.open').forEach(c => c.classList.remove('open'));
  chip.classList.add('open');
  element.innerHTML = chipPopHtml(chip.dataset.field, mods);
  const rect = chip.getBoundingClientRect(),
    width = element.offsetWidth,
    height = element.offsetHeight;
  element.style.left = clamp(rect.left, 8, innerWidth - width - 8) + 'px';
  element.style.top =
    (rect.bottom + 6 + height > innerHeight - 8 ? Math.max(8, rect.top - height - 6) : rect.bottom + 6) + 'px';
}
/* One chip's form or case changes; the rest of the text stays as typed. */
function setChipMods(index, kind, value) {
  const l = selectedLayer();
  if (!l || l.type !== 'text') return;
  clearTimeout(autoTextTimer);
  if (slide) finishSlide();
  let seen = -1;
  const text = AutoText.parts(l.text)
    .map(part => {
      if (!part.field) return part.text;
      if (++seen !== index) return AutoText.token(part.field, part.mods);
      const forms = (AutoText.FORMS[AutoText.kind(part.field)] || []).map(([id]) => id),
        cases = AutoText.CASES.map(([id]) => id),
        drop = kind === 'form' ? forms : cases,
        form = kind === 'form' ? value : part.mods.find(m => forms.includes(m)) || '',
        mode = kind === 'case' ? value : part.mods.find(m => cases.includes(m)) || '';
      return AutoText.token(part.field, [...part.mods.filter(m => !drop.includes(m) && m !== form && m !== mode), form, mode]);
    })
    .join('');
  if (text !== l.text) commit(() => (l.text = text));
  drawChipPop();
}
function textPanel(l) {
  const style = textStyle(l),
    styleName = style?.name || 'Без общего стиля';
  return `<div class="type-style-row"><div class="type-style-select"><span class="type-label">Общий стиль</span><button type="button" class="type-style-trigger" data-open-style-menu aria-haspopup="dialog" aria-expanded="false" aria-label="Выбрать общий стиль: ${esc(styleName)}"><span>${esc(styleName)}</span><i class="type-chevron" aria-hidden="true"></i></button></div><div class="text-style-actions"><button type="button" data-text-style="create" title="Создать стиль" aria-label="Создать стиль">＋</button>${style ? `<button type="button" data-text-style="rename" title="Переименовать стиль" aria-label="Переименовать стиль">✎</button>` : ''}</div></div>${style ? '<p class="section-note">Изменения применяются ко всем текстам этого стиля.</p>' : ''}<div class="type-font">${fontRow(l)}</div><div class="type-main-row"><div class="type-weight"><select data-prop="bold" aria-label="Начертание"><option value="false" ${!l.bold ? 'selected' : ''}>Обычное</option><option value="true" ${l.bold ? 'selected' : ''}>Жирное</option></select><i class="type-chevron" aria-hidden="true"></i></div>${scrubField('Размер текста', 'fontSize', l.fontSize, 4, 120, 1, '<span class="type-size-icon">A</span>')}</div><div class="type-metrics">${scrubField('Интерлиньяж', 'lineHeight', l.lineHeight ?? 1.25, 0.8, 3, 0.05, '<svg class="type-line-height-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 3h10M8 17h10M4 5v10M2 7l2-2 2 2M2 13l2 2 2-2"/></svg>')}${scrubField('Интервал', 'letterSpacing', l.letterSpacing ?? 0, -20, 80, 1, '<span class="type-metric-icon">A↔</span>', '%')}${scrubField('Наклон', 'skew', l.skew ?? 0, -30, 30, 1, '<span class="type-metric-icon type-skew-icon">A</span>', '°')}${l.type === 'text' ? textCaseField(l.textCase) : ''}</div><div class="type-align"><span class="type-label">Выравнивание</span>${l.type === 'text' ? `<div class="type-align-pair">${textAlignBar(l.align)}${textValignBar(l.valign)}</div>` : textAlignBar(l.align)}</div>${l.type === 'text' ? textFitRow(l) : ''}<div class="type-extras">${textStyleBar(l)}</div>${colorControl('Цвет', 'color', l.color || '#333333')}`;
}
function textCaseField(value) {
  return `<div class="type-field text-case-field"><span class="type-label">Регистр</span>${segments(
    'textCase',
    value || '',
    AutoText.CASES.map(([id, name, icon]) => [id, name, `<b class="case-glyph">${icon}</b>`]),
  )}</div>`;
}
function textValignBar(value) {
  const icon = y =>
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><path d="M5 ${y === 'top' ? 4 : y === 'bottom' ? 20 : 12}h14"/><path d="M9 ${{ top: 8, middle: 8, bottom: 11 }[y]}h6M9 ${{ top: 12, middle: 16, bottom: 16 }[y]}h6" opacity=".55"/></svg>`;
  return segments('valign', value || 'top', [
    ['top', 'По верхнему краю рамки', icon('top')],
    ['middle', 'По центру рамки', icon('middle')],
    ['bottom', 'По нижнему краю рамки', icon('bottom')],
  ]);
}
function textFitRow(l) {
  return `<div class="text-fit-row"><span class="type-label">Уменьшать, чтобы влезло ${infoTip('Текст не переносится, а уменьшается целиком, пока не влезет в рамку. Новая строка — только там, где нажат Enter.')}</span><button type="button" class="switch${l.fit ? ' on' : ''}" data-choice="fit" aria-pressed="${!!l.fit}" aria-label="Уменьшать, чтобы влезло"></button></div>`;
}
function gridTextPanel(l, prefix = '') {
  const prefixed = key => (prefix ? prefix + key[0].toUpperCase() + key.slice(1) : key),
    value = (key, fallback) => l[prefixed(key)] ?? fallback,
    settings = {
      font: value('font', l.font || 'Georgia'),
      fontSize: value('fontSize', prefix ? 9 : l.fontSize),
      bold: value('bold', prefix ? false : !!l.bold),
      italic: value('italic', prefix ? false : !!l.italic),
      underline: value('underline', prefix ? false : !!l.underline),
      strike: value('strike', prefix ? false : !!l.strike),
      lineHeight: value('lineHeight', 1.25),
      letterSpacing: value('letterSpacing', 0),
      align: value('align', 'center'),
      color: value('color', l.color || '#333333'),
    };
  let html = textPanel(settings),
    start = html.indexOf('<div class="type-font">');
  html = html.slice(start);
  if (prefix)
    html = html.replace(
      /(data-(?:prop|live|choice|color-key|scrub|font-target)=")([^"]+)/g,
      (_, attr, key) => attr + prefixed(key),
    );
  return html;
}
let vignetteTextTab = 'name',
  vignetteDialogTab = 'layout';
const vignetteGapIcon = {
  gap: '<rect x="2" y="4" width="4.5" height="12" rx="1"/><rect x="13.5" y="4" width="4.5" height="12" rx="1"/><path d="M8.5 10h3M9.5 8.5 8.3 10l1.2 1.5M10.5 8.5l1.2 1.5-1.2 1.5"/>',
  photoNameGap:
    '<rect x="4" y="2" width="12" height="7.5" rx="1"/><path d="M10 11.5v3.5M8.6 12.8 10 11.5l1.4 1.3M8.6 13.7 10 15l1.4-1.3M5 18h10"/>',
  nameDetailGap:
    '<path d="M4 3.5h12M10 6.5v6M8.6 7.8 10 6.5l1.4 1.3M8.6 11.2 10 12.5l1.4-1.3M6 16h8M7.5 18.5h5"/>',
};
function vignetteGapField(l, key) {
  return scrubField(
    vignetteGapLabel(l, key),
    key,
    round(vignetteGap(l, key)),
    0,
    vignetteGapMax[key],
    0.5,
    `<svg class="type-line-height-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${vignetteGapIcon[key]}</svg>`,
    'мм',
  );
}
function vignettePanel(l) {
  const teachers = l.source === 'teachers',
    row = (name, value) => `<div>${name}<strong>${value}</strong></div>`;
  return (
    `<section class="inspector-section"><div class="inspector-heading safety-heading"><h3>${teachers ? 'Виньетки учителей' : 'Виньетки учеников'}</h3><button type="button" class="safety-edit" data-open-vignette>Настроить</button></div><div class="safety-summary">${row('Карточек на странице', `${blockList(section()).min}–${blockList(section()).max}`)}${row('Ширина фото', `${round(l.minPhotoWidth)}–${round(l.photoWidth ?? 85)} мм`)}${row('Подпись', l.showDetail ? (teachers ? 'Имя и предмет' : 'Имя и цитата') : 'Только имя')}</div></section>` +
    `<section class="inspector-section typography-section"><div class="typography-heading"><h3>Отступы</h3></div><div class="type-metrics vignette-gaps">${vignetteGapField(l, 'gap')}${vignetteGapField(l, 'photoNameGap')}${l.showDetail ? vignetteGapField(l, 'nameDetailGap') : ''}</div></section>`
  );
}
function vignetteDetailName(l) {
  return l.source === 'teachers' ? 'Предмет' : 'Цитата';
}
function vignetteSettings(l) {
  if (vignetteDialogTab === 'layout') {
    const pair = (title, low, high, unit, attrs) =>
        `<div class="vignette-pair"><span>${title}</span><label>от<input data-prop="${low}" type="number" value="${round(l[low])}" ${attrs} aria-label="${title}: от"></label><label>до<input data-prop="${high}" type="number" value="${round(l[high] ?? 85)}" ${attrs} aria-label="${title}: до"></label><em>${unit}</em></div>`,
      list = blockList(section());
    return `<div class="vignette-dialog-group"><div class="vignette-block-note"><span><strong>${list.source === 'teachers' ? 'Учителя' : 'Ученики'} · ${list.min}–${list.max} на странице</strong><small>Кого и сколько карточек разместить — в настройках блока слева.</small></span><button type="button" data-vignette-block>Изменить</button></div>${pair('Ширина фото', 'minPhotoWidth', 'photoWidth', 'мм', 'min="5" max="180"')}<p class="vignette-field-note">Если карточки не помещаются, фото уменьшается до нижней границы, а дальше карточки переходят на следующую страницу. Отступы меняются на самой странице и в правой панели.</p></div>`;
  }
  const name = vignetteDetailName(l),
    show = !!l.showDetail,
    tab = show && vignetteTextTab === 'detail' ? 'detail' : 'name';
  return `<div class="vignette-dialog-group"><div class="vignette-detail-row"><span><strong>Показывать ${name === 'Цитата' ? 'цитаты' : 'предметы'}</strong><small>Под именем на каждой виньетке</small></span><button type="button" class="switch${show ? ' on' : ''}" data-choice="showDetail" aria-pressed="${show}" aria-label="${show ? 'Скрыть' : 'Показать'} ${name.toLowerCase()}"></button></div>${show ? `<div class="segments vignette-text-tabs" role="tablist" aria-label="Настройки подписей"><button type="button" data-vignette-type="name" role="tab" class="${tab === 'name' ? 'active' : ''}" aria-selected="${tab === 'name'}">Имя</button><button type="button" data-vignette-type="detail" role="tab" class="${tab === 'detail' ? 'active' : ''}" aria-selected="${tab === 'detail'}">${name}</button></div>` : ''}<div class="typography-section">${tab === 'detail' ? gridTextPanel(l, 'detail') : gridTextPanel(l) + `<div class="type-metrics vignette-min-size">${scrubField('Уменьшать до', 'minFontSize', l.minFontSize, 4, 120, 0.5, '<span class="type-metric-icon">A↓</span>', 'pt')}<p>Если длинное имя не помещается в две строки, кегль всех имён блока уменьшается до этого размера.</p></div>`}</div></div>`;
}
let vignettePage = 0,
  vignettePreviewFrame = 0,
  vignettePreviewToken = 0,
  vignetteCanvas = null;
function vignettePreview() {
  if (vignettePreviewFrame) return;
  vignettePreviewFrame = requestAnimationFrame(() => {
    vignettePreviewFrame = 0;
    drawVignettePreview();
  });
}
/* The preview is the real page render at a smaller zoom, so type, effects and spacing always match the canvas. */
async function drawVignettePreview() {
  const l = selectedLayer(),
    dialog = $('#vignette-dialog'),
    stage = dialog.querySelector('.vignette-preview-stage');
  if (!l || l.type !== 'grid' || !dialog.open || !stage || !window.fabric) return;
  const token = ++vignettePreviewToken,
    plan = plans.find(p => p.sectionId === section().id),
    pages = (plan?.pages || []).filter(g => g.records),
    issues = plan?.issues || [];
  vignettePage = clamp(vignettePage, 0, Math.max(0, pages.length - 1));
  const g = pages[vignettePage],
    template = g ? planner.getTemplatePage(g.templateId) : null,
    layer = template?.layers.find(item => item.type === 'grid' && !item.hidden) || l,
    noun = l.source === 'teachers' ? 'учителей' : 'учеников';
  $('#vignette-preview-head').innerHTML =
    `<strong>Пример</strong>${pages.length > 1 ? `<div class="vignette-pages"><button type="button" data-vignette-page="-1" aria-label="Предыдущая страница"${vignettePage ? '' : ' disabled'}>‹</button><span>Страница ${vignettePage + 1} из ${pages.length}</span><button type="button" data-vignette-page="1" aria-label="Следующая страница"${vignettePage < pages.length - 1 ? '' : ' disabled'}>›</button></div>` : ''}`;
  $('#vignette-preview-issues').innerHTML = issues
    .map(i => `<div class="issue ${i.severity}">${esc(i.text)}</div>`)
    .join('');
  const built = g && g.records.length ? await vignetteChildren(layer, g, template?.background) : null;
  if (token !== vignettePreviewToken) return;
  const empty = $('#vignette-preview-empty'),
    facts = $('#vignette-preview-facts');
  if (!built?.geo) {
    empty.hidden = false;
    empty.textContent =
      (g && g.records.length) || !plan
        ? 'Карточки не помещаются. Уменьшите нижнюю границу ширины фото или отступы.'
        : `В примере нет ${noun}. Укажите количество выше.`;
    facts.innerHTML = '';
    vignetteCanvas?.clear();
    return;
  }
  empty.hidden = true;
  const pw = pageWidth(),
    ph = pageHeight(),
    width = Math.max(160, stage.clientWidth - 2),
    scale = Math.min(width / pw, 440 / ph);
  if (!vignetteCanvas)
    vignetteCanvas = new fabric.StaticCanvas('vignette-preview-canvas', { renderOnAddRemove: false });
  const size = { width: Math.round(pw * scale), height: Math.round(ph * scale) };
  if (vignetteCanvas.width !== size.width || vignetteCanvas.height !== size.height)
    vignetteCanvas.setDimensions(size);
  vignetteCanvas.setZoom(scale);
  vignetteCanvas.clear();
  vignetteCanvas.backgroundColor = template?.background || '#fff';
  const b = layer.box;
  vignetteCanvas.add(
    boxGroup(built.children, {
      left: b.x + b.w / 2,
      top: b.y + b.h / 2,
      originX: 'center',
      originY: 'center',
      width: b.w,
      height: b.h,
      angle: layer.angle || 0,
      opacity: (layer.opacity ?? 100) / 100,
      objectCaching: false,
    }),
    new fabric.Rect({
      left: b.x,
      top: b.y,
      width: b.w,
      height: b.h,
      fill: 'transparent',
      stroke: '#b9a6c8',
      strokeWidth: 1 / scale,
      strokeDashArray: [4 / scale, 3 / scale],
      angle: layer.angle || 0,
    }),
  );
  vignetteCanvas.renderAll();
  const count = g.records.length;
  facts.innerHTML = `<span>${count} ${count % 10 === 1 && count % 100 !== 11 ? 'карточка' : [2, 3, 4].includes(count % 10) && ![12, 13, 14].includes(count % 100) ? 'карточки' : 'карточек'}</span><span>Фото <b>${mmLabel(built.geo.photoW)}</b></span><span>Имя <b>${round(g.actualFont || layer.fontSize)} pt</b></span>`;
}
function renderVignetteDialog() {
  const l = selectedLayer();
  if (!l || l.type !== 'grid') return;
  $('#vignette-dialog-title').textContent =
    l.source === 'teachers' ? 'Виньетки учителей' : 'Виньетки учеников';
  $$('#vignette-dialog [data-vignette-dialog-tab]').forEach(b => {
    const active = b.dataset.vignetteDialogTab === vignetteDialogTab;
    b.classList.toggle('active', active);
    b.setAttribute('aria-selected', String(active));
  });
  $('#vignette-controls').innerHTML = vignetteSettings(l);
  const source = l.source,
    noun = source === 'teachers' ? 'учителей' : 'учеников';
  $('#vignette-test-count').innerHTML =
    `<label class="vignette-sample-count">В примере<input data-vignette-test-count="${source}" type="number" min="0" max="${source === 'teachers' ? 60 : 80}" value="${view[source]}" aria-label="Количество ${noun} в примере">${noun}</label><div class="vignette-test-flags"><label class="check"><input type="checkbox" data-vignette-test-flag="long" ${view.long ? 'checked' : ''}>Длинное имя</label><label class="check"><input type="checkbox" data-vignette-test-flag="missing" ${view.missing ? 'checked' : ''}>Нет портрета</label></div>`;
  vignettePreview();
}
function openVignetteDialog() {
  if (preview || selectedLayer()?.type !== 'grid') return;
  vignetteDialogTab = 'layout';
  vignetteTextTab = 'name';
  vignettePage = 0;
  $('#vignette-dialog').append($('#color-pop'));
  renderVignetteDialog();
  $('#vignette-dialog').showModal();
}
let textStyleMenu = null;
function closeTextStyleMenu() {
  if (!textStyleMenu) return;
  textStyleMenu.trigger?.setAttribute('aria-expanded', 'false');
  textStyleMenu.element.remove();
  textStyleMenu = null;
}
function textStyleOption(style, currentId) {
  const selected = (style?.id || '') === currentId,
    name = style?.name || 'Без общего стиля',
    detail = style ? `${style.fontSize} · ${style.lineHeight || 1.25}` : 'Только для этого текста';
  return `<button type="button" class="text-style-option${selected ? ' selected' : ''}" data-style-option="${esc(style?.id || '')}" role="option" aria-selected="${selected}"><span class="text-style-sample">Ag</span><span class="text-style-option-name">${esc(name)}<small>${esc(detail)}</small></span>${selected ? '<span class="text-style-check" aria-hidden="true">✓</span>' : ''}</button>`;
}
function filterTextStyles(query) {
  if (!textStyleMenu) return;
  const list = textStyleMenu.element.querySelector('.text-style-list');
  if (!list) return;
  const selected = selectedLayer()?.styleId || '',
    q = query.trim().toLocaleLowerCase('ru');
  const styles = (doc.textStyles || []).filter(s => s.name.toLocaleLowerCase('ru').includes(q));
  list.innerHTML =
    (!q ? textStyleOption(null, selected) : '') +
    styles.map(s => textStyleOption(s, selected)).join('') +
    (q && !styles.length ? '<p class="text-style-empty">Стили не найдены</p>' : '');
}
function openTextStyleMenu(mode = 'browse') {
  const layer = selectedLayer();
  if (!layer || layer.type !== 'text') return;
  closeTextStyleMenu();
  const trigger = $('[data-open-style-menu]'),
    element = document.createElement('div');
  element.className = 'text-style-menu';
  element.setAttribute('role', 'dialog');
  element.setAttribute(
    'aria-label',
    mode === 'create' ? 'Создать стиль' : mode === 'rename' ? 'Переименовать стиль' : 'Стили текста',
  );
  const current = textStyle(layer);
  if (mode === 'browse') {
    element.innerHTML = `<div class="text-style-menu-head"><strong>Стили текста</strong><button type="button" data-style-close aria-label="Закрыть">×</button></div><div class="text-style-search"><span aria-hidden="true">⌕</span><input type="search" data-style-search placeholder="Поиск стиля" aria-label="Поиск стиля"></div><div class="text-style-list" role="listbox" aria-label="Стили текста"></div><div class="text-style-menu-foot"><button type="button" data-style-mode="create">＋ Новый стиль</button>${current ? '<button type="button" data-style-mode="rename">✎ Переименовать</button>' : ''}</div>`;
  } else {
    element.innerHTML = `<div class="text-style-menu-head"><strong>${mode === 'create' ? 'Новый стиль' : 'Переименовать стиль'}</strong><button type="button" data-style-close aria-label="Закрыть">×</button></div><form data-style-form><label>Название<input name="name" type="text" maxlength="60" required value="${esc(mode === 'rename' ? current?.name || '' : '')}" placeholder="Название стиля"></label><div class="text-style-form-actions"><button type="button" data-style-mode="browse">Отмена</button><button type="submit" class="primary">${mode === 'create' ? 'Создать' : 'Сохранить'}</button></div></form>`;
  }
  document.body.append(element);
  textStyleMenu = { element, trigger, mode, layerId: layer.id };
  if (mode === 'browse') filterTextStyles('');
  const rect = trigger?.getBoundingClientRect() || {
      left: innerWidth - 320,
      right: innerWidth - 20,
      top: 60,
      bottom: 95,
    },
    width = Math.min(320, innerWidth - 24);
  element.style.width = width + 'px';
  element.style.left = clamp(rect.right - width, 12, innerWidth - width - 12) + 'px';
  element.style.top = rect.bottom + 8 + 'px';
  if (rect.bottom + Math.min(element.scrollHeight, 440) > innerHeight - 12)
    element.style.top = Math.max(12, rect.top - Math.min(element.scrollHeight, 440) - 8) + 'px';
  trigger?.setAttribute('aria-expanded', 'true');
  if (mode === 'browse') element.querySelector('[data-style-search]').focus();
  else element.querySelector('[name=name]').focus();
}
function submitTextStyleMenu(name) {
  if (!textStyleMenu) return;
  const mode = textStyleMenu.mode,
    layer = allLayers().find(l => l.id === textStyleMenu.layerId),
    current = textStyle(layer),
    clean = name.trim().slice(0, 60);
  if (!clean) return notify('Укажите название стиля', true);
  if (mode === 'create' && (doc.textStyles || []).length >= 50) return notify('В макете уже 50 стилей', true);
  if (!layer) return closeTextStyleMenu();
  closeTextStyleMenu();
  commit(() => {
    if (mode === 'create') {
      const style = { id: 'style-' + uid(), name: clean };
      for (const key of textStyleKeys)
        style[key] =
          layer[key] ??
          (key === 'lineHeight'
            ? 1.25
            : key === 'letterSpacing' || key === 'skew'
              ? 0
              : ['bold', 'italic', 'underline', 'strike'].includes(key)
                ? false
                : '');
      doc.textStyles.push(style);
      layer.styleId = style.id;
      syncTextStyle(style);
    } else if (current) current.name = clean;
  });
}
function effectControls(l) {
  const open = strokeOpen(l),
    shadow = l.shadow;
  let body = effectSwitch('Обводка', 'strokeOn', open, glyph.outside);
  if (open) {
    body +=
      colorControl('Цвет обводки', 'stroke', l.stroke || '#333333') +
      slider('Толщина', 'strokeWidth', l.strokeWidth || 0.4, 0.1, 10, 0.1);
    if (l.type !== 'line') body += strokePlacement(l);
    body += `<p class="visual-label">Штрих</p>${segments('strokeDash', l.strokeDash || 'solid', [
      ['solid', 'Сплошная', glyph.solid],
      ['dashed', 'Пунктир', glyph.dashed],
      ['dotted', 'Точки', glyph.dotted],
    ])}`;
  }
  body += effectSwitch(
    'Тень',
    'shadowOn',
    !!shadow,
    '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="5" width="12" height="12" rx="2" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M9 20h10V9" fill="none" stroke="currentColor" stroke-width="1.8" opacity=".5"/></svg>',
  );
  if (shadow)
    body +=
      colorControl('Цвет тени', 'shadow.color', shadow.color || '#000000') +
      slider('Сдвиг X', 'shadow.offsetX', shadow.offsetX || 0, -20, 20, 0.5) +
      slider('Сдвиг Y', 'shadow.offsetY', shadow.offsetY || 0, -20, 20, 0.5) +
      slider('Размытие', 'shadow.blur', shadow.blur ?? 2, 0, 20, 0.5) +
      slider('Сила тени', 'shadow.opacity', shadow.opacity ?? 35, 0, 100, 1);
  return body;
}
/* Faux italic as in InDesign: each line leans around its own baseline; the frame stays upright. */
function applyTextSkew(object, degrees) {
  object.afSlant = Math.tan((clamp(Number(degrees) || 0, -30, 30) * Math.PI) / 180);
  if (object.afSkewPatched) return;
  object.afSkewPatched = true;
  const draw = object._renderChars;
  object._renderChars = function (method, ctx, line, left, top, lineIndex) {
    if (!this.afSlant) return draw.call(this, method, ctx, line, left, top, lineIndex);
    ctx.save();
    ctx.transform(1, 0, -this.afSlant, 1, this.afSlant * top, 0);
    draw.call(this, method, ctx, line, left, top, lineIndex);
    ctx.restore();
  };
}
function applyTextPaint(object, l) {
  if (!object || !l) return;
  applyTextSkew(object, l.skew);
  object.valign = l.valign || 'top';
  object.fit = !!l.fit;
  object.fitBase = (l.fontSize || 12) * 0.3528;
  const width = activeStroke(l),
    align = l.strokeAlign || 'center',
    drawn = align === 'outside' ? width * 2 : width;
  object.set({
    fontFamily: l.font || 'Arial',
    fontWeight: l.bold ? 'bold' : 'normal',
    fontStyle: l.italic ? 'italic' : 'normal',
    underline: !!l.underline,
    linethrough: !!l.strike,
    fill: l.color || '#333333',
    textAlign: l.align === 'justify' ? 'justify' : l.align || 'left',
    lineHeight: l.lineHeight || 1.25,
    charSpacing: (Number(l.letterSpacing) || 0) * 10,
    fontSize: (l.fontSize || 12) * 0.3528,
    stroke: width
      ? (/^#[0-9a-fA-F]{6}$/.test(l.stroke) ? l.stroke : '#333333') +
        Math.round((clamp(l.strokeOpacity ?? 100, 0, 100) / 100) * 255)
          .toString(16)
          .padStart(2, '0')
      : null,
    strokeWidth: drawn,
    strokeDashArray: width ? dashArray(l.strokeDash, width) : null,
    paintFirst: align === 'outside' ? 'stroke' : 'fill',
    strokeUniform: true,
    shadow: shadowPaint(l.shadow),
    dirty: true,
    objectCaching: false,
  });
  object.initDimensions?.();
  object.setCoords?.();
}
/* A text layer is a frame of fixed size, as in InDesign: the text lays out inside it and aligns to its top,
   middle or bottom. With «shrink to fit» explicit lines never wrap and the whole text shrinks by one factor. */
let frameTextClass = null;
function FrameText() {
  if (frameTextClass) return frameTextClass;
  const U = fabric.controlsUtils;
  const resize = (axisX, axisY) =>
    U.wrapWithFireEvent(
      'resizing',
      U.wrapWithFixedAnchor((e, t, x, y) => {
        const target = t.target,
          p = U.getLocalPoint(t, t.originX, t.originY, x, y),
          stroke = target.strokeWidth / (target.strokeUniform ? target.scaleX : 1);
        let changed = false;
        if (axisX) {
          const w = Math.max(Math.abs(p.x / target.scaleX) - stroke, 1);
          if (w !== target.width) {
            target.set('width', w);
            changed = true;
          }
        }
        if (axisY) {
          const h = Math.max(Math.abs(p.y / target.scaleY) - stroke, 1);
          if (h !== target.height) {
            target.set('height', h);
            changed = true;
          }
        }
        return changed;
      }),
    );
  frameTextClass = class extends fabric.Textbox {
    static createControls() {
      const controls = { ...fabric.Textbox.createControls().controls };
      for (const [key, x, y] of [
        ['mt', 0, 1],
        ['mb', 0, 1],
        ['tl', 1, 1],
        ['tr', 1, 1],
        ['bl', 1, 1],
        ['br', 1, 1],
      ])
        controls[key] = new fabric.Control({
          ...controls[key],
          actionHandler: resize(x, y),
          actionName: 'resizing',
          getActionName: () => 'resizing',
          cursorStyleHandler: U.scaleCursorStyleHandler,
        });
      return { controls };
    }
    initDimensions() {
      if (!this.initialized) return super.initDimensions();
      const width = this.width;
      if (this.fit && this.fitBase) {
        this.fontSize = this.fitBase;
        for (let i = 0; i < 12; i++) {
          super.initDimensions();
          this.width = width;
          const wide = Math.max(1e-3, ...this._textLines.map((_, n) => this.getLineWidth(n))),
            tall = Math.max(1e-3, this.calcTextHeight()),
            k = Math.min(1, (width * 0.995) / wide, (this.frameHeight || tall) / tall);
          if (k >= 1) break;
          this.fontSize = Math.max(0.5, this.fontSize * Math.min(k, 0.995));
        }
      } else {
        super.initDimensions();
        this.width = width;
      }
      this.contentHeight = this.height;
      if (this.frameHeight) this.height = this.frameHeight;
    }
    _wrapText(lines, desiredWidth) {
      return super._wrapText(lines, this.fit ? 1e6 : desiredWidth);
    }
    _getTopOffset() {
      const free = this.height - (this.contentHeight ?? this.height);
      return -this.height / 2 + free * ({ middle: 0.5, bottom: 1 }[this.valign] || 0);
    }
    _set(key, value) {
      if (key === 'height') this.frameHeight = value;
      return super._set(key, value);
    }
  };
  return frameTextClass;
}
function alignmentIcon(type) {
  const paths = {
    left: 'M4 3v18M7 7h12M7 12h8M7 17h12',
    cx: 'M12 3v18M5 7h14M8 12h8M5 17h14',
    right: 'M20 3v18M5 7h12M9 12h8M5 17h12',
    top: 'M3 4h18M7 7v12M12 7v8M17 7v12',
    cy: 'M3 12h18M7 5v14M12 8v8M17 5v14',
    bottom: 'M3 20h18M7 5v12M12 9v8M17 5v12',
  };
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="${paths[type]}"/></svg>`;
}
bindAutoText();
