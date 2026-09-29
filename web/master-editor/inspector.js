/* Master editor · Inspector render. */
'use strict';
function renderInspector() {
  const l = selectedLayer(),
    sec = section();
  let html = '';
  if (l) {
    const multi = selected.length > 1;
    html += block(
      'Положение',
      `<div class="align-tools">${[
        ['left', 'По левому краю'],
        ['cx', 'Центр по горизонтали'],
        ['right', 'По правому краю'],
        ['top', 'По верхнему краю'],
        ['cy', 'Центр по вертикали'],
        ['bottom', 'По нижнему краю'],
      ]
        .map(
          ([k, n]) => `<button data-align="${k}" title="${n}" aria-label="${n}">${alignmentIcon(k)}</button>`,
        )
        .join(
          '',
        )}</div><div class="field-grid">${number('X', 'box.x', l.box.x, l.type === 'grid' ? 0 : -pageWidth(), l.type === 'grid' ? pageWidth() : 2 * pageWidth())}${number('Y', 'box.y', l.box.y)}</div>${rotationRow(l)}`,
    );
    html += block(
      'Размер',
      `<div class="size-line">${number('W', 'box.w', layerW(l), 1, l.type === 'grid' ? pageWidth() : sheetWidth())}${l.type === 'svg' ? `<button type="button" class="icon-toggle${l.lockAspect !== false ? ' active' : ''}" data-choice="lockAspect" title="Сохранять пропорции" aria-label="Сохранять пропорции" aria-pressed="${l.lockAspect !== false}">${glyph.link}</button>` : ''}${number('H', 'box.h', l.box.h, 1, pageHeight())}</div>${layerMetrics(l)}`,
    );
    if (!multi && l.type === 'text')
      html +=
        block('Текст', autoTextField(l)) +
        `<section class="inspector-section typography-section"><div class="typography-heading"><h3>Типографика</h3></div>${textPanel(l)}</section>`;
    if (!multi && l.type === 'photo') html += photoContentPanel(l, { title: 'Что в кадре', key: l.id });
    if (!multi && l.type === 'grid') html += vignettePanel(l);
    if (!multi && l.type === 'collage' && l.flex)
      html +=
        collagePanel(l) +
        block('Что в кадре', MasterPhotos.panel(l.pick, pickKey(l.id + '/flex0'), section()));
    if (!multi && l.type === 'collage' && !l.flex) {
      const leaf = focusedLeaf(l);
      html +=
        collagePanel(l) +
        (leaf
          ? photoContentPanel(leaf, { title: 'Что в кадре', key: l.id + '/' + leaf.id, cell: true })
          : block(
              'Что в кадре',
              '<p class="section-note">Нажмите на кадр коллажа, чтобы выбрать, что в нём будет.</p>',
            ));
    }
    html += ['rect', 'ellipse', 'line', 'svg'].includes(l.type)
      ? vectorPanel(l)
      : block(
          'Оформление',
          `${['text', 'photo', 'grid', 'collage'].includes(l.type) ? '' : colorControl('Цвет', 'fill', l.color || l.fill || '#333333')}${effectControls(l)}`,
        );
  } else {
    const cover = !!sec.cover;
    html =
      block(
        'Страница',
        `<div class="field-grid"><button data-side="0" class="${view.side === 0 ? 'active' : ''}">${cover ? 'Оборотная' : 'Левая'}</button><button data-side="1" class="${view.side === 1 ? 'active' : ''}">${cover ? 'Лицевая' : 'Правая'}</button></div>${colorControl('Фон', 'page.background', page()?.background || '#ffffff')}`,
      ) +
      (cover ? spinePanel() : '');
  }
  const inspector = $('#inspector'),
    scrollTop = inspector.scrollTop,
    oldSwitch = inspector.querySelector('.photo-mode-switch'),
    contentKey =
      selected.length === 1
        ? l?.type === 'photo'
          ? l.id
          : l?.type === 'collage' && focusedLeaf(l)
            ? l.id + '/' + focusCell
            : ''
        : '',
    samePhoto = oldSwitch && contentKey && inspector.dataset.photoLayer === contentKey;
  if (samePhoto) {
    const next = document.createElement('div');
    next.innerHTML = html;
    const newSwitch = next.querySelector('.photo-mode-switch');
    if (newSwitch) {
      const nextMode = newSwitch.dataset.mode,
        previousMode = oldSwitch.dataset.mode;
      newSwitch.replaceWith(oldSwitch);
      inspector.replaceChildren(...next.childNodes);
      oldSwitch.dataset.mode = previousMode;
      for (const button of oldSwitch.querySelectorAll('[data-content-kind]')) {
        const active = button.dataset.contentKind === nextMode;
        button.classList.toggle('active', active);
        button.setAttribute('aria-pressed', String(active));
      }
      oldSwitch.getBoundingClientRect();
      requestAnimationFrame(() => {
        if (oldSwitch.isConnected) oldSwitch.dataset.mode = nextMode;
      });
    } else inspector.innerHTML = html;
  } else inspector.innerHTML = html;
  /* Swapping the markup drops the scroll position; keep the panel where the designer was working. */ inspector.scrollTop =
    scrollTop;
  inspector.dataset.photoLayer = contentKey;
  inspector.inert = preview;
  $$('[data-inspector]').forEach(b => b.classList.toggle('active', b.dataset.inspector === inspectorTab));
}
/* Rotation as in Figma: the angle, then rotate by 90° and mirror. Vignettes and collages are not mirrored. */
function rotationRow(l) {
  const icon = d =>
      `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${d}"/></svg>`,
    flip = !['grid', 'collage'].includes(l.type),
    button = (attrs, name, d, on) =>
      `<button type="button" class="icon-toggle${on ? ' active' : ''}" ${attrs} title="${name}" aria-label="${name}"${on == null ? '' : ` aria-pressed="${on}"`}>${icon(d)}</button>`;
  return `<div class="rotation-row"><label class="compact-number" title="Угол поворота"><span>${icon('M4 19h15M4 19 15 6M11 19a8 8 0 0 0-2.3-5.7')}</span><input aria-label="Угол поворота" data-prop="angle" type="number" value="${round(l.angle || 0)}" min="-180" max="180" step="0.1"><span>°</span></label><div class="rotation-actions">${button('data-action="rotate"', 'Повернуть на 90°', 'M19 12a7 7 0 1 1-2.05-4.95M19 4v4h-4')}${flip ? button('data-choice="flipX" data-value="toggle"', 'Отразить по горизонтали', 'M12 3v18M9 7 4 17h5zM15 7l5 10h-5z', !!l.flipX) + button('data-choice="flipY" data-value="toggle"', 'Отразить по вертикали', 'M3 12h18M7 9 17 4v5zM7 15l10 5v-5z', !!l.flipY) : ''}</div></div>`;
}
function render() {
  planner = MasterPlanner(doc, view);
  plans = planner.plan();
  MasterPhotos.refresh(doc, view);
  if (!doc.sections.some(s => s.id === view.section)) {
    view.section = doc.sections[0].id;
    view.spread = 0;
  }
  selected = selected.filter(id => allLayers().some(l => l.id === id));
  renderNavigation();
  renderInspector();
  renderAlbumDialog();
  renderScene();
  const sizeKey = pageWidth() + 'x' + pageHeight();
  if (sizeKey !== lastPageSize) {
    lastPageSize = sizeKey;
    fit();
  }
  $('#undo').disabled = !history.length;
  $('#redo').disabled = !future.length;
  setTool(tool);
}
