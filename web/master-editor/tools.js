/* Master editor · Drawing tools, pointer events, layer actions and the object menu. */
'use strict';
const drawTools = new Set(['text', 'photo', 'shape', 'collage', 'grid']);
function dragBox(x1, y1, x2, y2, type, shift) {
  const side = sideAt(x1);
  x2 = clamp(x2, sideX(side), sideX(side) + pageWidth());
  y2 = clamp(y2, 0, pageHeight());
  let x = Math.min(x1, x2),
    y = Math.min(y1, y2),
    w = Math.abs(x2 - x1),
    h = Math.abs(y2 - y1);
  if (type === 'line') {
    if (Math.abs(x2 - x1) >= Math.abs(y2 - y1)) {
      x = Math.min(x1, x2);
      y = y1 - 0.5;
      w = Math.abs(x2 - x1);
      h = 1;
    } else {
      x = x1 - 0.5;
      y = Math.min(y1, y2);
      w = 1;
      h = Math.abs(y2 - y1);
    }
  } else if (type === 'svg' && pendingSvg && !shift) {
    const aspect = pendingSvg.aspect || 1;
    if (w < h * aspect) w = h * aspect;
    else h = w / aspect;
    x = x2 < x1 ? x1 - w : x1;
    y = y2 < y1 ? y1 - h : y1;
  } else if (shift) {
    const size = Math.max(w, h);
    w = h = size;
    x = x2 < x1 ? x1 - size : x1;
    y = y2 < y1 ? y1 - size : y1;
  }
  x -= sideX(side);
  x = clamp(x, 0, pageWidth());
  y = clamp(y, 0, pageHeight());
  w = clamp(w, 0, pageWidth() - x);
  h = clamp(h, 0, pageHeight() - y);
  return { x, y, w, h };
}
function cancelDraw() {
  draw = null;
  if (rubber) {
    canvas.remove(rubber);
    rubber = null;
    canvas.requestRenderAll();
  }
}
canvas.on('mouse:down', opt => {
  const e = opt.e;
  if (space || tool === 'hand') {
    pan = { x: e.clientX, y: e.clientY };
    canvas.selection = false;
    return;
  }
  if (preview || draw) return;
  const point = canvas.getScenePoint(e);
  if (point.x < 0 || point.x > sheetWidth() || point.y < 0 || point.y > pageHeight()) return;
  view.side = sideAt(point.x);
  if (drawTools.has(tool)) {
    const type = tool === 'shape' ? shapeKind : tool;
    if (type === 'svg' && !pendingSvg) {
      pickSvg();
      return;
    }
    draw = {
      type,
      x: point.x,
      y: point.y,
      box: dragBox(point.x, point.y, point.x, point.y, type, e.shiftKey),
    };
    rubber = new fabric.Rect({
      left: point.x,
      top: point.y,
      width: 0.4,
      height: 0.4,
      fill: 'rgba(119,18,179,.08)',
      stroke: '#7712b3',
      strokeWidth: 0.35,
      strokeDashArray: [1.4, 1],
      selectable: false,
      evented: false,
      objectCaching: false,
      rx: type === 'ellipse' ? 20 : 0,
      ry: type === 'ellipse' ? 20 : 0,
    });
    canvas.add(rubber);
    return;
  }
  if (tool !== 'select') return;
  if (opt.target?.masterId && inspectorTab !== 'design') {
    inspectorTab = 'design';
    if (selected.includes(opt.target.masterId)) renderInspector();
  }
  press = { x: e.clientX, y: e.clientY, id: opt.target?.masterId || '', at: performance.now() };
  if (!opt.target?.masterId && !(opt.target instanceof fabric.ActiveSelection)) {
    selected = [];
    focusCell = null;
    renderInspector();
  }
});
canvas.on('mouse:move', opt => {
  if (pan) {
    const v = canvas.viewportTransform;
    v[4] += opt.e.clientX - pan.x;
    v[5] += opt.e.clientY - pan.y;
    pan = { x: opt.e.clientX, y: opt.e.clientY };
    syncSelectionCoords();
    canvas.requestRenderAll();
    placeCollageUi();
    placePhotoCropUi();
    return;
  }
  if (!draw || !rubber) {
    hoverCollageCell(opt);
    return;
  }
  const point = canvas.getScenePoint(opt.e);
  draw.box = dragBox(draw.x, draw.y, point.x, point.y, draw.type, opt.e.shiftKey);
  const side = sideAt(draw.x);
  rubber.set({
    left: sideX(side) + draw.box.x,
    top: draw.box.y,
    width: Math.max(draw.box.w, 0.4),
    height: Math.max(draw.box.h, 0.4),
    rx: draw.type === 'ellipse' ? Math.max(draw.box.w, 0.4) / 2 : 0,
    ry: draw.type === 'ellipse' ? Math.max(draw.box.h, 0.4) / 2 : 0,
  });
  rubber.setCoords();
  canvas.requestRenderAll();
});
canvas.on('mouse:up', opt => {
  clearGuides();
  if (draw) {
    const d = draw;
    cancelDraw();
    const dragged = d.type === 'line' ? Math.max(d.box.w, d.box.h) >= 3 : d.box.w >= 3 && d.box.h >= 3;
    let box = d.box;
    if (!dragged) {
      const preset = {
        text: [72, 18],
        photo: [72, 96],
        rect: [56, 40],
        ellipse: [48, 48],
        line: [70, 1],
        collage: [140, 100],
        grid: [170, 200],
        svg: [46, 46],
      };
      let [w, h] = preset[d.type] || [60, 40];
      if (d.type === 'svg' && pendingSvg) {
        const aspect = pendingSvg.aspect || 1;
        w = 46;
        h = 46 / aspect;
        if (h > 72) {
          h = 72;
          w = 72 * aspect;
        }
        if (w > 90) {
          w = 90;
          h = 90 / aspect;
        }
      }
      const x = clamp(d.x - sideX(sideAt(d.x)), 0, pageWidth() - w),
        y = clamp(d.y, 0, pageHeight() - h);
      box = { x, y, w, h };
    } else if (opt.e.shiftKey && d.type === 'svg') box.free = true;
    addLayer(d.type, box);
    return;
  }
  if (pan) {
    pan = null;
    canvas.setViewportTransform(canvas.viewportTransform);
    syncSelectionCoords();
    canvas.selection = !preview && tool === 'select';
    placeCollageUi();
    return;
  }
  if (
    tool === 'select' &&
    press &&
    selectedAt < press.at &&
    Math.hypot(opt.e.clientX - press.x, opt.e.clientY - press.y) < 5 &&
    opt.target?.masterId &&
    selected.length === 1 &&
    selected[0] === opt.target.masterId
  ) {
    const l = allLayers().find(i => i.id === opt.target.masterId);
    if (l?.type === 'collage' && !l.flex && !opt.e.shiftKey && !l.angle) {
      const id = collageHit(l, canvas.getScenePoint(opt.e))?.cell.id || null;
      if (id !== focusCell) {
        focusCell = id;
        cellMenu = null;
        renderInspector();
      }
    }
  }
  clearGuides();
  placeCollageUi();
  press = null;
});
canvas.on('mouse:dblclick', opt => {
  const layer = allLayers().find(l => l.id === opt.target?.masterId);
  if (layer?.type === 'photo' && layer.source === 'custom' && layer.dataUrl) {
    opt.e.preventDefault();
    startPhotoCrop(layer);
    return;
  }
  if (layer?.type === 'collage' && activeCollage() === layer) {
    const f = collageHit(layer, canvas.getScenePoint(opt.e));
    if (!f) return;
    if (f.cell.id !== focusCell) {
      focusCell = f.cell.id;
      cellMenu = null;
      renderInspector();
      placeCollageUi();
    }
    if (f.cell.source === 'custom' && f.cell.dataUrl) {
      opt.e.preventDefault();
      startPhotoCrop(layer, f.cell.id);
    }
  }
});
let pinching = false;
/* Wheel pans; Ctrl/⌘ + wheel and a trackpad pinch (which arrives as Ctrl + wheel) zoom around the cursor in proportion to the delta. */
canvas.on('mouse:wheel', opt => {
  const e = opt.e;
  e.preventDefault();
  e.stopPropagation();
  cancelAnimationFrame(zoomAnimation);
  const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? $('#canvas-host').clientHeight : 1;
  let dx = e.deltaX * unit,
    dy = e.deltaY * unit;
  if (e.ctrlKey || e.metaKey) {
    if (pinching) return;
    zoomAt(canvas.getZoom() * Math.exp(-clamp(dy, -30, 30) * 0.01), { x: e.offsetX, y: e.offsetY });
    return;
  }
  if (e.shiftKey && !dx) {
    dx = dy;
    dy = 0;
  }
  const v = canvas.viewportTransform;
  v[4] -= dx;
  v[5] -= dy;
  canvas.setViewportTransform(v);
  viewportChanged();
});
/* Safari reports a trackpad pinch as gesture events instead of Ctrl + wheel. */
{
  const host = $('#canvas-host');
  let pinchStart = 0;
  host.addEventListener('gesturestart', e => {
    e.preventDefault();
    cancelAnimationFrame(zoomAnimation);
    pinching = true;
    pinchStart = canvas.getZoom();
  });
  host.addEventListener('gesturechange', e => {
    e.preventDefault();
    const r = host.getBoundingClientRect();
    zoomAt(pinchStart * e.scale, { x: e.clientX - r.left, y: e.clientY - r.top });
  });
  host.addEventListener('gestureend', e => {
    e.preventDefault();
    pinching = false;
  });
}
canvas.on('contextmenu', opt => {
  opt.e.preventDefault();
  openObjectMenu(opt.e, opt.target);
});
function closeToolPops() {
  ['pointer', 'frame', 'shape'].forEach(id => {
    const pop = $('#' + id + '-pop'),
      caret = $('#' + id + '-caret');
    if (pop) pop.hidden = true;
    if (caret) caret.setAttribute('aria-expanded', 'false');
  });
}
function toggleToolPop(id) {
  const wasHidden = $('#' + id + '-pop').hidden;
  closeToolPops();
  if (wasHidden) {
    $('#' + id + '-pop').hidden = false;
    $('#' + id + '-caret').setAttribute('aria-expanded', 'true');
  }
}
function setTool(next) {
  const changed = next !== tool;
  if (changed) cancelDraw();
  tool = next;
  closeToolPops();
  canvas.selection = tool === 'select' && !preview;
  canvas.skipTargetFind = tool !== 'select' || preview;
  canvas.defaultCursor = tool === 'hand' ? 'grab' : tool === 'select' ? 'default' : 'crosshair';
  if (tool === 'select' || tool === 'hand') {
    const names = { select: 'Указатель', hand: 'Рука' },
      pointer = $('#pointer-tool');
    if (pointer) {
      pointer.dataset.tool = tool;
      pointer.setAttribute('aria-label', names[tool]);
      pointer.title = tool === 'hand' ? 'Рука · H' : 'Указатель · V';
    }
    $('#pointer-icon').src = 'assets/editor/' + (tool === 'hand' ? 'hand' : 'cursor') + '.svg';
    $$('#pointer-pop [data-pointer]').forEach(x => x.classList.toggle('active', x.dataset.pointer === tool));
  }
  if (tool === 'photo' || tool === 'collage' || tool === 'grid') {
    frameKind = tool;
    const names = { photo: 'Изображение', collage: 'Коллаж', grid: 'Виньетка' },
      frame = $('#frame-tool');
    if (frame) {
      frame.dataset.tool = tool;
      frame.setAttribute('aria-label', names[tool]);
    }
    $('#frame-icon').src = 'assets/editor/' + (tool === 'grid' ? 'vignette' : tool) + '.svg';
    $$('#frame-pop [data-frame]').forEach(x => x.classList.toggle('active', x.dataset.frame === tool));
  }
  $$('[data-tool]').forEach(b => b.classList.toggle('active', b.dataset.tool === tool));
  const hints = {
    select: 'Shift — несколько объектов · Alt — без прилипания · пробел — перемещение',
    hand: 'Перетащите холст',
    text: 'Потяните рамку текста',
    photo: 'Потяните рамку изображения',
    shape:
      shapeKind === 'svg'
        ? 'Потяните область SVG. Shift — свободные пропорции'
        : 'Потяните фигуру. Меню рядом — линия, квадрат, круг или SVG',
    collage: 'Потяните область коллажа',
    grid: 'Потяните область автовиньетки',
  };
}
function addLayer(type, box) {
  if (preview) return;
  const p = page();
  if (!p) return;
  if (type === 'grid' && p.layers.some(l => l.type === 'grid'))
    return notify('На этой странице уже есть виньетка', true);
  const b = {
    x: round(box.x),
    y: round(box.y),
    w: round(Math.max(box.w, 0.4)),
    h: round(Math.max(box.h, 0.4)),
  };
  b.w = clamp(b.w, 0.4, pageWidth());
  b.h = clamp(b.h, 0.4, pageHeight());
  b.x = clamp(b.x, 0, pageWidth() - b.w);
  b.y = clamp(b.y, 0, pageHeight() - b.h);
  const l = {
    id: uid(),
    type,
    name: {
      text: 'Текст',
      photo: 'Изображение',
      rect: 'Квадрат',
      ellipse: 'Круг',
      line: 'Линия',
      grid: 'Автовиньетка',
      collage: 'Коллаж',
      svg: 'SVG',
    }[type],
    opacity: 100,
    angle: 0,
    box: b,
  };
  if (type === 'text')
    Object.assign(l, {
      text: 'Новый текст',
      styleId: (doc.textStyles || []).some(style => style.id === 'text-body') ? 'text-body' : undefined,
      ...Object.fromEntries(
        textStyleKeys.map(key => [
          key,
          (doc.textStyles || []).find(style => style.id === 'text-body')?.[key] ??
            MasterDefaults.textStyles().find(style => style.id === 'text-body')[key],
        ]),
      ),
    });
  if (type === 'photo')
    Object.assign(l, {
      source: section().kind === 'repeat' ? 'item' : 'owner',
      cropX: 50,
      cropY: 50,
      cropZoom: 1,
    });
  if (['rect', 'ellipse', 'line'].includes(type)) l.fill = '#d9d2e1';
  if (type === 'svg') {
    if (!pendingSvg) return notify('Сначала выберите SVG', true);
    const aspect = pendingSvg.aspect || 1;
    if (!box.free) {
      b.h = round(clamp(b.w / aspect, 0.4, pageHeight()));
      b.y = round(clamp(b.y, 0, pageHeight() - b.h));
    }
    Object.assign(l, {
      name: pendingSvg.name || 'SVG',
      svg: pendingSvg.svg,
      fill: '#29282d',
      fillMode: 'original',
      stroke: '#29282d',
      strokeMode: 'original',
      strokeWidth: 0,
      strokeAlign: 'center',
      strokeCap: 'round',
      strokeJoin: 'round',
      strokeDash: 'solid',
      lockAspect: !box.free,
      aspect,
      flipX: false,
      flipY: false,
    });
  }
  if (type === 'grid')
    Object.assign(l, {
      source: blockList(section()).source,
      gap: 5,
      minPhotoWidth: 32,
      photoWidth: 85,
      photoNameGap: 3,
      nameDetailGap: 2,
      font: 'Arial',
      fontSize: 12,
      minFontSize: 10,
      color: '#333333',
      align: 'center',
      showDetail: false,
      detailFont: 'Arial',
      detailFontSize: 9,
      detailColor: '#333333',
      detailAlign: 'center',
      styleGroup: section().id,
    });
  if (type === 'collage') {
    Object.assign(l, {
      fill: '#e6e1ea',
      gapX: 4,
      gapY: 4,
      gapLinked: true,
      rows: Array.from({ length: 2 }, () =>
        Array.from({ length: 2 }, () => ({ ...CollageCore.leaf(uid), pick: defaultPick() })),
      ),
    });
    focusCell = null;
  }
  commit(() => {
    p.layers.push(l);
    if (type === 'grid') makeList(section());
    selected = [l.id];
    inspectorTab = 'design';
  });
  setTool('select');
}
/* A new page or cover size scales every object of it proportionally. */
/* Layers scale with the page; far edges round down so a layer on the page edge never ends up past it. */
function resizeDesign(cover, newW, newH) {
  const [oldW, oldH] = cover
    ? coverSection().pageSize || doc.pageSize || [210, 280]
    : doc.pageSize || [210, 280];
  for (const layer of cover
    ? coverSection().spreads.flatMap(sp => sp.pages.flatMap(p => p.layers))
    : doc.sections
        .filter(s => !s.cover)
        .flatMap(s => s.spreads.flatMap(sp => sp.pages.flatMap(p => p.layers)))) {
    const b = layer.box,
      edge = v => Math.floor(v * 10 + 1e-6) / 10,
      right = edge(((b.x + b.w) * newW) / oldW),
      bottom = edge(((b.y + b.h) * newH) / oldH);
    b.x = round((b.x * newW) / oldW);
    b.y = round((b.y * newH) / oldH);
    b.w = round(right - b.x);
    b.h = round(bottom - b.y);
  }
  if (cover) coverSection().pageSize = [newW, newH];
  else doc.pageSize = [newW, newH];
}
function property(key, value) {
  if (preview) return;
  const l = selectedLayer();
  if (section().cover && key.startsWith('section.')) return;
  if (
    key === 'section.kind' &&
    value !== 'flow' &&
    section().spreads.some(sp => sp.pages.some(p => p.layers.some(l => l.type === 'grid')))
  )
    return notify('Удалите виньетки перед сменой правила блока', true);
  commit(() => {
    if (key.startsWith('section.')) {
      section()[key.split('.')[1]] = value;
      return;
    }
    if (key.startsWith('safety.')) {
      const target = section().cover ? (section().safety ??= {}) : (doc.safety ??= {});
      target[key.split('.')[1]] = value;
      return;
    }
    if (['document.width', 'document.height', 'cover.width', 'cover.height'].includes(key)) {
      const cover = key.startsWith('cover.'),
        [oldW, oldH] = cover
          ? coverSection().pageSize || doc.pageSize || [210, 280]
          : doc.pageSize || [210, 280];
      if (!Number.isFinite(value) || value < 50 || value > 500) return;
      resizeDesign(cover, key.endsWith('width') ? value : oldW, key.endsWith('height') ? value : oldH);
      return;
    }
    if (key === 'page.background') {
      page().background = value;
      return;
    }
    if (!l) return;
    if (key === 'source' && l.type === 'photo') {
      if (photoCrop) endPhotoCrop(false);
    }
    if (key === 'styleId' && l.type === 'text') {
      l.styleId = value || undefined;
      syncTextStyle(textStyle(l));
      return;
    }
    if (l.type === 'collage' && ['gap', 'gapX', 'gapY'].includes(key)) {
      const v = Math.round(clamp(Number(value) || 0, 0, CollageCore.MAX_GAP) * 10) / 10;
      if (key === 'gap') {
        l.gapX = v;
        l.gapY = v;
      } else l[key] = v;
      return;
    }
    if (key === 'gapLinked' && l.type === 'collage') {
      l.gapLinked = !!value;
      if (value) l.gapY = l.gapX;
      return;
    }
    if (key.startsWith('cell.')) {
      const loc = locateCell(l, focusCell);
      if (loc && !loc.cell.split) loc.cell[key.slice(5)] = value;
      return;
    }
    let layers = chosen();
    if (
      l.type === 'grid' &&
      [
        'radius',
        'source',
        'min',
        'max',
        'gap',
        'minPhotoWidth',
        'photoWidth',
        'photoNameGap',
        'nameDetailGap',
        'font',
        'fontSize',
        'minFontSize',
        'color',
        'align',
        'strictMin',
        'excludeLead',
        'bold',
        'italic',
        'underline',
        'strike',
        'lineHeight',
        'letterSpacing',
        'showDetail',
        'detailFont',
        'detailFontSize',
        'detailColor',
        'detailAlign',
        'detailBold',
        'detailItalic',
        'detailUnderline',
        'detailStrike',
        'detailLineHeight',
        'detailLetterSpacing',
      ].includes(key)
    )
      layers = section()
        .spreads.flatMap(sp => sp.pages.flatMap(p => p.layers))
        .filter(i => i.type === 'grid');
    for (const item of layers) {
      if (key === 'strokeOn') {
        item.strokeOn = !!value;
        if (value && !(item.strokeWidth > 0)) item.strokeWidth = 0.4;
        continue;
      }
      if (key === 'shadowOn') {
        if (value) {
          if (!item.shadow)
            item.shadow = { color: '#000000', offsetX: 0, offsetY: 1.5, blur: 2, opacity: 35 };
        } else delete item.shadow;
        continue;
      }
      if (key === 'strokeMode') {
        item.strokeMode = value;
        if (value === 'color' && !(item.strokeWidth > 0)) item.strokeWidth = 0.4;
        continue;
      }
      if (key === 'lockAspect') {
        item.lockAspect = !!value;
        if (value && item.aspect) {
          item.box.h = clamp(round(item.box.w / item.aspect), 1, pageHeight());
          item.box.y = clamp(item.box.y, 0, pageHeight() - item.box.h);
        }
        continue;
      }
      if (key.startsWith('shadow.')) {
        item.shadow = Object.assign(
          { color: '#000000', offsetX: 0, offsetY: 1.5, blur: 2, opacity: 35 },
          item.shadow,
        );
        item.shadow[key.slice(7)] = value;
        continue;
      }
      if (key.startsWith('box.')) {
        const axis = key.split('.')[1];
        item.box[axis] = axis === 'w' && item.pin === 'wrap' ? value - spineGap() : value;
        if (item.type === 'svg' && item.lockAspect !== false && item.aspect) {
          if (axis === 'w') item.box.h = round(item.box.w / item.aspect);
          if (axis === 'h') item.box.w = round(item.box.h * item.aspect);
        }
        settle(item);
      } else if (item.type === 'text' && textStyleKeys.includes(key)) setTextFormat(item, key, value);
      else item[key] = value;
    }
  });
}
/* One object aligns to the printed (trimmed) page it sits on — on the cover also the spine; several align to each other. */
function align(which) {
  commit(() => {
    const boxes = chosen()
      .filter(l => !l.locked)
      .map(l => {
        const x = layerOffset(l, layerSide(l)) + l.box.x,
          w = layerW(l);
        return { l, x, y: l.box.y, w, h: l.box.h };
      });
    if (!boxes.length) return;
    const area =
      boxes.length > 1
        ? {
            left: Math.min(...boxes.map(b => b.x)),
            top: Math.min(...boxes.map(b => b.y)),
            right: Math.max(...boxes.map(b => b.x + b.w)),
            bottom: Math.max(...boxes.map(b => b.y + b.h)),
          }
        : pageRectAt(boxes[0].x + boxes[0].w / 2, !!section().cover);
    for (const b of boxes) {
      let x = b.x,
        y = b.y;
      if (which === 'left') x = area.left;
      if (which === 'cx') x = (area.left + area.right - b.w) / 2;
      if (which === 'right') x = area.right - b.w;
      if (which === 'top') y = area.top;
      if (which === 'cy') y = (area.top + area.bottom - b.h) / 2;
      if (which === 'bottom') y = area.bottom - b.h;
      b.l.box.x = round(b.l.box.x + x - b.x);
      b.l.box.y = round(y);
      settle(b.l);
    }
  });
}
function action(type) {
  if (preview) return;
  const sec = section();
  if (type === 'section-delete') return sectionAction('delete', sec.id);
  if (type.startsWith('section-')) {
    if (sec.cover) return;
    commit(() => {
      const i = doc.sections.indexOf(sec);
      {
        const next = clamp(
          i + (type === 'section-up' ? -1 : 1),
          doc.sections[0]?.cover ? 1 : 0,
          doc.sections.length - 1,
        );
        doc.sections.splice(i, 1);
        doc.sections.splice(next, 0, sec);
      }
    });
    return;
  }
  if (!selected.length) return;
  commit(() => {
    for (const sp of sec.spreads)
      for (const p of sp.pages) {
        const targets = p.layers.filter(l => selected.includes(l.id));
        if (type === 'delete') p.layers = p.layers.filter(l => !selected.includes(l.id));
        if (type === 'duplicate')
          for (const l of targets.filter(l => l.type !== 'grid')) {
            const copy = clone(l);
            copy.id = uid();
            if (copy.type === 'collage') reidentifyCollage(copy);
            copy.name += ' · копия';
            copy.box.x += 5;
            copy.box.y += 5;
            p.layers.push(copy);
            settle(copy);
          }
        if (type === 'rotate') targets.forEach(l => (l.angle = (((l.angle || 0) + 90 + 180) % 360) - 180));
        if (type === 'lock') {
          const next = !targets.every(l => l.locked);
          targets.forEach(l => {
            l.locked = next;
          });
        }
      }
    if (['forward', 'backward', 'front', 'back'].includes(type))
      for (const sp of sec.spreads) {
        const order = spreadStack(sp),
          mine = l => selected.includes(l.id);
        if (order.some(mine)) restack(sp, restackOrder(order, mine, type));
      }
    if (type === 'delete') selected = [];
  });
}
/* The spread's stack after «up», «down», «to front» or «to back» for the chosen layers. */
function restackOrder(order, mine, type) {
  if (type === 'front') return order.filter(l => !mine(l)).concat(order.filter(mine));
  if (type === 'back') return order.filter(mine).concat(order.filter(l => !mine(l)));
  const next = [...order];
  if (type === 'forward') {
    for (let i = next.length - 2; i >= 0; i--)
      if (mine(next[i]) && !mine(next[i + 1])) [next[i], next[i + 1]] = [next[i + 1], next[i]];
  } else
    for (let i = 1; i < next.length; i++)
      if (mine(next[i]) && !mine(next[i - 1])) [next[i], next[i - 1]] = [next[i - 1], next[i]];
  return next;
}
function copyLayers() {
  const list = chosen();
  if (!list.length) return;
  clipboard = clone(list);
}
function pasteLayers() {
  if (preview || !clipboard?.length) return;
  const p = page();
  if (!p) return;
  const copies = clipboard
    .filter(l => l.type !== 'grid' || !p.layers.some(i => i.type === 'grid'))
    .map(l => {
      const copy = clone(l);
      copy.id = uid();
      delete copy.z;
      if (copy.type === 'collage') reidentifyCollage(copy);
      return copy;
    });
  if (!copies.length) return notify('На этой странице уже есть виньетка', true);
  commit(() => {
    p.layers.push(...copies);
    selected = copies.map(l => l.id);
    if (copies.some(l => l.type === 'grid')) makeList(section());
  });
}
const menuGlyphs = {
  rename: '<path d="M11.6 3.8l2.6 2.6-7.8 7.8H3.8v-2.6z"/><path d="M10 5.4l2.6 2.6"/>',
  copy: '<rect x="3.25" y="3.25" width="11.5" height="11.5" rx="2" stroke-dasharray="2.2 1.7"/>',
  duplicate:
    '<rect x="6.2" y="6.2" width="8.2" height="8.2" rx="1.5"/><path d="M3.6 11.2V4.8A1.2 1.2 0 0 1 4.8 3.6h6.4"/>',
  paste:
    '<rect x="4.2" y="3.8" width="9.6" height="11" rx="1.5"/><path d="M7.2 3.8v-.6a1 1 0 0 1 1-1h1.6a1 1 0 0 1 1 1v.6"/>',
  delete: '<path d="M4 5.2h10M7.2 5.2V4h3.6v1.2M5.4 5.2l.5 9h6.2l.5-9"/>',
  up: '<path d="M9 14.2V4.2M5.2 8 9 4.2 12.8 8"/>',
  down: '<path d="M9 3.8v10M5.2 10 9 13.8 12.8 10"/>',
  front: '<path d="M4 3.4h10M9 14.2V6.6M5.6 9.6 9 6.2l3.4 3.4"/>',
  back: '<path d="M4 14.6h10M9 3.8v7.6M5.6 8.4 9 11.8l3.4-3.4"/>',
  lock: '<rect x="4.2" y="8" width="9.6" height="6.6" rx="1.4"/><path d="M6.4 8V6.2a2.6 2.6 0 0 1 5.2 0V8"/>',
  unlock:
    '<rect x="4.2" y="8" width="9.6" height="6.6" rx="1.4"/><path d="M6.4 8V6.2a2.6 2.6 0 0 1 4.8-1.4"/>',
  show: '<path d="M2.8 9s2.4-4 6.2-4 6.2 4 6.2 4-2.4 4-6.2 4-6.2-4-6.2-4z"/><circle cx="9" cy="9" r="1.7"/>',
};
function menuGlyph(name) {
  return `<svg viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${menuGlyphs[name]}</svg>`;
}
function shortcutLabel(key) {
  return (/Mac|iPhone|iPad/.test(navigator.userAgent) ? '⌘' : 'Ctrl+') + key;
}
function orderEnabled(kind) {
  return section().spreads.some(sp => {
    const order = spreadStack(sp),
      idx = [];
    order.forEach((l, i) => {
      if (selected.includes(l.id)) idx.push(i);
    });
    if (!idx.length) return false;
    const atTop = idx.every((i, n) => i === order.length - idx.length + n),
      atBottom = idx.every((i, n) => i === n);
    return kind === 'up' || kind === 'front' ? !atTop : !atBottom;
  });
}
function closeObjectMenu() {
  const menu = $('#object-menu');
  if (menu) menu.hidden = true;
}
function objectMenuRow(id, label, icon, kbd, enabled) {
  return `<button type="button" role="menuitem" data-object-menu="${id}"${enabled ? '' : ' disabled'}>${menuGlyph(icon)}<span>${label}</span>${kbd ? `<kbd>${kbd}</kbd>` : ''}</button>`;
}
function openObjectMenu(e, target) {
  if (preview || document.querySelector('dialog[open]') || canvas.getActiveObject()?.isEditing) return;
  const point = canvas.getPointer(e),
    onPage = point.x >= 0 && point.x <= sheetWidth() && point.y >= 0 && point.y <= pageHeight();
  if (!onPage) {
    closeObjectMenu();
    return;
  }
  view.side = sideAt(point.x);
  const id = target?.masterId;
  if (!id) {
    closeObjectMenu();
    return;
  }
  if (inspectorTab !== 'design') {
    inspectorTab = 'design';
    renderInspector();
  }
  if (id && !selected.includes(id)) {
    selected = [id];
    focusCell = null;
    if (target.side != null) view.side = target.side;
    const obj = canvas.getObjects().find(o => o.masterId === id) || target;
    changing = true;
    if (obj.selectable) canvas.setActiveObject(obj);
    else canvas.discardActiveObject();
    changing = false;
    canvas.requestRenderAll();
    renderInspector();
    placeCollageUi();
    if (window.innerWidth < 850) $('.right-panel').classList.add('mobile-open');
  }
  const has = selected.length > 0,
    layers = chosen(),
    locked = has && layers.every(l => l.locked),
    grids = has && layers.every(l => l.type === 'grid'),
    hidden = (page()?.layers || []).some(l => l.hidden),
    canPaste =
      !!clipboard?.length &&
      clipboard.some(l => l.type !== 'grid' || !(page()?.layers || []).some(i => i.type === 'grid'));
  let html =
    objectMenuRow('copy', 'Копировать', 'copy', shortcutLabel('C'), has) +
    objectMenuRow('duplicate', 'Дублировать', 'duplicate', shortcutLabel('D'), has && !grids) +
    objectMenuRow('paste', 'Вставить', 'paste', shortcutLabel('V'), canPaste) +
    objectMenuRow(
      'delete',
      layers.length === 1 && layers[0].type === 'collage' ? 'Удалить коллаж' : 'Удалить',
      'delete',
      focusCell && layers[0]?.type === 'collage' ? '' : 'Delete',
      has,
    ) +
    '<hr>' +
    objectMenuRow('forward', 'Вверх', 'up', '', has && orderEnabled('up')) +
    objectMenuRow('backward', 'Вниз', 'down', '', has && orderEnabled('down')) +
    objectMenuRow('front', 'На передний план', 'front', '', has && orderEnabled('front')) +
    objectMenuRow('back', 'На задний план', 'back', '', has && orderEnabled('back')) +
    '<hr>' +
    objectMenuRow('lock', locked ? 'Разблокировать' : 'Заблокировать', locked ? 'unlock' : 'lock', '', has);
  if (hidden) html += objectMenuRow('reveal', 'Показать скрытые', 'show', '', true);
  const menu = $('#object-menu');
  menu.innerHTML = html;
  menu.hidden = false;
  menu.style.left = '0px';
  menu.style.top = '0px';
  const box = menu.getBoundingClientRect();
  let left = e.clientX,
    top = e.clientY;
  if (left + box.width > window.innerWidth - 8) left = Math.max(8, e.clientX - box.width);
  if (top + box.height > window.innerHeight - 8) top = Math.max(8, e.clientY - box.height);
  menu.style.left = left + 'px';
  menu.style.top = top + 'px';
  menu.style.transformOrigin = `${left < e.clientX - 1 ? 'right' : 'left'} ${top < e.clientY - 1 ? 'bottom' : 'top'}`;
}
