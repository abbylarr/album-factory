/* Master editor · Inspector field builders, vector paint and live property sliders. */
'use strict';
function miniSpread(sp, owner = section()) {
  const size = owner.cover ? owner.pageSize : doc.pageSize,
    width = Number(size?.[0]) || 210,
    height = Number(size?.[1]) || 280;
  return `<div class="mini-spread" style="aspect-ratio:${2 * width}/${height}">${sp.pages
    .map(
      p =>
        `<div class="mini-page" style="background:${p.background}">${p.layers
          .filter(l => !l.hidden)
          .map(l => {
            const b = l.box,
              style = `left:${((l.pin === 'spine' && p === sp.pages[0] ? width + b.x : b.x) / width) * 100}%;top:${(b.y / height) * 100}%;width:${(b.w / width) * 100}%;height:${(b.h / height) * 100}%;background:${l.fill || 'transparent'};opacity:${(l.opacity ?? 100) / 100};border-radius:${l.type === 'ellipse' ? '50%' : '0'}`;
            return `<div class="mini-layer" style="${style}">${l.type === 'photo' ? `<img src="${esc(l.dataUrl || planner.placeholderSvg({ id: 's0' }))}" alt="">` : l.type === 'grid' || l.type === 'collage' ? '<div class="mini-grid">' + Array.from({ length: l.type === 'collage' ? 4 : 9 }, () => '<i></i>').join('') + '</div>' : l.type === 'svg' && l.svg ? `<img src="data:image/svg+xml;charset=utf-8,${encodeURIComponent(l.svg)}" alt="" style="object-fit:contain">` : l.type === 'text' ? `<span style="font-size:4px">${esc(l.text)}</span>` : ''}</div>`;
          })
          .join('')}</div>`,
    )
    .join('')}</div>`;
}
function renderNavigation() {
  hideIssues();
  const sec = section();
  let order = 0;
  const cards = [];
  for (const s of doc.sections) {
    const n = s.cover ? 0 : ++order,
      issues = s.cover ? [] : planner.designIssues(s),
      errors = issues.filter(i => i.severity === 'error').length,
      mark = issues.length
        ? `<button type="button" class="block-issue ${errors ? 'error' : 'warning'}" data-block-issues aria-label="${esc((errors ? 'Есть ошибки: ' : 'Есть предупреждения: ') + issues.map(i => i.text).join(' '))}">${errors ? '!' : '•'}</button>`
        : '',
      actions =
        s.cover || preview
          ? ''
          : '<button type="button" class="section-more section-gear" data-block-settings title="Настройки блока" aria-label="Настройки блока"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><path d="M3 6h9M15 6h2M3 14h2M8 14h9"/><circle cx="13.5" cy="6" r="1.8"/><circle cx="6.5" cy="14" r="1.8"/></svg></button><button type="button" class="section-more" data-block-menu-open title="Действия с блоком" aria-label="Действия с блоком" aria-haspopup="menu"><svg viewBox="0 0 18 18" fill="currentColor" aria-hidden="true"><circle cx="4" cy="9" r="1.3"/><circle cx="9" cy="9" r="1.3"/><circle cx="14" cy="9" r="1.3"/></svg></button>';
    cards.push(
      `<li class="section-card ${s.id === sec.id ? 'active' : ''}" data-section="${s.id}" role="button" tabindex="0" aria-label="${esc(s.name)}"${s.cover || preview ? '' : ' draggable="true" title="Перетащите, чтобы изменить порядок"'}>${miniSpread(s.spreads[0], s)}<div class="section-caption"><span class="section-name">${s.cover ? '' : `<b class="section-index" aria-hidden="true">${n}</b>`}<span class="section-title">${esc(s.name)}</span></span><small>${s.spreads.length} разв.</small>${actions}</div><div class="section-rule"><span>${esc(blockSummary(s))}</span>${mark}</div></li>`,
    );
  }
  $('#sections').innerHTML = cards.join('');
  $('#album-settings').title = `Настройки макета · ${albumSummary()}`;
  $('#section-title').textContent = sec.name;
  $('#add-spread').disabled = !!sec.cover;
  $('#duplicate-spread').disabled = !!sec.cover;
  const count = preview ? plans.find(p => p.sectionId === sec.id).spreads : sec.spreads.length;
  view.spread = clamp(view.spread, 0, Math.max(0, count - 1));
  $('#spread-label').textContent = sec.cover
    ? 'Оборотная сторона · лицевая сторона'
    : preview
      ? `Альбом · ${view.spread + 1} из ${count}`
      : `Разворот блока ${view.spread + 1} из ${count}` +
        (sec.kind === 'flow' ? ` · ${ROLE_NAMES[MasterPlan.roleOf(sec.spreads[view.spread])]}` : '');
  $('#spread-select').innerHTML = Array.from(
    { length: count },
    (_, i) => `<option value="${i}" ${view.spread === i ? 'selected' : ''}>${i + 1} / ${count}</option>`,
  ).join('');
  $('#prev-spread').disabled = view.spread === 0;
  $('#next-spread').disabled = view.spread >= count - 1;
  $('#delete-spread').disabled = !!sec.cover || sec.spreads.length <= 1;
  renderBlockSettings();
}
function field(label, key, value, type = 'number', attrs = '') {
  return `<label>${label}<input data-prop="${key}" type="${type}" value="${esc(type === 'number' ? round(value || 0) : value || '')}" ${attrs}></label>`;
}
function number(label, key, value, min = 0, max = pageHeight()) {
  return `<label class="compact-number" title="${label}"><span>${label}</span><input aria-label="${label}" data-prop="${key}" type="number" value="${round(value || 0)}" min="${min}" max="${max}" step="0.1"></label>`;
}
function select(label, key, value, options) {
  return `<label>${label}<select data-prop="${key}">${options.map(([k, n]) => `<option value="${k}" ${value === k ? 'selected' : ''}>${n}</option>`).join('')}</select></label>`;
}
/* Cover spine: with a sheet thickness it grows with the book; the canvas shows the design's own volume until another is picked. */
function spinePanel() {
  const cover = coverSection();
  if (!cover || !(coverSpine() > 0)) return '';
  const volume = doc.sheetThickness
      ? `<div class="safety-summary spine-rows"><div>Тестовый объём${infoTip('Примерить обложку на тонкую и толстую книгу. В заказе корешок посчитается сам.')}<span class="spine-volume"><button type="button" data-cover-volume="-1" aria-label="Меньше разворотов">−</button><output>${editorVolume().spreads}</output><button type="button" data-cover-volume="1" aria-label="Больше разворотов">+</button></span>разв.</div><div>Корешок<strong>${coverSpine()} мм</strong></div></div>`
      : '',
    bg = cover.spreads[0].pages[0].background;
  return block(
    'Корешок',
    `${volume}<div class="spine-color">${
      cover.spineColor
        ? `${colorControl('Цвет корешка', 'cover.spineColor', cover.spineColor)}<button type="button" class="spine-color-off" data-spine-color-off title="Убрать цвет корешка" aria-label="Убрать цвет корешка">−</button>`
        : `<label>Цвет корешка<button type="button" class="color-swatch no-color" data-color-key="cover.spineColor" data-color-value="${/^#[0-9a-fA-F]{6}$/.test(bg) ? bg : '#ffffff'}" aria-label="Цвет корешка: нет своего"><i></i><em>—</em></button></label>`
    }</div><button type="button" class="spine-add-text" data-spine-text><span aria-hidden="true">+</span>Текст на корешке</button>`,
  );
}
/* A text along the spine, reading bottom to top as on Russian books; it shrinks to fit the spine width. */
function addSpineText() {
  const sec = coverSection(),
    H = pageHeight(),
    s = coverSpine(),
    safe = Number(sec?.safety?.safe) || 8,
    w = Math.max(20, H - 2 * safe),
    h = Math.max(2, s - 2);
  if (!sec || !(s > 0)) return;
  const p = sec.spreads[0].pages[0],
    l = {
      id: uid(),
      type: 'text',
      name: 'Текст на корешке',
      spineContent: true,
      opacity: 100,
      angle: -90,
      pin: 'spine',
      box: { x: round(-w / 2), y: round((H - h) / 2), w: round(w), h: round(h) },
      text: '{{class}} · {{year}}',
      fit: true,
      ...Object.fromEntries(
        textStyleKeys.map(key => [
          key,
          (doc.textStyles || []).find(style => style.id === 'text-body')?.[key] ??
            MasterDefaults.textStyles().find(style => style.id === 'text-body')[key],
        ]),
      ),
    };
  l.align = 'center';
  l.valign = 'middle';
  const bg = sec.spineColor || sec.spreads[0].pages[0].background || '#ffffff',
    [r, g, b] = [1, 3, 5].map(i => parseInt(bg.slice(i, i + 2), 16) / 255);
  l.color = 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.55 ? '#ffffff' : '#333333';
  l.fontSize = Math.max(4, Math.min(24, Math.floor((h * 0.7) / 0.3528)));
  commit(() => {
    p.layers.push(l);
    selected = [l.id];
    inspectorTab = 'design';
  });
}
function block(title, body) {
  return `<section class="inspector-section"><h3>${title}</h3>${body}</section>`;
}
function colorControl(label, key, value) {
  const hex = /^#[0-9a-fA-F]{6}$/.test(value) ? value : '#333333';
  return `<label>${label}<button type="button" class="color-swatch" data-color-key="${key}" data-color-value="${hex}" style="--swatch:${hex}" aria-label="${label}"><i></i><em>${hex.toUpperCase()}</em></button></label>`;
}
const glyph = {
  center:
    '<svg viewBox="0 0 24 24"><rect x="5" y="5" width="14" height="14" fill="none" stroke="currentColor" stroke-width="3"/></svg>',
  inside:
    '<svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.4"/><rect x="7.5" y="7.5" width="9" height="9" fill="none" stroke="currentColor" stroke-width="2.4"/></svg>',
  outside:
    '<svg viewBox="0 0 24 24"><rect x="7" y="7" width="10" height="10" fill="none" stroke="currentColor" stroke-width="1.2"/><rect x="3.5" y="3.5" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2.2"/></svg>',
  solid: '<svg viewBox="0 0 24 24"><path d="M4 12h16" stroke="currentColor" stroke-width="2"/></svg>',
  dashed:
    '<svg viewBox="0 0 24 24"><path d="M4 12h4M10 12h4M16 12h4" stroke="currentColor" stroke-width="2"/></svg>',
  dotted:
    '<svg viewBox="0 0 24 24"><path d="M5 12h.1M9.5 12h.1M14 12h.1M18.5 12h.1" stroke="currentColor" stroke-width="3" stroke-linecap="round"/></svg>',
  capButt:
    '<svg viewBox="0 0 24 24"><path d="M7 7v10M7 12h11" stroke="currentColor" stroke-width="2"/></svg>',
  capRound:
    '<svg viewBox="0 0 24 24"><path d="M7 12h11" stroke="currentColor" stroke-width="4" stroke-linecap="round"/></svg>',
  capSquare:
    '<svg viewBox="0 0 24 24"><path d="M7 12h11" stroke="currentColor" stroke-width="4" stroke-linecap="square"/></svg>',
  joinMiter:
    '<svg viewBox="0 0 24 24"><path d="M5 18 12 6l7 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="miter"/></svg>',
  joinRound:
    '<svg viewBox="0 0 24 24"><path d="M5 18 12 6l7 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>',
  joinBevel:
    '<svg viewBox="0 0 24 24"><path d="M5 18 12 6l7 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="bevel"/></svg>',
  link: '<svg viewBox="0 0 24 24"><path d="M10 12h4M8.5 8H7a4 4 0 0 0 0 8h1.5M15.5 8H17a4 4 0 0 1 0 8h-1.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
};
function segments(key, value, items) {
  return `<div class="segments" role="group">${items.map(([id, name, icon]) => `<button type="button" data-choice="${key}" data-value="${id}" class="${value === id ? 'active' : ''}" title="${name}" aria-label="${name}" aria-pressed="${value === id ? 'true' : 'false'}">${icon || esc(name)}</button>`).join('')}</div>`;
}
function slider(label, key, value, min, max, step) {
  const v = Number(step) < 1 ? round(value || 0) : Math.round(Number(value) || 0);
  return `<label class="visual-slider"><span>${label}</span><input data-live="${key}" type="range" min="${min}" max="${max}" step="${step}" value="${v}" aria-label="${label}"><b>${v}</b></label>`;
}
function effectSwitch(label, key, on, icon) {
  return `<div class="effect-toggle"><span class="effect-title">${icon}<strong>${label}</strong></span><button type="button" class="switch${on ? ' on' : ''}" data-choice="${key}" aria-pressed="${on ? 'true' : 'false'}" aria-label="${on ? 'Выключить' : 'Включить'} ${label.toLowerCase()}"></button></div>`;
}
function strokePlacement(l) {
  return `<div class="effect-field"><span>Расположение обводки</span><div class="effect-placement" role="group" aria-label="Расположение обводки">${[
    ['inside', 'Внутри'],
    ['center', 'По центру'],
    ['outside', 'Снаружи'],
  ]
    .map(
      ([key, label]) =>
        `<button type="button" data-choice="strokeAlign" data-value="${key}" class="${(l.strokeAlign || 'center') === key ? 'active' : ''}" aria-label="${label}" aria-pressed="${(l.strokeAlign || 'center') === key}">${glyph[key]}<span>${label}</span></button>`,
    )
    .join('')}</div></div>`;
}
function strokeOpen(l) {
  if (l.type === 'svg') return (l.strokeMode || 'original') === 'color';
  return l.strokeOn === true || (l.strokeOn !== false && (l.strokeWidth || 0) > 0);
}
function activeStroke(l) {
  return strokeOpen(l) ? Math.max(Number(l.strokeWidth) || 0, 0.4) : 0;
}
function strokeColor(l) {
  return (
    (l.stroke || '#333333') +
    Math.round((clamp(l.strokeOpacity ?? 100, 0, 100) / 100) * 255)
      .toString(16)
      .padStart(2, '0')
  );
}
function vectorPanel(l) {
  const svg = l.type === 'svg',
    open = strokeOpen(l);
  let body = '';
  if (svg) {
    const preview = l.svg
      ? `<img src="data:image/svg+xml;charset=utf-8,${encodeURIComponent(l.svg)}" alt="">`
      : '<i class="svg-empty"></i>';
    body += `<div class="svg-well">${preview}<div><strong>Рисунок</strong><span>До 200 КБ, без скриптов</span></div><button type="button" data-action="replace-svg">Заменить</button></div><p class="visual-label">Заливка</p>${segments(
      'fillMode',
      l.fillMode || 'original',
      [
        ['original', 'Как в файле'],
        ['color', 'Цвет'],
        ['none', 'Нет'],
      ],
    )}`;
    if ((l.fillMode || 'original') === 'color')
      body += colorControl('Цвет заливки', 'fill', l.fill || '#29282d');
    body += `<p class="visual-label">Обводка</p>${segments('strokeMode', l.strokeMode || 'original', [
      ['original', 'Как в файле'],
      ['color', 'Цвет'],
      ['none', 'Нет'],
    ])}`;
  } else {
    body += colorControl('Заливка', 'fill', l.fill || '#d9d2e1');
    body += effectSwitch('Обводка', 'strokeOn', open, glyph.outside);
  }
  if (open) {
    body +=
      colorControl('Цвет обводки', 'stroke', l.stroke || '#333333') +
      slider('Толщина', 'strokeWidth', l.strokeWidth || 0.4, 0.1, 10, 0.1);
    if (l.type !== 'line') body += strokePlacement(l);
    body += `<p class="visual-label">Штрих</p>${segments('strokeDash', l.strokeDash || 'solid', [
      ['solid', 'Сплошная', glyph.solid],
      ['dashed', 'Пунктир', glyph.dashed],
      ['dotted', 'Точки', glyph.dotted],
    ])}<p class="visual-label">Концы и стыки</p><div class="segment-pair">${segments(
      'strokeCap',
      l.strokeCap || (svg ? 'round' : 'butt'),
      [
        ['butt', 'Плоский', glyph.capButt],
        ['round', 'Круглый', glyph.capRound],
        ['square', 'Квадратный', glyph.capSquare],
      ],
    )}${segments('strokeJoin', l.strokeJoin || 'miter', [
      ['miter', 'Острый', glyph.joinMiter],
      ['round', 'Скруглённый', glyph.joinRound],
      ['bevel', 'Срезанный', glyph.joinBevel],
    ])}</div>`;
  }
  const shadow = l.shadow;
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
      slider('Размытие', 'shadow.blur', shadow.blur || 0, 0, 20, 0.5) +
      slider('Сила тени', 'shadow.opacity', shadow.opacity ?? 35, 0, 100, 1);
  body += ``;
  return block('Оформление', body);
}
function sanitizeSvg(text) {
  const raw = String(text || '')
    .replace(/^\uFEFF/, '')
    .trim();
  if (raw.length < 20 || raw.length > 200000) return null;
  if (
    /<!DOCTYPE|<!ENTITY|<script|<\/script|<foreignObject|<iframe|<embed|<object|javascript:|vbscript:|data:text\/html/i.test(
      raw,
    ) ||
    /\son[a-z]+\s*=/i.test(raw)
  )
    return null;
  const doc = new DOMParser().parseFromString(raw, 'image/svg+xml');
  if (doc.querySelector('parsererror') || doc.documentElement.tagName.toLowerCase() !== 'svg') return null;
  if (doc.querySelector('script,foreignObject,iframe,embed,object')) return null;
  for (const el of doc.querySelectorAll('*')) {
    for (const attr of [...el.attributes]) {
      const name = attr.name.toLowerCase();
      if (name.startsWith('on')) return null;
      if ((name === 'href' || name.endsWith(':href')) && attr.value && !attr.value.startsWith('#'))
        return null;
    }
  }
  return new XMLSerializer().serializeToString(doc.documentElement);
}
function svgAspect(svg) {
  const doc = new DOMParser().parseFromString(svg, 'image/svg+xml'),
    el = doc.documentElement,
    vb = (el.getAttribute('viewBox') || '')
      .trim()
      .split(/[\s,]+/)
      .map(Number);
  if (vb.length === 4 && vb[2] > 0 && vb[3] > 0) return vb[2] / vb[3];
  const w = parseFloat(el.getAttribute('width')),
    h = parseFloat(el.getAttribute('height'));
  return w > 0 && h > 0 ? w / h : 1;
}
function pickSvg(layerId) {
  svgTarget = layerId || null;
  const input = $('#svg-file');
  if (!input) return;
  input.value = '';
  input.click();
}
function dashArray(kind, width) {
  const w = Math.max(width || 0.4, 0.3);
  if (kind === 'dashed') return [w * 2.2, w * 1.4];
  if (kind === 'dotted') return [w * 0.35, w * 1.5];
  return null;
}
function shadowPaint(shadow) {
  if (!shadow) return null;
  const hex = /^#[0-9a-fA-F]{6}$/.test(shadow.color || '') ? shadow.color : '#000000',
    n = parseInt(hex.slice(1), 16),
    a = (shadow.opacity ?? 35) / 100;
  return new fabric.Shadow({
    color: `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`,
    blur: shadow.blur || 0,
    offsetX: shadow.offsetX || 0,
    offsetY: shadow.offsetY || 0,
  });
}
function vectorLeaves(object, out = []) {
  if (!object) return out;
  if (object.type === 'group' && object.getObjects)
    object.getObjects().forEach(child => vectorLeaves(child, out));
  else out.push(object);
  return out;
}
function applyVectorPaint(object, l) {
  if (!object || !l) return;
  object.selectionRadius = l.type === 'rect' ? Number(l.radius) || 0 : 0;
  const width = activeStroke(l),
    align = l.type === 'line' ? 'center' : l.strokeAlign || 'center',
    drawn = align === 'inside' || align === 'outside' ? width * 2 : width,
    shadow = shadowPaint(l.shadow);
  object.set({ opacity: (l.opacity ?? 100) / 100, shadow, dirty: true, objectCaching: false });
  if (l.type === 'svg') {
    object.set({
      flipX: !!l.flipX,
      flipY: !!l.flipY,
      lockUniScaling: l.lockAspect !== false,
      stroke: null,
      strokeWidth: 0,
    });
    vectorLeaves(object).forEach(node => {
      if (l.fillMode === 'none') node.set('fill', 'transparent');
      else if (l.fillMode === 'color') node.set('fill', l.fill || '#29282d');
      if (l.strokeMode === 'none') node.set({ stroke: null, strokeWidth: 0 });
      else if (l.strokeMode === 'color')
        node.set({
          stroke: strokeColor(l),
          strokeWidth: drawn,
          strokeUniform: true,
          strokeLineCap: l.strokeCap || 'round',
          strokeLineJoin: l.strokeJoin || 'miter',
          strokeDashArray: dashArray(l.strokeDash, width),
          paintFirst: align === 'outside' ? 'stroke' : 'fill',
          dirty: true,
        });
    });
    object.clipPath =
      align === 'inside' && l.strokeMode === 'color' && width > 0
        ? new fabric.Rect({
            width: object.width || l.box.w,
            height: object.height || l.box.h,
            originX: 'center',
            originY: 'center',
          })
        : null;
  } else {
    object.set({
      fill: l.fill || '#d9d2e1',
      stroke: strokeColor(l),
      strokeWidth: drawn,
      strokeLineCap: l.strokeCap || 'butt',
      strokeLineJoin: l.strokeJoin || 'miter',
      strokeDashArray: width ? dashArray(l.strokeDash, width) : null,
      paintFirst: align === 'outside' ? 'stroke' : 'fill',
      strokeUniform: true,
    });
    if (object.type === 'rect' && l.type === 'rect') object.set({ rx: l.radius || 0, ry: l.radius || 0 });
    if (align === 'inside' && width > 0 && l.type === 'ellipse')
      object.clipPath = new fabric.Ellipse({
        rx: object.rx,
        ry: object.ry,
        originX: 'center',
        originY: 'center',
      });
    else if (align === 'inside' && width > 0 && l.type === 'rect')
      object.clipPath = new fabric.Rect({
        width: object.width,
        height: object.height,
        rx: l.radius || 0,
        ry: l.radius || 0,
        originX: 'center',
        originY: 'center',
      });
    else object.clipPath = null;
  }
  object.setCoords?.();
  canvas.requestRenderAll();
}
async function fabricSvg(l, b, base, side) {
  let object;
  try {
    const parsed = await fabric.loadSVGFromString(l.svg || '');
    const objects = parsed.objects || [];
    if (objects.length) {
      object = fabric.util.groupSVGElements(
        objects,
        Object.assign({}, parsed.options, { subTargetCheck: false, objectCaching: false }),
      );
      const gw = object.width || b.w,
        gh = object.height || b.h;
      object.set(
        Object.assign({}, base, {
          stroke: null,
          strokeWidth: 0,
          scaleX: b.w / Math.max(gw, 0.1),
          scaleY: b.h / Math.max(gh, 0.1),
          flipX: !!l.flipX,
          flipY: !!l.flipY,
          lockUniScaling: l.lockAspect !== false,
          left: layerOffset(l, side) + b.x + b.w / 2,
          top: b.y + b.h / 2,
          originX: 'center',
          originY: 'center',
        }),
      );
    }
  } catch (e) {
    notify('Не удалось показать SVG', true);
  }
  if (!object)
    object = new fabric.Rect(
      Object.assign({}, base, {
        width: b.w,
        height: b.h,
        fill: 'transparent',
        stroke: '#bca9ca',
        strokeWidth: 0.4,
        strokeDashArray: [2, 1.2],
      }),
    );
  return object;
}
function scheduleEffectRender() {
  if (effectFrame) return;
  effectFrame = requestAnimationFrame(() => {
    effectFrame = 0;
    renderScene();
  });
}
function assignLive(layer, key, value) {
  if (layer.type === 'collage' && ['gap', 'gapX', 'gapY'].includes(key)) {
    const v = clamp(value, 0, CollageCore.MAX_GAP);
    if (key === 'gap') {
      layer.gapX = v;
      layer.gapY = v;
    } else layer[key] = v;
    return;
  }
  if (key.startsWith('shadow.')) {
    layer.shadow = Object.assign(
      { color: '#000000', offsetX: 0, offsetY: 1.5, blur: 2, opacity: 35 },
      layer.shadow,
    );
    layer.shadow[key.slice(7)] = value;
    return;
  }
  layer[key] = value;
  if (key === 'strokeWidth' && value > 0 && layer.type !== 'svg') layer.strokeOn = true;
}
function finishSlide() {
  if (!slide) return;
  const start = slide.start;
  slide = null;
  if (JSON.stringify(doc) !== JSON.stringify(start)) {
    history.push(start);
    if (history.length > 60) history.shift();
    future = [];
    markDirty();
  }
  render();
}
function liveProperty(key, value) {
  if (!Number.isFinite(value)) return;
  if (!slide) slide = { start: clone(doc) };
  chosen().forEach(layer => {
    const style =
      layer.type === 'text' && textStyleKeys.includes(key) ? setTextFormat(layer, key, value) : null;
    if (!style) {
      if (
        layer.type === 'grid' &&
        ([
          'radius',
          'fontSize',
          'lineHeight',
          'letterSpacing',
          'detailFontSize',
          'detailLineHeight',
          'detailLetterSpacing',
        ].includes(key) ||
          vignetteLook(key))
      )
        blockGrids().forEach(item => assignLive(item, key, value));
      else assignLive(layer, key, value);
    }
    const obj = canvas.getObjects().find(o => o.masterId === layer.id);
    if (obj) {
      if (layer.type === 'text') applyTextPaint(obj, layer);
      else if (['rect', 'ellipse', 'line', 'svg'].includes(layer.type)) applyVectorPaint(obj, layer);
      else if (key === 'opacity') obj.set('opacity', (layer.opacity ?? 100) / 100);
      else scheduleEffectRender();
    }
    if (style) paintLinkedText(style);
  });
  syncTextOverflow();
  canvas.requestRenderAll();
}

