/* Master editor · State, save/load, header and package menu. */
'use strict';
const $ = s => document.querySelector(s),
  $$ = s => [...document.querySelectorAll(s)],
  clone = v => JSON.parse(JSON.stringify(v)),
  uid = () => crypto.randomUUID(),
  round = n => Math.round(n * 10) / 10,
  clamp = (n, a, b) => Math.max(a, Math.min(b, n)),
  esc = v =>
    String(v ?? '').replace(
      /[&<>"']/g,
      c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
    );
const icons = {
    text: 'text-box',
    photo: 'photo',
    rect: 'rect',
    grid: 'vignette',
    ellipse: 'ellipse',
    line: 'line',
    collage: 'collage',
    svg: 'svg',
  },
  img = key => `<img src="assets/editor/${key}.svg" alt="">`;
let doc = MasterDefaults.create(),
  serverId = new URLSearchParams(location.search).get('id'),
  revision = null,
  design = null,
  packageMeta = null,
  dirty = false,
  saving = false,
  savePromise = null,
  saveTimer = null,
  saveError = '',
  ready = false,
  history = [],
  future = [],
  renderToken = 0,
  changing = false,
  preview = false,
  inspectorTab = 'design',
  tool = 'select',
  selected = [],
  zoomMode = 'fit',
  clipboard = null,
  clipboardGeometry = null,
  recoveryPending = null,
  pan = null,
  space = false,
  packageMode = 'new',
  shapeKind = 'rect',
  frameKind = 'photo',
  focusCell = null,
  cellMenu = null,
  gapDrag = null,
  spaceDrag = null,
  selectedAt = 0,
  draw = null,
  rubber = null,
  colorPop = null,
  press = null,
  pendingSvg = null,
  svgTarget = null,
  slide = null,
  photoCrop = null;
const view = {
  teachers: 5,
  students: 22,
  owner: 's0',
  long: false,
  missing: false,
  section: 'students',
  spread: 0,
  side: 0,
};
const canvas = new fabric.Canvas('design-canvas', {
  preserveObjectStacking: true,
  selection: true,
  selectionColor: '#7712b30d',
  selectionBorderColor: '#a677c0',
  fireRightClick: false,
  stopContextMenu: true,
  uniformScaling: false,
});
fabric.FabricObject.prototype.set({
  cornerColor: '#fff',
  cornerStrokeColor: '#9063b2',
  borderColor: '#9063b2',
  cornerSize: 8,
  transparentCorners: false,
  padding: 0,
});
/* Selection outline follows a layer's rounded corners; selectionRadius is in mm, the border size in screen pixels. */
/* Selection frame and handles sit on the layer box like in Figma: a stroke (drawn doubled and clipped for "inside") must not widen them. */
const fabricCurrentDimensions = fabric.FabricObject.prototype._calculateCurrentDimensions;
fabric.FabricObject.prototype._calculateCurrentDimensions = function (options) {
  return fabricCurrentDimensions.call(this, this.boxSelection ? { ...options, strokeWidth: 0 } : options);
};
fabric.FabricObject.prototype.strokeBorders = function (ctx, size) {
  const r = Math.min(
    (this.selectionRadius || 0) * (this.canvas?.viewportTransform?.[0] || 1),
    Math.abs(size.x) / 2,
    Math.abs(size.y) / 2,
  );
  if (r > 0.5 && ctx.roundRect) {
    ctx.beginPath();
    ctx.roundRect(-size.x / 2, -size.y / 2, size.x, size.y, r);
    ctx.stroke();
  } else ctx.strokeRect(-size.x / 2, -size.y / 2, size.x, size.y);
};
let planner = MasterPlanner(doc, view),
  plans = [],
  lastPageSize = '',
  effectFrame = 0;
const assetCache = new Map();
const section = () => doc.sections.find(s => s.id === view.section) || doc.sections[0];
const pageWidth = () => Number((section().cover ? section().pageSize : doc.pageSize)?.[0]) || 210,
  pageHeight = () => Number((section().cover ? section().pageSize : doc.pageSize)?.[1]) || 280;
const page = () => section().spreads[Math.min(view.spread, section().spreads.length - 1)]?.pages[view.side];
const allLayers = () => doc.sections.flatMap(s => s.spreads.flatMap(sp => sp.pages.flatMap(p => p.layers)));
const chosen = () => allLayers().filter(l => selected.includes(l.id));
const selectedLayer = () => chosen()[0];
const textStyleKeys = [
  'font',
  'fontSize',
  'color',
  'align',
  'bold',
  'italic',
  'underline',
  'strike',
  'lineHeight',
  'letterSpacing',
  'skew',
  'textCase',
];
function textStyle(layer) {
  return (doc.textStyles || []).find(style => style.id === layer?.styleId);
}
function syncTextStyle(style) {
  if (!style) return;
  for (const layer of allLayers())
    if (layer.type === 'text' && layer.styleId === style.id)
      for (const key of textStyleKeys) layer[key] = style[key];
}
function paintLinkedText(style) {
  if (!style) return;
  for (const obj of canvas.getObjects()) {
    const layer = allLayers().find(item => item.id === obj.masterId);
    if (layer?.type === 'text' && layer.styleId === style.id) applyTextPaint(obj, layer);
  }
  canvas.requestRenderAll();
}
function setTextFormat(layer, key, value) {
  const style = textStyle(layer);
  if (style && textStyleKeys.includes(key)) {
    style[key] = value;
    syncTextStyle(style);
    return style;
  }
  layer[key] = value;
  return null;
}
function notify(message, error = false) {
  $('#feedback').textContent = message;
  $('#feedback').classList.toggle('error', error);
}
async function api(path, method = 'GET', body) {
  const r = await fetch('/api' + path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  const d = await r.json();
  if (!r.ok) throw Error(typeof d.detail === 'string' ? d.detail : 'Проверьте значения полей');
  return d;
}
/* The header stays quiet while work saves normally and speaks up only when it is not saved. */
function updateSaveState() {
  const state = $('#server-state'),
    retry = $('#retry-save'),
    kind = !ready ? '' : !navigator.onLine && (dirty || saving) ? 'offline' : saveError ? 'failed' : '';
  state.dataset.state = kind;
  state.classList.toggle('offline', kind === 'offline');
  state.classList.toggle('failed', kind === 'failed');
  state.textContent = { offline: 'Нет сети · не сохранено', failed: 'Не сохранено' }[kind] || '';
  state.title = kind === 'failed' ? saveError : kind === 'offline' ? 'Сохраним, когда появится сеть' : '';
  retry.hidden = kind !== 'failed';
  state.hidden = !kind;
}
function scheduleAutosave(delay = 900) {
  clearTimeout(saveTimer);
  if (!ready || !dirty || !navigator.onLine || recoveryPending) return;
  saveTimer = setTimeout(() => save().catch(() => {}), delay);
}
function markDirty() {
  dirty = true;
  saveError = '';
  updateSaveState();
  try {
    if (!recoveryPending) localStorage.setItem('af-package-' + serverId, JSON.stringify({ document: doc, revision }));
  } catch (e) {
    notify('Локальная копия не поместилась. Подключитесь и дождитесь сохранения на сервере.', true);
  }
  scheduleAutosave();
}
function ensureCover() {
  let changed = MasterPlan.upgrade(doc, uid);
  if (!Array.isArray(doc.pageSize)) {
    doc.pageSize = [210, 280];
    changed = true;
  }
  if (!doc.safety || Object.keys(doc.safety).length === 0) {
    doc.safety = { safe: 5, bleed: 3 };
    changed = true;
  }
  const coverIndex = doc.sections.findIndex(s => s.cover);
  if (coverIndex < 0) {
    doc.sections.unshift(MasterDefaults.createCover(doc.pageSize));
    changed = true;
  } else if (coverIndex > 0) {
    doc.sections.unshift(doc.sections.splice(coverIndex, 1)[0]);
    changed = true;
  }
  if (!Array.isArray(doc.textStyles) || doc.textStyles.length === 0) {
    doc.textStyles = MasterDefaults.textStyles();
    changed = true;
  }
  for (const layer of allLayers()) {
    if (layer.type !== 'text') continue;
    const style = textStyle(layer);
    if (style) for (const key of textStyleKeys)
      if (layer[key] !== style[key]) {
        layer[key] = style[key];
        changed = true;
      }
    const unified = AutoText.unifyCase(layer.text, style ? layer.textCase || '' : layer.textCase);
    if (unified.text !== layer.text) {
      layer.text = unified.text;
      layer.textCase = unified.textCase;
      changed = true;
    }
  }
  for (const s of doc.sections) {
    if (s.cover) continue;
    if (s.kind === 'flow') {
      const list = blockList(s);
      if (JSON.stringify(list) !== JSON.stringify(s.list)) {
        s.list = list;
        changed = true;
      }
      for (const sp of s.spreads)
        for (const p of sp.pages)
          for (const l of p.layers)
            if (l.type === 'grid' && l.source !== list.source) {
              l.source = list.source;
              changed = true;
            }
    }
    if (s.kind === 'repeat' && !MasterPlan.PEOPLE.includes(s.people)) {
      s.people = 'all';
      changed = true;
    }
  }
  if (!['spreads', 'book'].includes(doc.layout)) {
    doc.layout = 'spreads';
    changed = true;
  }
  if (MasterPhotos.migrate(doc)) changed = true;
  if (MasterPlan.linkParts(doc)) changed = true;
  for (const sec of doc.sections) for (const sp of sec.spreads || []) if (restack(sp)) changed = true;
  return changed;
}
/* Stacking is one order across the spread: `z` ranks the layers of both pages, so a layer crossing the fold
   keeps its place above or below the other page's layers. A layer without `z` yet (new, or an older design)
   goes on top of the ones that have it, and an older design keeps its look: left page, then right page. */
function spreadStack(spread) {
  const list = [];
  (spread?.pages || []).forEach((p, side) => p.layers.forEach((l, i) => list.push({ l, side, i })));
  return list
    .sort((a, b) => (a.l.z ?? Infinity) - (b.l.z ?? Infinity) || a.side - b.side || a.i - b.i)
    .map(e => e.l);
}
function isSpineContent(layer) {
  return layer.type === 'text' && layer.pin === 'spine' &&
    (layer.spineContent === true || (layer.spineContent == null && Math.abs(layer.angle || 0) === 90));
}
function stackGroups(spread, sec = section()) {
  const order = spreadStack(spread);
  return sec.cover && sec.spineColor
    ? [order.filter(l => !isSpineContent(l)), order.filter(isSpineContent)] : [order];
}
/* Number the spread in the given order and keep each page's list in that order; true when anything moved. */
function restack(spread, order = spreadStack(spread)) {
  let changed = false;
  order.forEach((l, i) => {
    if (l.z !== i) {
      l.z = i;
      changed = true;
    }
  });
  for (const p of spread?.pages || []) {
    const sorted = [...p.layers].sort((a, b) => a.z - b.z);
    if (sorted.some((l, i) => l !== p.layers[i])) {
      p.layers = sorted;
      changed = true;
    }
  }
  return changed;
}
function commit(fn) {
  history.push(clone(doc));
  if (history.length > 60) history.shift();
  future = [];
  fn();
  ensureCover();
  markDirty();
  render();
}
function undo() {
  if (!history.length) return;
  future.push(clone(doc));
  doc = history.pop();
  ensureCover();
  selected = [];
  markDirty();
  render();
}
function redo() {
  if (!future.length) return;
  history.push(clone(doc));
  doc = future.pop();
  ensureCover();
  selected = [];
  markDirty();
  render();
}
function save() {
  if (!ready) return Promise.reject(Error('Дождитесь загрузки макета'));
  if (recoveryPending) return Promise.reject(Error('Сначала выберите, что делать с несохранённой копией'));
  if (savePromise) return savePromise;
  clearTimeout(saveTimer);
  savePromise = (async () => {
    let result;
    while (dirty) {
      if (!navigator.onLine) throw Error('Нет сети. Подключитесь, чтобы сохранить изменения.');
      saving = true;
      updateSaveState();
      const snapshot = clone(doc);
      result = await api('/master-templates' + (serverId ? '/' + serverId : ''), serverId ? 'PUT' : 'POST', {
        document: snapshot,
        revision,
      });
      serverId = result.id;
      revision = result.revision;
      dirty = JSON.stringify(snapshot) !== JSON.stringify(doc);
      historyURL();
      try {
        if (dirty)
          localStorage.setItem('af-package-' + serverId, JSON.stringify({ document: doc, revision }));
        else localStorage.removeItem('af-package-' + serverId);
      } catch (e) {
        notify('Не удалось обновить локальную копию. Проверьте сохранение на сервере.', true);
      }
    }
    saveError = '';
    return result;
  })()
    .catch(error => {
      if (navigator.onLine) saveError = error.message;
      throw error;
    })
    .finally(() => {
      saving = false;
      savePromise = null;
      updateSaveState();
    });
  return savePromise;
}
function historyURL() {
  window.history.replaceState(null, '', '?id=' + encodeURIComponent(serverId));
}
async function load(id) {
  clearTimeout(saveTimer);
  $('#canvas-loading').hidden = false;
  ready = false;
  try {
    const data = await api('/master-templates/' + id);
    doc = data.document;
    serverId = data.id;
    revision = data.revision;
    recoveryPending = preserveRecovery(id, doc);
    packageMeta = data.package;
    if (packageMeta) design = await api('/designs/' + packageMeta.design_id);
    dirty = ensureCover();
    saveError = '';
    history = [];
    future = [];
    selected = [];
    view.section = doc.sections[0].id;
    view.spread = 0;
    view.side = 0;
    view.coverSpreads = null;
    view.coverSource = null;
    ready = true;
    historyURL();
    updateSaveState();
    if (dirty) markDirty();
    renderHeader();
    render();
    if (recoveryPending) showRecovery();
  } catch (e) {
    notify(e.message, true);
  } finally {
    $('#canvas-loading').hidden = true;
  }
}
/* The header names the design and the open package; the popover switches, renames and adds packages. */
function renderHeader() {
  const packages = design?.packages || [
      { template_id: serverId, name: packageMeta?.name || 'Основная', price: packageMeta?.price || 0 },
    ],
    current = packages.find(p => p.template_id === serverId) || packages[0],
    price = p => `${(p.price || 0).toLocaleString('ru-RU')} ₽`;
  $('#design-title').textContent = design?.name || doc.name;
  $('#package-name').textContent = current.name;
  $('#package-price').textContent = price(current);
  $('#package-pop-title').textContent = design ? `Комплектации «${design.name}»` : 'Комплектации';
  $('#package-list').innerHTML = packages
    .map(p => {
      const on = p.template_id === serverId;
      return `<li class="${on ? 'active' : ''}"><button type="button" class="package-option" data-package="${esc(p.template_id)}" aria-current="${on}"><span class="package-radio" aria-hidden="true"></span><span class="package-option-name">${esc(p.name)}</span><span class="package-option-price">${price(p)}</span></button>${on ? '<button type="button" class="package-edit" data-package-edit title="Название и цена" aria-label="Изменить название и цену"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12.5 4.5l3 3L7 16H4v-3z"/></svg></button>' : ''}</li>`;
    })
    .join('');
  $('#new-package').disabled = !design;
}
function togglePackagePop(open) {
  const pop = $('#package-pop');
  open ??= pop.hidden;
  pop.hidden = !open;
  $('#package-button').setAttribute('aria-expanded', String(open));
}
function freshIds(value) {
  const copy = clone(value);
  const walk = o => {
    if (!o || typeof o !== 'object') return;
    if (o.id) o.id = uid();
    Object.values(o).forEach(v => {
      if (Array.isArray(v)) v.forEach(walk);
      else if (v && typeof v === 'object') walk(v);
    });
  };
  walk(copy);
  return copy;
}

/* Keep the old unsaved document separately before the first new edit can replace it. */
function preserveRecovery(id, serverDocument) {
  try {
    const key = 'af-recovery-' + id;
    let stored = localStorage.getItem(key);
    if (!stored) {
      stored = localStorage.getItem('af-package-' + id);
      if (!stored) return null;
      const parsed = JSON.parse(stored);
      if (JSON.stringify(parsed.document) === JSON.stringify(serverDocument)) return null;
      localStorage.setItem(key, stored);
    }
    return JSON.parse(stored);
  } catch (error) {
    // Never overwrite the working copy if archiving failed (e.g. storage is full).
    const stored = localStorage.getItem('af-package-' + id);
    if (stored) return JSON.parse(stored);
    notify('Не удалось прочитать локальную копию: ' + error.message, true);
    return null;
  }
}
function showRecovery() {
  let modal = $('#recovery-dialog');
  if (!modal) {
    modal = document.createElement('dialog');
    modal.id = 'recovery-dialog';
    modal.setAttribute('aria-label', 'Восстановление несохранённых изменений');
    modal.innerHTML = `<div class="album-dialog-inner"><h2>Есть несохранённые изменения</h2><p>На сервере открыта другая версия. Выберите, какую продолжить.</p><p class="recovery-message"></p><div class="recovery-actions"><button type="button" data-recovery="restore" class="primary">Восстановить локальную копию</button><button type="button" data-recovery="download">Скачать копию</button><button type="button" data-recovery="server">Оставить серверную и удалить локальную копию</button></div></div>`;
    modal.addEventListener('cancel', e => e.preventDefault());
    modal.addEventListener('click', async e => {
      const action = e.target.closest('[data-recovery]')?.dataset.recovery;
      if (!action || !recoveryPending) return;
      if (action === 'download') {
        const url = URL.createObjectURL(new Blob([JSON.stringify(recoveryPending.document, null, 2)], {type: 'application/json'}));
        download(url, 'unsaved-master.json');
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        return;
      }
      try {
        const backup = recoveryPending;
        if (action === 'restore') {
          await api('/master-templates/validate', 'POST', {document: backup.document});
          const conflict = backup.revision != null && backup.revision !== revision;
          recoveryPending = null;
          revision = backup.revision ?? revision;
          commit(() => { doc = clone(backup.document); selected = []; view.section = doc.sections[0].id; view.spread = 0; });
          if (conflict) notify('Серверная версия изменилась. Копия восстановлена, но сохранение потребует разрешить конфликт. Скачайте её для переноса правок.', true);
        } else {
          recoveryPending = null;
          localStorage.removeItem('af-package-' + serverId);
          scheduleAutosave();
        }
        localStorage.removeItem('af-recovery-' + serverId);
        modal.close();
      } catch (error) {
        modal.querySelector('.recovery-message').textContent = error.message;
      }
    });
    document.body.append(modal);
  }
  modal.querySelector('.recovery-message').textContent = recoveryPending.revision !== revision
    ? 'За это время серверная версия могла измениться. При восстановлении защита от конфликтов сохранится.' : '';
  modal.showModal();
}
