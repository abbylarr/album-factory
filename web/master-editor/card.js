/* Master editor · Vignette cards. A first click selects the vignette: the panel shows the vignette and how many cards
   go on a page. A click on a photo or a caption of the selected vignette goes into that part (in every card, since all
   cards are the same) and the panel shows only its settings; Esc or a click between the cards goes back. A caption is
   dragged to another place around the photo. The «Показать» slider stays at the panel foot on every level. */
'use strict';
/* null: the vignette itself; 'photo', 'name' or 'detail': that part of every card. */
let cardPart = null,
  cardHover = null,
  cardDrag = null,
  cardClickWasSelected = false,
  /* The card clicked last: the photo bar stands over it. */
  cardIndex = 0;
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
  part = part || null;
  if (cardPart === part) return;
  cardPart = part;
  cardHover = null;
  $('#inspector').scrollTop = 0;
  renderInspector();
  placeVignetteUi();
}
function hoverCardPart(part) {
  part = part || null;
  if (cardHover === part) return;
  cardHover = part;
  placeCardUi();
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
    if (inside(card.photo)) return { part: card.lead ? 'lead' : 'photo', index };
  }
  return { part: 'photo', index: -1 };
}
/* The first click selects the vignette; a click on a selected vignette goes into the part under the pointer, or back
   to the vignette between the cards. The vignette still moves by dragging. */
