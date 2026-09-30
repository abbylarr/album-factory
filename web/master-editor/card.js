/* Master editor · Inside a vignette card: the first card is the main one, the others repeat it.
   Double-click (or Enter) enters it; the photo and captions are picked on the canvas, captions are dragged to
   another place around the photo, and the right panel shows only the picked part. Esc leaves the card. */
'use strict';
let cardEdit = null,
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
function cardLayer() {
  if (!cardEdit) return null;
  const l = selectedLayer();
  return l && l.type === 'grid' && selected.length === 1 && l.id === cardEdit.id && !preview ? l : null;
}
/* The card mode ends as soon as the vignette is no longer the only selection. */
function syncCardEdit() {
  if (cardEdit && !cardLayer()) {
    cardEdit = null;
    cardDrag = null;
    renderScene();
  }
}
function vignetteCards(l) {
  const obj = canvas.getObjects().find(o => o.masterId === l.id);
  return obj?.vignette?.cards?.length ? { obj, cards: obj.vignette.cards } : null;
}
function enterCard(l, part = 'photo') {
  if (preview || l?.type !== 'grid' || !vignetteCards(l)) return;
  if (part === 'detail' && !l.showDetail) part = 'photo';
  cardEdit = { id: l.id, part };
  renderInspector();
  renderScene();
}
function exitCard() {
  if (!cardEdit) return;
  cardEdit = null;
  cardDrag = null;
  renderInspector();
  renderScene();
}
function pickCardPart(part) {
  if (!cardEdit || cardEdit.part === part) return;
  cardEdit.part = part;
  renderInspector();
  placeCardUi();
}
/* Which part of a card lies under a scene point: used by the double-click that enters the card. */
function cardPartAt(l, point) {
  const found = vignetteCards(l);
  if (!found) return 'photo';
  const ox = layerOffset(l, found.obj.side) + l.box.x,
    oy = l.box.y,
    inside = r => r && point.x >= ox + r.x && point.x <= ox + r.x + r.w && point.y >= oy + r.y && point.y <= oy + r.y + r.h;
  for (const card of found.cards) {
    if (inside(card.detail)) return 'detail';
    if (inside(card.name)) return 'name';
  }
  return 'photo';
}
/* The place a caption dropped at a scene point takes around the photo of the main card. */
function cardZoneAt(photo, x, y) {
  if (x >= photo.x && x <= photo.x + photo.w && y >= photo.y && y <= photo.y + photo.h) return 'over';
  if (x >= photo.x && x <= photo.x + photo.w) return y < photo.y ? 'above' : 'below';
  if (y >= photo.y - photo.h * 0.25 && y <= photo.y + photo.h * 1.25) return x < photo.x ? 'left' : 'right';
  return y < photo.y ? 'above' : 'below';
}
/* Drop places drawn around the main photo while a caption is dragged. */
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
  const l = cardLayer(),
    found = l && !l.angle && !l.hidden ? vignetteCards(l) : null;
  if (!found) {
    host.hidden = true;
    host.innerHTML = '';
    return;
  }
  const ox = layerOffset(l, found.obj.side) + l.box.x,
    oy = l.box.y,
    card = found.cards[0],
    shift = r => ({ x: ox + r.x, y: oy + r.y, w: r.w, h: r.h }),
    box = r => {
      const a = sceneToHost(r.x, r.y),
        b = sceneToHost(r.x + r.w, r.y + r.h);
      return boxStyle({ left: a.x, top: a.y, width: b.x - a.x, height: b.y - a.y });
    },
    names = { photo: 'Фото', name: 'Имя', detail: vignetteDetailName(l) },
    part = (key, r) =>
      r
        ? `<div class="card-part ${key}${cardEdit.part === key ? ' active' : ''}${cardDrag?.part === key && cardDrag.moved ? ' lifted' : ''}" data-card-part="${key}" style="${box(shift(r))}"><span class="card-part-label">${names[key]}</span></div>`
        : '',
    photo = shift(card.photo);
  let html = part('photo', card.photo) + part('name', card.name) + part('detail', card.detail);
  if (cardDrag?.moved) {
    const zones = cardZoneBoxes(photo);
    html =
      Object.entries(zones)
        .map(
          ([zone, r]) =>
            `<div class="card-zone${cardDrag.zone === zone ? ' hot' : ''}" style="${box(r)}"><span>${CARD_ZONE_NAMES[zone]}</span></div>`,
        )
        .join('') +
      html +
      `<div class="card-ghost" style="${box({ ...cardDrag.rect, x: cardDrag.point.x - cardDrag.grab.x, y: cardDrag.point.y - cardDrag.grab.y })}"></div>`;
  }
  host.hidden = false;
  host.innerHTML = html;
}
function bindCardUi() {
  const host = $('#card-ui');
  host.addEventListener('pointerdown', e => {
    const hit = e.target.closest('[data-card-part]'),
      l = cardLayer();
    if (!hit || !l || e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    const key = hit.dataset.cardPart;
    pickCardPart(key);
    if (key === 'photo') return;
    const found = vignetteCards(l),
      card = found.cards[0],
      ox = layerOffset(l, found.obj.side) + l.box.x,
      oy = l.box.y,
      point = canvas.getScenePoint(e),
      r = card[key];
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
/* Right panel inside the card: the path back to the vignette, then the picked part only. */
function cardPanel(l) {
  const part = cardEdit.part,
    detailName = vignetteDetailName(l),
    tabs = [
      ['photo', 'Фото'],
      ['name', 'Имя'],
      ['detail', detailName],
    ],
    head = `<div class="card-head"><button type="button" class="card-back" data-card-exit title="Выйти из карточки · Esc"><svg viewBox="0 0 8 12" aria-hidden="true"><path d="M6 2 2 6l4 4" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>${esc(l.name || 'Виньетка')}</button><strong>Карточка</strong></div><div class="segments card-tabs" role="tablist" aria-label="Часть карточки">${tabs.map(([id, name]) => `<button type="button" role="tab" data-card-pick="${id}" class="${part === id ? 'active' : ''}" aria-selected="${part === id}">${name}</button>`).join('')}</div>`,
    section = (title, body) =>
      `<section class="inspector-section typography-section"><div class="typography-heading"><h3>${title}</h3></div>${body}</section>`,
    zones = key => {
      const current = l[key] || 'below';
      return `<div class="card-zones" role="radiogroup" aria-label="Где подпись">${Object.entries(CARD_ZONE_NAMES)
        .map(
          ([zone, name]) =>
            `<button type="button" role="radio" class="icon-toggle${current === zone ? ' active' : ''}" aria-checked="${current === zone}" data-choice="${key}" data-value="${zone}" title="${name}" aria-label="${name}"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${CARD_ZONE_GLYPHS[zone]}</svg></button>`,
        )
        .join('')}</div>`;
    },
    sideWidth = zone =>
      zone === 'left' || zone === 'right'
        ? `<div class="type-metrics">${scrubField('Ширина подписи', 'captionWidth', round(l.captionWidth ?? 40), 10, 150, 0.5, '<span class="type-metric-icon">↔</span>', 'мм')}</div>`
        : '';
  if (part === 'photo') {
    const ratio = Number(l.photoRatio) || 0.75,
      width = (key, value, label) =>
        `<label>${label}<input type="number" data-live="${key}" min="5" max="180" step="0.5" value="${round(value)}" aria-label="Ширина фото: ${label}"></label>`;
    return (
      head +
      section(
        'Фото',
        `<div class="segments card-ratio" role="radiogroup" aria-label="Пропорции фото">${PHOTO_RATIOS.map(([value, name]) => `<button type="button" role="radio" data-choice="photoRatio" data-value="${value}" class="${Math.abs(ratio - value) < 1e-3 ? 'active' : ''}" aria-checked="${Math.abs(ratio - value) < 1e-3}">${name}</button>`).join('')}</div><div class="block-pair vignette-photo-width"><span>Ширина${infoTip('Если карточки не помещаются, фото уменьшается до нижней границы, а остальные уходят на следующую страницу.')}</span>${width('minPhotoWidth', l.minPhotoWidth ?? 32, 'от')}${width('photoWidth', l.photoWidth ?? 85, 'до')}<em>мм</em></div><div class="type-metrics">${scrubField('Скругление', 'radius', l.radius || 0, 0, 100, 0.5, '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><path d="M4 16V10a6 6 0 0 1 6-6h6"/></svg>', 'мм')}</div>`,
      ) +
      block('Оформление', effectControls(l))
    );
  }
  if (part === 'name') {
    const zone = l.nameAt || 'below';
    return (
      head +
      section(
        'Место',
        `${zones('nameAt')}<div class="type-metrics">${vignetteGapField(l, 'photoNameGap')}</div>${sideWidth(zone)}`,
      ) +
      section(
        'Имя',
        gridTextPanel(l) +
          `<div class="type-metrics vignette-min-size">${scrubField('Длинные имена до', 'minFontSize', l.minFontSize ?? 10, 4, 120, 0.5, '<span class="type-metric-icon">A↓</span>', 'pt')}${infoTip('Если имя не помещается в две строки, кегль всех имён блока уменьшается, но не ниже этого.')}</div>`,
      )
    );
  }
  const show = !!l.showDetail,
    zone = l.detailAt || 'below',
    together = zone === (l.nameAt || 'below');
  return (
    head +
    `<section class="inspector-section typography-section"><div class="vignette-detail-row"><span>${detailName === 'Цитата' ? 'Цитата' : 'Предмет'} в карточке</span><button type="button" class="switch${show ? ' on' : ''}" data-choice="showDetail" aria-pressed="${show}" aria-label="${detailName} в карточке"></button></div></section>` +
    (show
      ? section(
          'Место',
          `${zones('detailAt')}<div class="type-metrics">${together ? vignetteGapField(l, 'nameDetailGap') : vignetteGapField(l, 'photoNameGap')}</div>${sideWidth(zone)}`,
        ) + section(detailName, gridTextPanel(l, 'detail'))
      : '')
  );
}
