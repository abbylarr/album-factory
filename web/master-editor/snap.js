/* Master editor · Snapping guides and spacing handles. */
'use strict';
let snapMarks = [];
function sceneBounds(obj) {
  obj.setCoords();
  const r = obj.getBoundingRect(),
    left = r.left,
    top = r.top,
    width = r.width,
    height = r.height;
  return {
    left,
    top,
    right: left + width,
    bottom: top + height,
    width,
    height,
    cx: left + width / 2,
    cy: top + height / 2,
  };
}
function findCanvasObject(id) {
  const active = canvas.getActiveObject();
  if (active instanceof fabric.ActiveSelection) {
    const inner = active.getObjects().find(o => o.masterId === id);
    if (inner) return inner;
  }
  return canvas.getObjects().find(o => o.masterId === id) || null;
}
function movingIds(target) {
  const ids = new Set(),
    list = target instanceof fabric.ActiveSelection ? target.getObjects() : [target];
  for (const obj of list) if (obj?.masterId) ids.add(obj.masterId);
  return ids;
}
function snapTargets(skip) {
  const w = pageWidth(),
    h = pageHeight(),
    kind = safetyKind(),
    geo = safetyGeometry(kind, w, h, safetyValues(kind), spineGap()),
    xs = [],
    ys = [];
  const addX = (pos, kind, bounds) => {
    if (pos >= -2 && pos <= sheetWidth() + 2) xs.push({ pos, kind, bounds, axis: 'x' });
  };
  const addY = (pos, kind, bounds) => {
    if (pos >= -2 && pos <= h + 2) ys.push({ pos, kind, bounds, axis: 'y' });
  };
  const edges = (r, type) => {
    addX(r[0], type);
    addX(r[0] + r[2], type);
    addY(r[1], type);
    addY(r[1] + r[3], type);
  };
  for (let side = 0; side < 2; side++) {
    const x = sideX(side);
    addX(x, 'trim');
    addX(x + w, 'trim');
    addX(x + w / 2, 'center');
  }
  addY(0, 'trim');
  addY(h, 'trim');
  addY(h / 2, 'center');
  for (const r of geo.trims) {
    edges(r, 'bleed');
    if (kind === 'book') addX(r[0] + r[2] / 2, 'center');
  }
  geo.safes.forEach(r => edges(r, 'safe'));
  for (const r of geo.spines) {
    addX(r[0], 'spine');
    addX(r[0] + r[2], 'spine');
  }
  geo.gaps.forEach(x => addX(x, 'gap'));
  for (const obj of canvas.getObjects()) {
    if (!obj.masterId || skip.has(obj.masterId)) continue;
    const b = sceneBounds(obj);
    addX(b.left, 'object', b);
    addX(b.cx, 'object', b);
    addX(b.right, 'object', b);
    addY(b.top, 'object', b);
    addY(b.cy, 'object', b);
    addY(b.bottom, 'object', b);
  }
  return { xs, ys };
}
const snapRank = { center: 0, safe: 1, bleed: 2, spine: 3, gap: 4, trim: 5, object: 6 };
function bestShift(edges, lines, threshold) {
  let best = null;
  for (const edge of edges)
    for (const line of lines) {
      const delta = line.pos - edge,
        abs = Math.abs(delta);
      if (abs > threshold) continue;
      const score = abs + (snapRank[line.kind] ?? 9) * 0.0001;
      if (!best || score < best.score) best = { delta, score };
    }
  return best ? best.delta : 0;
}
function guideSpan(axis, line, bounds) {
  const w = pageWidth(),
    h = pageHeight();
  if (line.kind === 'object' && line.bounds) {
    const other = line.bounds;
    if (axis === 'x')
      return { from: Math.min(bounds.top, other.top), to: Math.max(bounds.bottom, other.bottom) };
    return { from: Math.min(bounds.left, other.left), to: Math.max(bounds.right, other.right) };
  }
  if (axis === 'x') return { from: 0, to: h };
  const start = clamp(Math.floor(Math.min(bounds.left, bounds.right) / w), 0, 1),
    end = clamp(Math.floor(Math.max(bounds.left, bounds.right - 0.01) / w), 0, 1);
  return { from: start * w, to: (Math.max(start, end) + 1) * w };
}
function renderGuides() {
  const host = $('#guide-ui');
  if (!host) return;
  if (!snapMarks.length) {
    host.hidden = true;
    host.innerHTML = '';
    return;
  }
  const zoom = canvas.getZoom() || 1,
    pad = 12 / zoom;
  host.hidden = false;
  host.innerHTML = snapMarks
    .map(mark => {
      const from = mark.from - pad,
        to = mark.to + pad;
      if (mark.axis === 'x') {
        const a = sceneToHost(mark.pos, from),
          b = sceneToHost(mark.pos, to),
          top = Math.min(a.y, b.y);
        return `<i class="guide-line v" style="left:${Math.round(a.x)}px;top:${Math.round(top)}px;height:${Math.max(1, Math.round(Math.abs(b.y - a.y)))}px"></i>`;
      }
      const a = sceneToHost(from, mark.pos),
        b = sceneToHost(to, mark.pos),
        left = Math.min(a.x, b.x);
      return `<i class="guide-line h" style="left:${Math.round(left)}px;top:${Math.round(a.y)}px;width:${Math.max(1, Math.round(Math.abs(b.x - a.x)))}px"></i>`;
    })
    .join('');
}
function clearGuides() {
  snapMarks = [];
  const host = $('#guide-ui');
  if (host) {
    host.hidden = true;
    host.innerHTML = '';
  }
}
function paintMatch(bounds, xs, ys) {
  const eps = 0.2,
    marks = [];
  const take = (axis, lines, edges) => {
    for (const line of lines) {
      if (!edges.some(edge => Math.abs(edge - line.pos) <= eps)) continue;
      const span = guideSpan(axis, line, bounds),
        key = axis + ':' + Math.round(line.pos * 10),
        found = marks.find(m => m.key === key);
      if (found) {
        found.from = Math.min(found.from, span.from);
        found.to = Math.max(found.to, span.to);
      } else marks.push({ key, axis, pos: line.pos, from: span.from, to: span.to });
    }
  };
  take('x', xs, [bounds.left, bounds.cx, bounds.right]);
  take('y', ys, [bounds.top, bounds.cy, bounds.bottom]);
  snapMarks = marks;
  renderGuides();
}
function hideDragUi() {
  const ui = $('#collage-ui');
  if (ui) ui.hidden = true;
  const space = $('#space-ui');
  if (space) space.hidden = true;
}
function snapMove(target) {
  if (!target) return;
  const bounds = sceneBounds(target),
    lines = snapTargets(movingIds(target)),
    threshold = 6 / (canvas.getZoom() || 1);
  const dx = bestShift([bounds.left, bounds.cx, bounds.right], lines.xs, threshold),
    dy = bestShift([bounds.top, bounds.cy, bounds.bottom], lines.ys, threshold);
  if (dx || dy) {
    target.set({ left: target.left + dx, top: target.top + dy });
    target.setCoords();
  }
  paintMatch(dx || dy ? sceneBounds(target) : bounds, lines.xs, lines.ys);
}
function nearlyStraight(obj) {
  const angle = Math.abs(obj?.angle || 0) % 180;
  return angle < 0.8 || Math.abs(angle - 180) < 0.8;
}
function snapResize(target, corner, mode) {
  if (!target || !corner || corner === 'mtr' || !nearlyStraight(target)) {
    clearGuides();
    return;
  }
  const moveL = corner === 'ml' || corner === 'tl' || corner === 'bl',
    moveR = corner === 'mr' || corner === 'tr' || corner === 'br',
    moveT = corner === 'mt' || corner === 'tl' || corner === 'tr',
    moveB = corner === 'mb' || corner === 'bl' || corner === 'br';
  if (!moveL && !moveR && !moveT && !moveB) {
    clearGuides();
    return;
  }
  const bounds = sceneBounds(target),
    lines = snapTargets(movingIds(target)),
    threshold = 6 / (canvas.getZoom() || 1);
  let left = bounds.left,
    right = bounds.right,
    top = bounds.top,
    bottom = bounds.bottom,
    dx = 0,
    dy = 0;
  if (moveL && !moveR) {
    dx = bestShift([left], lines.xs, threshold);
    left += dx;
  } else if (moveR && !moveL) {
    dx = bestShift([right], lines.xs, threshold);
    right += dx;
  }
  if (moveT && !moveB) {
    dy = bestShift([top], lines.ys, threshold);
    top += dy;
  } else if (moveB && !moveT) {
    dy = bestShift([bottom], lines.ys, threshold);
    bottom += dy;
  }
  if (right - left < 1) {
    left = bounds.left;
    right = bounds.right;
    dx = 0;
  }
  if (bottom - top < 1) {
    top = bounds.top;
    bottom = bounds.bottom;
    dy = 0;
  }
  if (dx || dy) {
    const patch = {};
    if (dx) {
      const newW = right - left;
      if (mode === 'resize') patch.width = Math.max(newW / Math.abs(target.scaleX || 1), 1);
      else patch.scaleX = (target.scaleX || 1) * (newW / (bounds.width || 1));
      patch.left = target.left + ((left + right) / 2 - bounds.cx);
    }
    if (dy) {
      const newH = bottom - top;
      if (mode === 'resize') patch.height = Math.max(newH / Math.abs(target.scaleY || 1), 1);
      else patch.scaleY = (target.scaleY || 1) * (newH / (bounds.height || 1));
      patch.top = target.top + ((top + bottom) / 2 - bounds.cy);
    }
    target.set(patch);
    target.setCoords();
    target.dirty = true;
  }
  paintMatch(sceneBounds(target), lines.xs, lines.ys);
}
function onSnap(opt, mode) {
  if (spaceDrag) return;
  hideDragUi();
  if (opt.e?.altKey || (mode !== 'move' && opt.e?.shiftKey)) {
    clearGuides();
    return;
  }
  if (mode === 'move') snapMove(opt.target);
  else snapResize(opt.target, opt.transform?.corner || '', mode);
}
const hideVignetteUi = () => {
  const host = $('#vignette-ui');
  if (host && !host.hidden) {
    host.hidden = true;
    host.innerHTML = '';
  }
};
canvas.on('object:moving', opt => {
  hideVignetteUi();
  onSnap(opt, 'move');
});
canvas.on('object:scaling', opt => {
  hideVignetteUi();
  onSnap(opt, 'scale');
});
canvas.on('object:resizing', opt => {
  hideVignetteUi();
  onSnap(opt, 'resize');
});
/* Shift while rotating steps by 15°, so 45°, 90° and 180° are easy to hit. */
canvas.on('object:rotating', opt => {
  hideVignetteUi();
  hideDragUi();
  clearGuides();
  const target = opt.target;
  if (!opt.e?.shiftKey || !target) return;
  const angle = Math.round((target.angle || 0) / 15) * 15;
  if (angle !== target.angle) {
    target.rotate(angle);
    target.setCoords();
  }
});
function crossMid(a0, a1, b0, b1, fallback) {
  const from = Math.max(a0, b0),
    to = Math.min(a1, b1);
  return to > from ? (from + to) / 2 : fallback;
}
function layerSceneBox(layer) {
  const obj = findCanvasObject(layer.id);
  if (!obj) return null;
  const angle = Math.abs(layer.angle || obj.angle || 0) % 180;
  if (angle > 0.8 && Math.abs(angle - 180) > 0.8) {
    const b = sceneBounds(obj);
    b.layer = layer;
    b.obj = obj;
    return b;
  }
  const x = layerOffset(layer, obj.side || 0) + layer.box.x,
    y = layer.box.y,
    w = layerW(layer);
  return {
    left: x,
    top: y,
    right: x + w,
    bottom: y + layer.box.h,
    width: w,
    height: layer.box.h,
    cx: x + w / 2,
    cy: y + layer.box.h / 2,
    layer,
    obj,
  };
}
function relateBoxes(a, b, forceAxis) {
  const gapX = Math.max(a.left, b.left) - Math.min(a.right, b.right),
    gapY = Math.max(a.top, b.top) - Math.min(a.bottom, b.bottom),
    axis =
      forceAxis ||
      (gapX >= 0 && gapY < 0
        ? 'x'
        : gapY >= 0 && gapX < 0
          ? 'y'
          : Math.abs(a.cx - b.cx) >= Math.abs(a.cy - b.cy)
            ? 'x'
            : 'y');
  if (axis === 'x') {
    const left = a.cx <= b.cx ? a : b,
      right = left === a ? b : a;
    return {
      axis,
      gap: right.left - left.right,
      anchor: left,
      mover: right,
      mid: crossMid(left.top, left.bottom, right.top, right.bottom, (left.cy + right.cy) / 2),
    };
  }
  const top = a.cy <= b.cy ? a : b,
    bottom = top === a ? b : a;
  return {
    axis,
    gap: bottom.top - top.bottom,
    anchor: top,
    mover: bottom,
    mid: crossMid(top.left, top.right, bottom.left, bottom.right, (top.cx + bottom.cx) / 2),
  };
}
function objectPair(forceAxis) {
  if (preview || tool !== 'select' || selected.length !== 2) return null;
  const boxes = chosen()
    .filter(l => !l.hidden)
    .map(layerSceneBox)
    .filter(Boolean);
  if (boxes.length !== 2) return null;
  return relateBoxes(boxes[0], boxes[1], forceAxis);
}
function spaceScreen(rel) {
  const zoom = canvas.getZoom() || 1;
  let cx, cy;
  if (rel.axis === 'x') {
    cx = rel.anchor.right + rel.gap / 2;
    cy = rel.mid;
  } else {
    cx = rel.mid;
    cy = rel.anchor.bottom + rel.gap / 2;
  }
  const p = sceneToHost(cx, cy),
    along = Math.max(20, Math.min(32, Math.abs(rel.gap) * zoom || 20)),
    cross = 40;
  if (rel.axis === 'x') return { left: p.x - along / 2, top: p.y - cross / 2, width: along, height: cross };
  return { left: p.x - cross / 2, top: p.y - along / 2, width: cross, height: along };
}
function spaceHtml(rel) {
  const box = spaceScreen(rel),
    value = round(rel.gap),
    limit = rel.axis === 'x' ? pageWidth() : pageHeight();
  return `<div class="gap-hit ${rel.axis}" role="slider" tabindex="0" aria-label="Расстояние между объектами" aria-valuemin="${-limit}" aria-valuemax="${limit}" aria-valuenow="${value}" aria-valuetext="${value} мм" title="Перетащите или используйте стрелки · Shift — 10 мм" style="left:${box.left}px;top:${box.top}px;width:${box.width}px;height:${box.height}px"><i class="gap-tick"></i><b class="gap-badge">${value}</b></div>`;
}
function moveSpaceHandle() {
  const host = $('#space-ui'),
    rel = objectPair(spaceDrag?.axis),
    hit = host?.querySelector('.gap-hit');
  if (!host || !rel || !hit) return;
  const box = spaceScreen(rel),
    value = round(rel.gap);
  hit.style.left = box.left + 'px';
  hit.style.top = box.top + 'px';
  hit.style.width = box.width + 'px';
  hit.style.height = box.height + 'px';
  hit.classList.toggle('dragging', !!spaceDrag);
  const badge = hit.querySelector('.gap-badge');
  if (badge) badge.textContent = String(value);
  hit.setAttribute('aria-valuenow', String(value));
  hit.setAttribute('aria-valuetext', value + ' мм');
}
function placeSpaceUi() {
  const host = $('#space-ui');
  if (!host) return;
  if (spaceDrag) {
    host.hidden = false;
    moveSpaceHandle();
    return;
  }
  const rel = objectPair();
  if (!rel) {
    host.hidden = true;
    host.innerHTML = '';
    return;
  }
  host.hidden = false;
  host.innerHTML = spaceHtml(rel);
}
function syncLayerObject(layer) {
  const obj = findCanvasObject(layer.id);
  if (!obj || obj.group) return;
  obj.set({
    left: layerOffset(layer, obj.side || 0) + layer.box.x + layerW(layer) / 2,
    top: layer.box.y + layer.box.h / 2,
    dirty: true,
  });
  obj.setCoords();
}
function restorePairSelection() {
  const targets = selected.map(id => findCanvasObject(id)).filter(o => o && o.selectable);
  changing = true;
  if (targets.length === 1) canvas.setActiveObject(targets[0]);
  else if (targets.length > 1) canvas.setActiveObject(new fabric.ActiveSelection(targets, { canvas }));
  changing = false;
  canvas.requestRenderAll();
}
function bindSpaceUi() {
  const host = $('#space-ui');
  if (!host) return;
  host.addEventListener('pointerdown', e => {
    const hit = e.target.closest('.gap-hit');
    if (!hit || spaceDrag) return;
    const rel = objectPair();
    if (!rel) return;
    e.preventDefault();
    e.stopPropagation();
    let mover = rel.mover.layer,
      direction = 1;
    if (mover.locked && !rel.anchor.layer.locked) {
      mover = rel.anchor.layer;
      direction = -1;
    }
    if (mover.locked) return;
    spaceDrag = {
      axis: rel.axis,
      x: e.clientX,
      y: e.clientY,
      startGap: rel.gap,
      mover,
      direction,
      startPos: mover.box[rel.axis === 'x' ? 'x' : 'y'],
      startDoc: clone(doc),
      moved: false,
      engaged: false,
    };
    hit.classList.add('dragging');
    try {
      hit.setPointerCapture(e.pointerId);
    } catch (err) {}
    document.body.style.cursor = rel.axis === 'x' ? 'ew-resize' : 'ns-resize';
  });
  host.addEventListener('pointermove', e => {
    if (!spaceDrag) return;
    if (!spaceDrag.engaged) {
      if (Math.hypot(e.clientX - spaceDrag.x, e.clientY - spaceDrag.y) < 2) return;
      changing = true;
      canvas.discardActiveObject();
      spaceDrag.engaged = true;
    }
    const zoom = canvas.getZoom() || 1,
      delta = (spaceDrag.axis === 'x' ? e.clientX - spaceDrag.x : e.clientY - spaceDrag.y) / zoom,
      key = spaceDrag.axis === 'x' ? 'x' : 'y',
      size = spaceDrag.axis === 'x' ? 'w' : 'h',
      limit = spaceDrag.axis === 'x' ? pageWidth() : pageHeight();
    let pos = clamp(
      spaceDrag.startPos + spaceDrag.direction * delta,
      0,
      Math.max(0, limit - spaceDrag.mover.box[size]),
    );
    pos = round(pos);
    if (pos !== spaceDrag.mover.box[key]) {
      spaceDrag.mover.box[key] = pos;
      spaceDrag.moved = true;
      syncLayerObject(spaceDrag.mover);
      canvas.requestRenderAll();
    }
    moveSpaceHandle();
  });
  const endSpace = () => {
    if (!spaceDrag) return;
    const drag = spaceDrag;
    spaceDrag = null;
    document.body.style.cursor = '';
    changing = false;
    if (drag.moved) {
      history.push(drag.startDoc);
      if (history.length > 60) history.shift();
      future = [];
      markDirty();
      render();
    } else if (drag.engaged) {
      restorePairSelection();
      placeCollageUi();
    } else placeSpaceUi();
  };
  host.addEventListener('pointerup', endSpace);
  host.addEventListener('pointercancel', endSpace);
}
bindSpaceUi();
$('#space-ui').addEventListener('keydown', e => {
  const hit = e.target.closest('[role="slider"]');
  if (!hit) return;
  const axis = hit.classList.contains('x') ? 'x' : 'y',
    positive = axis === 'x' ? 'ArrowRight' : 'ArrowDown',
    negative = axis === 'x' ? 'ArrowLeft' : 'ArrowUp';
  if (e.key !== positive && e.key !== negative) return;
  e.preventDefault();
  e.stopPropagation();
  const rel = objectPair(axis);
  if (!rel) return;
  let mover = rel.mover.layer,
    direction = 1;
  if (mover.locked && !rel.anchor.layer.locked) {
    mover = rel.anchor.layer;
    direction = -1;
  }
  if (mover.locked) return;
  const key = axis === 'x' ? 'x' : 'y',
    size = axis === 'x' ? 'w' : 'h',
    limit = axis === 'x' ? pageWidth() : pageHeight(),
    step = (e.shiftKey ? 10 : 1) * (e.key === positive ? 1 : -1),
    next = round(clamp(mover.box[key] + direction * step, 0, Math.max(0, limit - mover.box[size])));
  if (next === mover.box[key]) return;
  const before = clone(doc);
  changing = true;
  canvas.discardActiveObject();
  mover.box[key] = next;
  syncLayerObject(mover);
  restorePairSelection();
  changing = false;
  history.push(before);
  if (history.length > 60) history.shift();
  future = [];
  markDirty();
  renderInspector();
  placeCollageUi();
  $('#space-ui [role="slider"]')?.focus();
});