canvas.on('mouse:down:before', opt => {
  const id = opt.target?.masterId;
  cardClickWasSelected = !!id && selected.length === 1 && selected[0] === id;
});
canvas.on('mouse:down', opt => {
  const l = allLayers().find(x => x.id === opt.target?.masterId);
  if (l?.type !== 'grid' || tool !== 'select' || !cardClickWasSelected) return;
  const hit = cardPartAt(l, canvas.getScenePoint(opt.e));
  if (hit.index >= 0) cardIndex = hit.index;
  pickCardPart(hit.index < 0 ? null : hit.part);
  placeCardBar();
});
/* What a click would go into: the part under the pointer lights up in every card. */
canvas.on('mouse:move', opt => {
  const l = activeCardLayer();
  if (!l || cardDrag || vignetteDrag) return hoverCardPart(null);
  const over = opt.target?.masterId === l.id ? cardPartAt(l, canvas.getScenePoint(opt.e)) : null;
  hoverCardPart(over && over.index >= 0 && over.part !== cardPart ? over.part : null);
});
canvas.on('mouse:out', () => hoverCardPart(null));
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
  placeCardBar();
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
  const state = key => (cardPart === key ? ' active' : cardHover === key ? ' hover' : '');
  found.cards.forEach((card, index) => {
    const own = card.lead ? 'lead' : 'photo';
    if (cardPart === own || cardHover === own)
      html += `<div class="card-part photo${state(own)}" style="${box(shift(card.photo))}"></div>`;
    for (const key of ['name', 'detail'])
      if (card[key])
        html += `<div class="card-part ${key}${state(key)}${lifted?.part === key ? ' lifted' : ''}" data-card-part="${key}" data-card="${index}" style="${box(shift(card[key]))}"></div>`;
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
  host.addEventListener('pointerover', e => {
    const key = e.target.closest('[data-card-part]')?.dataset.cardPart;
    if (key && !cardDrag) hoverCardPart(key === cardPart ? null : key);
  });
  host.addEventListener('pointerout', e => {
    if (e.target.closest('[data-card-part]') && !e.relatedTarget?.closest?.('[data-card-part]')) hoverCardPart(null);
  });
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
/* The bar over a vignette photo, like the bar over a plain photo: small buttons that open small menus — the shape of the
   photo and the width it may take. Over the class teacher only his own shape. It is drawn once and then only updated,
   so a width being dragged keeps its field; while a menu is open it stays where it opened. */
let cardBarMenu = null;
const ratioName = r => PHOTO_RATIOS.find(([value]) => Math.abs(value - r) < 1e-3)?.[1] || '3:4';
function ratioIcon(r) {
  const h = 12,
    w = Math.min(14, h * r),
    hh = w < h * r ? w / r : h;
  return `<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="${(16 - w) / 2}" y="${(16 - hh) / 2}" width="${w}" height="${hh}" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.4"/></svg>`;
}
const widthIcon =
  '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 8h12M4.5 5.5 2 8l2.5 2.5M11.5 5.5 14 8l-2.5 2.5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';
function cardBarRatioKey() {
  return cardPart === 'lead' ? 'leadRatio' : 'photoRatio';
}
function widthLabel(l) {
  return `${round(l.minPhotoWidth ?? 32)}–${round(l.photoWidth ?? 85)}`;
}
function cardBarHtml(l) {
  const key = cardBarRatioKey(),
    ratio = Number(l[key]) || 0.75,
    lead = cardPart === 'lead',
    field = (k, value, label) =>
      `<div class="type-field"><span class="type-label">${label}</span><div class="type-value type-value-suffixed" data-scrub="${k}" data-min="5" data-max="180" data-step="0.5" title="${label}: потяните влево или вправо"><span class="type-inline-scrub" aria-hidden="true">${widthIcon}</span><input data-live="${k}" type="number" min="5" max="180" step="0.5" value="${round(value)}" aria-label="Ширина фото ${label}"><span class="type-suffix">мм</span></div></div>`,
    menu =
      cardBarMenu === 'ratio'
        ? `<div class="cell-sources card-bar-menu" role="menu"><p class="menu-label">${lead ? 'Портрет руководителя' : 'Пропорции фото'}</p>${PHOTO_RATIOS.map(
            ([value, name]) =>
              `<button type="button" class="menu-row${Math.abs(ratio - value) < 1e-3 ? ' on' : ''}" role="menuitemradio" aria-checked="${Math.abs(ratio - value) < 1e-3}" data-bar-ratio="${value}"><i class="ratio-glyph">${ratioIcon(value)}</i><span>${name}</span>${Math.abs(ratio - value) < 1e-3 ? cellGlyph.tick : ''}</button>`,
          ).join('')}</div>`
        : cardBarMenu === 'width'
          ? `<div class="cell-sources card-bar-menu card-width-menu" role="menu"><p class="menu-label">Ширина фото</p><div class="card-width-fields">${field('minPhotoWidth', l.minPhotoWidth ?? 32, 'от')}${field('photoWidth', l.photoWidth ?? 85, 'до')}</div><p class="card-bar-note" aria-live="polite"></p></div>`
          : '';
  return (
    `<div class="cell-bar card-bar" role="toolbar" aria-label="${lead ? 'Классный руководитель' : 'Фото виньетки'}">` +
    `<button type="button" class="card-bar-btn" data-bar-menu="ratio" aria-haspopup="menu" aria-expanded="${cardBarMenu === 'ratio'}" title="${lead ? 'Пропорции портрета руководителя' : 'Пропорции фото'}">${ratioIcon(ratio)}<span>${ratioName(ratio)}</span>${cellGlyph.caret}</button>` +
    (lead
      ? ''
      : `<button type="button" class="card-bar-btn" data-bar-menu="width" aria-haspopup="menu" aria-expanded="${cardBarMenu === 'width'}" title="Ширина фото, мм">${widthIcon}<span class="card-bar-width">${widthLabel(l)}</span>${cellGlyph.caret}</button>`) +
    menu +
    `</div>`
  );
}
/* Under the width: with «от» or «до» in hand, how many cards the page takes and how wide their photos really get. */
function cardBarNote(l) {
  const fits = cardsRange().fits;
  if (!widthPreview) return `влезает до ${shownFits(l)}`;
  const n = widthPreviewCount(l, widthPreview),
    geo = planner.gridGeometry(n, l);
  return [
    plural(n, 'карточка', 'карточки', 'карточек'),
    geo && `фото ${round(geo.photoW)} мм`,
    widthPreview === 'minPhotoWidth' && n > fits && `в блоке до ${fits}`,
  ]
    .filter(Boolean)
    .join(' · ');
}
function placeCardBar() {
  const host = $('#card-bar-ui');
  if (!host || !canvas) return;
  const l = (cardPart === 'photo' || cardPart === 'lead') && !cardDrag ? activeCardLayer() : null,
    found = l && vignetteCards(l),
    card =
      found &&
      (cardPart === 'lead'
        ? found.cards.find(c => c.lead)
        : found.cards.filter(c => !c.lead)[Math.min(cardIndex, found.cards.filter(c => !c.lead).length - 1)]);
  if (!card) {
    host.hidden = true;
    host.innerHTML = '';
    cardBarMenu = null;
    return;
  }
  const ox = layerOffset(l, found.obj.side) + l.box.x,
    oy = l.box.y,
    a = sceneToHost(ox + card.photo.x, oy + card.photo.y),
    z = sceneToHost(ox + card.photo.x + card.photo.w, oy + card.photo.y + card.photo.h),
    key = `${l.id}/${cardPart}/${cardBarMenu || ''}`;
  let bar = host.querySelector('.card-bar');
  const fresh = !bar || host.dataset.key !== key;
  if (fresh) {
    const keep = bar && host.dataset.layer === l.id && cardBarMenu ? { top: bar.style.top, left: bar.style.left, below: bar.classList.contains('below') } : null;
    host.innerHTML = cardBarHtml(l);
    host.dataset.key = key;
    host.dataset.layer = l.id;
    bar = host.querySelector('.card-bar');
    /* A menu opens where the bar stands; it does not jump to the photo the cards moved to. */
    if (keep?.top) {
      bar.style.top = keep.top;
      bar.style.left = keep.left;
      bar.classList.toggle('below', keep.below);
    }
  } else {
    const ratio = Number(l[cardBarRatioKey()]) || 0.75,
      label = bar.querySelector('[data-bar-menu="ratio"] span'),
      width = bar.querySelector('.card-bar-width');
    if (label) label.textContent = ratioName(ratio);
    if (width) width.textContent = widthLabel(l);
    for (const input of bar.querySelectorAll('input[data-live]'))
      if (input !== document.activeElement && !input.closest('.scrubbing'))
        input.value = String(round(l[input.dataset.live] ?? (input.dataset.live === 'photoWidth' ? 85 : 32)));
  }
  host.hidden = false;
  const note = bar.querySelector('.card-bar-note');
  if (note) note.textContent = cardBarNote(l);
  /* While a menu is open or a width shows its page the cards move; the bar stays put under the pointer. */
  if ((cardBarMenu || widthPreview) && bar.style.top) return placeBar(host);
  const above = a.y - 56 >= 8;
  bar.classList.toggle('below', !above);
  bar.style.top = (above ? a.y - 10 : z.y + 10) + 'px';
  bar.style.left = (a.x + z.x) / 2 + 'px';
  placeBar(host);
}
function toggleCardBarMenu(menu) {
  cardBarMenu = cardBarMenu === menu ? null : menu;
  placeCardBar();
}
{
  const host = $('#card-bar-ui');
  host.addEventListener('input', e => {
    const el = e.target;
    if (!el.dataset?.live || el.value === '' || !el.validity.valid) return;
    vignetteLive(el.dataset.live, Number(el.value), el);
    syncLiveInputs(el);
  });
  host.addEventListener('change', () => {
    if (slide) finishSlide();
  });
  host.addEventListener('click', e => {
    const open = e.target.closest('[data-bar-menu]');
    if (open) return toggleCardBarMenu(open.dataset.barMenu);
    const ratio = e.target.closest('[data-bar-ratio]');
    if (ratio) {
      cardBarMenu = null;
      property(cardBarRatioKey(), Number(ratio.dataset.barRatio));
    }
  });
  host.addEventListener('keydown', e => {
    if (e.key === 'Escape' && cardBarMenu) {
      toggleCardBarMenu(cardBarMenu);
      return e.stopPropagation();
    }
    if (e.key === 'Enter') e.target.blur?.();
    e.stopPropagation();
  });
  /* A click anywhere else closes the menu. */
  document.addEventListener(
    'pointerdown',
    e => {
      if (cardBarMenu && !e.target.closest('#card-bar-ui')) toggleCardBarMenu(cardBarMenu);
    },
    true,
  );
}
/* A value set in one place shows in its twins: the panel and the bar over the photo. */
function syncLiveInputs(source) {
  const l = selectedLayer();
  if (!l) return;
  for (const input of $$('input[data-live$="hotoWidth"]'))
    if (input !== source && input !== document.activeElement) {
      const key = input.dataset.live;
      input.value = String(round(l[key] ?? (key === 'photoWidth' ? 85 : 32)));
      if (input.style.width && !input.closest('.card-bar')) input.style.width = Math.max(1, input.value.length) + 'ch';
    }
}
/* «Карточки» on the vignette level: how many go on a page and the gap between them. */
function cardsSection(l) {
  const { low, high, fits } = cardsRange();
  return (
    `<section class="inspector-section typography-section card-section"><h3>Карточки</h3>` +
    `<div class="card-group"><p class="card-sub">На странице <span class="vignette-fits">влезает до ${shownFits(l)}</span></p>` +
    `<div class="type-metrics vignette-cells vignette-limits">${vignetteCell('От', 'min', low, fits, '≥', { attr: 'data-list', step: 1 })}${vignetteCell('До', 'max', blockList(section()).max < 100 ? high : '', fits, '≤', { attr: 'data-list', step: 1, placeholder: fits })}</div></div>` +
    `<div class="card-group"><div class="type-metrics">${vignetteGapField(l, 'gap')}</div></div>` +
    `</section>`
  );
}
const CARD_PART_GLYPHS = {
  photo: '<rect x="4" y="2.5" width="12" height="15" rx="1.5"/><circle cx="10" cy="8" r="2.4"/><path d="M6 15.5c.8-2.4 2.2-3.5 4-3.5s3.2 1.1 4 3.5"/>',
  name: '<path d="M4 7h12M6 11h8"/>',
  detail: '<path d="M5 8h10M7 11.5h6" stroke-dasharray="1.6 1.8"/>',
  lead: '<rect x="3" y="2" width="14" height="16" rx="1.5"/><circle cx="10" cy="8" r="2.6"/><path d="M6 15.5c.9-2.6 2.3-3.7 4-3.7s3.1 1.1 4 3.7"/>',
};
function cardPartName(l, part) {
  return part === 'photo' ? 'Фото' : part === 'name' ? 'Имя' : part === 'lead' ? 'Руководитель' : vignetteDetailName(l);
}
/* The class teacher has a card of his own only as «Крупнее» in a block kept to its spreads. */
function leadShown(l) {
  return l.lead === 'big' && blockList(section()).source === 'teachers' && spreadsFill();
}
function cardPartList(l) {
  return ['photo', 'name', 'detail'].concat(leadShown(l) ? ['lead'] : []);
}
/* «Классный руководитель»: whether he stands out, and the shape of his portrait, his own whatever the cards have. */
function leadSection(l) {
  const ratio = Number(l.leadRatio) || 0.75,
    segments = (key, items, value) =>
      `<div class="segments" role="radiogroup">${items.map(([id, name]) => `<button type="button" role="radio" data-choice="${key}" data-value="${id}" class="${String(value) === String(id) ? 'active' : ''}" aria-checked="${String(value) === String(id)}">${name}</button>`).join('')}</div>`;
  return (
    `<section class="inspector-section typography-section card-section"><h3>Классный руководитель</h3>` +
    `<div class="card-group">${segments('lead', [['card', 'Как все'], ['big', 'Крупнее']], l.lead || 'card')}</div>` +
    `<div class="card-group"><p class="card-sub">Пропорции портрета</p><div class="segments card-ratio" role="radiogroup" aria-label="Пропорции портрета руководителя">${PHOTO_RATIOS.map(([value, name]) => `<button type="button" role="radio" data-choice="leadRatio" data-value="${value}" class="${Math.abs(ratio - value) < 1e-3 ? 'active' : ''}" aria-checked="${Math.abs(ratio - value) < 1e-3}">${name}</button>`).join('')}</div></div>` +
    `</section>`
  );
}
function cardPartIcon(part) {
  return `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${CARD_PART_GLYPHS[part]}</svg>`;
}
/* The parts of a card on the vignette level: what each is set to now; a click goes into it, as a click on the canvas. */
function cardPartsSection(l) {
  const ratio = PHOTO_RATIOS.find(([value]) => Math.abs((Number(l.photoRatio) || 0.75) - value) < 1e-3)?.[1] || '3:4',
    zone = key => (CARD_ZONE_NAMES[l[key] || 'below'] || '').toLowerCase(),
    rows = [
      ['photo', `${ratio} · ${round(l.minPhotoWidth ?? 32)}–${round(l.photoWidth ?? 85)} мм`],
      ['name', `${zone('nameAt')} · ${round(l.minFontSize ?? l.fontSize)}–${round(l.fontSize)} pt`],
      ['detail', l.showDetail ? zone('detailAt') : 'нет'],
    ].concat(leadShown(l) ? [['lead', `крупнее · ${ratioName(Number(l.leadRatio) || 0.75)}`]] : []);
  return (
    `<section class="inspector-section typography-section card-section"><h3>В карточке</h3><div class="card-parts">` +
    rows
      .map(
        ([part, note]) =>
          `<button type="button" class="card-part-link" data-card-pick="${part}" data-card-hover="${part}"><span class="card-part-icon">${cardPartIcon(part)}</span><span class="card-part-copy"><strong>${cardPartName(l, part)}</strong><small>${esc(note)}</small></span><svg class="vignette-list-go" viewBox="0 0 8 12" aria-hidden="true"><path d="M2 2l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg></button>`,
      )
      .join('') +
    `</div></section>`
  );
}
/* Inside a part: back to the vignette, and the other parts one click away. */
function cardNav(l) {
  return `<div class="card-nav"><button type="button" class="card-back" data-card-pick="" title="К виньетке · Esc"><svg viewBox="0 0 8 12" aria-hidden="true"><path d="M6 2 2 6l4 4" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>Виньетка</button><div class="segments card-tabs" role="tablist" aria-label="Часть карточки">${cardPartList(l)
    .map(
      part =>
        `<button type="button" role="tab" data-card-pick="${part}" class="${cardPart === part ? 'active' : ''}" aria-selected="${cardPart === part}">${cardPartName(l, part)}</button>`,
    )
    .join('')}</div></div>`;
}
/* «Фото» inside the card: its shape, the width it may take, corners and look. */
function photoSection(l) {
  const ratio = Number(l.photoRatio) || 0.75,
    mm = { suffix: 'мм' };
  return (
    `<section class="inspector-section typography-section card-section"><h3>Фото</h3>` +
    `<div class="card-group"><p class="card-sub">Пропорции</p><div class="segments card-ratio" role="radiogroup" aria-label="Пропорции фото">${PHOTO_RATIOS.map(([value, name]) => `<button type="button" role="radio" data-choice="photoRatio" data-value="${value}" class="${Math.abs(ratio - value) < 1e-3 ? 'active' : ''}" aria-checked="${Math.abs(ratio - value) < 1e-3}">${name}</button>`).join('')}</div></div>` +
    `<div class="card-group"><div class="type-metrics">${vignetteCell('Ширина от', 'minPhotoWidth', round(l.minPhotoWidth ?? 32), 180, '↔', { ...mm, min: 5 })}${vignetteCell('до', 'photoWidth', round(l.photoWidth ?? 85), 180, '↔', { ...mm, min: 5 })}${vignetteCell('Скругление', 'radius', l.radius || 0, 100, '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><path d="M4 16V10a6 6 0 0 1 6-6h6"/></svg>', { ...mm, min: 0 })}</div></div>` +
    lookGroup('photo', effectControls(l), [strokeOpen(l) && 'обводка', l.shadow && 'тень'].filter(Boolean)) +
    `</section>`
  );
}
/* Pinned to the panel foot on every level: the page the canvas shows, how many fit and what stops more. */
function vignetteDock(l) {
  const { low, high, fits, shown } = cardsRange(),
    limiter = cardsLimiter();
  return (
    `<div class="vignette-dock">` +
    `<label class="vignette-shown"><span>Показать <b class="vignette-shown-value">${shown}</b></span><input type="range" data-cards-shown min="${low}" max="${high}" step="1" value="${shown}"${low === high ? ' disabled' : ''} aria-label="Сколько карточек показать на странице"></label>` +
    `<div class="vignette-status" role="status">${vignetteStatusText(fits, nameFontInfo(l))}</div>` +
    `<button type="button" class="vignette-limiter cards-limiter" data-limiter="${limiter?.key || ''}" title="Уменьшите, чтобы влезло больше"${limiter ? '' : ' hidden'}>${limiter ? `мешает ${limiter.label}` : ''}</button>` +
    `</div>`
  );
}
/* The whole vignette panel for the level the designer is on. */
function vignettePanel(l, place) {
  const body =
    cardPart === 'lead'
      ? cardNav(l) + leadSection(l)
      : cardPart === 'photo'
      ? cardNav(l) + photoSection(l)
      : cardPart === 'name' || cardPart === 'detail'
        ? cardNav(l) + captionsSection(l)
        : place + vignetteSection(l) + cardsSection(l) + cardPartsSection(l);
  return body + vignetteDock(l);
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
  label.textContent = `влезает до ${shownFits(l)}`;
  setLimiterHint($('#inspector .cards-limiter'), cardsLimiter());
  setLimiterHint($('#inspector .name-size-limiter'), font.limiter, font.limiter ? `на холсте ${round(font.size)} pt` : '');
  const status = $('#inspector .vignette-status');
  if (status) status.innerHTML = vignetteStatusText(fits, font);
  const note = $('#card-bar-ui .card-bar-note');
  if (note) note.textContent = cardBarNote(l);
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
  let n = previewCount(),
    base = l;
  /* In a block kept to its spreads the page holds its own share of the list, laid out as the block does. */
  if (spreadsFill() && !widthPreview) {
    const template = section().spreads.flatMap(sp => sp.pages).find(p => p.layers.includes(l)),
      page = template && previewPage(template, {});
    if (page?.layoutCount) {
      n = page.layoutCount;
      base = planner.pageSettings(l, page);
    }
  }
  const source = l.source || 'students',
    people = MasterPlanner(doc, { ...view, [source]: n }).people(source),
    size = settings => {
      const geo = planner.gridGeometry(n, settings);
      return geo ? planner.nameFont(settings, geo, people).size : null;
    },
    now = size(base);
  if (now == null || now >= l.fontSize) return { size: now, limiter: null };
  const zone = l.nameAt || 'below',
    side = zone === 'left' || zone === 'right',
    grows = settings => (size(settings) ?? 0) > now,
    photo = { key: 'photoWidth', label: 'ширина фото' },
    count = { key: 'max', label: 'число карточек' };
  let limiter;
  if (side && grows({ ...base, captionWidth: (l.captionWidth ?? 40) + 30 }))
    limiter = { key: 'captionWidth', label: 'ширина подписи' };
  else if (grows({ ...base, photoWidth: (l.photoWidth ?? 85) + 40 })) limiter = side ? { ...photo, label: 'высота фото' } : photo;
  else limiter = count;
  return { size: now, limiter };
}
function vignetteStatusText(fits, font) {
  return `<span>${spreadsFill() ? 'блок принимает до' : 'влезает до'} <b>${fits}</b></span>${font.size == null ? '' : `<span>имя <b>${round(font.size)}</b> pt</span>`}`;
}
/* «Подписи»: the name and the subject (or quote), each with its place by the photo and its type. The name size is a
   range: names are set at «до» and shrink block-wide, down to «от», until the longest one fits two lines. */
function captionsSection(l) {
  const part = cardPart === 'detail' ? 'detail' : 'name',
    detailName = vignetteDetailName(l),
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
  return `<section class="inspector-section typography-section card-section"><h3>${cardPartName(l, part)}</h3>${body}</section>`;
}
/* The canvas shows each vignette page with a chosen number of cards, not a whole pretend class: what matters while
   designing is how a page looks at 4, 12 or 30 cards. The «Показать» slider picks it between the block's limits;
   while a limit is dragged, the page shows that limit. Names come from an endless test list. */
const shownCards = {};
let cardsPreview = 0;
function vignetteFits(list, sec = section()) {
  return planner.listCapacity({ ...sec, list: { ...list, max: 100 } });
}
/* A block kept to its own spreads takes the whole list on them: «Показать» is how many people the block gets. */
function spreadsFill(sec = section()) {
  return blockList(sec).fill === 'spreads' && !sec.continues;
}
/* How many cards this vignette itself takes: its own size, the block's «до», squeezed rows counted. */
function pageFits(l) {
  const most = blockList(section()).max;
  let n = 0;
  for (let i = 1; i <= 100; i++) {
    const geo = planner.gridGeometry(i, l);
    if (geo && i - Math.max(0, i - geo.cols * geo.rows) <= most) n = i;
  }
  return n;
}
/* What «влезает до» says for the vignette: its own page in a block kept to its spreads, else the tightest page. */
function shownFits(l = selectedLayer()) {
  return spreadsFill() && l?.type === 'grid' ? pageFits(l) : cardsRange().fits;
}
function spreadsCapacity(sec = section()) {
  const list = blockList(sec),
    grids = blockGrids(sec).map(g => ({ ...g, max: list.max }));
  return grids.length ? planner.fillCapacity(grids, list.source === 'teachers' && grids[0].lead === 'big', list.min) : 0;
}
function cardsRange(sec = section()) {
  const list = blockList(sec);
  if (spreadsFill(sec)) {
    const fits = spreadsCapacity(sec),
      high = Math.max(1, fits);
    return { low: 1, high, fits, shown: clamp(shownCards[sec.id] ?? high, 1, high), block: true };
  }
  const fits = vignetteFits(list, sec),
    high = Math.max(1, Math.min(list.max, fits)),
    low = Math.max(1, Math.min(list.min, high));
  return { low, high, fits, shown: clamp(shownCards[sec.id] ?? high, low, high) };
}
function previewPage(template, g) {
  const grid = template?.layers.find(l => l.type === 'grid');
  if (!grid) return g;
  const source = grid.source || 'students',
    n = previewCount();
  if (spreadsFill() && !widthPreview) {
    /* The pages share the list: the page shows its part of n people, as the block lays them out. */
    const run = MasterPlanner(doc, { ...view, [source]: n }),
      page = run.plan().find(p => p.sectionId === section().id)?.pages.find(p => p.templateId === template.id);
    return page || g;
  }
  const records = MasterPlanner(doc, { ...view, [source]: n }).people(source),
    geo = planner.gridGeometry(n, grid),
    font = geo ? planner.nameFont(grid, geo, records).size : grid.fontSize;
  return { templateId: template.id, records, layoutCount: n, source, actualFont: font };
}
/* While the photo width «от» or «до» is set, the page shows what it means: at «от» as many cards as fit with photos
   that small, at «до» as many as still get photos that wide. */
let widthPreview = null;
function widthPreviewCount(l, key) {
  const widest = Number(l.photoWidth ?? 85) - 0.05;
  let n = 0;
  for (let i = 1; i <= 100; i++) {
    const geo = planner.gridGeometry(i, l);
    if (geo && (key === 'minPhotoWidth' || geo.photoW >= widest)) n = i;
  }
  return Math.max(1, n);
}
function previewCount() {
  const l = selectedLayer();
  if (widthPreview && l?.type === 'grid') return widthPreviewCount(l, widthPreview);
  return cardsPreview || cardsRange().shown;
}
function showWidthPreview(key) {
  key = key || null;
  if (key === widthPreview) return;
  widthPreview = key;
  renderScene();
  refreshCardsFit();
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
  /* A part row of the panel lights that part up on the canvas. */
  inspector.addEventListener('pointerover', e => {
    const part = e.target.closest?.('[data-card-hover]')?.dataset.cardHover;
    if (part) hoverCardPart(part);
  });
  inspector.addEventListener('pointerout', e => {
    if (e.target.closest?.('[data-card-hover]') && !e.relatedTarget?.closest?.('[data-card-hover]')) hoverCardPart(null);
  });
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
  /* The photo width fields, in the panel or in the bar over the photo, show their page under the pointer and while set. */
  const widthKey = target => {
      const key = target?.closest?.('.type-value[data-scrub]')?.querySelector('input')?.dataset.live;
      return key === 'minPhotoWidth' || key === 'photoWidth' ? key : null;
    },
    widthBusy = () => widthKey(document.activeElement) || document.querySelector('.type-value.scrubbing input[data-live$="hotoWidth"]');
  document.addEventListener('pointerover', e => {
    const key = widthKey(e.target);
    if (key && selectedLayer()?.type === 'grid') showWidthPreview(key);
  });
  document.addEventListener('pointerout', e => {
    if (widthKey(e.target) && !widthKey(e.relatedTarget) && !widthBusy()) showWidthPreview(null);
  });
  document.addEventListener('focusin', e => {
    const key = widthKey(e.target);
    if (key && selectedLayer()?.type === 'grid') showWidthPreview(key);
  });
  document.addEventListener('focusout', e => {
    if (widthKey(e.target) && !widthKey(e.relatedTarget)) showWidthPreview(null);
  });
  addEventListener('pointerup', () =>
    setTimeout(() => {
      if (widthPreview && !widthBusy() && !widthKey(document.querySelector('.type-value:hover'))) showWidthPreview(null);
    }),
  );
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
