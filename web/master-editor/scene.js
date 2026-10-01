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
    const part = geo.parts,
      photoX = part.photo.x,
      photoY = part.photo.y,
      pad = Math.min(geo.overInset, geo.photoW / 4);
    /* A short last row may stand in the middle of the full rows above it. */
    const lastStart = records.length - (records.length % geo.cols || geo.cols),
      lastShift = l.centerLastRow ? ((geo.cols - (records.length - lastStart)) * (geo.cellW + l.gap)) / 2 : 0;
    for (let i = 0; i < records.length; i++) {
      const x = geo.offsetX + (i % geo.cols) * (geo.cellW + l.gap) + (i >= lastStart ? lastShift : 0),
        y = geo.offsetY + Math.floor(i / geo.cols) * (geo.cellH + l.gap),
        px = x + photoX,
        py = y + photoY;
      const el = await imageElement(planner.placeholderSvg(records[i]));
      /* The portrait covers the photo box whatever its proportions. */
      const cover = Math.max(geo.photoW / el.naturalWidth, geo.photoH / el.naturalHeight),
        photo = new fabric.FabricImage(el, {
          left: px + geo.photoW / 2,
          top: py + geo.photoH / 2,
          originX: 'center',
          originY: 'center',
          scaleX: cover,
          scaleY: cover,
          opacity: records[i].missing ? 0.2 : 1,
        }),
        corner = Math.min(Number(l.radius) || 0, geo.photoW / 2, geo.photoH / 2);
      photo.clipPath = new fabric.Rect({
        width: geo.photoW / cover,
        height: geo.photoH / cover,
        rx: corner / cover,
        ry: corner / cover,
        originX: 'center',
        originY: 'center',
      });
      if (l.shadow)
        shadows.push(
          new fabric.Rect({
            left: px - reach,
            top: py - reach,
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
            left: px + geo.photoW / 2,
            top: py + geo.photoH / 2,
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
      const nameBox = new fabric.Textbox(AutoText.applyCase(records[i].name, l.textCase), {
        left: x + part.name.x,
        top: y + part.name.y,
        width: part.name.w,
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
        ...captionLookPaint(l, 'name'),
      });
      const detailText = l.showDetail && records[i].detail && part.detail ? AutoText.applyCase(records[i].detail, l.detailTextCase) : '',
        detailBox = detailText
          ? new fabric.Textbox(detailText, {
              left: x + part.detail.x,
              top: y + part.detail.y,
              width: part.detail.w,
              fontFamily: l.detailFont || l.font,
              fontWeight: l.detailBold ? 'bold' : 'normal',
              fontStyle: l.detailItalic ? 'italic' : 'normal',
              underline: !!l.detailUnderline,
              linethrough: !!l.detailStrike,
              /* Each subject or quote shrinks on its own card, as in print. */
              fontSize: planner.detailFont(l, geo, detailText).size * 0.3528,
              lineHeight: l.detailLineHeight || 1.25,
              charSpacing: (Number(l.detailLetterSpacing) || 0) * 10,
              textAlign: l.detailAlign || 'center',
              fill: l.detailColor || l.color,
              ...captionLookPaint(l, 'detail'),
            })
          : null;
      /* Slanted like page texts: each line leans around its own baseline, as in print. */
      applyTextSkew(nameBox, l.skew);
      if (detailBox) applyTextSkew(detailBox, l.detailSkew);
      /* Captions of one zone hug each other; over the photo they rest on its bottom edge, beside it they stand at the
         set height by the text they really have, so «низ» puts the last line at the photo foot (as in master_layout). */
      const floor = py + geo.photoH - pad,
        beside = zone => zone === 'left' || zone === 'right',
        height = clamp(Number(l.sideAlign ?? 0.5) || 0, 0, 1),
        stand = h => py + Math.max(0, (geo.photoH - h) * height);
      if (beside(part.name.zone))
        nameBox.set(
          'top',
          stand(
            nameBox.height +
              (detailBox && part.detail.zone === part.name.zone ? geo.nameDetailGap + detailBox.height : 0),
          ),
        );
      if (detailBox && beside(part.detail.zone) && part.detail.zone !== part.name.zone)
        detailBox.set('top', stand(detailBox.height));
      if (detailBox && part.detail.zone === 'over') detailBox.set('top', floor - detailBox.height);
      if (part.name.zone === 'over')
        nameBox.set(
          'top',
          (detailBox && part.detail.zone === 'over' ? detailBox.top - geo.nameDetailGap : floor) - nameBox.height,
        );
      else if (detailBox && part.detail.zone === part.name.zone)
        detailBox.set('top', nameBox.top + nameBox.height + geo.nameDetailGap);
      children.push(nameBox);
      if (detailBox) children.push(detailBox);
      cards.push({
        x,
        y,
        photo: { x: px, y: py, w: geo.photoW, h: geo.photoH },
        name: { x: nameBox.left, y: nameBox.top, w: part.name.w, h: nameBox.height, zone: part.name.zone },
        detail: detailBox
          ? { x: detailBox.left, y: detailBox.top, w: part.detail.w, h: detailBox.height, zone: part.detail.zone }
          : null,
      });
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
      )
      /* Vignette pages show the chosen number of cards, not the whole test class (card.js). */
      .map((g, side) => previewPage(sec.spreads[view.spread].pages[side], g));
  const objects = [],
    backs = [],
    spineFills = [];
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
    if (side === 1 && sec.cover && sec.spineColor && spineGap() > 0)
      spineFills.push(
        Object.assign(
          new fabric.Rect({
            left: pageWidth(),
            top: 0,
            width: spineGap(),
            height: pageHeight(),
            fill: sec.spineColor,
            strokeWidth: 0,
            selectable: false,
            evented: false,
          }),
          { spineFill: true },
        ),
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
          flipX: !!l.flipX && l.type !== 'grid' && l.type !== 'collage',
          flipY: !!l.flipY && l.type !== 'grid' && l.type !== 'collage',
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
        object = new (FrameText())(AutoText.applyCase(planner.resolvedText(l, g), l.textCase), {
          ...base,
          width: b.w,
          frameHeight: b.h,
          valign: l.valign || 'top',
          fit: !!l.fit,
          fitBase: l.fontSize * 0.3528,
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
          editable: false,
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
            // Always clipped to the box: an SVG photo is not cropped exactly and would spill past it.
            object.clipPath = new fabric.Rect({
              width: cw,
              height: ch,
              rx: ((Number(l.radius) || 0) * cw) / b.w,
              ry: ((Number(l.radius) || 0) * ch) / b.h,
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
        object.vignette = { geo: built.geo, cards: built.cards, part: g?.part || 1, parts: g?.parts || 1 };
        /* A vignette is never rotated or mirrored. */
        object.set({ lockRotation: true });
        object.setControlVisible('mtr', false);
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
              // Always clipped to the frame: an SVG photo is not cropped exactly and would spill into the gaps.
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
      // A spine anchor also belongs to ordinary shapes crossing the fold.
      // Designated spine text stays above the paint. Legacy spine titles were rotated 90°.
      object.spineText = !!sec.cover && isSpineContent(l);
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
  // Both sides from one spread of the design stack as that spread says; pages paired otherwise stay side by side.
  const ids = (pages || []).map(g => g?.templateId).filter(Boolean),
    owner = sec.spreads.find(sp => ids.length && ids.every(id => sp.pages.some(p => p.id === id)));
  if (owner) {
    const rank = new Map(spreadStack(owner).map((l, i) => [l.id, i]));
    objects.sort((a, b) => (rank.get(a.masterId) ?? 0) - (rank.get(b.masterId) ?? 0));
  }
  changing = true;
  canvas.discardActiveObject();
  canvas.clear();
  canvas.backgroundColor = '#f0f0f2';
  const artwork = spineFills.length ? objects.filter(o => !o.spineText) : objects,
    spineText = spineFills.length ? objects.filter(o => o.spineText) : [];
  canvas.add(...backs, ...artwork, ...spineFills, ...spineText, ...bookMarks(), ...safetyGuides());
  const targets = objects.filter(o => selected.includes(o.masterId) && o.selectable);
  if (targets.length === 1) canvas.setActiveObject(targets[0]);
  else if (targets.length > 1) canvas.setActiveObject(new fabric.ActiveSelection(targets, { canvas }));
  canvas.requestRenderAll();
  changing = false;
  syncTextOverflow();
  placeCollageUi();
  placePhotoCropUi();
}
function syncSelectionCoords() {
  const active = canvas.getActiveObject();
  if (!active) return;
  active.setCoords();
  if (active instanceof fabric.ActiveSelection) active.forEachObject(o => o.setCoords());
}
/* Canvas zoom: 2 px per mm reads as 100 %. The buttons walk through round presets, the wheel and pinch zoom by their delta. */
const ZOOM_MIN = 0.2,
  ZOOM_MAX = 32,
  ZOOM_PRESETS = [10, 25, 50, 75, 100, 150, 200, 300, 400, 600, 800, 1200, 1600];
let zoomAnimation = 0;
function updateZoomControls() {
  const zoom = canvas.getZoom();
  $('#zoom-value').textContent = `${Math.round(zoom * 50)}%`;
  $('#zoom-out').disabled = zoom <= ZOOM_MIN + 1e-6;
  $('#zoom-in').disabled = zoom >= ZOOM_MAX - 1e-6;
  $('#zoom-fit').setAttribute('aria-pressed', zoomMode === 'fit');
}
function viewportChanged() {
  syncSelectionCoords();
  if (snapMarks.length) renderGuides();
  placeCollageUi();
  placePhotoCropUi();
  updateZoomControls();
}
/* Zoom keeping the scene point under `point` (host pixels) in place. */
function zoomAt(zoom, point) {
  zoom = clamp(zoom, ZOOM_MIN, ZOOM_MAX);
  canvas.zoomToPoint(new fabric.Point(point.x, point.y), zoom);
  zoomMode = zoom / 2;
  viewportChanged();
}
function hostCenter() {
  const host = $('#canvas-host');
  return { x: host.clientWidth / 2, y: host.clientHeight / 2 };
}
function animateZoom(target, point = hostCenter()) {
  cancelAnimationFrame(zoomAnimation);
  const from = canvas.getZoom(),
    to = clamp(target, ZOOM_MIN, ZOOM_MAX),
    start = performance.now(),
    duration = 140;
  if (Math.abs(to - from) < 1e-6) return;
  if (document.hidden) return zoomAt(to, point);
  const frame = now => {
    const t = Math.min(1, Math.max(0, now - start) / duration),
      eased = 1 - Math.pow(1 - t, 3);
    zoomAt(from * Math.pow(to / from, eased), point);
    if (t < 1) zoomAnimation = requestAnimationFrame(frame);
  };
  zoomAnimation = requestAnimationFrame(frame);
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
  const percent = canvas.getZoom() * 50,
    next =
      direction > 0
        ? ZOOM_PRESETS.find(p => p > percent * 1.01)
        : [...ZOOM_PRESETS].reverse().find(p => p < percent / 1.01);
  if (next) animateZoom(next / 50);
}
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
/* The cover unfolds as back · spine · front; the spine width follows the book's volume and sheet thickness (or is fixed without a thickness). The canvas shows a book of the design's own spreads, or the volume picked in the cover panel. */
function editorVolume() {
  const spreads =
    view.coverSpreads || doc.sections.filter(s => !s.cover).reduce((n, s) => n + s.spreads.length, 0);
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
/* A layer may hang past the page edges (a decoration half off the trim is cut in print), but a strip of it stays on the sheet so it can be picked up again. */
const KEEP_ON_SHEET = 10;
function keepOnSheet(pos, size, from, to) {
  const keep = Math.min(size, KEEP_ON_SHEET);
  return round(clamp(pos, from - size + keep, to - keep));
}
function maxLayerSize() {
  return 2 * Math.max(pageWidth(), pageHeight());
}
/* A cover layer lives on the side that holds its centre, so it stacks above that side's layers; a wrap runs under both sides and stays with the back. */
function placeOnCover(l, left, width, top = l.box.y, height = l.box.h) {
  const W = pageWidth(),
    H = pageHeight(),
    s = spineGap(),
    pages = section().spreads[0].pages,
    max = maxLayerSize(),
    h = clamp(height, 1, max),
    w = clamp(width, 1, max + s),
    L = keepOnSheet(left, w, 0, 2 * W + s),
    R = L + w,
    eps = 0.5;
  let side = 0,
    pin = null,
    x = L,
    bw = Math.min(w, max);
  if (R <= W + eps);
  else if (L >= W + s - eps) {
    side = 1;
    x = L - W - s;
  } else if (L <= W + eps && R >= W + s - eps && wrapKinds.has(l.type) && w - s >= W / 2) {
    pin = 'wrap';
    bw = clamp(w - s, 1, max);
  } else {
    pin = 'spine';
    x = L - W - s / 2;
    side = L + w / 2 >= W + s / 2 ? 1 : 0;
  }
  if (pin) l.pin = pin;
  else delete l.pin;
  if (pin !== 'spine') delete l.spineContent;
  l.box.x = round(x);
  l.box.w = round(bw);
  l.box.h = round(h);
  l.box.y = keepOnSheet(top, l.box.h, 0, H);
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
  placeOnCover(l, layerOffset(l, layerSide(l)) + l.box.x, layerW(l));
}
/* A layer belongs to a page but may cross the fold and hang past the edges: it keeps a strip on the spread and moves to the page that holds its centre. Vignettes stay inside their page. */
function layerSide(l) {
  const i = (section().spreads[view.spread]?.pages || []).findIndex(p => p.layers.includes(l));
  return i < 0 ? 0 : i;
}
function fitSpread(l) {
  const W = pageWidth(),
    H = pageHeight(),
    b = l.box;
  if (l.type === 'grid') {
    b.w = clamp(b.w, 1, W);
    b.h = clamp(b.h, 1, H);
    b.x = clamp(b.x, 0, W - b.w);
    b.y = clamp(b.y, 0, H - b.h);
    return;
  }
  const side = layerSide(l),
    max = maxLayerSize();
  b.w = clamp(b.w, 1, max);
  b.h = clamp(b.h, 1, max);
  b.x = keepOnSheet(b.x, b.w, -side * W, (2 - side) * W);
  b.y = keepOnSheet(b.y, b.h, 0, H);
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
      if (section().cover) placeOnCover(l, left, w, y, h);
      else {
        l.box = { x: left - side * pageWidth(), y, w, h };
        settle(l);
      }
      l.angle = ((((angle + 180) % 360) + 360) % 360) - 180;
    }),
  );
});
