/* Master editor · Colour picker, fonts and text style bars. */
'use strict';
const swatchColors = [
  '#000000',
  '#ffffff',
  '#fafafa',
  '#e6e1ea',
  '#333333',
  '#7712b3',
  '#e7d4f3',
  '#d4537e',
  '#f4b942',
  '#3d8bfd',
  '#5f6b7a',
  '#b9b6be',
];
const recentColorKey = 'master-editor-recent-colors';
let recentColors = [],
  colorPicking = false;
try {
  const saved = JSON.parse(localStorage.getItem(recentColorKey) || '[]');
  if (Array.isArray(saved))
    recentColors = saved
      .filter(c => typeof c === 'string' && /^#[0-9a-f]{6}$/i.test(c))
      .slice(0, 10)
      .map(c => c.toLowerCase());
} catch {}
function rememberColor(hex) {
  hex = hex.toLowerCase();
  recentColors = [hex, ...recentColors.filter(c => c !== hex)].slice(0, 10);
  try {
    localStorage.setItem(recentColorKey, JSON.stringify(recentColors));
  } catch {}
  renderRecentColors();
}
function renderRecentColors() {
  const wrap = $('#color-recent-wrap');
  wrap.hidden = !recentColors.length;
  $('#color-recent').innerHTML = recentColors
    .map(
      c =>
        `<button type="button" data-swatch="${c}" style="--swatch:${c}" aria-label="Недавний цвет ${c.toUpperCase()}" title="${c.toUpperCase()}"></button>`,
    )
    .join('');
}
function hexToHsv(hex) {
  let r = parseInt(hex.slice(1, 3), 16) / 255,
    g = parseInt(hex.slice(3, 5), 16) / 255,
    b = parseInt(hex.slice(5, 7), 16) / 255;
  const max = Math.max(r, g, b),
    min = Math.min(r, g, b),
    d = max - min;
  let h = 0;
  if (d) {
    if (max === r) h = ((g - b) / d) % 6;
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h = h * 60;
    if (h < 0) h += 360;
  }
  return { h, s: max ? d / max : 0, v: max };
}
function hsvToHex(h, s, v) {
  const c = v * s,
    x = c * (1 - Math.abs(((h / 60) % 2) - 1)),
    m = v - c;
  let r = 0,
    g = 0,
    b = 0;
  if (h < 60) [r, g, b] = [c, x, 0];
  else if (h < 120) [r, g, b] = [x, c, 0];
  else if (h < 180) [r, g, b] = [0, c, x];
  else if (h < 240) [r, g, b] = [0, x, c];
  else if (h < 300) [r, g, b] = [x, 0, c];
  else [r, g, b] = [c, 0, x];
  const n = k =>
    Math.round((k + m) * 255)
      .toString(16)
      .padStart(2, '0');
  return '#' + n(r) + n(g) + n(b);
}
function paintColor(hex, opacity) {
  if (!colorPop) return;
  colorPop.moved = true;
  const key = colorPop.key;
  const touch = o => {
    o.dirty = true;
    if (o.group) {
      o.group.dirty = true;
      o.group.objectCaching = false;
    }
  };
  if (key === 'page.background') {
    if (page()) page().background = hex;
    const bg = canvas
      .getObjects()
      .find(
        o =>
          !o.masterId &&
          o.height === pageHeight() &&
          Math.abs((o.left || 0) - view.side * (pageWidth() + spineGap() / 2)) < 1,
      );
    if (bg) {
      bg.set('fill', hex);
      touch(bg);
    } else renderScene();
    const mini = document.querySelectorAll('.section-card.active .mini-page')[view.side];
    if (mini) mini.style.background = hex;
    canvas.requestRenderAll();
  } else {
    const l = selectedLayer();
    if (!l) return;
    if (key === 'shadow.color') {
      l.shadow = Object.assign(
        { color: '#000000', offsetX: 0, offsetY: 1.5, blur: 2, opacity: 35 },
        l.shadow,
      );
      l.shadow.color = hex;
      if (opacity != null) l.shadow.opacity = opacity;
    } else if (key === 'stroke') {
      l.stroke = hex;
      if (opacity != null) l.strokeOpacity = opacity;
    } else if (key === 'fill' || key === 'color' || key === 'detailColor') {
      if (key === 'color' && l.type === 'text') setTextFormat(l, 'color', hex);
      else if (l.type === 'grid')
        section()
          .spreads.flatMap(sp => sp.pages.flatMap(p => p.layers))
          .filter(item => item.type === 'grid')
          .forEach(item => (item[key] = hex));
      else l[key] = hex;
      if (opacity != null) l.opacity = opacity;
    }
    if (key === 'color' && l.type === 'text') paintLinkedText(textStyle(l));
    const obj = canvas.getObjects().find(o => o.masterId === l.id);
    if (obj) {
      if (l.type === 'text') applyTextPaint(obj, l);
      else if (['rect', 'ellipse', 'line', 'svg'].includes(l.type)) applyVectorPaint(obj, l);
      else if (key === 'shadow.color' || key === 'stroke') {
        scheduleEffectRender();
      } else {
        if (opacity != null && key !== 'stroke') {
          obj.set('opacity', opacity / 100);
          touch(obj);
        }
        if (l.type === 'grid' && ['color', 'detailColor'].includes(key)) {
          scheduleEffectRender();
        } else if (l.type === 'collage' && key === 'fill') {
          (obj.getObjects?.() || []).forEach(child => {
            if (child.collageRole === 'cell' && child.type === 'rect') {
              child.set('fill', hex);
              touch(child);
            }
          });
        } else if (key === 'fill' || key === 'color') {
          obj.set('fill', hex);
          touch(obj);
        }
      }
    }
    canvas.requestRenderAll();
    if ($('#vignette-dialog').open) vignettePreview();
  }
  document.querySelectorAll(`[data-color-key="${key}"]`).forEach(b => {
    b.dataset.colorValue = hex;
    b.style.setProperty('--swatch', hex);
    const em = b.querySelector('em');
    if (em) em.textContent = hex.toUpperCase();
  });
}
function syncColorPop(apply = true) {
  if (!colorPop) return;
  const { h, s, v } = colorPop.hsv,
    hex = hsvToHex(h, s, v),
    pop = $('#color-pop');
  $('#color-sv').style.background =
    `linear-gradient(to top,#000,transparent),linear-gradient(to right,#fff,hsl(${h} 100% 50%))`;
  $('#color-sv-knob').style.left = s * 100 + '%';
  $('#color-sv-knob').style.top = (1 - v) * 100 + '%';
  $('#color-hue-knob').style.left = (h / 360) * 100 + '%';
  $('#color-hue-knob').style.top = '50%';
  $('#color-alpha').style.backgroundImage =
    `linear-gradient(90deg,transparent,${hex}),linear-gradient(45deg,#e6e4ea 25%,transparent 25%),linear-gradient(-45deg,#e6e4ea 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#e6e4ea 75%),linear-gradient(-45deg,transparent 75%,#e6e4ea 75%)`;
  $('#color-alpha-knob').style.left = colorPop.opacity + '%';
  $('#color-alpha-knob').style.top = '50%';
  $('#color-hex').value = hex.toUpperCase();
  $('#color-alpha-input').value = Math.round(colorPop.opacity);
  $('#color-alpha').hidden = colorPop.key === 'page.background';
  $('#color-alpha-input').hidden = $('#color-alpha').hidden;
  $('#color-alpha-input').nextElementSibling.hidden = $('#color-alpha').hidden;
  if (apply) paintColor(hex, colorPop.key === 'page.background' ? null : colorPop.opacity);
  let rect = colorPop.anchor.getBoundingClientRect();
  if (rect.width < 2) {
    $('.right-panel').classList.add('mobile-open');
    rect = colorPop.anchor.getBoundingClientRect();
  }
  pop.hidden = false;
  const left = Math.max(
    8,
    Math.min(rect.width ? rect.left : innerWidth - pop.offsetWidth - 16, innerWidth - pop.offsetWidth - 8),
  );
  const below = rect.bottom + 8;
  pop.style.left = left + 'px';
  pop.style.top =
    Math.max(
      8,
      below + pop.offsetHeight > innerHeight ? Math.max(8, rect.top - pop.offsetHeight - 8) : below,
    ) + 'px';
}
function openColor(button) {
  if (colorPop?.anchor === button) return closeColor(false);
  if (colorPop) {
    const changed = colorPop.moved && JSON.stringify(doc) !== JSON.stringify(colorPop.start);
    if (changed) {
      rememberColor(hsvToHex(colorPop.hsv.h, colorPop.hsv.s, colorPop.hsv.v));
      history.push(colorPop.start);
      if (history.length > 60) history.shift();
      future = [];
      markDirty();
    }
    colorPop = null;
  }
  colorPop = {
    key: button.dataset.colorKey,
    anchor: button,
    hsv: hexToHsv(button.dataset.colorValue || '#333333'),
    opacity: colorOpacity(button.dataset.colorKey),
    start: clone(doc),
    moved: false,
  };
  $('#color-swatches').innerHTML = swatchColors
    .map(c => `<button type="button" data-swatch="${c}" style="--swatch:${c}" aria-label="${c}"></button>`)
    .join('');
  renderRecentColors();
  syncColorPop(false);
}
function closeColor(doRender = true) {
  if (!colorPop) return;
  const changed = colorPop.moved && JSON.stringify(doc) !== JSON.stringify(colorPop.start);
  if (changed) {
    rememberColor(hsvToHex(colorPop.hsv.h, colorPop.hsv.s, colorPop.hsv.v));
    history.push(colorPop.start);
    if (history.length > 60) history.shift();
    future = [];
    markDirty();
  }
  colorPop = null;
  $('#color-pop').hidden = true;
  if (doRender) render();
  else if (changed) setTimeout(() => render(), 0);
}
const loadedFonts = new Set();
function fontKind(bytes) {
  const h = String.fromCharCode(bytes[0], bytes[1], bytes[2], bytes[3]);
  if (h === 'OTTO') return 'otf';
  if (h === 'true' || h === 'typ1' || (bytes[0] === 0 && bytes[1] === 1 && bytes[2] === 0 && bytes[3] === 0))
    return 'ttf';
  return '';
}
function bytesToBase64(bytes) {
  let binary = '';
  for (let i = 0; i < bytes.length; i += 0x8000)
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}
async function ensureFonts() {
  let added = false;
  for (const font of doc.fonts || []) {
    if (loadedFonts.has(font.id)) continue;
    try {
      const face = new FontFace(font.id, `url(${font.dataUrl})`);
      await face.load();
      document.fonts.add(face);
      loadedFonts.add(font.id);
      added = true;
    } catch (e) {
      loadedFonts.add(font.id);
      notify('Шрифт «' + font.name + '» не подключился', true);
    }
  }
  return added;
}
function strokeActive(l) {
  return l.strokeOn != null ? !!l.strokeOn : (l.strokeWidth || 0) > 0;
}
function colorOpacity(key) {
  const l = selectedLayer();
  if (key === 'stroke') return l?.strokeOpacity ?? 100;
  if (key === 'shadow.color') return l?.shadow?.opacity ?? 35;
  return l?.opacity ?? 100;
}
function fontChoices() {
  return [
    ['Arial', 'Arial'],
    ['Georgia', 'Georgia'],
    ['Times New Roman', 'Times New Roman'],
    ...(doc.fonts || []).map(f => [f.id, f.name]),
  ];
}
function fontRow(layer, prefix = '') {
  const key = prefix + 'font',
    options = fontChoices()
      .map(
        ([k, n]) =>
          `<option value="${esc(k)}" ${layer.font === k ? 'selected' : ''} style="font-family:'${esc(k)}',sans-serif">${esc(n)}</option>`,
      )
      .join('');
  const mine = (doc.fonts || []).find(f => f.id === layer.font);
  return `<div class="font-row"><label class="font-select"><select data-prop="${key}" aria-label="Шрифт">${options}</select><i class="type-chevron" aria-hidden="true"></i></label><label class="font-add" title="Добавить шрифт" aria-label="Добавить шрифт"><input id="font-upload" data-font-target="${key}" type="file" accept=".ttf,.otf,font/ttf,font/otf"><span aria-hidden="true">＋</span></label></div>${mine ? `<button type="button" class="text-button" data-font-remove="${esc(mine.id)}">Убрать «${esc(mine.name)}»</button>` : ''}`;
}
function markIcon(name) {
  const paths = {
    left: 'M4 6h16M4 12h10M4 18h16',
    center: 'M4 6h16M7 12h10M4 18h16',
    right: 'M4 6h16M10 12h10M4 18h16',
    justify: 'M4 6h16M4 12h16M4 18h16',
    solid: 'M4 12h16',
    dashed: 'M4 12h3.5M10.2 12h3.5M16.5 12h3.5',
    dotted: 'M5 12h.1M9 12h.1M13 12h.1M17 12h.1M21 12h.1',
    centerStroke: 'M6 6h12v12H6z',
    outside: 'M4 4h16v16H4zM7 7h10v10H7z',
  };
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[name]}"/></svg>`;
}
function styleButton(on, attrs, label, glyph) {
  return `<button type="button" class="icon-toggle" ${attrs} aria-pressed="${on ? 'true' : 'false'}" aria-label="${label}" title="${label}">${glyph}</button>`;
}
function textStyleBar(l, prefix = '') {
  const flags = [
    ['bold', 'Жирный', '<b>B</b>'],
    ['italic', 'Курсив', '<i>I</i>'],
    ['underline', 'Подчёркнутый', '<span class="u">U</span>'],
    ['strike', 'Зачёркнутый', '<span class="s">S</span>'],
  ];
  return `<div class="segments" role="toolbar" aria-label="Начертание">${flags.map(([key, name, icon]) => `<button type="button" data-choice="${prefix + key}" data-value="toggle" class="${l[key] ? 'active' : ''}" title="${name}" aria-label="${name}" aria-pressed="${l[key] ? 'true' : 'false'}">${icon}</button>`).join('')}</div>`;
}
function textAlignBar(value, prefix = '') {
  const icons = {
    left: '<svg viewBox="0 0 24 24"><path d="M4 7h16M4 12h10M4 17h16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>',
    center:
      '<svg viewBox="0 0 24 24"><path d="M4 7h16M7 12h10M4 17h16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>',
    right:
      '<svg viewBox="0 0 24 24"><path d="M4 7h16M10 12h10M4 17h16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>',
    justify:
      '<svg viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>',
  };
  return segments(prefix + 'align', value || 'left', [
    ['left', 'Слева', icons.left],
    ['center', 'По центру', icons.center],
    ['right', 'Справа', icons.right],
    ['justify', 'По ширине', icons.justify],
  ]);
}
function scrubField(label, key, value, min, max, step, icon, suffix = '') {
  const v = Number(value),
    fullLabel = key === 'letterSpacing' ? 'Межбуквенный интервал' : label,
    attrs = `data-scrub="${key}" data-min="${min}" data-max="${max}" data-step="${step}" title="${fullLabel}: потяните влево или вправо"`;
  return `<div class="type-field ${key === 'fontSize' ? 'type-font-size' : ''}">${key === 'fontSize' ? '' : `<span class="type-label">${label}</span>`}<div class="type-value${suffix ? ' type-value-suffixed' : ''}" ${attrs}><span class="type-inline-scrub" aria-hidden="true">${icon}</span><input data-live="${key}" type="number" min="${min}" max="${max}" step="${step}" value="${v}" ${suffix ? `style="width:${Math.max(1, String(v).length)}ch"` : ''} aria-label="${fullLabel}">${suffix ? `<span class="type-suffix">${suffix}</span>` : ''}</div></div>`;
}
