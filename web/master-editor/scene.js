/* Master editor · Photo crop, scene render, zoom, selection and cover geometry. */
'use strict';
async function imageElement(src) {
  if (!assetCache.has(src))
    assetCache.set(
      src,
      new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = () => reject(Error('Не удалось загрузить изображение'));
        image.src = src;
      }),
    );
  return assetCache.get(src);
}
/* The photo being cropped: a photo layer or one frame of a collage. */
function cropSubject(layerId, cellId) {
  const layer = allLayers().find(l => l.id === layerId);
  if (!layer) return null;
  if (!cellId) return { layer, item: layer, box: { ...layer.box, w: layerW(layer) } };
  const f = collageFrames(layer).find(fr => fr.cell.id === cellId);
  return f
    ? { layer, item: f.cell, box: { x: layer.box.x + f.x, y: layer.box.y + f.y, w: f.w, h: f.h } }
    : null;
}
function photoCropMetrics() {
  if (!photoCrop) return null;
  const subject = cropSubject(photoCrop.id, photoCrop.cell),
    obj = findCanvasObject(photoCrop.id);
  if (!subject || !obj) return null;
  const { layer, item } = subject,
    b = subject.box,
    zoom = canvas.getZoom() || 1,
    point = sceneToHost(layerOffset(layer, obj.side || 0) + b.x, b.y),
    iw = photoCrop.image.naturalWidth,
    ih = photoCrop.image.naturalHeight,
    scale = Math.max(b.w / iw, b.h / ih) * photoCrop.zoom,
    displayW = iw * scale * zoom,
    displayH = ih * scale * zoom;
  return {
    layer,
    left: point.x,
    top: point.y,
    width: b.w * zoom,
    height: b.h * zoom,
    displayW,
    displayH,
    extraX: Math.max(0, displayW - b.w * zoom),
    extraY: Math.max(0, displayH - b.h * zoom),
    item,
  };
}
function paintPhotoCropImage() {
  const m = photoCropMetrics(),
    img = $('#photo-crop-ui .photo-crop-window img');
  if (!m || !img) return;
  Object.assign(img.style, {
    width: m.displayW + 'px',
    height: m.displayH + 'px',
    left: (-m.extraX * photoCrop.x) / 100 + 'px',
    top: (-m.extraY * photoCrop.y) / 100 + 'px',
  });
  const output = $('#photo-crop-ui [data-crop-zoom-value]');
  if (output) output.textContent = Math.round(photoCrop.zoom * 100) + '%';
}
function placePhotoCropUi() {
  const host = $('#photo-crop-ui'),
    m = photoCropMetrics();
  if (!host) return;
  if (!m) {
    host.hidden = true;
    host.innerHTML = '';
    return;
  }
  host.hidden = false;
  const actionsTop =
    m.top + m.height + 86 > host.clientHeight ? Math.max(8, m.top - 58) : m.top + m.height + 16;
  host.innerHTML = `<div class="photo-crop-window" style="left:${m.left}px;top:${m.top}px;width:${m.width}px;height:${m.height}px;transform:rotate(${m.layer.angle || 0}deg)"><img src="${esc(m.item.dataUrl)}" alt="Переместить фото внутри кадра" draggable="false" style="width:${m.displayW}px;height:${m.displayH}px;left:${(-m.extraX * photoCrop.x) / 100}px;top:${(-m.extraY * photoCrop.y) / 100}px"></div><div class="photo-crop-actions" style="left:${clamp(m.left + m.width / 2, Math.min(165, host.clientWidth / 2), Math.max(host.clientWidth - 165, host.clientWidth / 2))}px;top:${actionsTop}px"><button type="button" data-crop-step="-0.1" aria-label="Уменьшить фото">−</button><input type="range" data-crop-zoom min="100" max="400" step="5" value="${Math.round(photoCrop.zoom * 100)}" aria-label="Масштаб фото"><output data-crop-zoom-value>${Math.round(photoCrop.zoom * 100)}%</output><button type="button" data-crop-step="0.1" aria-label="Увеличить фото">＋</button><button type="button" data-crop-cancel>Отмена</button><button type="button" data-crop-save>Готово</button></div>`;
}
async function startPhotoCrop(layer, cellId = null) {
  const subject = layer && (layer.type === 'photo' || cellId) ? cropSubject(layer.id, cellId) : null,
    item = subject?.item;
  if (!item || item.source !== 'custom' || !item.dataUrl || preview || layer.locked) return;
  cellMenu = null;
  try {
    const image = await imageElement(item.dataUrl);
    if (!cropSubject(layer.id, cellId)) return;
    photoCrop = {
      id: layer.id,
      cell: cellId,
      image,
      x: clamp(Number(item.cropX ?? 50), 0, 100),
      y: clamp(Number(item.cropY ?? 50), 0, 100),
      zoom: clamp(Number(item.cropZoom ?? 1), 1, 4),
      drag: null,
    };
    selected = [layer.id];
    placePhotoCropUi();
    placeCollageUi();
  } catch (error) {
    notify(error.message, true);
  }
}
function endPhotoCrop(save) {
  const crop = photoCrop;
  if (!crop) return;
  photoCrop = null;
  placePhotoCropUi();
  placeCollageUi();
  if (save) {
    const item = cropSubject(crop.id, crop.cell)?.item;
    if (
      item &&
      (Math.abs((item.cropX ?? 50) - crop.x) > 0.01 ||
        Math.abs((item.cropY ?? 50) - crop.y) > 0.01 ||
        Math.abs((item.cropZoom ?? 1) - crop.zoom) > 0.001)
    )
      commit(() => {
        item.cropX = round(crop.x);
        item.cropY = round(crop.y);
        item.cropZoom = Math.round(crop.zoom * 100) / 100;
      });
  }
}
const photoCropHost = $('#photo-crop-ui');
photoCropHost.addEventListener('pointerdown', e => {
  const img = e.target.closest('.photo-crop-window img');
  if (!img || !photoCrop) return;
  e.preventDefault();
  e.stopPropagation();
  photoCrop.drag = { x: e.clientX, y: e.clientY, startX: photoCrop.x, startY: photoCrop.y };
  img.setPointerCapture(e.pointerId);
});
photoCropHost.addEventListener('pointermove', e => {
  const crop = photoCrop,
    drag = crop?.drag;
  if (!drag) return;
  const m = photoCropMetrics();
  if (!m) return;
  const angle = ((m.layer.angle || 0) * Math.PI) / 180,
    dx = e.clientX - drag.x,
    dy = e.clientY - drag.y,
    localX = dx * Math.cos(angle) + dy * Math.sin(angle),
    localY = -dx * Math.sin(angle) + dy * Math.cos(angle);
  crop.x = m.extraX ? clamp(drag.startX - (localX / m.extraX) * 100, 0, 100) : 50;
  crop.y = m.extraY ? clamp(drag.startY - (localY / m.extraY) * 100, 0, 100) : 50;
  paintPhotoCropImage();
});
const stopPhotoDrag = () => {
  if (photoCrop) photoCrop.drag = null;
};
photoCropHost.addEventListener('pointerup', stopPhotoDrag);
photoCropHost.addEventListener('pointercancel', stopPhotoDrag);
photoCropHost.addEventListener('input', e => {
  if (e.target.matches('[data-crop-zoom]') && photoCrop) {
    photoCrop.zoom = clamp(Number(e.target.value) / 100, 1, 4);
    paintPhotoCropImage();
  }
});
photoCropHost.addEventListener('click', e => {
  if (e.target.closest('[data-crop-save]')) endPhotoCrop(true);
  else if (e.target.closest('[data-crop-cancel]')) endPhotoCrop(false);
  else {
    const step = e.target.closest('[data-crop-step]');
    if (step && photoCrop) {
      photoCrop.zoom = clamp(Math.round((photoCrop.zoom + Number(step.dataset.cropStep)) * 100) / 100, 1, 4);
      placePhotoCropUi();
    }
  }
});
photoCropHost.addEventListener(
  'wheel',
  e => {
    if (!photoCrop || !e.target.closest('.photo-crop-window')) return;
    e.preventDefault();
    photoCrop.zoom = clamp(Math.round((photoCrop.zoom + (e.deltaY < 0 ? 0.1 : -0.1)) * 100) / 100, 1, 4);
    placePhotoCropUi();
  },
  { passive: false },
);
function safetyGuides() {
  if (preview) return [];
  const w = pageWidth(),
    h = pageHeight(),
    kind = safetyKind(),
    geo = safetyGeometry(kind, w, h, safetyValues(kind), spineGap()),
    base = { selectable: false, evented: false, excludeFromExport: true },
    rect = ([left, top, width, height], style) =>
      new fabric.Rect({ left, top, width, height, ...base, ...style }),
    line = (x, style) => new fabric.Line([x, 0, x, h], { ...base, strokeWidth: 0.5, ...style });
  return [
    ...geo.bands.map(r => rect(r, { fill: '#f6a4a455', strokeWidth: 0 })),
    ...geo.spines.map(r => rect(r, { fill: '#9b8cee22', stroke: '#8170b6', strokeWidth: 0.4 })),
    ...geo.trims.map(r =>
      rect(r, { fill: 'transparent', stroke: '#e68b93', strokeWidth: 0.55, strokeDashArray: [3, 2] }),
    ),
    ...geo.safes.map(r => rect(r, { fill: 'transparent', stroke: '#1670d8', strokeWidth: 0.55 })),
    ...geo.gaps.map(x => line(x, { stroke: '#888', strokeDashArray: [3, 2] })),
    ...geo.folds.map(x => line(x, { stroke: '#35b8c8', strokeDashArray: [2, 2] })),
  ];
}
/* Group whose frame is exactly the layer box. The first child spans the box; strokes and shadows past its edges must not move the content or grow the frame. */
function boxGroup(children, options) {
  const group = new fabric.Group(children, {
      ...options,
      layoutManager: new fabric.LayoutManager(new fabric.FixedLayout()),
    }),
    c = children[0].getRelativeCenterPoint();
  for (const child of children) {
    child.set({ left: child.left - c.x, top: child.top - c.y });
    child.setCoords();
  }
  group.set({ width: options.width, height: options.height });
  group.setCoords();
  return group;
}
/* Cards of one vignette page in layer coordinates; shared by the canvas and the settings preview. */
async function vignetteChildren(l, g, background) {
  const b = l.box;
  const records = g.records || [],
    geo = planner.gridGeometry(g.layoutCount || Math.max(1, records.length), l),
    children = [
      new fabric.Rect({
        left: 0,
        top: 0,
        width: b.w,
        height: b.h,
        fill: background || '#fff',
        stroke: null,
        strokeWidth: 0,
        evented: false,
      }),
    ],
    cards = [],
    shadows = [],
    align = l.strokeAlign || 'center',
    sw =
      align === 'inside' && geo ? Math.min(activeStroke(l), geo.photoW / 2, geo.photoH / 2) : activeStroke(l),
    inset = align === 'inside' ? sw / 2 : align === 'outside' ? -sw / 2 : 0,
    reach = align === 'outside' ? sw : align === 'center' ? sw / 2 : 0;
  if (geo) {
    for (let i = 0; i < records.length; i++) {
      const x = geo.offsetX + (i % geo.cols) * (geo.cellW + l.gap),
        y = geo.offsetY + Math.floor(i / geo.cols) * (geo.cellH + l.gap);
      const el = await imageElement(planner.placeholderSvg(records[i]));
      const photo = new fabric.FabricImage(el, {
          left: x,
          top: y,
          scaleX: geo.photoW / el.naturalWidth,
          scaleY: geo.photoW / 0.75 / el.naturalHeight,
          opacity: records[i].missing ? 0.2 : 1,
        }),
        corner = Math.min(Number(l.radius) || 0, geo.photoW / 2, geo.photoH / 2);
      if (corner)
        photo.clipPath = new fabric.Rect({
          width: el.naturalWidth,
          height: el.naturalHeight,
          rx: corner / photo.scaleX,
          ry: corner / photo.scaleY,
          originX: 'center',
          originY: 'center',
        });
      if (l.shadow)
        shadows.push(
          new fabric.Rect({
            left: x - reach,
            top: y - reach,
            width: geo.photoW + 2 * reach,
            height: geo.photoH + 2 * reach,
            rx: corner && corner + reach,
            ry: corner && corner + reach,
            fill: background || '#fff',
            strokeWidth: 0,
            shadow: shadowPaint(l.shadow),
            evented: false,
          }),
        );
      children.push(photo);
      if (sw)
        children.push(
          new fabric.Rect({
            left: x + geo.photoW / 2,
            top: y + geo.photoH / 2,
            originX: 'center',
            originY: 'center',
            width: Math.max(geo.photoW - 2 * inset, 0.2),
            height: Math.max(geo.photoH - 2 * inset, 0.2),
            rx: Math.max(0, corner - inset),
            ry: Math.max(0, corner - inset),
            fill: 'transparent',
            stroke: strokeColor(l),
            strokeWidth: sw,
            strokeUniform: true,
            strokeDashArray: dashArray(l.strokeDash, sw),
            strokeLineCap: l.strokeCap || 'butt',
            strokeLineJoin: l.strokeJoin || 'miter',
            evented: false,
            objectCaching: false,
          }),
        );
      const nameBox = new fabric.Textbox(records[i].name, {
        left: x,
        top: y + geo.photoH + geo.photoNameGap,
        width: geo.cellW,
        fontFamily: l.font,
        fontWeight: l.bold ? 'bold' : 'normal',
        fontStyle: l.italic ? 'italic' : 'normal',
        underline: !!l.underline,
        linethrough: !!l.strike,
        fontSize: (g.actualFont || l.fontSize) * 0.3528,
        lineHeight: l.lineHeight || 1.25,
        charSpacing: (Number(l.letterSpacing) || 0) * 10,
        textAlign: l.align || 'center',
        fill: l.color,
        strokeWidth: 0,
      });
      children.push(nameBox);
      cards.push({
        x,
        y,
        photoBottom: y + geo.photoH,
        nameTop: nameBox.top,
        nameBottom: nameBox.top + nameBox.height,
        detail: !!(l.showDetail && records[i].detail),
      });
      if (l.showDetail && records[i].detail)
        children.push(
          new fabric.Textbox(records[i].detail, {
            left: x,
            top: nameBox.top + nameBox.height + geo.nameDetailGap,
            width: geo.cellW,
            fontFamily: l.detailFont || l.font,
            fontWeight: l.detailBold ? 'bold' : 'normal',
            fontStyle: l.detailItalic ? 'italic' : 'normal',
            underline: !!l.detailUnderline,
            linethrough: !!l.detailStrike,
            fontSize: (l.detailFontSize || 9) * 0.3528,
            lineHeight: l.detailLineHeight || 1.25,
            charSpacing: (Number(l.detailLetterSpacing) || 0) * 10,
            textAlign: l.detailAlign || 'center',
            fill: l.detailColor || l.color,
            strokeWidth: 0,
          }),
        );
    }
  }
  children.splice(1, 0, ...shadows);
  return { children, geo, cards };
}
async function renderScene() {
  clearGuides();
  const token = ++renderToken;
  const fontsAdded = await ensureFonts();
  if (token !== renderToken) return;
  if (fontsAdded) {
    render();
    return;
  }
  const sec = section(),
    plan = plans.find(p => p.sectionId === sec.id);
  const pages = preview
    ? plan.pages.slice(view.spread * 2, view.spread * 2 + 2)
    : sec.spreads[view.spread]?.pages.map(
        p =>
          plan.pages.find(g => g.templateId === p.id) || {
            templateId: p.id,
            personId: view.owner,
            records: planner.people(p.layers.find(l => l.type === 'grid')?.source || 'students').slice(0, 8),
          },
      );
  const objects = [],
    backs = [];
  for (let side = 0; side < 2; side++) {
    const g = pages?.[side],
      p = planner.getTemplatePage(g?.templateId),
      pageIndex = preview ? view.spread * 2 + side : (plan?.pages.indexOf(g) ?? -1);
    backs.push(
      new fabric.Rect({
        left: side * (pageWidth() + spineGap() / 2),
        top: 0,
        width: pageWidth() + spineGap() / 2,
        height: pageHeight(),
        fill: p?.background || '#fff',
        stroke: '#e5e1e8',
        strokeWidth: 0.25,
        selectable: false,
        evented: false,
        shadow: new fabric.Shadow({ color: '#2222220a', blur: 9, offsetX: 0, offsetY: 3 }),
      }),
    );
    if (!p) continue;
    for (const l of p.layers.filter(l => !l.hidden)) {
      let object;
      const b = { ...l.box, w: layerW(l) },
        base = {
          left: layerOffset(l, side) + b.x + b.w / 2,
          top: b.y + b.h / 2,
          originX: 'center',
          originY: 'center',
          angle: l.angle || 0,
          opacity: (l.opacity ?? 100) / 100,
          stroke: l.stroke || '#333333',
          strokeWidth: 0,
          selectable: !preview && !l.locked,
          evented: !preview,
          lockMovementX: !!l.locked,
          lockMovementY: !!l.locked,
          lockRotation: !!l.locked,
          lockScalingX: !!l.locked,
          lockScalingY: !!l.locked,
          lockScalingFlip: true,
          cornerColor: '#ffffff',
          cornerStrokeColor: '#9664b5',
          borderColor: '#9664b5',
          transparentCorners: false,
          cornerSize: 7,
        };
      if (l.type === 'text') {
        object = new fabric.Textbox(planner.resolvedText(l, g), {
          ...base,
          width: b.w,
          fontSize: l.fontSize * 0.3528,
          fontFamily: l.font,
          fill: l.color,
          textAlign: l.align === 'justify' ? 'justify' : l.align || 'left',
          lineHeight: l.lineHeight || 1.25,
          charSpacing: (Number(l.letterSpacing) || 0) * 10,
          fontWeight: l.bold ? 'bold' : 'normal',
          fontStyle: l.italic ? 'italic' : 'normal',
          underline: !!l.underline,
          linethrough: !!l.strike,
          editable: !AutoText.fields(l.text).size && !preview && !l.locked,
          splitByGrapheme: false,
        });
        applyTextPaint(object, l);
      } else if (l.type === 'photo') {
        const picked = l.source === 'class' ? MasterPhotos.image(sec.id, pageIndex, l.id) : null,
          src = picked?.src || planner.resolvedPhoto(l, g);
        if (src) {
          try {
            const el = await imageElement(src);
            const ratio = b.w / b.h,
              w = el.naturalWidth,
              h = el.naturalHeight,
              zoom = clamp(Number(l.cropZoom ?? 1), 1, 4),
              baseW = w / h > ratio ? h * ratio : w,
              baseH = w / h > ratio ? h : w / ratio,
              cw = picked ? picked.crop[2] * w : baseW / zoom,
              ch = picked ? picked.crop[3] * h : baseH / zoom;
            object = new fabric.FabricImage(el, {
              ...base,
              width: cw,
              height: ch,
              cropX: picked ? picked.crop[0] * w : ((w - cw) * (l.cropX ?? 50)) / 100,
              cropY: picked ? picked.crop[1] * h : ((h - ch) * (l.cropY ?? 50)) / 100,
              scaleX: b.w / cw,
              scaleY: b.h / ch,
            });
            if (l.radius)
              object.clipPath = new fabric.Rect({
                width: cw,
                height: ch,
                rx: (l.radius * cw) / b.w,
                ry: (l.radius * ch) / b.h,
                originX: 'center',
                originY: 'center',
              });
          } catch (e) {
            notify(e.message, true);
          }
        }
        if (!object)
          object = new fabric.Rect({
            ...base,
            width: b.w,
            height: b.h,
            fill: '#f1edf4',
            stroke: '#bca9ca',
            strokeWidth: 0.5,
            strokeDashArray: [2, 2],
          });
      } else if (l.type === 'grid') {
        const built = await vignetteChildren(l, g, p.background);
        object = boxGroup(built.children, {
          ...base,
          width: b.w,
          height: b.h,
          subTargetCheck: false,
          objectCaching: false,
        });
        object.vignette = { geo: built.geo, cards: built.cards };
      } else if (l.type === 'collage') {
        const frames = l.flex ? flexLayout(l, sec.id, pageIndex) : collageFrames(l),
          radius = Number(l.radius) || 0,
          stroke = activeStroke(l),
          children = [
            new fabric.Rect({
              left: 0,
              top: 0,
              width: b.w,
              height: b.h,
              fill: 'transparent',
              strokeWidth: 0,
            }),
          ];
        for (const f of frames) {
          const r = Math.min(radius, f.w / 2, f.h / 2),
            tag = (o, role) => {
              o.collageId = f.cell.id;
              o.collageRole = role;
              children.push(o);
            };
          let placed = false;
          const picked =
              (f.cell.source || 'class') === 'class' && !f.cell.forced
                ? MasterPhotos.image(sec.id, pageIndex, l.id + '/' + f.cell.id)
                : null,
            src = picked?.src || planner.resolvedPhoto(f.cell, g);
          if (src) {
            try {
              const el = await imageElement(src);
              const ratio = f.w / f.h,
                iw = el.naturalWidth,
                ih = el.naturalHeight,
                zoom = clamp(Number(f.cell.cropZoom ?? 1), 1, 4),
                baseW = iw / ih > ratio ? ih * ratio : iw,
                baseH = iw / ih > ratio ? ih : iw / ratio,
                cw = picked ? picked.crop[2] * iw : baseW / zoom,
                ch = picked ? picked.crop[3] * ih : baseH / zoom;
              const img = new fabric.FabricImage(el, {
                left: f.x,
                top: f.y,
                originX: 'left',
                originY: 'top',
                width: cw,
                height: ch,
                cropX: picked ? picked.crop[0] * iw : ((iw - cw) * (f.cell.cropX ?? 50)) / 100,
                cropY: picked ? picked.crop[1] * ih : ((ih - ch) * (f.cell.cropY ?? 50)) / 100,
                scaleX: f.w / cw,
                scaleY: f.h / ch,
                strokeWidth: 0,
              });
              if (r)
                img.clipPath = new fabric.Rect({
                  width: cw,
                  height: ch,
                  rx: (r * cw) / f.w,
                  ry: (r * ch) / f.h,
                  originX: 'center',
                  originY: 'center',
                });
              tag(img, 'cell');
              placed = true;
            } catch (e) {
              notify(e.message, true);
            }
          }
          if (!placed)
            tag(
              new fabric.Rect({
                left: f.x,
                top: f.y,
                width: Math.max(f.w, 0.2),
                height: Math.max(f.h, 0.2),
                fill: l.fill || '#e6e1ea',
                rx: r,
                ry: r,
                stroke: '#d5d0da',
                strokeWidth: 0.3,
                strokeUniform: true,
              }),
              'cell',
            );
          if (stroke) {
            const width = l.strokeAlign === 'inside' ? Math.min(stroke, f.w / 2, f.h / 2) : stroke,
              inset = l.strokeAlign === 'inside' ? width / 2 : l.strokeAlign === 'outside' ? -width / 2 : 0;
            tag(
              new fabric.Rect({
                left: f.x + f.w / 2,
                top: f.y + f.h / 2,
                originX: 'center',
                originY: 'center',
                width: Math.max(f.w - 2 * inset, 0.2),
                height: Math.max(f.h - 2 * inset, 0.2),
                rx: Math.max(r - inset, 0),
                ry: Math.max(r - inset, 0),
                fill: 'transparent',
                stroke: strokeColor(l),
                strokeWidth: width,
                strokeDashArray: dashArray(l.strokeDash, width),
              }),
              'outline',
            );
          }
        }
        object = boxGroup(children, {
          ...base,
          width: b.w,
          height: b.h,
          subTargetCheck: false,
          objectCaching: false,
        });
      } else if (l.type === 'svg') object = await fabricSvg(l, b, base, side);
      else if (l.type === 'ellipse')
        object = new fabric.Ellipse({ ...base, rx: b.w / 2, ry: b.h / 2, fill: l.fill });
      else
        object = new fabric.Rect({
          ...base,
          width: b.w,
          height: b.h,
          rx: l.radius || 0,
          ry: l.radius || 0,
          fill: l.fill,
        });
      if (object && ['rect', 'ellipse', 'line', 'svg'].includes(l.type)) applyVectorPaint(object, l);
      else if (object && ['photo', 'collage'].includes(l.type) && (l.shadow || strokeOpen(l))) {
        const width = l.type === 'photo' ? activeStroke(l) : 0,
          patch = { shadow: shadowPaint(l.shadow) };
        if (width)
          Object.assign(patch, {
            stroke: strokeColor(l),
            strokeWidth: l.strokeAlign === 'outside' || l.strokeAlign === 'inside' ? width * 2 : width,
            strokeDashArray: dashArray(l.strokeDash, width),
            paintFirst: l.strokeAlign === 'outside' ? 'stroke' : 'fill',
            strokeUniform: true,
          });
        object.set(patch);
        if (l.strokeAlign === 'inside' && width > 0) {
          const clipW = object.type === 'image' ? object.width : b.w,
            clipH = object.type === 'image' ? object.height : b.h;
          object.clipPath = new fabric.Rect({
            width: clipW,
            height: clipH,
            rx: ((l.radius || 0) * clipW) / b.w,
            ry: ((l.radius || 0) * clipH) / b.h,
            originX: 'center',
            originY: 'center',
          });
        }
      }
      object.masterId = l.id;
      object.boxSelection = ['photo', 'rect', 'ellipse', 'svg'].includes(l.type);
      object.selectionRadius = ['collage', 'grid', 'ellipse', 'line', 'svg'].includes(l.type)
        ? 0
        : Number(l.radius) || 0;
      object.pageId = p.id;
      object.side = side;
      object.baseWidth = b.w;
      object.baseHeight = b.h;
      objects.push(object);
    }
  }
  if (token !== renderToken) return;
  changing = true;
  canvas.discardActiveObject();
  canvas.clear();
  canvas.backgroundColor = '#f0f0f2';
  canvas.add(...backs, ...objects, ...bookMarks(), ...safetyGuides());
  const targets = objects.filter(o => selected.includes(o.masterId) && o.selectable);
  if (targets.length === 1) canvas.setActiveObject(targets[0]);
  else if (targets.length > 1) canvas.setActiveObject(new fabric.ActiveSelection(targets, { canvas }));
  canvas.requestRenderAll();
  changing = false;
  placeCollageUi();
  placePhotoCropUi();
  if ($('#vignette-dialog')?.open) vignettePreview();
}
function syncSelectionCoords() {
  const active = canvas.getActiveObject();
  if (!active) return;
  active.setCoords();
  if (active instanceof fabric.ActiveSelection) active.forEachObject(o => o.setCoords());
}
function updateZoomControls() {
  const zoom = canvas.getZoom();
  $('#zoom-value').textContent = `${Math.round(zoom * 50)}%`;
  $('#zoom-out').disabled = zoom <= 0.2;
  $('#zoom-in').disabled = zoom >= 8;
  $('#zoom-fit').setAttribute('aria-pressed', zoomMode === 'fit');
}
function fit() {
  const host = $('#canvas-host'),
    w = host.clientWidth,
    h = host.clientHeight;
  canvas.setDimensions({ width: w, height: h });
  const scale =
    zoomMode === 'fit'
      ? Math.max(0.2, Math.min((w - 70) / sheetWidth(), (h - 180) / pageHeight()))
      : Number(zoomMode) * 2;
  canvas.setViewportTransform([
    scale,
    0,
    0,
    scale,
    (w - sheetWidth() * scale) / 2,
    (h - pageHeight() * scale) / 2 - 5,
  ]);
  syncSelectionCoords();
  placeCollageUi();
  placePhotoCropUi();
  updateZoomControls();
}
function stepZoom(direction) {
  const current = canvas.getZoom(),
    zoom = clamp(current * (direction > 0 ? 1.25 : 0.8), 0.2, 8);
  if (zoom === current) return;
  const host = $('#canvas-host');
  canvas.zoomToPoint(new fabric.Point(host.clientWidth / 2, host.clientHeight / 2), zoom);
  zoomMode = zoom / 2;
  syncSelectionCoords();
  placeCollageUi();
  placePhotoCropUi();
  updateZoomControls();
}
new ResizeObserver(() => fit()).observe($('#canvas-host'));
function syncSelection() {
  if (changing) return;
  const objects = canvas.getActiveObjects(),
    next = objects.map(o => o.masterId).filter(Boolean);
  if (next.join() !== selected.join()) {
    focusCell = null;
    cellMenu = null;
    selectedAt = performance.now();
  }
  selected = next;
  if (objects[0]) view.side = objects[0].side;
  if (selected.length) inspectorTab = 'design';
  renderInspector();
  if (selected.length && window.innerWidth < 850) $('.right-panel').classList.add('mobile-open');
  placeCollageUi();
}
canvas.on('selection:created', syncSelection);
canvas.on('selection:updated', syncSelection);
canvas.on('selection:cleared', () => {
  if (!changing) {
    selected = [];
    focusCell = null;
    cellMenu = null;
    renderInspector();
    $('.right-panel').classList.remove('mobile-open');
    placeCollageUi();
  }
});
/* The cover unfolds as back · spine · front; the spine width follows the book's volume and sheet thickness (or is fixed without a thickness). The canvas shows the test class book, or the volume picked in the cover panel. */
function editorVolume() {
  const spreads =
    view.coverSpreads ||
    plans
      .filter(p => !doc.sections.find(s => s.id === p.sectionId)?.cover)
      .reduce((n, p) => n + p.spreads, 0);
  return { spreads, pages: 2 * spreads - (doc.layout === 'book' && spreads ? 2 : 0) };
}
const SPINE_BOARD = 3.5,
  SPINE_MIN = 8;
