/* Master editor · Vignette cards. A selected vignette shows its card settings at once: a click on a photo or a
   caption on the canvas picks that part (in every card, since all cards are the same), a caption is dragged to
   another place around the photo. */
'use strict';
let cardPart = 'photo',
  cardDrag = null;
const CARD_ZONE_NAMES = {
    below: 'Под фото',
    above: 'Над фото',
    left: 'Слева',
    right: 'Справа',
    over: 'На фото',
  },
  CARD_ZONE_GLYPHS = {
    below: '<rect x="5" y="2.5" width="10" height="9" rx="1"/><path d="M5 15h10M7 17.5h6"/>',
    above: '<path d="M5 2.5h10M7 5h6"/><rect x="5" y="8.5" width="10" height="9" rx="1"/>',
    left: '<path d="M2 8h5M2 10.5h4"/><rect x="9" y="4.5" width="9" height="11" rx="1"/>',
    right: '<rect x="2" y="4.5" width="9" height="11" rx="1"/><path d="M13 8h5M13 10.5h4"/>',
    over: '<rect x="4" y="3" width="12" height="14" rx="1"/><path d="M6.5 13h7M7.5 15h5"/>',
  },
  PHOTO_RATIOS = [
    [0.75, '3:4'],
    [0.8, '4:5'],
    [1, '1:1'],
    [2 / 3, '2:3'],
  ];

