/* Master editor · On-canvas collage and vignette handles. */
'use strict';
function collageLayout(layer) {
  return CollageCore.layout(layer);
}
function collageFrames(layer) {
  return CollageCore.frames(layer);
}
function locateCell(layer, id) {
  return CollageCore.locate(layer, id);
}
/* The photo layer or focused collage frame the inspector's content panel edits. */
function contentTarget() {
  const l = selectedLayer();
  if (!l || selected.length !== 1) return null;
  return l.type === 'photo' ? l : l.type === 'collage' ? (l.flex ? l : focusedLeaf(l)) : null;
}
/* A selected photo layer gets the same source bar as a collage frame, minus splitting. */
function activePhoto() {
  if (preview || tool !== 'select' || selected.length !== 1 || photoCrop) return null;
  const l = selectedLayer();
  return l && l.type === 'photo' && !l.hidden ? l : null;
}
/* The frame the source bar and its menu edit: the selected photo or the focused collage frame. */
function barCell() {
  const l = selectedLayer();
  return l?.type === 'photo' ? l : l ? focusedLeaf(l) : null;
}
function focusedLeaf(layer) {
  const loc = locateCell(layer, focusCell);
  return loc && !loc.cell.split ? loc.cell : null;
}
/* Structural edits of the selected collage; call inside commit(). */
function collageAction(type) {
  const l = selectedLayer();
  if (!l || l.type !== 'collage') return;
  cellMenu = null;
  if (type === 'add-row') return CollageCore.addRow(l, uid);
  if (type === 'add-col') return CollageCore.addColumn(l, uid);
  if (type === 'split-h' || type === 'split-v') {
    const keep = CollageCore.split(l, focusCell, type.slice(-1), uid);
    if (keep) focusCell = keep;
    return;
  }
  if (type === 'remove') {
    if (CollageCore.remove(l, focusCell)) focusCell = null;
    return;
  }
  if (type === 'remove-row') {
    if (CollageCore.removeRow(l, focusCell)) focusCell = null;
  }
}
function activeCollage() {
  if (preview || tool !== 'select' || selected.length !== 1) return null;
  const l = selectedLayer();
  return l && l.type === 'collage' && !l.flex && !l.angle && !l.hidden ? l : null;
}
function collageOrigin(layer) {
  const obj = canvas.getObjects().find(o => o.masterId === layer.id);
  return { x: layerOffset(layer, obj ? obj.side : 0) + layer.box.x, y: layer.box.y };
}
function sceneToHost(x, y) {
  const v = canvas.viewportTransform;
  return { x: v[4] + x * v[0], y: v[5] + y * v[3] };
}
function frameScreen(origin, f) {
  const a = sceneToHost(origin.x + f.x, origin.y + f.y),
    b = sceneToHost(origin.x + f.x + f.w, origin.y + f.y + f.h);
  return { left: a.x, top: a.y, width: Math.max(b.x - a.x, 0), height: Math.max(b.y - a.y, 0) };
}
function boxStyle(r) {
  return `left:${r.left}px;top:${r.top}px;width:${r.width}px;height:${r.height}px`;
}
const mmLabel = v => String(Math.round(Number(v || 0) * 10) / 10).replace('.', ',') + ' мм';
function collageHit(layer, point) {
  const origin = collageOrigin(layer);
  return (
    collageFrames(layer).find(
      f =>
        point.x >= origin.x + f.x &&
        point.x <= origin.x + f.x + f.w &&
        point.y >= origin.y + f.y &&
        point.y <= origin.y + f.y + f.h,
    ) || null
  );
}
function gutterScreen(g, ox, oy, layer) {
  const a = sceneToHost(ox + g.x, oy + g.y),
    b = sceneToHost(ox + g.x + Math.max(g.w, 0), oy + g.y + Math.max(g.h, 0));
  let left = a.x,
    top = a.y,
    width = Math.max(b.x - a.x, 0),
    height = Math.max(b.y - a.y, 0);
  const min = 16,
    edge = 22,
    bounds = {
      left: sceneToHost(ox, oy).x,
      top: sceneToHost(ox, oy).y,
      right: sceneToHost(ox + layer.box.w, oy).x,
      bottom: sceneToHost(ox, oy + layer.box.h).y,
    };
  if (g.axis === 'x') {
    if (width < min) {
      left -= (min - width) / 2;
      width = min;
    }
    const limitTop = Math.max(top, bounds.top + edge),
      limitBottom = Math.min(top + height, bounds.bottom - edge);
    top = limitTop;
    height = Math.max(limitBottom - limitTop, 8);
  } else {
    if (height < min) {
      top -= (min - height) / 2;
      height = min;
    }
    const limitLeft = Math.max(left, bounds.left + edge),
      limitRight = Math.min(left + width, bounds.right - edge);
    left = limitLeft;
    width = Math.max(limitRight - limitLeft, 8);
  }
  return { left, top, width, height };
}
function moveGapHandles() {
  const l = gapDrag?.layer,
    host = $('#collage-ui');
  if (!l || !host) return;
  const origin = collageOrigin(l),
    { frames, gutters } = collageLayout(l);
  host.querySelectorAll('.gap-hit').forEach(el => {
    const g = gutters[Number(el.dataset.i)];
    if (!g) return;
    const box = gutterScreen(g, origin.x, origin.y, l);
    Object.assign(el.style, {
      left: box.left + 'px',
      top: box.top + 'px',
      width: box.width + 'px',
      height: box.height + 'px',
    });
    el.classList.toggle('dragging', el.dataset.i === gapDrag.index);
    const badge = el.querySelector('.gap-badge');
    if (badge) badge.textContent = mmLabel(g.axis === 'x' ? l.gapX : l.gapY);
  });
  const focus = host.querySelector('.cell-focus'),
    f = frames.find(fr => fr.cell.id === focusCell);
  if (focus && f) focus.setAttribute('style', boxStyle(frameScreen(origin, f)));
}
function syncCollageGaps(layer) {
  const obj = canvas.getObjects().find(o => o.masterId === layer.id);
  if (!obj?.getObjects || !gapDrag) return;
  const nowFrames = collageFrames(layer);
  let changed = false;
  for (const child of obj.getObjects()) {
    if (!child.collageId) continue;
    const was = gapDrag.frames.find(f => f.cell.id === child.collageId),
      now = nowFrames.find(f => f.cell.id === child.collageId);
    if (!was || !now || was.w < 0.2 || was.h < 0.2) continue;
    const left = child._gapLeft + (now.x - was.x),
      top = child._gapTop + (now.y - was.y);
    child.objectCaching = false;
    child.dirty = true;
    if (child.type === 'image') {
      child.left = left;
      child.top = top;
      child.scaleX = child._gapScaleX * (now.w / was.w);
      child.scaleY = child._gapScaleY * (now.h / was.h);
    } else {
      child.left = left;
      child.top = top;
      child.width = Math.max(child._gapWidth + (now.w - was.w), 0.2);
      child.height = Math.max(child._gapHeight + (now.h - was.h), 0.2);
    }
    changed = true;
  }
  if (changed) {
    obj.dirty = true;
    canvas.requestRenderAll();
  }
}
let gapFrame = 0;
function scheduleGapPaint() {
  if (gapFrame) return;
  gapFrame = requestAnimationFrame(() => {
    gapFrame = 0;
    if (!gapDrag) return;
    moveGapHandles();
    syncCollageGaps(gapDrag.layer);
  });
}
function framePreview(cell) {
  const sec = section(),
    plan = plans.find(p => p.sectionId === sec.id),
    page = sec.spreads[Math.min(view.spread, Math.max(sec.spreads.length - 1, 0))]?.pages[view.side],
    generated = plan?.pages.find(g => g.templateId === page?.id) || { personId: view.owner };
  return planner.resolvedPhoto(cell, generated);
}
/* What can fill a photo frame. Portraits come from the order, general photos from the class shoot. */
const portraitSources = [
  ['item', 'Герой разворота', 'Ученик, которому посвящён личный разворот'],
  ['owner', 'Владелец альбома', 'Ученик, чья это копия альбома'],
  ['lead', 'Классный руководитель', 'Портрет классного руководителя'],
];
const contentKinds = [
  ['class', 'Общее фото'],
  ['portrait', 'Портрет'],
  ['custom', 'Своё'],
];
function portraitChoices(current) {
  const repeat = section().kind === 'repeat';
  return portraitSources.filter(([id]) => id !== 'item' || repeat || current === 'item');
}
/* A new general-photo slot: on personal spreads it shows the hero by default. */
function defaultPick() {
  return section().kind === 'repeat' ? { category: 'any', who: 'hero' } : { category: 'any' };
}
function sourceLabel(item) {
  const source = item.source || 'class';
  if (source === 'custom') return 'Своё изображение';
  if (source === 'class') return MasterPhotos.category(doc, MasterPhotos.upgrade(item.pick)?.category).name;
  return portraitSources.find(([id]) => id === source)?.[1] || 'Фото';
}
const cellGlyph = {
  whole:
    '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M1.5 5V2.5a1 1 0 0 1 1-1H5M11 1.5h2.5a1 1 0 0 1 1 1V5M14.5 11v2.5a1 1 0 0 1-1 1H11M5 14.5H2.5a1 1 0 0 1-1-1V11" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><rect x="4.5" y="4.5" width="7" height="7" rx="1" fill="none" stroke="currentColor" stroke-width="1.4"/></svg>',
  h: '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="1.5" y="3" width="13" height="10" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M8 3v10" stroke="currentColor" stroke-width="1.4"/></svg>',
  v: '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="1.5" y="3" width="13" height="10" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M1.5 8h13" stroke="currentColor" stroke-width="1.4"/></svg>',
  remove:
    '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  crop: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 1.5v10h10M1.5 4.5h10v10" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  caret:
    '<svg class="caret" viewBox="0 0 10 10" aria-hidden="true"><path d="M2.5 4 5 6.5 7.5 4" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  tick: '<svg class="mark" viewBox="0 0 16 16" aria-hidden="true"><path d="M3.2 8.4 6.3 11.5 12.8 4.6" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  upload:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 16V4m0 0-4 4m4-4 4 4M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/></svg>',
};
function thumb(src) {
  return src ? `<img src="${esc(src)}" alt="">` : '<i class="thumb-empty"></i>';
}
/* Grouped list of what can fill the focused frame. */
function cellSourceMenu(cell) {
  const source = cell.source || 'class',
    pick = source === 'class' ? MasterPhotos.upgrade(cell.pick) || {} : defaultPick(),
    row = (attrs, on, body) =>
      `<button type="button" class="menu-row${on ? ' on' : ''}" role="menuitemradio" aria-checked="${on}" ${attrs}>${body}${on ? cellGlyph.tick : ''}</button>`;
  const hero =
    section().kind === 'repeat'
      ? `<button type="button" class="menu-toggle" role="menuitemcheckbox" aria-checked="${pick.who === 'hero'}" data-cell-who="${pick.who === 'hero' ? '' : 'hero'}"><span>С героем разворота</span><i class="switch" aria-hidden="true"></i></button>`
      : '';
  const cats = MasterPhotos.categoryRows(
    doc,
    source === 'class' ? pick.category || 'any' : null,
    'data-cell-category',
  );
  const people = portraitChoices(source)
    .map(([id, label]) =>
      row(
        `data-cell-source="${id}"`,
        source === id,
        `${thumb(framePreview({ source: id }))}<span>${label}</span>`,
      ),
    )
    .join('');
  const file = `<label class="menu-row${source === 'custom' ? ' on' : ''}">${cell.dataUrl ? thumb(cell.dataUrl) : `<i class="thumb-empty upload">${cellGlyph.upload}</i>`}<span>${cell.dataUrl ? 'Заменить файл' : 'Загрузить файл'}</span>${source === 'custom' ? cellGlyph.tick : ''}<input data-cell-file type="file" accept="image/jpeg,image/png,image/webp" hidden></label>`;
  return `<p class="menu-label">Общее фото</p>${hero}${cats}<p class="menu-label">Портрет</p>${people}<p class="menu-label">Своё изображение</p>${file}`;
}
/* Floating toolbar above the focused frame or selected photo: what is in it, split (collage only), crop, delete. */
function cellBar(l, f, origin) {
  const host = $('#canvas-host'),
    photo = l.type === 'photo';
  let r, cell, allowed;
  if (photo) {
    const b = findCanvasObject(l.id)?.getBoundingRect();
    if (!b) return '';
    const a = sceneToHost(b.left, b.top),
      z = sceneToHost(b.left + b.width, b.top + b.height);
    r = { left: a.x, top: a.y, width: z.x - a.x, height: z.y - a.y };
    cell = l;
    allowed = { split: false, remove: !l.locked };
  } else {
    r = frameScreen(origin, f);
    cell = f.cell;
    allowed = CollageCore.can(l, cell.id);
  }
  const above = r.top - 52 >= 8,
    top = above ? r.top - 10 : r.top + r.height + 10,
    left = r.left + r.width / 2,
    open = cellMenu === cell.id,
    src = cell.source === 'custom' ? cell.dataUrl : framePreview(cell);
  const crop =
    cell.source === 'custom' && cell.dataUrl
      ? `<button type="button" data-cell-crop title="Кадрировать · двойной клик" aria-label="Кадрировать">${cellGlyph.crop}</button>`
      : '';
  const lead = photo
      ? ''
      : `<button type="button" data-collage-whole title="Выделить весь коллаж · Esc" aria-label="Выделить весь коллаж">${cellGlyph.whole}</button><i class="bar-sep"></i>`,
    split = photo
      ? ''
      : `<i class="bar-sep"></i><button type="button" data-collage="split-h" title="Разделить по ширине" aria-label="Разделить по ширине"${allowed.split ? '' : ' disabled'}>${cellGlyph.h}</button><button type="button" data-collage="split-v" title="Разделить по высоте" aria-label="Разделить по высоте"${allowed.split ? '' : ' disabled'}>${cellGlyph.v}</button>`,
    remove = photo
      ? `<button type="button" class="danger" data-photo-remove title="Удалить изображение · Delete" aria-label="Удалить изображение"${allowed.remove ? '' : ' disabled'}>${cellGlyph.remove}</button>`
      : `<button type="button" class="danger" data-collage="remove" title="Удалить кадр · Delete" aria-label="Удалить кадр"${allowed.remove ? '' : ' disabled'}>${cellGlyph.remove}</button>`;
  return `<div class="cell-bar${above ? '' : ' below'}" style="left:${left}px;top:${top}px" role="toolbar" aria-label="${photo ? 'Изображение' : 'Кадр коллажа'}">${lead}<button type="button" class="cell-source" data-cell-sources aria-haspopup="menu" aria-expanded="${open}" title="Что в кадре">${thumb(src)}<span>${esc(sourceLabel(cell))}</span>${cellGlyph.caret}</button>${split}${photo ? '<i class="bar-sep"></i>' : ''}${crop}${remove}${open ? `<div class="cell-sources" role="menu">${cellSourceMenu(cell)}</div>` : ''}</div>`;
}
function placeCollageUi() {
  placeTextEditUi();
  placeSpaceUi();
  placeVignetteUi();
  const host = $('#collage-ui');
  if (!host || !canvas) return;
  if (gapDrag) {
    host.querySelector('.cell-bar')?.remove();
    moveGapHandles();
    return;
  }
  const pl = activePhoto();
  if (pl) {
    const bar = cellBar(pl);
    host.hidden = false;
    host.innerHTML = bar;
    placeBar(host);
    return;
  }
  const l = photoCrop ? null : activeCollage();
  if (!l) {
    host.hidden = true;
    host.innerHTML = '';
    return;
  }
  const origin = collageOrigin(l),
    { frames, gutters } = collageLayout(l),
    linked = CollageCore.gapsLinked(l);
  const gaps = gutters
    .map((g, i) => {
      const box = gutterScreen(g, origin.x, origin.y, l);
      return `<div class="gap-hit ${g.axis}" data-axis="${g.axis}" data-i="${i}" style="${boxStyle(box)}" title="${linked ? 'Зазор между кадрами' : g.axis === 'x' ? 'Зазор по ширине' : 'Зазор по высоте'}"><i class="gap-tick"></i><b class="gap-badge">${mmLabel(g.axis === 'x' ? l.gapX : l.gapY)}</b></div>`;
    })
    .join('');
  const focus = frames.find(f => f.cell.id === focusCell);
  if (!focus) {
    focusCell = null;
    cellMenu = null;
  }
  const boxA = sceneToHost(origin.x, origin.y),
    boxB = sceneToHost(origin.x + l.box.w, origin.y + l.box.h),
    plus = `<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M6 2.2v7.6M2.2 6h7.6" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>`,
    spanX = Math.max(boxB.x - boxA.x, 24),
    spanY = Math.max(boxB.y - boxA.y, 24),
    allowed = CollageCore.can(l, focusCell);
  const adds = `${allowed.addRow ? `<div class="collage-edge down" style="left:${boxA.x}px;top:${boxB.y + 14}px;width:${spanX}px"><button type="button" class="collage-add" data-collage="add-row" style="--span:${spanX}px" title="Добавить ряд" aria-label="Добавить ряд">${plus}</button></div>` : ''}${allowed.addColumn ? `<div class="collage-edge right" style="left:${boxB.x + 14}px;top:${boxA.y}px;height:${spanY}px"><button type="button" class="collage-add" data-collage="add-col" style="--span:${spanY}px" title="Добавить колонку" aria-label="Добавить колонку">${plus}</button></div>` : ''}`;
  host.hidden = false;
  host.innerHTML = `<div class="cell-hover" hidden></div>${gaps}${focus ? `<div class="cell-focus" style="${boxStyle(frameScreen(origin, focus))}"></div>` : ''}${adds}${focus ? cellBar(l, focus, origin) : ''}`;
  placeBar(host);
}
function placeBar(host) {
  const bar = host.querySelector('.cell-bar');
  if (bar) {
    const half = bar.offsetWidth / 2,
      center = parseFloat(bar.style.left);
    bar.style.left = clamp(center, half + 8, Math.max(half + 8, host.clientWidth - half - 8)) + 'px';
    const menu = bar.querySelector('.cell-sources');
    if (menu) {
      const hr = host.getBoundingClientRect(),
        br = bar.getBoundingClientRect();
      let mr = menu.getBoundingClientRect();
      if (mr.bottom > hr.bottom - 8 && br.top - hr.top > hr.bottom - br.bottom) {
        menu.classList.add('up');
        mr = menu.getBoundingClientRect();
      }
      if (mr.right > hr.right - 8)
        menu.style.left = Math.max(hr.left + 8 - br.left, hr.right - 8 - mr.right) + 'px';
      menu.style.maxHeight =
        Math.max(160, (menu.classList.contains('up') ? br.top - hr.top : hr.bottom - br.bottom) - 20) + 'px';
    }
  }
}
/* Thin outline under the pointer so it is clear which frame a click will pick. */
function hoverCollageCell(opt) {
  const host = $('#collage-ui'),
    hover = host?.querySelector('.cell-hover');
  if (!hover) return;
  const l = activeCollage();
  const f =
    l && !gapDrag && opt.target?.masterId === l.id ? collageHit(l, canvas.getScenePoint(opt.e)) : null;
  if (!f || f.cell.id === focusCell) {
    hover.hidden = true;
    return;
  }
  hover.hidden = false;
  hover.setAttribute('style', boxStyle(frameScreen(collageOrigin(l), f)));
}
function setCellSource(source, extra) {
  commit(() => {
    const cell = barCell();
    if (cell) CollageCore.setSource(cell, source, extra);
    cellMenu = null;
  });
}
function readImageFile(file, done) {
  if (!file) return;
  if (file.size > 1_000_000 || !['image/jpeg', 'image/png', 'image/webp'].includes(file.type))
    return notify('Выберите PNG, JPEG или WebP до 1 МБ', true);
  const reader = new FileReader();
  reader.onload = () => done(reader.result);
  reader.readAsDataURL(file);
}
function bindCollageUi() {
  const host = $('#collage-ui');
  host.addEventListener('pointerdown', e => {
    const hit = e.target.closest('.gap-hit');
    if (hit) {
      e.preventDefault();
      e.stopPropagation();
      const l = activeCollage();
      if (!l) return;
      const axis = hit.dataset.axis,
        obj = canvas.getObjects().find(o => o.masterId === l.id);
      obj?.getObjects?.().forEach(child => {
        child._gapLeft = child.left;
        child._gapTop = child.top;
        child._gapScaleX = child.scaleX || 1;
        child._gapScaleY = child.scaleY || 1;
        child._gapWidth = child.width;
        child._gapHeight = child.height;
      });
      gapDrag = {
        axis,
        index: hit.dataset.i,
        x: e.clientX,
        y: e.clientY,
        start: Number(axis === 'x' ? l.gapX : l.gapY) || 0,
        linked: CollageCore.gapsLinked(l),
        layer: l,
        startDoc: clone(doc),
        frames: collageFrames(l),
        moved: false,
      };
      cellMenu = null;
      hit.classList.add('dragging');
      try {
        hit.setPointerCapture(e.pointerId);
      } catch (err) {}
      document.body.style.cursor = axis === 'x' ? 'ew-resize' : 'ns-resize';
      placeCollageUi();
      return;
    }
    if (e.target.closest('.cell-bar,.collage-add') && !e.target.closest('input,label.menu-row'))
      e.preventDefault();
  });
  host.addEventListener('pointermove', e => {
    if (!gapDrag) return;
    const l = gapDrag.layer,
      zoom = canvas.getZoom() || 1,
      delta = (gapDrag.axis === 'x' ? e.clientX - gapDrag.x : e.clientY - gapDrag.y) / zoom,
      key = gapDrag.axis === 'x' ? 'gapX' : 'gapY',
      limit = CollageCore.maxGap(l, gapDrag.linked ? null : gapDrag.axis),
      next = Math.round(clamp(gapDrag.start + delta, 0, limit) * 10) / 10;
    if (Math.abs(next - (Number(l[key]) || 0)) < 0.05) return;
    if (gapDrag.linked) {
      l.gapX = next;
      l.gapY = next;
    } else l[key] = next;
    gapDrag.moved = true;
    scheduleGapPaint();
  });
  const endGap = () => {
    if (!gapDrag) return;
    if (gapFrame) {
      cancelAnimationFrame(gapFrame);
      gapFrame = 0;
    }
    const drag = gapDrag;
    gapDrag = null;
    document.body.style.cursor = '';
    if (drag.moved) {
      history.push(drag.startDoc);
      if (history.length > 60) history.shift();
      future = [];
      markDirty();
      render();
    } else placeCollageUi();
  };
  host.addEventListener('pointerup', endGap);
  host.addEventListener('pointercancel', endGap);
  host.addEventListener('change', e => {
    const input = e.target.closest('[data-cell-file]');
    if (input) readImageFile(input.files?.[0], dataUrl => setCellSource('custom', { dataUrl }));
  });
  host.addEventListener('click', e => {
    if (e.target.closest('[data-collage-whole]')) {
      e.stopPropagation();
      focusCell = null;
      cellMenu = null;
      renderInspector();
      placeCollageUi();
      return;
    }
    if (e.target.closest('[data-new-category]')) {
      e.stopPropagation();
      cellMenu = null;
      MasterPhotos.newCategory();
      return;
    }
    if (e.target.closest('[data-cell-sources]')) {
      e.stopPropagation();
      const id = barCell()?.id;
      cellMenu = cellMenu === id ? null : id;
      placeCollageUi();
      return;
    }
    const cat = e.target.closest('[data-cell-category]'),
      who = e.target.closest('[data-cell-who]');
    if (cat || who) {
      e.stopPropagation();
      const cell = barCell();
      if (!cell) return;
      const base =
          cell.source === 'class' ? MasterPhotos.upgrade(cell.pick) || { category: 'any' } : defaultPick(),
        pick = {
          ...base,
          ...(cat ? { category: cat.dataset.cellCategory } : { who: who.dataset.cellWho || undefined }),
        };
      if (!pick.who) delete pick.who;
      commit(() => {
        const target = barCell();
        if (target) CollageCore.setSource(target, 'class', { pick });
        if (cat) cellMenu = null;
      });
      return;
    }
    const src = e.target.closest('[data-cell-source]');
    if (src) {
      e.stopPropagation();
      setCellSource(src.dataset.cellSource);
      return;
    }
    if (e.target.closest('[data-cell-crop]')) {
      e.stopPropagation();
      const l = selectedLayer();
      startPhotoCrop(l, l?.type === 'collage' ? focusCell : null);
      return;
    }
    if (e.target.closest('[data-photo-remove]')) {
      e.stopPropagation();
      cellMenu = null;
      action('delete');
      return;
    }
    const act = e.target.closest('[data-collage]');
    if (!act || act.disabled) return;
    e.stopPropagation();
    commit(() => collageAction(act.dataset.collage));
  });
  document.addEventListener(
    'pointerdown',
    e => {
      if (!cellMenu || gapDrag || e.target.closest('.cell-bar')) return;
      cellMenu = null;
      placeCollageUi();
    },
    true,
  );
}
bindCollageUi();
/* Spacing handles on a selected vignette, same gesture as collage gaps: between cards, photo → name, name → caption. */
const vignetteGapMax = { gap: 30, photoNameGap: 20, nameDetailGap: 20 },
  vignetteGapDefault = { gap: 5, photoNameGap: 3, nameDetailGap: 2 };