function bookSheets(spreads) {
  return doc.layout === 'book' && spreads ? spreads - 1 : spreads;
}
function coverSpine() {
  const t = doc.sheetThickness;
  if (!t) return Number(coverSection()?.safety?.spine) || 0;
  return Math.max(
    SPINE_MIN,
    2 * Math.ceil(Math.round((SPINE_BOARD + bookSheets(editorVolume().spreads) * t) * 100) / 200),
  );
}
function spineGap() {
  return section()?.cover ? coverSpine() : 0;
}
function sideX(side) {
  return side * (pageWidth() + spineGap());
}
function sideAt(x) {
  return x >= pageWidth() + spineGap() / 2 ? 1 : 0;
}
function sheetWidth() {
  return 2 * pageWidth() + spineGap();
}
/* A cover layer may be pinned to the spine: «spine» keeps its offset from the spine centre, «wrap» — a background or photo at least half a side wide running over the spine — grows with it (its stored width leaves the spine out). */
const wrapKinds = new Set(['photo', 'rect', 'ellipse', 'line', 'svg']);
function layerOffset(l, side) {
  const s = spineGap();
  return l.pin === 'spine' ? pageWidth() + s / 2 : l.pin === 'wrap' ? 0 : sideX(side);
}
function layerW(l) {
  return l.box.w + (l.pin === 'wrap' ? spineGap() : 0);
}
function placeOnCover(l, left, width) {
  const W = pageWidth(),
    s = spineGap(),
    pages = section().spreads[0].pages,
    w = clamp(width, 1, 2 * W + s),
    L = clamp(left, 0, 2 * W + s - w),
    R = L + w,
    eps = 0.5;
  let side = 0,
    pin = null,
    x = L,
    bw = w;
  if (R <= W + eps);
  else if (L >= W + s - eps) {
    side = 1;
    x = L - W - s;
  } else if (L <= W + eps && R >= W + s - eps && wrapKinds.has(l.type) && w - s >= W / 2) {
    pin = 'wrap';
    bw = Math.max(1, w - s);
  } else {
    pin = 'spine';
    x = L - W - s / 2;
  }
  if (pin) l.pin = pin;
  else delete l.pin;
  l.box.x = round(x);
  l.box.w = round(bw);
  const from = pages.findIndex(p => p.layers.includes(l));
  if (from >= 0 && from !== side) {
    pages[from].layers.splice(pages[from].layers.indexOf(l), 1);
    pages[side].layers.push(l);
  }
}
function settle(l) {
  if (!section().cover) {
    fitSpread(l);
    settleSide(l);
    return;
  }
  const H = pageHeight(),
    left = layerOffset(l, layerSide(l)) + l.box.x,
    width = layerW(l);
  l.box.h = clamp(l.box.h, 1, H);
  l.box.y = clamp(l.box.y, 0, H - l.box.h);
  placeOnCover(l, left, width);
}
/* A layer belongs to a page but may cross the fold: its box stays within the spread and it moves to the page that holds its centre. Vignettes stay on their page. */
function layerSide(l) {
  const i = (section().spreads[view.spread]?.pages || []).findIndex(p => p.layers.includes(l));
  return i < 0 ? 0 : i;
}
function fitSpread(l) {
  const W = pageWidth(),
    H = pageHeight(),
    b = l.box,
    grid = l.type === 'grid',
    side = layerSide(l),
    left = grid ? 0 : -side * W,
    right = grid ? W : (2 - side) * W;
  b.w = clamp(b.w, 1, right - left);
  b.h = clamp(b.h, 1, H);
  b.x = clamp(b.x, left, right - b.w);
  b.y = clamp(b.y, 0, H - b.h);
}
function settleSide(l) {
  const pages = section().spreads[view.spread]?.pages,
    from = layerSide(l),
    to = l.box.x + from * pageWidth() + l.box.w / 2 >= pageWidth() ? 1 : 0;
  if (!pages || l.type === 'grid' || from === to || !pages[to] || !pages[from].layers.includes(l)) return;
  pages[from].layers.splice(pages[from].layers.indexOf(l), 1);
  pages[to].layers.push(l);
  l.box.x += (from - to) * pageWidth();
}
canvas.on('object:modified', event => {
  clearGuides();
  if (changing || preview) return;
  const objects = event.target instanceof fabric.ActiveSelection ? event.target.getObjects() : [event.target];
  const changes = objects
    .filter(o => o.masterId)
    .map(o => {
      const c = o.getCenterPoint(),
        scale = o.getObjectScaling(),
        l = allLayers().find(l => l.id === o.masterId),
        w = round((l?.type === 'grid' ? o.baseWidth : o.width) * scale.x),
        h = round((l?.type === 'grid' ? o.baseHeight : o.height) * scale.y);
      return {
        l,
        w,
        h,
        left: round(c.x - w / 2),
        side: o.side || 0,
        y: round(c.y - h / 2),
        angle: round(o.getTotalAngle()),
      };
    });
  commit(() =>
    changes.forEach(({ l, w, h, left, side, y, angle }) => {
      if (l.type === 'svg' && l.lockAspect !== false && l.aspect && !l.pin) h = round(w / l.aspect);
      if (section().cover) {
        l.box.h = clamp(h, 1, pageHeight());
        l.box.y = clamp(y, 0, pageHeight() - l.box.h);
        placeOnCover(l, left, w);
      } else {
        l.box = { x: left - side * pageWidth(), y, w, h };
        settle(l);
      }
      l.angle = ((((angle + 180) % 360) + 360) % 360) - 180;
    }),
  );
});
canvas.on('text:editing:exited', ({ target }) => {
  const l = allLayers().find(l => l.id === target.masterId);
  if (l && l.text !== target.text)
    commit(() => {
      l.text = target.text.slice(0, 2000);
      l.box.h = round(Math.min(pageHeight() - l.box.y, target.height));
    });
});
