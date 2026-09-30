/* Master editor · Auto text, text panels, vignette panel and text style menu. */
'use strict';
/* Opacity and corner radius as drag-to-change fields, shown next to the layer's size. */
function layerMetrics(l) {
  const rounded = !['ellipse', 'line', 'svg', 'grid'].includes(l.type),
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
function chipMenuGroups() {
  return AutoText.GROUPS.map(
    ([title, rows]) =>
      `<p class="menu-label">${esc(title)}</p>${rows.map(([field, label]) => `<button type="button" class="chip-row" role="menuitem" data-insert-chip="${esc(field)}"><span class="text-chip">${esc(label)}</span></button>`).join('')}`,
  ).join('');
}
function autoTextHtml(text) {
  return AutoText.parts(text)
    .map(part => (part.field ? chipHtml(part.field, part.mods) : esc(part.text)))
    .join('');
}
function autoTextField(l) {
  return `<div class="auto-text-field"><div class="auto-text" contenteditable="true" role="textbox" aria-multiline="true" aria-label="Текст" spellcheck="false" data-auto-text>${autoTextHtml(l.text)}</div><button type="button" class="auto-text-add" data-chip-menu aria-haspopup="menu" aria-expanded="false" title="Вставить данные заказа">＋ Данные</button><div class="chip-menu" role="menu" aria-label="Данные заказа" hidden>${chipMenuGroups()}</div></div><p class="section-note">Чипы заменяются данными каждого альбома; пустое значение не печатается.</p>`;
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
  /* A break left at the end is an empty line nobody sees; it would only take height from the frame. */
  return out.replace(/\u200b/g, '').replace(/\n+$/, '').slice(0, 2000);
}
function autoTextInput(box) {
  const layer = selectedLayer();
  if (!layer || layer.type !== 'text') return;
  if (!slide) slide = { start: clone(doc) };
  layer.text = autoTextValue(box);
  clearTimeout(autoTextTimer);
  /* On the canvas the frame itself is the editor; the rendered text comes back when editing ends. */
  if (!box.closest('#text-edit-ui')) autoTextTimer = setTimeout(renderScene, 200);
}
/* A click on a chip selects its label (a chip is one whole piece); a new chip then goes right after it, never inside. */
function outsideChips(range) {
  const chip = node => (node.nodeType === 1 ? node : node.parentElement)?.closest('.text-chip');
  const start = chip(range.startContainer),
    end = chip(range.endContainer);
  if (!start && !end) return range;
  const out = range.cloneRange();
  if (start) out.setStartAfter(start);
  if (end) out.setEndAfter(end);
  return out;
}
function insertChip(field) {
  const box = chipBox();
  if (!box || !(field in AutoText.FIELDS)) return;
  const range =
    chipRange && box.contains(chipRange.startContainer)
      ? outsideChips(chipRange)
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
  document.addEventListener('selectionchange', () => {
    const sel = getSelection();
    if (!sel.rangeCount) return;
    const node = sel.anchorNode,
      el = node?.nodeType === 1 ? node : node?.parentElement;
    if (el?.closest('[data-auto-text]')) chipRange = sel.getRangeAt(0).cloneRange();
  });
  const closeChips = () =>
    document.querySelectorAll('.auto-text-field .chip-menu:not([hidden])').forEach(menu => {
      menu.hidden = true;
      menu.parentElement.querySelector('[data-chip-menu]')?.setAttribute('aria-expanded', 'false');
    });
  document.addEventListener(
    'pointerdown',
    e => {
      if (!e.target.closest?.('.auto-text-field')) closeChips();
      if (chipPop && !chipPop.element.contains(e.target) && !e.target.closest?.('[data-auto-text] .text-chip'))
        closeChipPop();
      if (
        textEdit &&
        !e.target.closest?.('#text-edit-ui') &&
        e.target.closest?.('.canvas-main,.left-panel,.editor-header,#inspector [data-auto-text]')
      )
        finishTextEdit();
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
  /* Enter on a selected text frame starts typing in it, as a double click does. */
  document.addEventListener('keydown', e => {
    if (
      e.key !== 'Enter' ||
      e.target !== document.body ||
      textEdit ||
      selected.length !== 1 ||
      document.querySelector('dialog[open]')
    )
      return;
    const l = selectedLayer();
    if (l?.type !== 'text') return;
    e.preventDefault();
    startTextEdit(l);
  });
  for (const host of [$('#inspector'), $('#text-edit-ui')]) {
    host.addEventListener('keydown', e => {
      if (e.key === 'Escape' && e.target.closest?.('.auto-text-field')) {
        const open = host.querySelector('.chip-menu:not([hidden])');
        closeChips();
        if (!open && host.id === 'text-edit-ui') {
          e.preventDefault();
          e.stopPropagation();
          finishTextEdit();
        }
        return;
      }
      if (e.target.closest?.('[data-auto-text]') && e.key === 'Enter') {
        e.preventDefault();
        if ((e.metaKey || e.ctrlKey) && host.id === 'text-edit-ui') finishTextEdit();
        else document.execCommand('insertText', false, '\n');
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
          if (open && host.id === 'text-edit-ui') fitChipMenu(menu);
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
  $('#inspector').addEventListener('focusout', e => {
    if (!e.target.closest?.('[data-auto-text]') || e.relatedTarget?.closest?.('.auto-text-field')) return;
    clearTimeout(autoTextTimer);
    if (slide) finishSlide();
  });
  const editHost = $('#text-edit-ui');
  /* A click in the empty part of the frame puts the caret at the end of the text. */
  editHost.addEventListener('pointerdown', e => {
    if (!e.target.classList.contains('text-edit-frame')) return;
    e.preventDefault();
    focusTextEnd(e.target.querySelector('[data-auto-text]'), false);
  });
  /* The frame covers the canvas, so the wheel still pans and zooms it; the data menu scrolls itself. */
  editHost.addEventListener(
    'wheel',
    e => {
      if (e.target.closest('.chip-menu')) return;
      e.preventDefault();
      canvas.upperCanvasEl.dispatchEvent(new WheelEvent('wheel', e));
    },
    { passive: false },
  );
}
/* On the canvas the data menu opens below the frame, or above it when there is more room there, and fits the view. */
function fitChipMenu(menu) {
  const view = $('#canvas-host').getBoundingClientRect(),
    frame = menu.parentElement.getBoundingClientRect(),
    button = menu.parentElement.querySelector('[data-chip-menu]').offsetHeight + 6,
    below = view.bottom - frame.bottom - 16,
    above = frame.top - button - view.top - 16,
    up = below < 240 && above > below;
  menu.style.top = up ? 'auto' : '';
  menu.style.bottom = up ? `calc(100% + ${button + 8}px)` : '';
  menu.style.maxHeight = Math.max(120, Math.min(320, up ? above : below)) + 'px';
}
/* Text on the canvas: a double click opens the text with its chips right in the frame, set in the frame's own type. */
let textEdit = null;
function chipBox() {
  return (textEdit && $('#text-edit-ui [data-auto-text]')) || $('#inspector [data-auto-text]');
}
function focusTextEnd(box, all) {
  if (!box) return;
  box.focus();
  const range = document.createRange();
  range.selectNodeContents(box);
  if (!all) range.collapse(false);
  const sel = getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
}
function startTextEdit(layer, selectAll = false) {
  if (preview || !layer || layer.type !== 'text' || layer.locked) return;
  finishTextEdit();
  closeChipPop();
  const host = $('#text-edit-ui');
  textEdit = { layerId: layer.id };
  host.hidden = false;
  host.innerHTML = `<div class="text-edit-frame auto-text-field"><div class="text-edit-box" contenteditable="true" role="textbox" aria-multiline="true" aria-label="Текст" spellcheck="false" data-auto-text>${autoTextHtml(layer.text)}</div><button type="button" class="auto-text-add text-edit-add" data-chip-menu aria-haspopup="menu" aria-expanded="false" title="Вставить данные заказа">＋ Данные</button><div class="chip-menu" role="menu" aria-label="Данные заказа" hidden>${chipMenuGroups()}</div></div>`;
  placeTextEditUi();
  focusTextEnd(host.querySelector('[data-auto-text]'), selectAll);
}
function finishTextEdit() {
  if (!textEdit) return;
  const host = $('#text-edit-ui'),
    box = host.querySelector('[data-auto-text]'),
    l = allLayers().find(i => i.id === textEdit.layerId);
  textEdit = null;
  closeChipPop();
  clearTimeout(autoTextTimer);
  if (l && box) {
    const text = autoTextValue(box);
    if (text !== l.text) {
      if (!slide) slide = { start: clone(doc) };
      l.text = text;
    }
  }
  host.hidden = true;
  host.innerHTML = '';
  if (slide) finishSlide();
  else render();
}
/* Follows the frame on every redraw, zoom and pan; the canvas copy of the text hides while the frame is edited. */
function placeTextEditUi() {
  if (!textEdit) return;
  const l = selectedLayer();
  if (preview || selected.length !== 1 || l?.id !== textEdit.layerId) return finishTextEdit();
  const frame = $('#text-edit-ui .text-edit-frame'),
    box = frame?.querySelector('[data-auto-text]'),
    object = canvas.getObjects().find(o => o.masterId === l.id);
  if (!box) return;
  if (object?.visible) {
    object.set({ visible: false, hasControls: false, hasBorders: false });
    canvas.requestRenderAll();
  }
  const side = object ? object.side || 0 : Math.max(0, section().spreads[view.spread]?.pages.findIndex(p => p.layers.includes(l)) ?? 0),
    zoom = canvas.getZoom(),
    w = layerW(l) * zoom,
    h = l.box.h * zoom,
    c = sceneToHost(layerOffset(l, side) + l.box.x + layerW(l) / 2, l.box.y + l.box.h / 2);
  Object.assign(frame.style, {
    left: c.x - w / 2 + 'px',
    top: c.y - h / 2 + 'px',
    width: w + 'px',
    height: h + 'px',
    transform: l.angle ? `rotate(${l.angle}deg)` : '',
    justifyContent: { middle: 'center', bottom: 'flex-end' }[l.valign] || 'flex-start',
  });
  Object.assign(box.style, {
    fontFamily: `"${l.font || 'Arial'}"`,
    fontSize: (object?.fontSize || (l.fontSize || 12) * 0.3528) * zoom + 'px',
    fontWeight: l.bold ? 'bold' : 'normal',
    fontStyle: l.italic ? 'italic' : 'normal',
    textDecoration: [l.underline && 'underline', l.strike && 'line-through'].filter(Boolean).join(' ') || 'none',
    textTransform: { upper: 'uppercase', lower: 'lowercase', title: 'capitalize' }[l.textCase] || 'none',
    color: l.color || '#333333',
    textAlign: l.align || 'left',
    lineHeight: String((l.lineHeight || 1.25) * 1.13),
    letterSpacing: (Number(l.letterSpacing) || 0) / 100 + 'em',
    whiteSpace: l.fit ? 'pre' : 'pre-wrap',
    transform: l.skew ? `skewX(${-l.skew}deg)` : '',
  });
  if (chipPop) drawChipPop();
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
  return chipBox()?.querySelectorAll('.text-chip')[index] || null;
}
function chipPopHtml(field, mods) {
  const forms = AutoText.FORMS[AutoText.kind(field)] || [],
    form = forms.find(([id]) => id && mods.includes(id))?.[0] || '';
  return `<p class="menu-label">${esc(AutoText.FIELDS[field])}</p>${forms.map(([id, name, note]) => `<button type="button" class="menu-row${id === form ? ' on' : ''}" data-chip-form="${id}" role="menuitemradio" aria-checked="${id === form}"><span>${esc(name)}</span>${note ? `<small>${esc(note)}</small>` : ''}</button>`).join('')}`;
}
function openChipPop(index) {
  closeChipPop();
  const l = selectedLayer(),
    chip = chipAt(index);
  if (!l || l.type !== 'text' || !chip || !AutoText.FORMS[AutoText.kind(chip.dataset.field)]?.length) return;
  const element = document.createElement('div');
  element.className = 'cell-sources chip-pop';
  element.setAttribute('role', 'menu');
  element.setAttribute('aria-label', 'Настройка данных');
  document.body.append(element);
  element.addEventListener('pointerdown', e => e.preventDefault());
  element.addEventListener('click', e => {
    const form = e.target.closest('[data-chip-form]');
    if (form) setChipForm(chipPop.index, form.dataset.chipForm);
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
/* Only the chip's data form changes; typography belongs to the whole text frame. */
function setChipForm(index, value) {
  const l = selectedLayer();
  if (!l || l.type !== 'text') return;
  clearTimeout(autoTextTimer);
  if (slide) finishSlide();
  let seen = -1,
    changed = null;
  const text = AutoText.parts(l.text)
    .map(part => {
      if (!part.field) return part.text;
      if (++seen !== index) return AutoText.token(part.field, part.mods);
      const forms = (AutoText.FORMS[AutoText.kind(part.field)] || []).map(([id]) => id);
      changed = { field: part.field, mods: [...part.mods.filter(m => !forms.includes(m)), value].filter(Boolean) };
      return AutoText.token(changed.field, changed.mods);
    })
    .join('');
  const chip = chipAt(index);
  if (chip && changed) {
    chip.dataset.mods = changed.mods.join('|');
    chip.textContent = AutoText.label(changed.field, changed.mods);
  }
  if (text !== l.text) commit(() => (l.text = text));
  drawChipPop();
}
/* A shared style reads like a chip «Ag Name · size/line» with a detach button; a text without one
   just offers to pick or create one, so it is always clear whether a style drives this text. */
const STYLE_ICONS = {
  apply:
    '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="5" cy="5" r="1.6"/><circle cx="11" cy="5" r="1.6"/><circle cx="5" cy="11" r="1.6"/><circle cx="11" cy="11" r="1.6"/></svg>',
  detach:
    '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" aria-hidden="true"><path d="M6.5 4.5 8 3a2.8 2.8 0 0 1 4 4L10.5 8.5M9.5 11.5 8 13a2.8 2.8 0 0 1-4-4l1.5-1.5M3 3l10 10"/></svg>',
};
function textPanel(l) {
  const style = textStyle(l),
    head = style
      ? `<div class="type-style-row applied"><button type="button" class="type-style-chip" data-open-style-menu aria-haspopup="dialog" aria-expanded="false" title="Сменить стиль" aria-label="Стиль «${esc(style.name)}». Сменить стиль"><b class="type-style-ag" aria-hidden="true">Ag</b><span>${esc(style.name)}</span><small>${esc(`${style.fontSize}/${style.lineHeight || 1.25}`)}</small></button><div class="text-style-actions"><button type="button" data-text-style="rename" title="Переименовать стиль" aria-label="Переименовать стиль">✎</button><button type="button" data-text-style-detach title="Отвязать от стиля" aria-label="Отвязать от стиля">${STYLE_ICONS.detach}</button></div></div><p class="section-note">Изменения применяются ко всем текстам стиля «${esc(style.name)}».</p>`
      : `<div class="type-style-row"><span class="type-label">Стиль</span><div class="text-style-actions"><button type="button" data-text-style="create" title="Создать стиль из этого текста" aria-label="Создать стиль из этого текста">＋</button><button type="button" data-open-style-menu aria-haspopup="dialog" aria-expanded="false" title="Применить стиль" aria-label="Применить стиль">${STYLE_ICONS.apply}</button></div></div>`;
  return `${head}<div class="type-font">${fontRow(l)}</div><div class="type-main-row"><div class="type-weight"><select data-prop="bold" aria-label="Начертание"><option value="false" ${!l.bold ? 'selected' : ''}>Обычное</option><option value="true" ${l.bold ? 'selected' : ''}>Жирное</option></select><i class="type-chevron" aria-hidden="true"></i></div>${scrubField('Размер текста', 'fontSize', l.fontSize, 4, 120, 1, '<span class="type-size-icon">A</span>')}</div><div class="type-metrics">${scrubField('Интерлиньяж', 'lineHeight', l.lineHeight ?? 1.25, 0.8, 3, 0.05, '<svg class="type-line-height-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 3h10M8 17h10M4 5v10M2 7l2-2 2 2M2 13l2 2 2-2"/></svg>')}${scrubField('Интервал', 'letterSpacing', l.letterSpacing ?? 0, -20, 80, 1, '<span class="type-metric-icon">A↔</span>', '%')}${scrubField('Наклон', 'skew', l.skew ?? 0, -30, 30, 1, '<span class="type-metric-icon type-skew-icon">A</span>', '°')}${l.type === 'text' ? textCaseField(l.textCase) : ''}</div><div class="type-align"><span class="type-label">Выравнивание</span>${l.type === 'text' ? `<div class="type-align-pair">${textAlignBar(l.align)}${textValignBar(l.valign)}</div>` : textAlignBar(l.align)}</div>${l.type === 'text' ? textFitRow(l) : ''}<div class="type-extras">${textStyleBar(l)}</div>${colorControl('Цвет', 'color', l.color || '#333333')}`;
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
/* A vignette is a frame the block's list flows into: who and how many live in the block, the card design lives here. */
function vignetteListLink() {
  const list = blockList(section());
  return `<button type="button" class="vignette-list-link" data-open-block title="Кого и сколько на странице — в настройках блока"><span class="vignette-list-icon">${kindIcon('flow')}</span><span class="vignette-list-copy"><strong>${list.source === 'teachers' ? 'Учителя' : 'Ученики'}</strong><small>${list.min}–${list.max} на странице</small></span><svg class="vignette-list-go" viewBox="0 0 8 12" aria-hidden="true"><path d="M2 2l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg></button>`;
}
/* Outside the card: how cards are laid out. What a card looks like is edited inside it (card.js). */
function vignettePanel(l) {
  const zone = CARD_ZONE_NAMES[l.nameAt || 'below'].toLowerCase(),
    ratio = PHOTO_RATIOS.find(([value]) => Math.abs(value - (Number(l.photoRatio) || 0.75)) < 1e-3)?.[1] || '3:4',
    caption = l.showDetail ? `имя и ${vignetteDetailName(l).toLowerCase()}` : 'имя';
  return (
    `<section class="inspector-section typography-section"><div class="typography-heading"><h3>Раскладка</h3></div><div class="type-metrics vignette-gaps">${vignetteGapField(l, 'gap')}</div></section>` +
    `<section class="inspector-section typography-section"><div class="typography-heading"><h3>Карточка</h3></div><button type="button" class="card-enter" data-card-enter title="Двойной клик по карточке · Enter"><span class="card-enter-copy"><strong>Фото ${ratio} · ${caption}</strong><small>${caption[0].toUpperCase() + caption.slice(1)} — ${zone}</small></span><span class="card-enter-go">Изменить</span></button></section>`
  );
}
function vignetteDetailName(l) {
  return l.source === 'teachers' ? 'Предмет' : 'Цитата';
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
/* Explain the corner marker using the text actually rendered, after resolving data chips. */
function syncTextOverflow() {
  const panel = $('#inspector [data-text-overflow]');
  if (!panel) return;
  const object = canvas.getObjects().find(o => o.masterId === selectedLayer()?.id),
    reason = object?.overflowDetails?.();
  panel.hidden = !reason;
  if (!reason) return;
  panel.querySelector('[data-overflow-message]').textContent = reason.height
    ? `Не хватает высоты: текст занимает ${Math.ceil(object.contentHeight * 10) / 10} мм, рамка — ${round(object.height)} мм.${reason.width ? ' Есть и строка шире рамки.' : ''}`
    : 'Есть строка шире рамки. Увеличьте ширину или уменьшите текст.';
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
    /* Fabric widens every line to the longest word; here only a word wider than the frame sticks out. */
    _wrapLine(lineIndex, desiredWidth, data, reserved = 0) {
      const min = this.dynamicMinWidth;
      this.dynamicMinWidth = 0;
      const lines = super._wrapLine(lineIndex, desiredWidth, { ...data, largestWordWidth: 0 }, reserved);
      this.dynamicMinWidth = min;
      return lines;
    }
    /* Text past the frame is hidden, as in InDesign, and a red «+» at the corner says some of it does not fit. */
    overflowDetails() {
      if (this.fit || !this.text?.trim() || !this._textLines) return null;
      const height = (this.contentHeight ?? 0) > this.height + 0.05,
        width = this._textLines.some((_, n) => this.getLineWidth(n) > this.width + 0.05);
      return height || width ? { height, width } : null;
    }
    overflows() {
      return !!this.overflowDetails();
    }
    /* Overset text as in InDesign: it starts at the top of the frame and only whole lines that fit are shown. */
    fittingHeight() {
      if (this.fit || !this._textLines || (this.contentHeight ?? 0) <= this.height + 0.05) return null;
      let top = 0,
        bottom = 0;
      for (let i = 0; i < this._textLines.length; i++) {
        const line = this.getHeightOfLine(i),
          glyphs = top + line / this.lineHeight;
        if (glyphs > this.height + 0.05) break;
        bottom = glyphs;
        top += line;
      }
      return bottom;
    }
    _render(ctx) {
      const w = this.width,
        h = this.height,
        pad = this.strokeWidth || 0;
      if (this.isEditing) return super._render(ctx);
      const fitting = this.fittingHeight();
      ctx.save();
      ctx.beginPath();
      if (fitting === null) ctx.rect(-w / 2 - pad, -h / 2 - pad, w + pad * 2, h + pad * 2);
      else ctx.rect(-w / 2 - pad, -h / 2 - pad, w + pad * 2, fitting + pad);
      ctx.clip();
      super._render(ctx);
      ctx.restore();
      if (!this.overflows()) return;
      const s = Math.min(3, w / 3, h / 3),
        x = w / 2 - s,
        y = h / 2 - s;
      ctx.save();
      ctx.fillStyle = '#ffffff';
      ctx.strokeStyle = '#d33a2f';
      ctx.lineWidth = s / 8;
      ctx.fillRect(x, y, s, s);
      ctx.strokeRect(x, y, s, s);
      ctx.beginPath();
      ctx.moveTo(x + s / 2, y + s * 0.22);
      ctx.lineTo(x + s / 2, y + s * 0.78);
      ctx.moveTo(x + s * 0.22, y + s / 2);
      ctx.lineTo(x + s * 0.78, y + s / 2);
      ctx.stroke();
      ctx.restore();
    }
    _getTopOffset() {
      const free = Math.max(0, this.height - (this.contentHeight ?? this.height));
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
