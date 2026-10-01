/* Master editor · Global handlers, keyboard, file menu and start-up. */
'use strict';
$('#object-menu').onclick = e => {
  const b = e.target.closest('[data-object-menu]');
  if (!b || b.disabled) return;
  const type = b.dataset.objectMenu;
  closeObjectMenu();
  if (type === 'copy') return copyLayers();
  if (type === 'paste') return pasteLayers();
  if (type === 'reveal')
    return commit(() => {
      (page()?.layers || []).forEach(l => {
        if (l.hidden) l.hidden = false;
      });
    });
  action(type);
};
$('#object-menu').addEventListener('contextmenu', e => e.preventDefault());
$('#canvas-host').addEventListener('contextmenu', e => {
  if (e.target.closest('textarea,input')) return;
  e.preventDefault();
  if (e.target.tagName === 'CANVAS') return;
  openObjectMenu(e, canvas.findTarget(e));
});
document.addEventListener(
  'pointerdown',
  e => {
    if (!e.target.closest('#object-menu')) closeObjectMenu();
  },
  true,
);
document.addEventListener('wheel', () => closeObjectMenu(), { capture: true, passive: true });
window.addEventListener('resize', closeObjectMenu);
$$('[data-tool]').forEach(
  b =>
    (b.onclick = () => {
      selected = [];
      canvas.discardActiveObject();
      setTool(b.dataset.tool);
    }),
);
$('#pointer-caret').onclick = e => {
  e.stopPropagation();
  toggleToolPop('pointer');
};
$('#shape-caret').onclick = e => {
  e.stopPropagation();
  toggleToolPop('shape');
};
$('#frame-caret').onclick = e => {
  e.stopPropagation();
  toggleToolPop('frame');
};
$('#pointer-pop').onclick = e => {
  const b = e.target.closest('[data-pointer]');
  if (!b) return;
  setTool(b.dataset.pointer);
};
$('#frame-pop').onclick = e => {
  const b = e.target.closest('[data-frame]');
  if (!b) return;
  frameKind = b.dataset.frame;
  setTool(frameKind);
};
$('#shape-pop').onclick = e => {
  const b = e.target.closest('[data-shape]');
  if (!b) return;
  shapeKind = b.dataset.shape;
  $('#shape-icon').src = 'assets/editor/' + shapeKind + '.svg';
  $$('#shape-pop [data-shape]').forEach(x => x.classList.toggle('active', x.dataset.shape === shapeKind));
  setTool('shape');
  if (shapeKind === 'svg') pickSvg();
};
document.addEventListener('click', e => {
  if (!e.target.closest('.tool-menu')) closeToolPops();
});
function ratioOf(el, e) {
  const r = el.getBoundingClientRect();
  return { x: clamp((e.clientX - r.left) / r.width, 0, 1), y: clamp((e.clientY - r.top) / r.height, 0, 1) };
}
function bindColorDrag(el, fn) {
  const move = e => {
    if (!colorPop) return;
    fn(ratioOf(el, e));
    syncColorPop();
  };
  el.onpointerdown = e => {
    e.stopPropagation();
    el.setPointerCapture(e.pointerId);
    move(e);
  };
  el.onpointermove = e => {
    if (e.buttons) move(e);
  };
}
bindColorDrag($('#color-sv'), p => {
  colorPop.hsv.s = p.x;
  colorPop.hsv.v = 1 - p.y;
});
bindColorDrag($('#color-hue'), p => {
  colorPop.hsv.h = p.x * 359.9;
});
bindColorDrag($('#color-alpha'), p => {
  colorPop.opacity = Math.round(p.x * 100);
});
$('#color-hex').oninput = e => {
  if (!colorPop) return;
  let v = e.target.value.trim();
  if (!v.startsWith('#')) v = '#' + v;
  if (!/^#[0-9a-fA-F]{6}$/.test(v)) return;
  colorPop.hsv = hexToHsv(v);
  syncColorPop();
};
$('#color-alpha-input').oninput = e => {
  if (!colorPop) return;
  colorPop.opacity = clamp(Number(e.target.value) || 0, 0, 100);
  syncColorPop();
};
$('#color-pop').onpointerdown = e => {
  const b = e.target.closest('[data-swatch]');
  if (!b || !colorPop) return;
  e.preventDefault();
  colorPop.hsv = hexToHsv(b.dataset.swatch);
  syncColorPop();
};
function stopCanvasPipette() {
  colorPicking = false;
  document.body.classList.remove('color-picking');
  if (colorPop) syncColorPop(false);
}
function pickCanvasColor(e) {
  if (!colorPicking) return;
  e.preventDefault();
  e.stopImmediatePropagation();
  if (!e.target.closest('#canvas-host')) return stopCanvasPipette();
  try {
    const surface = canvas.lowerCanvasEl,
      rect = surface.getBoundingClientRect(),
      x = Math.floor(((e.clientX - rect.left) * surface.width) / rect.width),
      y = Math.floor(((e.clientY - rect.top) * surface.height) / rect.height);
    if (x >= 0 && y >= 0 && x < surface.width && y < surface.height) {
      const pixel = surface.getContext('2d').getImageData(x, y, 1, 1).data;
      const hex =
        '#' +
        [...pixel]
          .slice(0, 3)
          .map(n => n.toString(16).padStart(2, '0'))
          .join('');
      colorPop.hsv = hexToHsv(hex);
      syncColorPop();
    }
  } catch {
    notify('Не удалось взять цвет с холста', true);
  }
  stopCanvasPipette();
}
$('#color-eyedropper').onclick = async () => {
  if (!colorPop) return;
  if (typeof EyeDropper === 'function') {
    const current = colorPop;
    try {
      const result = await new EyeDropper().open();
      if (colorPop === current && /^#[0-9a-f]{6}$/i.test(result.sRGBHex)) {
        colorPop.hsv = hexToHsv(result.sRGBHex);
        syncColorPop();
      }
    } catch (e) {
      if (e.name !== 'AbortError') notify('Не удалось взять цвет с экрана', true);
    }
    return;
  }
  colorPicking = true;
  $('#color-pop').hidden = true;
  document.body.classList.add('color-picking');
  notify('Нажмите на цвет на холсте. Esc — отмена.');
};
document.addEventListener('pointerdown', pickCanvasColor, true);
document.addEventListener(
  'keydown',
  e => {
    if (colorPicking && e.key === 'Escape') {
      e.preventDefault();
      stopCanvasPipette();
    }
  },
  true,
);
document.addEventListener(
  'pointerdown',
  e => {
    if (colorPop && !colorPicking && !e.target.closest('#color-pop') && !e.target.closest('[data-color-key]'))
      closeColor(false);
  },
  true,
);
$('#inspector').oninput = e => {
  const el = e.target;
  /* Number cells grow with their value; sliders keep their width. */
  if (
    el.type !== 'range' &&
    (el.dataset?.live === 'letterSpacing' ||
    el.dataset?.live === 'skew' ||
    vignetteLiveKeys.has(el.dataset?.live) ||
    el.closest?.('.vignette-max') ||
    el.closest('.collage-gaps') ||
    el.closest('.layer-metrics'))
  )
    el.style.width = Math.max(1, el.value.length) + 'ch';
  if (!el.dataset?.live || el.value === '' || !el.validity.valid) return;
  const value = Number(el.value);
  if (selectedLayer()?.type === 'grid' && (vignetteLiveKeys.has(el.dataset.live) || captionLookKey(el.dataset.live)))
    vignetteLive(el.dataset.live, value);
  else if (selectedLayer()?.type === 'grid' && (el.dataset.live === 'box.w' || el.dataset.live === 'box.h'))
    vignetteBoxLive(el.dataset.live.slice(4), value);
  else liveProperty(el.dataset.live, value);
  const badge = el.parentElement?.querySelector('b');
  if (badge) badge.textContent = String(String(el.step).includes('.') ? round(value) : Math.round(value));
};
$('#inspector').onpointerdown = e => {
  const range = e.target.closest && e.target.closest('input[type=range][data-live]');
  if (range && !slide) slide = { start: clone(doc) };
};
$('#inspector').onchange = async e => {
  if (MasterPhotos.change(e)) return;
  const el = e.target;
  /* Cards-per-page limits of the block's list. A typed «до» stays a limit even when more would fit later; an empty one
     means as many as fit, and the page follows the area when it changes. */
  if (el.dataset.list) {
    cardsPreview = 0;
    if (el.dataset.list === 'max' && el.value === '') return blockSet('max', 100);
    if (el.value === '' || !el.validity.valid) return el.reportValidity();
    return blockSet(el.dataset.list, value);
  }
  if (el.dataset.flex) {
    const l = selectedLayer();
    if (!l?.flex) return;
    if (el.value === '' || !el.validity.valid) {
      el.reportValidity();
      return;
    }
    const key = el.dataset.flex,
      v = clamp(Math.round(Number(el.value)) || 1, 1, CollageCore.FLEX_MAX);
    commit(() => {
      const t = selectedLayer();
      t.flex = { ...t.flex, [key]: v };
      if (t.flex.min > t.flex.max) {
        if (key === 'min') t.flex.max = v;
        else t.flex.min = v;
      }
      if (flexShow[t.id] > t.flex.max) delete flexShow[t.id];
    });
    return;
  }
  if (el.dataset?.live) {
    finishSlide();
    return;
  }
  if (el.id === 'font-upload') {
    const file = el.files?.[0];
    el.value = '';
    if (!file) return;
    if (file.size > 1500000) return notify('Шрифт больше 1,5 МБ', true);
    if ((doc.fonts || []).length >= 12) return notify('В макете уже 12 шрифтов', true);
    const bytes = new Uint8Array(await file.arrayBuffer());
    const format = fontKind(bytes);
    if (!format) return notify('Нужен файл TTF или OTF', true);
    const name = (file.name.replace(/\.(ttf|otf)$/i, '').trim() || 'Шрифт').slice(0, 60);
    const id = 'font-' + uid();
    const dataUrl = 'data:font/' + format + ';base64,' + bytesToBase64(bytes);
    commit(() => {
      doc.fonts = [...(doc.fonts || []), { id, name, dataUrl }];
      const layer = selectedLayer();
      if (layer?.type === 'text') setTextFormat(layer, 'font', id);
      else if (layer?.type === 'grid')
        section()
          .spreads.flatMap(sp => sp.pages.flatMap(p => p.layers))
          .filter(item => item.type === 'grid')
          .forEach(item => (item[el.dataset.fontTarget || 'font'] = id));
    });
    return;
  }
  if (el.id === 'photo-upload' || el.id === 'cell-upload') {
    const file = el.files?.[0];
    if (!file) return;
    if (file.size > 1_000_000 || !['image/jpeg', 'image/png', 'image/webp'].includes(file.type))
      return notify('Выберите PNG, JPEG или WebP до 1 МБ', true);
    const target = selectedLayer();
    if (!target) return;
    const targetId = target.id, targetDocument = doc, cellId = el.id === 'cell-upload' ? focusCell : null;
    if (el.id === 'cell-upload' && !cellId) return;
    const reader = new FileReader();
    reader.onload = () => {
      if (preview || doc !== targetDocument) return notify('Макет изменился. Выберите файл заново.', true);
      const live = allLayers().find(l => l.id === targetId);
      const item = cellId && live ? locateCell(live, cellId)?.cell : live;
      if (!live || !item || item.split || (cellId && live.flex))
        return notify('Исходный кадр удалён или изменён. Выберите файл заново.', true);
      commit(() => CollageCore.setSource(item, 'custom', { dataUrl: reader.result }));
      el.value = '';
    };
    reader.onerror = () => notify('Не удалось прочитать изображение', true);
    reader.readAsDataURL(file);
    return;
  }
  if (!el.dataset.prop) return;
  if (el.type === 'number' && !el.reportValidity()) return;
  const value = ['bold', 'detailBold'].includes(el.dataset.prop)
    ? el.value === 'true'
    : el.type === 'checkbox'
      ? el.checked
      : el.type === 'number'
        ? Number(el.value)
        : el.value;
  property(el.dataset.prop, value);
};
let scrub = null;
/* A number field drags from its icon and padding; the digits themselves stay a plain text field to select and retype. */
document.addEventListener('pointerdown', e => {
  const field = e.target.closest('.type-value[data-scrub]');
  if (!field || e.button !== 0 || e.target.tagName === 'INPUT') return;
  const input = field.querySelector('input[data-live],input[data-list],input[data-album-size],input[data-sheet-thickness]');
  if (!input) return;
  scrub = {
    field,
    input,
    pointerId: e.pointerId,
    startX: e.clientX,
    start: Number(input.value || input.placeholder),
    step: Number(field.dataset.step),
    min: Number(field.dataset.min),
    max: Number(field.dataset.max),
    dragging: false,
  };
});
document.addEventListener('pointermove', e => {
  if (!scrub || e.pointerId !== scrub.pointerId) return;
  const { field, input, startX, start, step, min, max } = scrub,
    delta = e.clientX - startX;
  if (!scrub.dragging) {
    if (Math.abs(delta) < 4) return;
    scrub.dragging = true;
    field.classList.add('scrubbing');
    field.setPointerCapture(e.pointerId);
  }
  e.preventDefault();
  const steps = Math.round(delta / 5),
    decimals = (String(step).split('.')[1] || '').length,
    value = Number(clamp(start + steps * step, min, max).toFixed(decimals));
  if (Number(input.value) === value) return;
  input.value = String(value);
  input.dispatchEvent(new Event('input', { bubbles: true }));
});
function endScrub(e) {
  if (!scrub || e.pointerId !== scrub.pointerId) return;
  const { field, input, dragging } = scrub;
  scrub = null;
  field.classList.remove('scrubbing');
  if (dragging) {
    if (input.dataset.albumSize || input.dataset.list || input.hasAttribute('data-sheet-thickness'))
      input.dispatchEvent(new Event('change', { bubbles: true }));
    else finishSlide();
  } else if (e.type === 'pointerup') {
    input.focus();
    input.select();
  }
}
document.addEventListener('pointerup', endScrub);
document.addEventListener('pointercancel', endScrub);
/* Layer rows reorder by dragging, like Photoshop; the drop line shows where the layer lands. */
let layerDrag = null;
const layerDropMark = (row, above) => {
  document.querySelectorAll('#inspector .editor-layer.drop-above, #inspector .editor-layer.drop-below').forEach(el => el.classList.remove('drop-above', 'drop-below'));
  if (row) row.classList.add(above ? 'drop-above' : 'drop-below');
};
const layerDropAt = e => {
  const row = e.target.closest('[data-layer-row]');
  if (!row || !layerDrag || row.dataset.layerRow === layerDrag) return null;
  const box = row.getBoundingClientRect();
  return { row, above: e.clientY < box.top + box.height / 2 };
};
$('#inspector').addEventListener('dragstart', e => {
  const row = e.target.closest?.('[data-layer-row]');
  if (!row) return;
  layerDrag = row.dataset.layerRow;
  row.classList.add('is-dragging');
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', layerDrag);
});
$('#inspector').addEventListener('dragover', e => {
  const drop = layerDropAt(e);
  layerDropMark(drop?.row, drop?.above);
  if (drop) e.preventDefault();
});
$('#inspector').addEventListener('drop', e => {
  const drop = layerDropAt(e), id = layerDrag;
  layerDropMark(null);
  if (!drop) return;
  e.preventDefault();
  layerPanelMove(id, drop.row.dataset.layerRow, drop.above);
});
$('#inspector').addEventListener('dragend', () => {
  layerDrag = null;
  layerDropMark(null);
  document.querySelectorAll('#inspector .is-dragging').forEach(el => el.classList.remove('is-dragging'));
});
$('#inspector').onclick = e => {
  const layerAction = e.target.closest('[data-layer-action]');
  if (layerAction) {
    layerPanelAction(layerAction.dataset.layerId, layerAction.dataset.layerAction);
    return;
  }
  const layerButton = e.target.closest('[data-layer-select]');
  if (layerButton) {
    const id = layerButton.dataset.layerSelect;
    const sp = section().spreads[view.spread];
    view.side = Math.max(0, sp.pages.findIndex(p => p.layers.some(l => l.id === id)));
    selected = [id]; focusCell = null;
    renderInspector(); renderScene();
    return;
  }
  if (MasterPhotos.click(e)) return;
  if (e.target.closest('[data-spine-color-off]')) return commit(() => delete coverSection().spineColor);
  if (e.target.closest('[data-spine-text]')) return addSpineText();
  const volumeBtn = e.target.closest('[data-cover-volume]');
  if (volumeBtn) {
    const step = volumeBtn.dataset.coverVolume;
    view.coverSource = null;
    view.coverSpreads = step === 'auto' ? null : clamp(editorVolume().spreads + Number(step), 1, 200);
    renderInspector();
    renderScene();
    return;
  }
  const albumButton = e.target.closest('[data-open-album]');
  if (albumButton) return openAlbum(albumButton.dataset.openAlbum);
  const collageMode = e.target.closest('[data-collage-mode]');
  if (collageMode) {
    const l = selectedLayer(),
      want = collageMode.dataset.collageMode === 'flex';
    if (l?.type !== 'collage' || want === !!l.flex) return;
    commit(() => {
      const t = selectedLayer();
      if (want) {
        const leaves = CollageCore.leaves(t),
          first = leaves.find(c => (c.source || 'class') === 'class');
        t.flex = { min: 1, max: clamp(leaves.length, 2, 4) };
        t.pick = MasterPhotos.upgrade(first?.pick) || defaultPick();
      } else {
        delete t.flex;
        delete t.pick;
      }
      focusCell = null;
      cellMenu = null;
    });
    return;
  }
  const showButton = e.target.closest('[data-flex-show]');
  if (showButton) {
    const l = selectedLayer();
    if (!l) return;
    const n = Number(showButton.dataset.flexShow);
    if (n) flexShow[l.id] = n;
    else delete flexShow[l.id];
    renderInspector();
    renderScene();
    return;
  }
  if (e.target.closest('[data-open-block]')) return openBlockSettings();
  const cardPick = e.target.closest('[data-card-pick]');
  if (cardPick) return pickCardPart(cardPick.dataset.cardPick);
  /* «мешает …» leads to the setting it names, on the level that holds it: the vignette, the photo or the name. */
  const limiter = e.target.closest('[data-limiter]');
  if (limiter) {
    const key = limiter.dataset.limiter;
    if (!key) return;
    pickCardPart(
      ['minFontSize', 'captionWidth', 'photoNameGap'].includes(key)
        ? 'name'
        : ['minPhotoWidth', 'photoWidth'].includes(key)
          ? 'photo'
          : null,
    );
    const field = $(`#inspector [data-live="${key}"], #inspector [data-list="${key}"]`);
    if (!field) return;
    const box = field.closest('.type-value');
    box.scrollIntoView({ block: 'center', behavior: 'smooth' });
    box.classList.remove('flash');
    void box.offsetWidth;
    box.classList.add('flash');
    return field.focus({ preventScroll: true });
  }
  const safetyButton = e.target.closest('[data-open-safety]');
  if (safetyButton) return openSafety(safetyButton.dataset.openSafety);
  const colorBtn = e.target.closest('[data-color-key]');
  if (colorBtn) return openColor(colorBtn);
  const styleTrigger = e.target.closest('[data-open-style-menu]');
  if (styleTrigger) {
    openTextStyleMenu();
    return;
  }
  if (e.target.closest('[data-text-style-detach]')) return property('styleId', '');
  const styleAction = e.target.closest('[data-text-style]');
  if (styleAction) {
    openTextStyleMenu(styleAction.dataset.textStyle);
    return;
  }
  const removeFont = e.target.closest('[data-font-remove]');
  if (removeFont) {
    const id = removeFont.dataset.fontRemove;
    loadedFonts.delete(id);
    commit(() => {
      doc.fonts = (doc.fonts || []).filter(font => font.id !== id);
      allLayers().forEach(layer => {
        if (layer.font === id) layer.font = 'Arial';
      });
      (doc.textStyles || []).forEach(style => {
        if (style.font === id) style.font = 'Arial';
      });
    });
    return;
  }
  const contentKind = e.target.closest('[data-content-kind]'),
    contentSource = e.target.closest('[data-content-source]');
  if (contentKind || contentSource) {
    const item = contentTarget();
    if (!item) return;
    const current = item.source || 'class',
      wanted = contentSource
        ? contentSource.dataset.contentSource
        : {
            class: 'class',
            custom: 'custom',
            portrait: CollageCore.PORTRAITS.includes(current) ? current : 'owner',
          }[contentKind.dataset.contentKind];
    if (wanted === current) return;
    if (photoCrop) endPhotoCrop(false);
    commit(() => {
      const target = contentTarget();
      if (target)
        CollageCore.setSource(
          target,
          wanted,
          wanted === 'class' && !target.pick ? { pick: defaultPick() } : {},
        );
    });
    return;
  }
  if (e.target.closest('[data-content-crop]')) {
    const l = selectedLayer();
    startPhotoCrop(l, l?.type === 'collage' ? focusCell : null);
    return;
  }
  const gapLink = e.target.closest('[data-gap-link]');
  if (gapLink) {
    const l = selectedLayer();
    if (l?.type === 'collage') property('gapLinked', !CollageCore.gapsLinked(l));
    return;
  }
  const collageButton = e.target.closest('[data-collage]');
  if (collageButton) {
    if (!collageButton.disabled) commit(() => collageAction(collageButton.dataset.collage));
    return;
  }
  const choice = e.target.closest('[data-choice]');
  if (choice) {
    const key = choice.dataset.choice,
      l = selectedLayer();
    if (!l) return;
    if (key === 'showDetail') return property('showDetail', !l.showDetail);
    if (key === 'photoRatio' || key === 'leadRatio') return property(key, Number(choice.dataset.value));
    if (key === 'strokeOn') return property('strokeOn', !strokeOpen(l));
    if (key === 'shadowOn') return property('shadowOn', !l.shadow);
    const look = l.type === 'grid' && captionLookKey(key);
    if (look) return commit(() => setCaptionLook(key, !l[look.field]));
    if (key === 'lockAspect') return property('lockAspect', l.lockAspect === false);
    if (
      key === 'flipX' ||
      key === 'flipY' ||
      key === 'fit' ||
      key === 'bold' ||
      key === 'italic' ||
      key === 'underline' ||
      key === 'strike' ||
      key === 'detailBold' ||
      key === 'detailItalic' ||
      key === 'detailUnderline' ||
      key === 'detailStrike' ||
      key === 'showDetail' ||
      key === 'centerLastRow'
    )
      return property(key, !l[key]);
    return property(key, choice.dataset.value);
  }
  const toggle = e.target.closest('[data-toggle]');
  if (toggle) {
    const key = toggle.dataset.toggle,
      l = selectedLayer();
    if (!l) return;
    if (key === 'stroke.on') return property('strokeOn', !strokeOpen(l));
    if (key === 'shadow') return property('shadowOn', !l.shadow);
    return property(key, !l[key]);
  }
  const a0 = e.target.closest('[data-action]');
  if (a0 && a0.dataset.action === 'replace-svg') {
    pickSvg(selectedLayer()?.id);
    return;
  }
  const cellBtn = e.target.closest('[data-cell]');
  if (cellBtn) {
    focusCell = cellBtn.dataset.cell;
    renderInspector();
    renderScene();
    return;
  }
  const col = e.target.closest('[data-collage]');
  if (col) return commit(() => collageAction(col.dataset.collage));
  const alignment = e.target.closest('[data-align]');
  if (alignment) return align(alignment.dataset.align);
  const a = e.target.closest('[data-action]');
  if (a) return action(a.dataset.action);
  if (e.target.dataset.side) {
    view.side = Number(e.target.dataset.side);
    selected = [];
    renderInspector();
  }
};
document.addEventListener('click', e => {
  if (
    textStyleMenu &&
    !textStyleMenu.element.contains(e.target) &&
    !e.target.closest('[data-open-style-menu],[data-text-style]')
  )
    closeTextStyleMenu();
});
document.addEventListener(
  'keydown',
  e => {
    if (e.key === 'Escape' && textStyleMenu) {
      e.preventDefault();
      e.stopImmediatePropagation();
      closeTextStyleMenu();
    }
  },
  true,
);
document.addEventListener('input', e => {
  if (e.target.matches('[data-style-search]')) filterTextStyles(e.target.value);
});
document.addEventListener('click', e => {
  if (!textStyleMenu || !textStyleMenu.element.contains(e.target)) return;
  const close = e.target.closest('[data-style-close]');
  if (close) {
    closeTextStyleMenu();
    return;
  }
  const mode = e.target.closest('[data-style-mode]');
  if (mode) {
    openTextStyleMenu(mode.dataset.styleMode);
    return;
  }
  const option = e.target.closest('[data-style-option]');
  if (option) {
    const id = option.dataset.styleOption;
    closeTextStyleMenu();
    property('styleId', id);
  }
});
document.addEventListener('submit', e => {
  if (!e.target.matches('[data-style-form]')) return;
  e.preventDefault();
  submitTextStyleMenu(e.target.elements.namedItem('name').value);
});
$$('[data-inspector]').forEach(
  b =>
    (b.onclick = () => {
      inspectorTab = b.dataset.inspector;
      renderInspector();
    }),
);
$('#prev-spread').onclick = () => {
  view.spread--;
  selected = [];
  render();
};
$('#next-spread').onclick = () => {
  view.spread++;
  selected = [];
  render();
};
$('#spread-select').onchange = e => {
  view.spread = Number(e.target.value);
  selected = [];
  render();
};
$('#add-section').onclick = () => openBlockDialog();
$('#album-settings').onclick = () => openAlbum('format');
$('#add-spread').onclick = () => {
  if (section().cover) return;
  commit(() => {
    section().spreads.splice(view.spread + 1, 0, {
      id: uid(),
      ...(section().kind === 'flow' ? { role: 'outro' } : {}),
      pages: [
        { id: uid(), background: '#ffffff', layers: [] },
        { id: uid(), background: '#ffffff', layers: [] },
      ],
    });
    view.spread++;
    selected = [];
  });
};
$('#duplicate-spread').onclick = () => {
  if (section().cover) return;
  commit(() => {
    const copy = freshIds(section().spreads[view.spread]);
    if (copy.role === 'last') copy.role = 'repeat';
    section().spreads.splice(view.spread + 1, 0, copy);
    view.spread++;
    selected = [];
  });
};
$('#delete-spread').onclick = () => {
  if (section().cover || section().spreads.length <= 1) return;
  commit(() => {
    section().spreads.splice(view.spread, 1);
    view.spread = Math.max(0, view.spread - 1);
    selected = [];
  });
};
$('#show-properties').onclick = () => $('.right-panel').classList.toggle('mobile-open');
$('#close-properties').onclick = () => $('.right-panel').classList.remove('mobile-open');
$('#zoom-out').onclick = () => stepZoom(-1);
$('#zoom-in').onclick = () => stepZoom(1);
$('#zoom-fit').onclick = () => {
  cancelAnimationFrame(zoomAnimation);
  zoomMode = 'fit';
  fit();
};
$('#undo').onclick = undo;
$('#redo').onclick = redo;
$('#preview-toggle').onclick = () =>
  ClassPreview.open({
    document: () => clone(doc),
    templateId: async () => {
      if (!serverId) await save();
      return serverId;
    },
    sectionName: id => doc.sections.find(s => s.id === id)?.name,
    inspectCover: (spreads, label) => {
      view.coverSpreads = spreads;
      view.coverSource = {label: 'Из предпросмотра: ' + label, document: JSON.stringify(doc)};
      view.section = coverSection().id; view.spread = 0; selected = [];
      render();
    },
    revealIssue: key => {
      const parts = String(key).split('/');
      for (const sec of doc.sections) for (let n = 0; n < sec.spreads.length; n++)
        for (let side = 0; side < 2; side++) {
          const layer = sec.spreads[n].pages[side].layers.find(l => parts.includes(l.id));
          if (!layer) continue;
          view.section = sec.id; view.spread = n; view.side = side; selected = [layer.id];
          render(); return true;
        }
      notify('Ошибка относится к данным класса; проверьте фотографии и анкеты.', true);
      return false;
    },
  });
$('#retry-save').onclick = () => save().catch(() => {});
window.addEventListener('offline', () => {
  clearTimeout(saveTimer);
  updateSaveState();
});
window.addEventListener('online', () => {
  saveError = '';
  updateSaveState();
  scheduleAutosave(0);
});
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden' && dirty && navigator.onLine) save().catch(() => {});
});
$('#package-button').onclick = () => togglePackagePop();
$('#package-pop').onclick = async e => {
  const edit = e.target.closest('[data-package-edit]');
  if (edit) {
    togglePackagePop(false);
    return packageDialog('edit');
  }
  const option = e.target.closest('[data-package]');
  if (!option) return;
  togglePackagePop(false);
  if (option.dataset.package === serverId) return;
  try {
    if (dirty) await save();
    await load(option.dataset.package);
  } catch (error) {
    notify(error.message, true);
    renderHeader();
  }
};
document.addEventListener('click', e => {
  if (!e.target.closest('.package-menu')) togglePackagePop(false);
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && !$('#package-pop').hidden) {
    togglePackagePop(false);
    $('#package-button').focus();
  }
});
function packageDialog(mode) {
  packageMode = mode;
  $('#package-dialog-title').textContent = mode === 'new' ? 'Новая комплектация' : 'Настройки комплектации';
  $('#package-help').textContent =
    mode === 'new'
      ? 'Скопируем текущие блоки. Правки новой комплектации не изменят исходную.'
      : 'Название и цена относятся к этой комплектации. Для новых заказов опубликуйте новую версию.';
  $('#package-form [name=name]').value = mode === 'edit' ? packageMeta?.name || 'Основная' : '';
  $('#package-form [name=price]').value = mode === 'edit' ? packageMeta?.price || 0 : 1500;
  $('#package-form .form-error').textContent = '';
  $('#package-dialog').showModal();
}
/* Settings dialogs apply changes at once, so a click on the backdrop closes them like the × button. */
for (const dialog of $$('#album-dialog,#safety-dialog')) {
  let fromBackdrop = false;
  dialog.addEventListener('pointerdown', e => {
    fromBackdrop = e.target === dialog;
  });
  dialog.addEventListener('click', e => {
    if (e.target === dialog && fromBackdrop) dialog.close();
  });
}
$('#new-package').onclick = () => {
  togglePackagePop(false);
  packageDialog('new');
};
$$('[data-close]').forEach(b => (b.onclick = () => b.closest('dialog').close()));
$('#package-form').onsubmit = async e => {
  e.preventDefault();
  const f = e.target,
    b = f.querySelector('[type=submit]'),
    values = Object.fromEntries(new FormData(f));
  b.disabled = true;
  try {
    if (dirty) await save();
    values.price = Number(values.price);
    if (packageMode === 'new') {
      const result = await api('/designs/' + design.id + '/packages', 'POST', {
        ...values,
        source_id: serverId,
      });
      $('#package-dialog').close();
      await load(result.template_id);
    } else {
      await api('/master-templates/' + serverId + '/package', 'PUT', { ...values, revision });
      $('#package-dialog').close();
      await load(serverId);
    }
  } catch (error) {
    f.querySelector('.form-error').textContent = error.message;
  } finally {
    b.disabled = false;
  }
};
$('#publish-master').onclick = () => {
  $('#publish-summary').textContent =
    `${design?.name || doc.name} / ${packageMeta?.name || 'Основная'} · ${(packageMeta?.price || 0).toLocaleString('ru-RU')} ₽ за альбом`;
  $('#publish-error').textContent = '';
  $('#publish-dialog').showModal();
};
$('#confirm-publish').onclick = async () => {
  const b = $('#confirm-publish');
  b.disabled = true;
  try {
    if (dirty) await save();
    const r = await api('/master-templates/' + serverId + '/publish', 'POST', { revision });
    $('#publish-dialog').close();
    notify(`Опубликована версия ${r.version}. Комплектация доступна в новых заказах.`);
  } catch (e) {
    $('#publish-error').textContent = e.message;
  } finally {
    b.disabled = false;
  }
};
const fileMenu = $('.file-menu');
document.addEventListener('pointerdown', e => {
  if (fileMenu.open && !fileMenu.contains(e.target)) fileMenu.open = false;
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && fileMenu.open) {
    fileMenu.open = false;
    fileMenu.querySelector('summary').focus();
  }
});
fileMenu.querySelector('div').addEventListener('click', e => {
  if (e.target.closest('button')) fileMenu.open = false;
});
fileMenu.querySelector('input[type=file]').addEventListener('change', () => {
  fileMenu.open = false;
});
function download(data, name) {
  const a = document.createElement('a');
  a.href = data;
  a.download = name;
  a.click();
}
$('#export').onclick = () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' }));
  download(url, (packageMeta?.name || 'master') + '.json');
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
$('#import').onchange = async e => {
  const f = e.target.files?.[0];
  if (!f) return;
  if (f.size > 8_000_000) return notify('Файл больше 8 МБ', true);
  try {
    const parsed = JSON.parse(await f.text());
    await api('/master-templates/validate', 'POST', { document: parsed });
    commit(() => {
      doc = parsed;
      view.section = doc.sections[0].id;
      view.spread = 0;
      selected = [];
    });
    notify('Макет импортирован в текущую комплектацию');
  } catch (error) {
    notify(error.message, true);
  }
  e.target.value = '';
};
$('#recover').onclick = async () => {
  try {
    const stored = localStorage.getItem('af-package-' + serverId);
    if (!stored) return notify('Локальной копии нет');
    const parsed = JSON.parse(stored);
    await api('/master-templates/validate', 'POST', { document: parsed.document });
    commit(() => {
      doc = parsed.document;
      view.section = doc.sections[0].id;
      view.spread = 0;
      selected = [];
    });
    notify('Локальные изменения восстановлены. Проверьте и сохраните.');
  } catch (e) {
    notify(e.message, true);
  }
};
$('#export-png').onclick = () => {
  const active = canvas.getActiveObject(), transform = canvas.viewportTransform.slice(),
    helpers = canvas.getObjects().filter(o => o.excludeFromExport),
    visibility = helpers.map(o => o.visible);
  changing = true;
  try {
    canvas.discardActiveObject();
    helpers.forEach(o => o.set('visible', false));
    canvas.setViewportTransform([2, 0, 0, 2, 0, 0]);
    download(canvas.toDataURL({format: 'png', left: 0, top: 0,
      width: 2 * sheetWidth(), height: 2 * pageHeight(), multiplier: 2}), 'spread-preview.png');
  } catch (error) {
    notify('Не удалось выгрузить PNG: ' + error.message, true);
  } finally {
    helpers.forEach((o, i) => o.set('visible', visibility[i]));
    canvas.setViewportTransform(transform);
    if (active) canvas.setActiveObject(active);
    changing = false;
    canvas.requestRenderAll();
  }
};
document.addEventListener('keydown', e => {
  const editing =
    e.target.closest('input,textarea,select,[contenteditable="true"]') || canvas.getActiveObject()?.isEditing;
  if (editing) return;
  const mod = e.metaKey || e.ctrlKey;
  if (mod && e.key.toLowerCase() === 's') {
    e.preventDefault();
    save().catch(e => notify(e.message, true));
    return;
  }
  if (mod && e.key.toLowerCase() === 'z') {
    e.preventDefault();
    e.shiftKey ? redo() : undo();
    return;
  }
  if (mod && ['=', '+', '-', '_', '0'].includes(e.key)) {
    e.preventDefault();
    if (e.key === '0') $('#zoom-fit').click();
    else stepZoom(e.key === '-' || e.key === '_' ? -1 : 1);
    return;
  }
  if (mod && e.key.toLowerCase() === 'd') {
    e.preventDefault();
    action('duplicate');
    return;
  }
  if (mod && e.key.toLowerCase() === 'c') {
    if (chosen().length) {
      e.preventDefault();
      copyLayers();
    }
    return;
  }
  if (mod && e.key.toLowerCase() === 'v') {
    e.preventDefault();
    pasteLayers();
    return;
  }
  if (e.key === ' ') {
    e.preventDefault();
    space = true;
    canvas.skipTargetFind = true;
    return;
  }
  if (e.key === 'Escape') {
    if (photoCrop) {
      endPhotoCrop(false);
      return;
    }
    if (!$('#object-menu').hidden) {
      closeObjectMenu();
      return;
    }
    if (colorPop) {
      closeColor();
      return;
    }
    if (cellMenu) {
      cellMenu = null;
      placeCollageUi();
      return;
    }
    if (focusCell && activeCollage()) {
      focusCell = null;
      renderInspector();
      placeCollageUi();
      return;
    }
    if (cardPart && activeCardLayer()) {
      pickCardPart(null);
      return;
    }
    if (!$('#pointer-pop').hidden || !$('#frame-pop').hidden || !$('#shape-pop').hidden) {
      closeToolPops();
      return;
    }
    selected = [];
    canvas.discardActiveObject();
    $('.right-panel').classList.remove('mobile-open');
    setTool('select');
    renderInspector();
    return;
  }
  if (preview) return;
  if (['Delete', 'Backspace'].includes(e.key)) {
    e.preventDefault();
    const collage = activeCollage();
    if (collage && focusCell && CollageCore.can(collage, focusCell).remove) {
      commit(() => collageAction('remove'));
      return;
    }
    action('delete');
    return;
  }
  if (e.key.startsWith('Arrow') && selected.length) {
    e.preventDefault();
    const step = e.shiftKey ? 10 : 1;
    commit(() =>
      chosen()
        .filter(l => !l.locked)
        .forEach(l => {
          if (e.key === 'ArrowLeft') l.box.x -= step;
          if (e.key === 'ArrowRight') l.box.x += step;
          if (e.key === 'ArrowUp') l.box.y -= step;
          if (e.key === 'ArrowDown') l.box.y += step;
          settle(l);
        }),
    );
    return;
  }
  const shapeKeys = { r: 'rect', o: 'ellipse', l: 'line', s: 'svg' };
  if (shapeKeys[e.key.toLowerCase()]) {
    shapeKind = shapeKeys[e.key.toLowerCase()];
    $('#shape-icon').src = 'assets/editor/' + shapeKind + '.svg';
    $$('#shape-pop [data-shape]').forEach(b => b.classList.toggle('active', b.dataset.shape === shapeKind));
    setTool('shape');
    if (shapeKind === 'svg') pickSvg();
    return;
  }
  const tools = { v: 'select', h: 'hand', t: 'text', f: 'photo', g: 'grid', c: 'collage' };
  if (tools[e.key.toLowerCase()]) setTool(tools[e.key.toLowerCase()]);
});
document.addEventListener('keyup', e => {
  if (e.key === ' ') {
    space = false;
    setTool(tool);
  }
});
window.addEventListener('beforeunload', e => {
  if (dirty) {
    e.preventDefault();
    e.returnValue = '';
  }
});
$('#svg-file').onchange = async e => {
  const file = e.target.files?.[0];
  e.target.value = '';
  if (!file) return;
  if (file.size > 200_000) return notify('SVG больше 200 КБ', true);
  let svg;
  try {
    svg = sanitizeSvg(await file.text());
  } catch (err) {
    svg = null;
  }
  if (!svg) return notify('Этот SVG нельзя добавить', true);
  const aspect = svgAspect(svg) || 1,
    name = (file.name.replace(/\.svg$/i, '') || 'SVG').slice(0, 80);
  if (svgTarget) {
    const id = svgTarget;
    svgTarget = null;
    commit(() => {
      const l = allLayers().find(x => x.id === id);
      if (!l) return;
      l.svg = svg;
      l.aspect = aspect;
      l.name = name;
      if (l.lockAspect !== false) {
        l.box.h = round(clamp(l.box.w / aspect, 0.4, pageHeight()));
        l.box.y = round(clamp(l.box.y, 0, pageHeight() - l.box.h));
      }
    });
    return;
  }
  pendingSvg = { svg, aspect, name };
  shapeKind = 'svg';
  $('#shape-icon').src = 'assets/editor/svg.svg';
  $$('#shape-pop [data-shape]').forEach(x => x.classList.toggle('active', x.dataset.shape === 'svg'));
  setTool('shape');
  notify('Потяните по странице, чтобы разместить SVG');
};
MasterPhotos.bind({
  commit,
  doc: () => doc,
  inspector: () => {
    renderInspector();
    renderAlbumDialog();
  },
  rules: () => openAlbum('auto'),
  target: () => {
    const l = selectedLayer();
    if (!l || selected.length !== 1) return null;
    if (l.type === 'photo') return { obj: l };
    if (l.type === 'collage' && l.flex) return { obj: l };
    if (l.type === 'collage') {
      const loc = locateCell(l, focusCell);
      return loc && !loc.cell.split ? { obj: loc.cell } : null;
    }
    return null;
  },
  updated: () => {
    renderScene();
    renderAlbumDialog();
    const active = document.activeElement;
    if (!$('#inspector').contains(active) || active.tagName === 'BUTTON') renderInspector();
  },
});
// Observed only now: fitting the canvas reaches helpers from every editor script, so all of them must have run.
new ResizeObserver(() => fit()).observe($('#canvas-host'));
if (serverId) load(serverId);
else location.replace('/static/master-catalog.html');
