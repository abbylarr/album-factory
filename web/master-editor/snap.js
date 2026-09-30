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
const edgeBox = (left, top, right, bottom) => ({
  left,
  top,
  right,
  bottom,
  cx: (left + right) / 2,
  cy: (top + bottom) / 2,
});
/* What stays after trimming, in scene mm: one rectangle per printed page (on the cover — the back and the front). Snapping, alignment and edge distances use these, not the sheet with its bleed. */
function printedPages() {
  const w = pageWidth(),
    h = pageHeight(),
    s = spineGap(),
    kind = safetyKind(),
    geo = safetyGeometry(kind, w, h, safetyValues(kind), s);
  if (kind === 'book') return geo.trims.map(([x, y, rw, rh]) => edgeBox(x, y, x + rw, y + rh));
  const [x, y, rw, rh] = geo.trims[0] || [0, 0, 2 * w + s, h];
  return [edgeBox(x, y, w, y + rh), edgeBox(w + s, y, x + rw, y + rh)];
}
function spineBox() {
  const s = spineGap(),
    p = printedPages()[0];
  return s > 0 ? edgeBox(pageWidth(), p.top, pageWidth() + s, p.bottom) : null;
}
/* The printed page under scene x (or the nearest one); with `spine`, the cover spine counts as one too. */
function pageRectAt(x, spine = false) {
  const list = printedPages(),
    band = spine && spineBox();
  if (band) list.push(band);
  const gap = r => (x < r.left ? r.left - x : x > r.right ? x - r.right : 0);
  return list.reduce((best, r) => (gap(r) < gap(best) ? r : best));
}
/* Distances from a box to the edges of the printed page holding its centre: the nearer one on each axis (both when equal), or all four. */
function edgeMeasures(b, all = false) {
  const p = pageRectAt(b.cx),
    out = [],
    mid = (a0, a1, b0, b1) => (Math.max(a0, b0) + Math.min(a1, b1)) / 2,
    keep = pair => {
      const shown = pair.filter(m => m.value > 0.05);
      if (all || shown.length < 2 || Math.abs(shown[0].value - shown[1].value) < 0.05) return shown;
      return [shown[0].value < shown[1].value ? shown[0] : shown[1]];
    };
  if (b.bottom > p.top && b.top < p.bottom) {
    const at = mid(b.top, b.bottom, p.top, p.bottom);
    out.push(
      ...keep([
        { axis: 'x', from: p.left, to: b.left, at, value: b.left - p.left },
        { axis: 'x', from: b.right, to: p.right, at, value: p.right - b.right },
      ]),
    );
  }
  if (b.right > p.left && b.left < p.right) {
    const at = mid(b.left, b.right, p.left, p.right);
    out.push(
      ...keep([
        { axis: 'y', from: p.top, to: b.top, at, value: b.top - p.top },
        { axis: 'y', from: b.bottom, to: p.bottom, at, value: p.bottom - b.bottom },
      ]),
    );
  }
  return out.map(m => ({ ...m, type: 'measure' }));
}
/* Distances between two boxes: the gap when they are apart on an axis, the inner edge distances when one overlaps the other. */
function pairMeasures(a, b) {
  const out = [],
    axis = (name, lo, hi, crossLo, crossHi) => {
      const at = (Math.max(a[crossLo], b[crossLo]) + Math.min(a[crossHi], b[crossHi])) / 2;
      if (a[hi] <= b[lo]) out.push({ axis: name, from: a[hi], to: b[lo], at });
      else if (b[hi] <= a[lo]) out.push({ axis: name, from: b[hi], to: a[lo], at });
      else {
        out.push({ axis: name, from: Math.min(a[lo], b[lo]), to: Math.max(a[lo], b[lo]), at });
        out.push({ axis: name, from: Math.min(a[hi], b[hi]), to: Math.max(a[hi], b[hi]), at });
      }
    };
  axis('x', 'left', 'right', 'top', 'bottom');
  axis('y', 'top', 'bottom', 'left', 'right');
  return out
    .map(m => ({ ...m, value: m.to - m.from, type: 'measure' }))
    .filter(m => m.value > 0.05);
}
function snapTargets(skip, moving) {
  const w = pageWidth(),
    h = pageHeight(),
    kind = safetyKind(),
    geo = safetyGeometry(kind, w, h, safetyValues(kind), spineGap()),
    sheet = sheetWidth(),
    xs = [],
    ys = [];
  const addX = (pos, kind, extra) => {
    if (pos >= -2 && pos <= sheet + 2) xs.push({ pos, kind, ...extra });
  };
  const addY = (pos, kind, extra) => {
    if (pos >= -2 && pos <= h + 2) ys.push({ pos, kind, ...extra });
  };
  const pages = printedPages();
  for (const p of pages) {
    addX(p.left, 'trim');
    addX(p.right, 'trim');
    addX(p.cx, 'center');
    addY(p.top, 'trim');
    addY(p.bottom, 'trim');
    addY(p.cy, 'center');
  }
  const spine = spineBox();
  if (spine) addX(spine.cx, 'center');
  addX(0, 'sheet');
  addX(sheet, 'sheet');
  addY(0, 'sheet');
  addY(h, 'sheet');
  for (const r of geo.safes) {
    addX(r[0], 'safe');
    addX(r[0] + r[2], 'safe');
    addY(r[1], 'safe');
    addY(r[1] + r[3], 'safe');
  }
  for (const r of geo.spines) {
    addX(r[0], 'safe');
    addX(r[0] + r[2], 'safe');
  }
  geo.gaps.forEach(x => addX(x, 'safe'));
  const home = moving && pageRectAt(moving.cx);
  for (const obj of canvas.getObjects()) {
    if (!obj.masterId || skip.has(obj.masterId)) continue;
    const b = sceneBounds(obj);
    addX(b.left, 'object', { bounds: b });
    addX(b.cx, 'object', { bounds: b });
    addX(b.right, 'object', { bounds: b });
    addY(b.top, 'object', { bounds: b });
    addY(b.cy, 'object', { bounds: b });
    addY(b.bottom, 'object', { bounds: b });
    /* Equal margins: an edge distance of another object on the spread is offered to the moving one, on either side of its page. */
    if (!home || !nearlyStraight(obj)) continue;
    for (const m of edgeMeasures(b, true)) {
      if (m.value < 0.5 || m.value > 100) continue;
      const add = m.axis === 'x' ? addX : addY,
        [lo, hi] = m.axis === 'x' ? [home.left, home.right] : [home.top, home.bottom];
      add(lo + m.value, 'margin', { edge: 'min', ref: m });
      add(hi - m.value, 'margin', { edge: 'max', ref: m });
    }
  }
  return { xs, ys };
}
/* Reach in screen pixels and a small penalty: the trimmed page wins over the sheet and safety lines, those over other objects. */
const snapPolicy = {
  trim: [8, 0],
  center: [8, 0],
  sheet: [6, 1.5],
  safe: [6, 1.5],
  margin: [6, 2],
  object: [5, 2.5],
};
function edgesOf(b, axis) {
  return axis === 'x'
    ? [
        { pos: b.left, role: 'min' },
        { pos: b.cx, role: 'mid' },
        { pos: b.right, role: 'max' },
      ]
    : [
        { pos: b.top, role: 'min' },
        { pos: b.cy, role: 'mid' },
        { pos: b.bottom, role: 'max' },
      ];
}
function bestShift(edges, lines) {
  const zoom = canvas.getZoom() || 1;
  let best = null;
  for (const edge of edges)
    for (const line of lines) {
      if (line.edge && line.edge !== edge.role) continue;
      const [reach, penalty] = snapPolicy[line.kind] || [5, 3],
        px = Math.abs(line.pos - edge.pos) * zoom;
      if (px > reach) continue;
      const score = px + penalty;
      if (!best || score < best.score) best = { delta: line.pos - edge.pos, score, line };
    }
  return best;
}
function guideSpan(axis, line, bounds) {
  if (line.kind === 'object' && line.bounds) {
    const other = line.bounds;
    if (axis === 'x')
      return { from: Math.min(bounds.top, other.top), to: Math.max(bounds.bottom, other.bottom) };
    return { from: Math.min(bounds.left, other.left), to: Math.max(bounds.right, other.right) };
  }
  if (axis === 'x') return { from: 0, to: pageHeight() };
  const pages = printedPages().filter(p => p.right > bounds.left && p.left < bounds.right),
    list = pages.length ? pages : [pageRectAt(bounds.cx)];
  return { from: Math.min(...list.map(p => p.left)), to: Math.max(...list.map(p => p.right)) };
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
      if (mark.type === 'measure') {
        const x = mark.axis === 'x',
          a = x ? sceneToHost(mark.from, mark.at) : sceneToHost(mark.at, mark.from),
          b = x ? sceneToHost(mark.to, mark.at) : sceneToHost(mark.at, mark.to),
          length = Math.max(1, Math.round(x ? b.x - a.x : b.y - a.y)),
          line = x
            ? `<i class="guide-measure h" style="left:${Math.round(a.x)}px;top:${Math.round(a.y)}px;width:${length}px"></i>`
            : `<i class="guide-measure v" style="left:${Math.round(a.x)}px;top:${Math.round(a.y)}px;height:${length}px"></i>`;
        return `${line}<b class="guide-badge ${x ? 'h' : 'v'}" style="left:${Math.round((a.x + b.x) / 2)}px;top:${Math.round((a.y + b.y) / 2)}px">${mmLabel(mark.value)}</b>`;
      }
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
/* Guides for the lines the box now sits on, its distances to the page edges and, after an equal-margin snap, the margin it copied. */
function paintMatch(bounds, lines, used = []) {
  const eps = 0.2,
    marks = [];
  const take = (axis, list, edges) => {
    for (const line of list) {
      if (line.kind === 'margin' || !edges.some(edge => Math.abs(edge - line.pos) <= eps)) continue;
      const span = guideSpan(axis, line, bounds),
        key = axis + ':' + Math.round(line.pos * 10),
        found = marks.find(m => m.key === key);
      if (found) {
        found.from = Math.min(found.from, span.from);
        found.to = Math.max(found.to, span.to);
      } else marks.push({ key, axis, pos: line.pos, from: span.from, to: span.to });
    }
  };
  if (lines) {
    take('x', lines.xs, [bounds.left, bounds.cx, bounds.right]);
    take('y', lines.ys, [bounds.top, bounds.cy, bounds.bottom]);
  }
  const measures = edgeMeasures(bounds);
  for (const line of used)
    if (line?.kind === 'margin') {
      const same = edgeMeasures(bounds, true).find(
        m => m.axis === line.ref.axis && Math.abs(m.value - line.ref.value) < 0.05,
      );
      if (same) measures.push(same);
      measures.push({ ...line.ref, type: 'measure' });
    }
  const seen = new Set();
  snapMarks = marks.concat(
    measures.filter(m => {
      const key = [m.axis, m.from, m.to, m.at].map(v => (typeof v === 'number' ? v.toFixed(2) : v)).join();
      return !seen.has(key) && seen.add(key);
    }),
  );
  renderGuides();
}
function hideDragUi() {
  const ui = $('#collage-ui');
  if (ui) ui.hidden = true;
  const space = $('#space-ui');
  if (space) space.hidden = true;
}
function snapMove(target, free) {
  if (!target) return;
  const bounds = sceneBounds(target);
  if (free) {
    paintMatch(bounds, null);
    return;
  }
  const lines = snapTargets(movingIds(target), bounds),
    sx = bestShift(edgesOf(bounds, 'x'), lines.xs),
    sy = bestShift(edgesOf(bounds, 'y'), lines.ys),
    dx = sx?.delta || 0,
    dy = sy?.delta || 0;
  if (dx || dy) {
    target.set({ left: target.left + dx, top: target.top + dy });
    target.setCoords();
  }
  paintMatch(dx || dy ? sceneBounds(target) : bounds, lines, [sx?.line, sy?.line]);
}
function nearlyStraight(obj) {
  const angle = Math.abs(obj?.angle || 0) % 180;
  return angle < 0.8 || Math.abs(angle - 180) < 0.8;
}
function snapResize(target, corner, mode, free) {
  if (!target || !corner || corner === 'mtr') {
    clearGuides();
    return;
  }
  if (free || !nearlyStraight(target)) {
    paintMatch(sceneBounds(target), null);
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
    lines = snapTargets(movingIds(target), bounds),
    used = [];
  let left = bounds.left,
    right = bounds.right,
    top = bounds.top,
    bottom = bounds.bottom,
    dx = 0,
    dy = 0;
  const shift = (pos, role, list) => {
    const best = bestShift([{ pos, role }], list);
    if (best) used.push(best.line);
    return best?.delta || 0;
  };
  if (moveL && !moveR) {
    dx = shift(left, 'min', lines.xs);
    left += dx;
  } else if (moveR && !moveL) {
    dx = shift(right, 'max', lines.xs);
    right += dx;
  }
  if (moveT && !moveB) {
    dy = shift(top, 'min', lines.ys);
    top += dy;
  } else if (moveB && !moveT) {
    dy = shift(bottom, 'max', lines.ys);
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
  paintMatch(sceneBounds(target), lines, used);
}
/* Alt switches snapping off (Shift too while resizing) but distances to the page edges stay on screen. */
function onSnap(opt, mode) {
  if (spaceDrag) return;
  hideDragUi();
  const free = !!(opt.e?.altKey || (mode !== 'move' && opt.e?.shiftKey));
  if (mode === 'move') snapMove(opt.target, free);
  else snapResize(opt.target, opt.transform?.corner || '', mode, free);
}
/* Alt over the canvas measures the selection: to the page edges, or to the object under the cursor. */
let measureHover = null,
  altMeasuring = false;
function altMeasure(on, target = measureHover) {
  const active = canvas.getActiveObject();
  if (!on || !active || preview || tool !== 'select' || active.isEditing || press || canvas._currentTransform) {
    if (altMeasuring) {
      altMeasuring = false;
      clearGuides();
    }
    return;
  }
  const a = sceneBounds(active),
    other =
      target?.masterId && !movingIds(active).has(target.masterId) && canvas.getObjects().includes(target)
        ? sceneBounds(target)
        : null;
  altMeasuring = true;
  snapMarks = other ? pairMeasures(a, other) : edgeMeasures(a, true);
  renderGuides();
}
canvas.on('mouse:move', opt => {
  measureHover = opt.target || null;
  if (opt.e?.altKey || altMeasuring) altMeasure(!!opt.e?.altKey);
});
canvas.on('mouse:out', () => {
  measureHover = null;
});
document.addEventListener('keydown', e => {
  if (e.key === 'Alt' && !e.repeat && !e.target.closest?.('input,textarea,select,[contenteditable="true"]'))
    altMeasure(true);
});
document.addEventListener('keyup', e => {
  if (e.key === 'Alt') altMeasure(false);
});
window.addEventListener('blur', () => altMeasure(false));
const hideVignetteUi = () => {
  for (const host of [$('#vignette-ui'), $('#card-ui')])
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