/* The vignette whose card settings and canvas handles are showing. */
function activeCardLayer() {
  if (preview || tool !== 'select' || selected.length !== 1 || photoCrop) return null;
  const l = selectedLayer();
  return l && l.type === 'grid' && !l.hidden ? l : null;
}
function vignetteCards(l) {
  const obj = canvas.getObjects().find(o => o.masterId === l.id);
  return obj?.vignette?.cards?.length ? { obj, cards: obj.vignette.cards } : null;
}
function pickCardPart(part) {
  if (cardPart === part) return;
  cardPart = part;
  renderInspector();
  placeVignetteUi();
}
/* Which part of which card lies under a scene point. */
function cardPartAt(l, point) {
  const found = vignetteCards(l);
  if (!found) return { part: 'photo', index: -1 };
  const ox = layerOffset(l, found.obj.side) + l.box.x,
    oy = l.box.y,
    inside = r =>
      r && point.x >= ox + r.x && point.x <= ox + r.x + r.w && point.y >= oy + r.y && point.y <= oy + r.y + r.h;
  for (const [index, card] of found.cards.entries()) {
    if (inside(card.detail)) return { part: 'detail', index };
    if (inside(card.name)) return { part: 'name', index };
    if (inside(card.photo)) return { part: 'photo', index };
  }
  return { part: 'photo', index: -1 };
}
/* A click on the vignette picks the part under the pointer; the vignette itself still selects and moves. */
canvas.on('mouse:down', opt => {
  const l = allLayers().find(x => x.id === opt.target?.masterId);
  if (l?.type !== 'grid' || tool !== 'select') return;
  const hit = cardPartAt(l, canvas.getScenePoint(opt.e));
  if (hit.index < 0 || hit.part === cardPart) return;
  cardPart = hit.part;
  if (selected.length === 1 && selected[0] === l.id) {
    renderInspector();
    placeVignetteUi();
  }
});
/* The place a caption dropped at a scene point takes around the photo of its card. */
function cardZoneAt(photo, x, y) {
  if (x >= photo.x && x <= photo.x + photo.w && y >= photo.y && y <= photo.y + photo.h) return 'over';
  if (x >= photo.x && x <= photo.x + photo.w) return y < photo.y ? 'above' : 'below';
  if (y >= photo.y - photo.h * 0.25 && y <= photo.y + photo.h * 1.25) return x < photo.x ? 'left' : 'right';
  return y < photo.y ? 'above' : 'below';
}
function cardZoneBoxes(photo) {
  const band = Math.max(6, Math.min(photo.w, photo.h) * 0.35);
  return {
    above: { x: photo.x, y: photo.y - band, w: photo.w, h: band },
    below: { x: photo.x, y: photo.y + photo.h, w: photo.w, h: band },
    left: { x: photo.x - band, y: photo.y, w: band, h: photo.h },
    right: { x: photo.x + photo.w, y: photo.y, w: band, h: photo.h },
    over: { x: photo.x + photo.w * 0.15, y: photo.y + photo.h * 0.55, w: photo.w * 0.7, h: photo.h * 0.35 },
  };
}
function placeCardUi() {
  const host = $('#card-ui');
  if (!host || !canvas) return;
  const l = activeCardLayer(),
    found = l && !vignetteDrag ? vignetteCards(l) : null;
  if (!found) {
    host.hidden = true;
    host.innerHTML = '';
    return;
  }
  const ox = layerOffset(l, found.obj.side) + l.box.x,
    oy = l.box.y,
    shift = r => ({ x: ox + r.x, y: oy + r.y, w: r.w, h: r.h }),
    screen = r => {
      const a = sceneToHost(r.x, r.y),
        b = sceneToHost(r.x + r.w, r.y + r.h);
      return { left: a.x, top: a.y, width: b.x - a.x, height: b.y - a.y };
    },
    box = r => boxStyle(screen(r)),
    lifted = cardDrag?.moved ? cardDrag : null;
  let html = '';
  found.cards.forEach((card, index) => {
    if (cardPart === 'photo') html += `<div class="card-part photo active" style="${box(shift(card.photo))}"></div>`;
    for (const key of ['name', 'detail'])
      if (card[key])
        html += `<div class="card-part ${key}${cardPart === key ? ' active' : ''}${lifted?.part === key ? ' lifted' : ''}" data-card-part="${key}" data-card="${index}" style="${box(shift(card[key]))}"></div>`;
  });
  if (lifted)
    html +=
      Object.entries(cardZoneBoxes(lifted.photo))
        .map(
          ([zone, r]) =>
            `<div class="card-zone${lifted.zone === zone ? ' hot' : ''}" style="${box(r)}"><span>${CARD_ZONE_NAMES[zone]}</span></div>`,
        )
        .join('') +
      `<div class="card-ghost" style="${box({ ...lifted.rect, x: lifted.point.x - lifted.grab.x, y: lifted.point.y - lifted.grab.y })}"></div>`;
  host.hidden = false;
  host.innerHTML = html;
}
function bindCardUi() {
  const host = $('#card-ui');
  host.addEventListener('pointerdown', e => {
    const hit = e.target.closest('[data-card-part]'),
      l = activeCardLayer();
    if (!hit || !l || e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    const key = hit.dataset.cardPart,
      found = vignetteCards(l),
      card = found.cards[Number(hit.dataset.card)],
      ox = layerOffset(l, found.obj.side) + l.box.x,
      oy = l.box.y,
      point = canvas.getScenePoint(e),
      r = card[key];
    pickCardPart(key);
    cardDrag = {
      part: key,
      pointerId: e.pointerId,
      start: { x: e.clientX, y: e.clientY },
      grab: { x: point.x - (ox + r.x), y: point.y - (oy + r.y) },
      rect: { w: r.w, h: r.h },
      photo: { x: ox + card.photo.x, y: oy + card.photo.y, w: card.photo.w, h: card.photo.h },
      point,
      zone: r.zone,
      from: r.zone,
      moved: false,
    };
  });
  addEventListener('pointermove', e => {
    const drag = cardDrag;
    if (!drag || e.pointerId !== drag.pointerId) return;
    if (!drag.moved && Math.hypot(e.clientX - drag.start.x, e.clientY - drag.start.y) < 4) return;
    drag.moved = true;
    drag.point = canvas.getScenePoint(e);
    drag.zone = cardZoneAt(drag.photo, drag.point.x, drag.point.y);
    document.body.style.cursor = 'grabbing';
    placeCardUi();
  });
  const end = e => {
    const drag = cardDrag;
    if (!drag || e.pointerId !== drag.pointerId) return;
    cardDrag = null;
    document.body.style.cursor = '';
    if (drag.moved && drag.zone !== drag.from) property(drag.part === 'name' ? 'nameAt' : 'detailAt', drag.zone);
    else placeCardUi();
  };
  addEventListener('pointerup', end);
  addEventListener('pointercancel', end);
}
bindCardUi();
/* «Карточки»: everything that decides how many cards fit a page, side by side — the count, the photo shape and width,
   the gap. Next to «влезает до» stands the setting that stops more from fitting; a click on it leads to that field. */
function cardsSection(l) {
  const { low, high, fits, shown } = cardsRange(),
    ratio = Number(l.photoRatio) || 0.75,
    limiter = cardsLimiter(),
    hint = `<button type="button" class="vignette-limiter cards-limiter" data-limiter="${limiter?.key || ''}" title="Уменьшите, чтобы влезло больше"${limiter ? '' : ' hidden'}>${limiter ? `мешает ${limiter.label}` : ''}</button>`,
    mm = { suffix: 'мм' };
  return (
    `<section class="inspector-section typography-section card-section"><h3>Карточки</h3>` +
    `<div class="card-group"><p class="card-sub">На странице <span class="vignette-fits">влезает до ${fits}</span></p>` +
    `<div class="type-metrics vignette-cells vignette-limits">${vignetteCell('От', 'min', low, fits, '≥', { attr: 'data-list', step: 1 })}${vignetteCell('До', 'max', blockList(section()).max < 100 ? high : '', fits, '≤', { attr: 'data-list', step: 1, placeholder: fits })}</div>${hint}` +
    `<label class="vignette-shown"><span>Показать <b class="vignette-shown-value">${shown}</b></span><input type="range" data-cards-shown min="${low}" max="${high}" step="1" value="${shown}"${low === high ? ' disabled' : ''} aria-label="Сколько карточек показать на странице"></label></div>` +
    `<div class="card-group"><p class="card-sub">Фото</p><div class="segments card-ratio" role="radiogroup" aria-label="Пропорции фото">${PHOTO_RATIOS.map(([value, name]) => `<button type="button" role="radio" data-choice="photoRatio" data-value="${value}" class="${Math.abs(ratio - value) < 1e-3 ? 'active' : ''}" aria-checked="${Math.abs(ratio - value) < 1e-3}">${name}</button>`).join('')}</div>` +
    `<div class="type-metrics">${vignetteCell('Ширина от', 'minPhotoWidth', round(l.minPhotoWidth ?? 32), 180, '↔', { ...mm, min: 5 })}${vignetteCell('до', 'photoWidth', round(l.photoWidth ?? 85), 180, '↔', { ...mm, min: 5 })}${vignetteGapField(l, 'gap')}${vignetteCell('Скругление', 'radius', l.radius || 0, 100, '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><path d="M4 16V10a6 6 0 0 1 6-6h6"/></svg>', { ...mm, min: 0 })}</div></div>` +
    lookGroup('photo', effectControls(l), [strokeOpen(l) && 'обводка', l.shadow && 'тень'].filter(Boolean)) +
    `</section>`
  );
}
/* What stops one more card from fitting the tightest vignette of the block. Each setting is tried at its loosest; the one
   that frees most cards is named. The vignette size is named only when no setting helps. */
function cardsLimiter(sec = section()) {
  const list = blockList(sec),
    grids = blockGrids(sec);
  if (!grids.length) return null;
  const count = grid => {
      let n = 0;
      for (let i = 1; i <= 100; i++) if (planner.gridGeometry(i, grid)) n = i;
      return n;
    },
    tight = grids.reduce((a, b) => (count(b) < count(a) ? b : a)),
    now = count(tight);
  if (list.max < 100 && list.max <= now) return null;
  const side = tight.nameAt === 'left' || tight.nameAt === 'right',
    tries = [
      { key: 'minPhotoWidth', label: `ширина фото от ${round(tight.minPhotoWidth ?? 32)} мм`, grid: { minPhotoWidth: 5 } },
      { key: 'minFontSize', label: `имя от ${round(tight.minFontSize ?? tight.fontSize)} pt`, grid: { minFontSize: 4 } },
      { key: 'gap', label: `между карточками ${round(tight.gap ?? 5)} мм`, grid: { gap: 0 } },
      { key: 'photoNameGap', label: 'отступы подписей', grid: { photoNameGap: 0, nameDetailGap: 0 } },
      side && { key: 'captionWidth', label: `ширина подписи ${round(tight.captionWidth ?? 40)} мм`, grid: { captionWidth: 10 } },
    ]
      .filter(Boolean)
      .map(t => ({ ...t, fits: count({ ...tight, ...t.grid }) }))
      .filter(t => t.fits > now)
      .sort((a, b) => b.fits - a.fits);
  if (tries.length) return { key: tries[0].key, label: tries[0].label };
  if (count({ ...tight, box: { ...tight.box, w: pageWidth(), h: pageHeight() } }) <= now) return null;
  /* The size is the vignette's own: it leads there only from the vignette that holds the limit. */
  return tight.id === selectedLayer()?.id
    ? { key: 'box.w', label: 'размер виньетки' }
    : { key: '', label: 'размер виньетки на другой странице' };
}
/* While a size is dragged the inspector is not redrawn: the count that fits and the limiter follow by hand. */
function refreshCardsFit() {
  const label = $('#inspector .vignette-fits'),
    l = selectedLayer();
  if (!label || l?.type !== 'grid') return;
  const fits = cardsRange().fits,
    font = nameFontInfo(l);
  label.textContent = `влезает до ${fits}`;
  setLimiterHint($('#inspector .cards-limiter'), cardsLimiter());
  setLimiterHint($('#inspector .name-size-limiter'), font.limiter, font.limiter ? `на холсте ${round(font.size)} pt` : '');
  const status = $('#inspector .vignette-status');
  if (status) status.innerHTML = vignetteStatusText(fits, font);
}
function setLimiterHint(hint, limiter, lead = '') {
  if (!hint) return;
  if (limiter) hint.dataset.limiter = limiter.key;
  else delete hint.dataset.limiter;
  hint.textContent = [lead, limiter && `мешает ${limiter.label}`].filter(Boolean).join(' · ');
  hint.hidden = !hint.textContent;
}
/* The size the names really get on the canvas page, and when it stays under «до», the setting that holds it:
   beside the photo the caption width or the photo height, elsewhere the photo width or the number of cards. */
function nameFontInfo(l) {
  const n = cardsPreview || cardsRange().shown,
    source = l.source || 'students',
    people = MasterPlanner(doc, { ...view, [source]: n }).people(source),
    size = settings => {
      const geo = planner.gridGeometry(n, settings);
      return geo ? planner.nameFont(settings, geo, people).size : null;
    },
    now = size(l);
  if (now == null || now >= l.fontSize) return { size: now, limiter: null };
  const zone = l.nameAt || 'below',
    side = zone === 'left' || zone === 'right',
    grows = settings => (size(settings) ?? 0) > now,
    photo = { key: 'photoWidth', label: 'ширина фото' },
    count = { key: 'max', label: 'число карточек' };
  let limiter;
  if (side && grows({ ...l, captionWidth: (l.captionWidth ?? 40) + 30 }))
    limiter = { key: 'captionWidth', label: 'ширина подписи' };
  else if (grows({ ...l, photoWidth: (l.photoWidth ?? 85) + 40 })) limiter = side ? { ...photo, label: 'высота фото' } : photo;
  else limiter = count;
  return { size: now, limiter };
}
function vignetteStatusText(fits, font) {
  return `<span>влезает до <b>${fits}</b></span>${font.size == null ? '' : `<span>имя <b>${round(font.size)}</b> pt</span>`}`;
}
/* «Подписи»: the name and the subject (or quote), each with its place by the photo and its type. The name size is a
   range: names are set at «до» and shrink block-wide, down to «от», until the longest one fits two lines. */
function captionsSection(l) {
  const part = cardPart === 'detail' ? 'detail' : 'name',
    detailName = vignetteDetailName(l),
    tabs = `<div class="segments card-tabs" role="tablist" aria-label="Подпись">${[
      ['name', 'Имя'],
      ['detail', detailName],
    ]
      .map(
        ([id, name]) =>
          `<button type="button" role="tab" data-card-pick="${id}" class="${part === id ? 'active' : ''}" aria-selected="${part === id}">${name}</button>`,
      )
      .join('')}</div>`,
    group = (title, body) => `<div class="card-group">${title ? `<p class="card-sub">${title}</p>` : ''}${body}</div>`,
    zones = key => {
      const current = l[key] || 'below';
      return `<div class="card-zones" role="radiogroup" aria-label="Где подпись">${Object.entries(CARD_ZONE_NAMES)
        .map(
          ([zone, name]) =>
            `<button type="button" role="radio" class="icon-toggle${current === zone ? ' active' : ''}" aria-checked="${current === zone}" data-choice="${key}" data-value="${zone}" title="${name}" aria-label="${name}"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${CARD_ZONE_GLYPHS[zone]}</svg></button>`,
        )
        .join('')}</div>`;
    },
    /* The gap to the photo, and for a caption beside the photo its width and height (from the photo top to its foot). */
    place = (key, gapKey) => {
      const zone = l[key] || 'below',
        side = zone === 'left' || zone === 'right';
      /* Over the photo the caption keeps its own distance from the photo edge. */
      if (zone === 'over' && gapKey === 'photoNameGap') gapKey = 'overInset';
      return `${zones(key)}<div class="type-metrics">${vignetteGapField(l, gapKey)}${side ? vignetteCell('Ширина подписи', 'captionWidth', round(l.captionWidth ?? 40), 150, '↔', { min: 10, suffix: 'мм' }) : ''}</div>${side ? `<label class="caption-height"><span>По высоте</span><input type="range" data-live="sideAlign" min="0" max="1" step="0.01" value="${l.sideAlign ?? 0.5}" list="caption-height-marks" aria-label="Подпись сбоку по высоте: от верха фото до низа"><datalist id="caption-height-marks"><option value="0"></option><option value="0.5"></option><option value="1"></option></datalist><small><i>верх</i><i>середина</i><i>низ</i></small></label>` : ''}`;
    };
  let body;
  /* A caption size is a range «от–до». Keys are the name's; gridTextPanel prefixes them for the subject or quote. */
  const sizeRange = (what, low, high, title) => {
    const size = (key, value, label) =>
      `<div class="type-value" data-scrub="${key}" data-min="4" data-max="120" data-step="0.5" title="Кегль ${label}: потяните влево или вправо"><span class="type-inline-scrub" aria-hidden="true"><span class="type-size-icon">A</span></span><input data-live="${key}" type="number" min="4" max="120" step="0.5" value="${round(value)}" aria-label="Кегль ${what} ${label}"></div>`;
    return `<div class="type-field name-size-range" title="${title}">${size('minFontSize', low, 'от')}<span class="name-size-dash">–</span>${size('fontSize', high, 'до')}</div>`;
  };
  if (part === 'name') {
    const range = sizeRange(
      'имени',
      l.minFontSize ?? l.fontSize,
      l.fontSize,
      'Имена набираются кеглем «до»; если самое длинное не помещается в две строки, все имена блока уменьшаются, но не мельче «от»',
    );
    const font = nameFontInfo(l),
      text = gridTextPanel(l, '', '', range),
      at = text.indexOf('<div class="type-metrics">'),
      hint = `<button type="button" class="vignette-limiter name-size-limiter" data-limiter="${font.limiter?.key || ''}" title="Измените, чтобы имена стали крупнее"${font.limiter ? '' : ' hidden'}>на холсте ${round(font.size ?? l.fontSize)} pt${font.limiter ? ` · мешает ${font.limiter.label}` : ''}</button>`;
    body =
      group('Место', place('nameAt', 'photoNameGap')) +
      group('Текст', at < 0 ? text + hint : text.slice(0, at) + hint + text.slice(at)) +
      lookGroup('name', captionLookControls(l, 'name'), captionLookState(l, 'name'));
  } else {
    const show = !!l.showDetail,
      together = (l.detailAt || 'below') === (l.nameAt || 'below');
    body =
      group(
        '',
        `<div class="vignette-detail-row"><span>${detailName} в карточке</span><button type="button" class="switch${show ? ' on' : ''}" data-choice="showDetail" aria-pressed="${show}" aria-label="${detailName} в карточке"></button></div>`,
      ) +
      (show
        ? group('Место', place('detailAt', together ? 'nameDetailGap' : 'photoNameGap')) +
          group(
            'Текст',
            gridTextPanel(
              l,
              'detail',
              '',
              sizeRange(
                l.source === 'teachers' ? 'предмета' : 'цитаты',
                l.detailMinFontSize ?? l.detailFontSize ?? 9,
                l.detailFontSize ?? 9,
                `${detailName} набирается кеглем «до»; длинная уменьшается в своей карточке, но не мельче «от»`,
              ),
            ),
          ) +
          lookGroup('detail', captionLookControls(l, 'detail'), captionLookState(l, 'detail'))
        : '');
  }
  return `<section class="inspector-section typography-section card-section"><h3>Подписи</h3>${tabs}${body}</section><div class="vignette-status" role="status">${vignetteStatusText(cardsRange().fits, nameFontInfo(l))}</div>`;
}
/* The canvas shows each vignette page with a chosen number of cards, not a whole pretend class: what matters while
   designing is how a page looks at 4, 12 or 30 cards. The «Показать» slider picks it between the block's limits;
   while a limit is dragged, the page shows that limit. Names come from an endless test list. */
const shownCards = {};
let cardsPreview = 0;
function vignetteFits(list, sec = section()) {
  return planner.listCapacity({ ...sec, list: { ...list, max: 100 } });
}
function cardsRange(sec = section()) {
  const list = blockList(sec),
    fits = vignetteFits(list, sec),
    high = Math.max(1, Math.min(list.max, fits)),
    low = Math.max(1, Math.min(list.min, high));
  return { low, high, fits, shown: clamp(shownCards[sec.id] ?? high, low, high) };
}
function previewPage(template, g) {
  const grid = template?.layers.find(l => l.type === 'grid');
  if (!grid) return g;
  const source = grid.source || 'students',
    n = cardsPreview || cardsRange().shown,
    records = MasterPlanner(doc, { ...view, [source]: n }).people(source),
    geo = planner.gridGeometry(n, grid),
    font = geo ? planner.nameFont(grid, geo, records).size : grid.fontSize;
  return { templateId: template.id, records, layoutCount: n, source, actualFont: font };
}
function showCardsPreview(n) {
  const next = Math.max(0, Math.min(99, Number(n) || 0));
  if (next === cardsPreview) return;
  cardsPreview = next;
  renderScene();
  refreshCardsFit();
}
{
  const inspector = $('#inspector'),
    limit = target => target?.closest?.('.vignette-limits .type-field'),
    value = field => {
      const input = field.querySelector('[data-list]'),
        { fits } = cardsRange();
      return Math.min(Number(input.value) || fits, fits);
    };
  /* A limit under the pointer or being set shows its page; leaving it brings the chosen page back. */
  inspector.addEventListener('pointerover', e => {
    const field = limit(e.target);
    if (field) showCardsPreview(value(field));
  });
  inspector.addEventListener('pointerout', e => {
    if (limit(e.target) && !limit(e.relatedTarget) && !inspector.querySelector('[data-list]:focus')) showCardsPreview(0);
  });
  inspector.addEventListener('focusin', e => {
    if (e.target.matches('[data-list]')) showCardsPreview(value(limit(e.target)));
  });
  inspector.addEventListener('focusout', e => {
    if (e.target.matches('[data-list]')) showCardsPreview(0);
  });
  inspector.addEventListener('input', e => {
    if (e.target.matches('[data-list]')) return showCardsPreview(value(limit(e.target)));
    if (!e.target.matches('[data-cards-shown]')) return;
    shownCards[section().id] = Number(e.target.value);
    const label = inspector.querySelector('.vignette-shown-value');
    if (label) label.textContent = e.target.value;
    renderScene();
    refreshCardsFit();
  });
}
/* Caption look: an outline and a shadow per caption (name, subject or quote), the same in every card of the block.
   The outline goes round the letters, outside them, so the letters keep their weight. Keys read «nameStroke.width». */
const CAPTION_LOOK = {
  Stroke: { color: '#ffffff', width: 0.3 },
  Shadow: { color: '#000000', offsetX: 0, offsetY: 0.4, blur: 0.6, opacity: 50 },
};
function captionLookKey(key) {
  const m = /^(name|detail)(Stroke|Shadow)(?:On|\.(\w+))$/.exec(key || '');
  return m ? { field: m[1] + m[2], kind: m[2], prop: m[3] || null } : null;
}
function setCaptionLook(key, value) {
  const look = captionLookKey(key);
  if (!look) return false;
  for (const item of section()
    .spreads.flatMap(sp => sp.pages.flatMap(p => p.layers))
    .filter(i => i.type === 'grid')) {
    if (!look.prop) {
      if (value) item[look.field] = { ...CAPTION_LOOK[look.kind], ...item[look.field] };
      else delete item[look.field];
    } else item[look.field] = { ...CAPTION_LOOK[look.kind], ...item[look.field], [look.prop]: value };
  }
  return true;
}
/* Fabric options for a caption's look on the canvas (sizes in mm, as the scene). */
function captionLookPaint(l, prefix) {
  const stroke = l[prefix + 'Stroke'],
    shadow = l[prefix + 'Shadow'];
  return {
    stroke: stroke ? stroke.color : null,
    strokeWidth: stroke ? stroke.width * 2 : 0,
    paintFirst: 'stroke',
    strokeLineJoin: 'round',
    shadow: shadowPaint(shadow),
  };
}
function captionLookControls(l, prefix) {
  const stroke = l[prefix + 'Stroke'],
    shadow = l[prefix + 'Shadow'];
  let body = effectSwitch('Обводка', prefix + 'StrokeOn', !!stroke, glyph.outside);
  if (stroke)
    body +=
      colorControl('Цвет обводки', prefix + 'Stroke.color', stroke.color) +
      slider('Толщина', prefix + 'Stroke.width', stroke.width, 0.05, 2, 0.05);
  body += effectSwitch(
    'Тень',
    prefix + 'ShadowOn',
    !!shadow,
    '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="5" width="12" height="12" rx="2" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M9 20h10V9" fill="none" stroke="currentColor" stroke-width="1.8" opacity=".5"/></svg>',
  );
  if (shadow)
    body +=
      colorControl('Цвет тени', prefix + 'Shadow.color', shadow.color) +
      slider('Сдвиг X', prefix + 'Shadow.offsetX', shadow.offsetX, -5, 5, 0.1) +
      slider('Сдвиг Y', prefix + 'Shadow.offsetY', shadow.offsetY, -5, 5, 0.1) +
      slider('Размытие', prefix + 'Shadow.blur', shadow.blur, 0, 5, 0.1) +
      slider('Сила тени', prefix + 'Shadow.opacity', shadow.opacity, 0, 100, 1);
  return body;
}
function captionLookState(l, prefix) {
  return [l[prefix + 'Stroke'] && 'обводка', l[prefix + 'Shadow'] && 'тень'].filter(Boolean);
}
/* «Оформление» of a vignette folds away: it is optional. Folded by default; what is switched on shows in its title. */
const openLooks = new Set();
function lookGroup(id, body, on) {
  return `<details class="card-group look-group" data-look="${id}"${openLooks.has(id) ? ' open' : ''}><summary class="card-sub">Оформление${on.length ? `<span class="look-state">${on.join(' · ')}</span>` : ''}</summary>${body}</details>`;
}
$('#inspector').addEventListener(
  'toggle',
  e => {
    const id = e.target.dataset?.look;
    if (!id) return;
    if (e.target.open) openLooks.add(id);
    else openLooks.delete(id);
  },
  true,
);