let vignetteDrag = null,
  vignetteFrame = 0;
function vignetteGap(l, key) {
  return Number(l[key] ?? vignetteGapDefault[key]) || 0;
}
function vignetteGapLabel(l, key) {
  return key === 'gap'
    ? 'Между карточками'
    : key === 'photoNameGap'
      ? 'Фото — имя'
      : l.source === 'teachers'
        ? 'Имя — предмет'
        : 'Имя — цитата';
}
function activeVignette() {
  if (preview || tool !== 'select' || selected.length !== 1 || photoCrop) return null;
  const l = selectedLayer();
  return l && l.type === 'grid' && !l.angle && !l.hidden ? l : null;
}
function vignetteHandles(l) {
  const obj = canvas.getObjects().find(o => o.masterId === l.id),
    data = obj?.vignette;
  if (!data?.geo || !data.cards.length) return [];
  const { geo, cards } = data,
    ox = layerOffset(l, obj.side) + l.box.x,
    oy = l.box.y,
    gap = vignetteGap(l, 'gap'),
    cols = Math.min(geo.cols, cards.length),
    rows = Math.ceil(cards.length / geo.cols),
    left = cards[0].x,
    top = cards[0].y,
    right = left + cols * geo.cellW + (cols - 1) * gap,
    bottom = top + rows * geo.cellH + (rows - 1) * gap,
    out = [];
  for (let c = 1; c < cols; c++)
    out.push({
      key: 'gap',
      axis: 'x',
      x: ox + left + c * geo.cellW + (c - 1) * gap,
      y: oy + top,
      w: gap,
      h: bottom - top,
    });
  for (let r = 1; r < rows; r++)
    out.push({
      key: 'gap',
      axis: 'y',
      x: ox + left,
      y: oy + top + r * geo.cellH + (r - 1) * gap,
      w: right - left,
      h: gap,
    });
  return out;
}
/* Inside a card: the spacing of the main card only — photo to each caption place, name to the second caption. */
function cardHandles(l) {
  const obj = canvas.getObjects().find(o => o.masterId === l.id),
    card = obj?.vignette?.cards?.[0];
  if (!card) return [];
  const ox = layerOffset(l, obj.side) + l.box.x,
    oy = l.box.y,
    p = card.photo,
    gap = vignetteGap(l, 'photoNameGap'),
    pad = Math.min(gap, p.w / 4),
    out = [],
    seen = new Set();
  for (const text of [card.name, card.detail].filter(Boolean)) {
    if (seen.has(text.zone)) continue;
    seen.add(text.zone);
    const strip = {
      below: { axis: 'y', sign: 1, x: p.x, y: p.y + p.h, w: p.w, h: gap },
      above: { axis: 'y', sign: -1, x: p.x, y: p.y - gap, w: p.w, h: gap },
      left: { axis: 'x', sign: -1, x: p.x - gap, y: p.y, w: gap, h: p.h },
      right: { axis: 'x', sign: 1, x: p.x + p.w, y: p.y, w: gap, h: p.h },
      over: { axis: 'y', sign: -1, x: p.x, y: p.y + p.h - pad, w: p.w, h: pad },
    }[text.zone];
    out.push({ key: 'photoNameGap', ...strip, x: ox + strip.x, y: oy + strip.y });
  }
  if (card.detail && card.detail.zone === card.name.zone)
    out.push({
      key: 'nameDetailGap',
      axis: 'y',
      sign: card.name.zone === 'over' ? -1 : 1,
      x: ox + card.name.x,
      y: oy + card.name.y + card.name.h,
      w: card.name.w,
      h: vignetteGap(l, 'nameDetailGap'),
    });
  return out;
}
function vignetteHitBox(h) {
  const a = sceneToHost(h.x, h.y),
    b = sceneToHost(h.x + Math.max(h.w, 0), h.y + Math.max(h.h, 0)),
    min = h.key === 'gap' ? 14 : 10;
  let left = a.x,
    top = a.y,
    width = b.x - a.x,
    height = b.y - a.y;
  if (h.axis === 'x' && width < min) {
    left -= (min - width) / 2;
    width = min;
  }
  if (h.axis === 'y' && height < min) {
    top -= (min - height) / 2;
    height = min;
  }
  return { left, top, width, height };
}
function placeVignetteUi() {
  placeCardUi();
  const host = $('#vignette-ui');
  if (!host || !canvas) return;
  const l = activeVignette();
  if (!l) {
    host.hidden = true;
    host.innerHTML = '';
    return;
  }
  const drag = vignetteDrag,
    handles = cardLayer() ? cardHandles(l) : vignetteHandles(l),
    dragged = drag ? Math.min(drag.index, handles.length - 1) : -1;
  host.hidden = false;
  host.innerHTML = handles
    .map(
      (h, i) =>
        `<div class="gap-hit vignette-gap ${h.axis} ${h.key}${i === dragged ? ' dragging' : ''}" data-vignette-gap="${h.key}" data-axis="${h.axis}" data-sign="${h.sign || 1}" style="${boxStyle(vignetteHitBox(h))}" title="${vignetteGapLabel(l, h.key)}"><i class="gap-tick"></i><b class="gap-badge">${mmLabel(vignetteGap(l, h.key))}</b></div>`,
    )
    .join('');
}
function bindVignetteUi() {
  const host = $('#vignette-ui');
  host.addEventListener('pointerdown', e => {
    const hit = e.target.closest('[data-vignette-gap]'),
      l = activeVignette();
    if (!hit || !l || e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    const key = hit.dataset.vignetteGap,
      axis = hit.dataset.axis;
    vignetteDrag = {
      key,
      axis,
      sign: Number(hit.dataset.sign) || 1,
      index: [...host.children].indexOf(hit),
      x: e.clientX,
      y: e.clientY,
      start: vignetteGap(l, key),
      value: null,
    };
    hit.classList.add('dragging');
    document.body.style.cursor = axis === 'x' ? 'ew-resize' : 'ns-resize';
  });
  addEventListener('pointermove', e => {
    const drag = vignetteDrag;
    if (!drag) return;
    const delta = (drag.sign * (drag.axis === 'x' ? e.clientX - drag.x : e.clientY - drag.y)) / (canvas.getZoom() || 1),
      next = Math.round(clamp(drag.start + delta, 0, vignetteGapMax[drag.key]) * 2) / 2;
    if (next === (drag.value ?? drag.start)) return;
    drag.value = next;
    if (vignetteFrame) return;
    vignetteFrame = requestAnimationFrame(() => {
      vignetteFrame = 0;
      if (!vignetteDrag || vignetteDrag.value == null) return;
      vignetteLive(vignetteDrag.key, vignetteDrag.value);
      $$(`#inspector [data-live="${vignetteDrag.key}"]`).forEach(input => {
        input.value = String(vignetteDrag.value);
        input.style.width = Math.max(1, input.value.length) + 'ch';
      });
    });
  });
  const end = () => {
    if (!vignetteDrag) return;
    if (vignetteFrame) {
      cancelAnimationFrame(vignetteFrame);
      vignetteFrame = 0;
    }
    const drag = vignetteDrag;
    vignetteDrag = null;
    document.body.style.cursor = '';
    if (
      drag.value != null &&
      selectedLayer()?.type === 'grid' &&
      vignetteGap(selectedLayer(), drag.key) !== drag.value
    )
      vignetteLive(drag.key, drag.value);
    if (slide) finishSlide();
    else placeVignetteUi();
  };
  addEventListener('pointerup', end);
  addEventListener('pointercancel', end);
}
bindVignetteUi();
function reidentifyCollage(layer) {
  CollageCore.reidentify(layer, uid);
}