function layersPanel() {
  if (preview) return '';
  const sec = section(), spread = sec.spreads[view.spread], groups = stackGroups(spread, sec),
    painted = sec.cover && sec.spineColor && spineGap() > 0,
    names = {text:'Текст',photo:'Фото',rect:'Фигура',ellipse:'Круг',line:'Линия',grid:'Виньетка',collage:'Коллаж',svg:'SVG'},
    icons = {text:'text-box',photo:'photo',rect:'rect',ellipse:'ellipse',line:'line',grid:'vignette',collage:'collage',svg:'svg'};
  /* Text layers are named by what they print, like in Photoshop. */
  const title = l => {
    const words = l.type === 'text' ? AutoText.applyCase(planner.resolvedText(l, {}), l.textCase).replace(/\s+/g, ' ').trim() : '';
    return words || l.name || names[l.type] || 'Объект';
  };
  const row = l => {
    const name = title(l),
      toggle = (action, label, icon, on) => `<button type="button" class="editor-layer-${action}" data-layer-action="${action}" data-layer-id="${esc(l.id)}" title="${label}" aria-label="${label}: ${esc(name)}" aria-pressed="${on}">${menuGlyph(icon)}</button>`;
    return `<div class="editor-layer${l.hidden ? ' is-hidden' : ''}${l.locked ? ' is-locked' : ''}" draggable="true" data-layer-row="${esc(l.id)}">
      ${toggle('visibility', l.hidden ? 'Показать' : 'Скрыть', l.hidden ? 'hide' : 'show', !!l.hidden)}
      <button type="button" class="editor-layer-select" data-layer-select="${esc(l.id)}" title="${esc(name)}"><img src="assets/editor/${icons[l.type] || 'rect'}.svg" alt=""><span>${esc(name)}</span></button>
      ${toggle('lock', l.locked ? 'Разблокировать' : 'Заблокировать', l.locked ? 'lock' : 'unlock', !!l.locked)}
      <button type="button" class="editor-layer-delete" data-layer-action="delete" data-layer-id="${esc(l.id)}" title="Удалить" aria-label="Удалить: ${esc(name)}">${menuGlyph('delete')}</button>
    </div>`;
  };
  const rows = order => [...order].reverse().map(row).join(''),
    system = label => `<div class="editor-layer-system"><span>${label}</span>${menuGlyph('lock')}</div>`;
  return `<section class="inspector-section inspector-layers"><h3>Слои</h3><div class="editor-layer-list">${painted ? rows(groups[1] || []) + system('Заливка корешка') : groups.slice(1).reverse().map(rows).join('')}${rows(groups[0])}${system('Фон страниц')}</div></section>`;
}
