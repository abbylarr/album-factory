/* Master editor · Blocks: settings, block dialog and the sidebar block list. */
'use strict';
/* Block rules live in the block's card on the left: how it unfolds, whom it is for and the roles of its spreads. */
const ROLE_NAMES = {
  intro: 'Открывающий',
  repeat: 'Повторяемый',
  last: 'Последний неполный',
  outro: 'Закрывающий',
};
const ROLE_HELP = {
  intro: 'один раз в начале блока',
  repeat: 'повторяется, пока в списке есть люди',
  last: 'заменяет повторяемый разворот, если список закончился на его середине',
  outro: 'один раз в конце блока',
};
const PEOPLE_NAMES = {
  all: 'Каждому ученику',
  others: 'Всем, кроме владельца',
  owner: 'Только владельцу альбома',
  off: 'Выключен',
};
const PEOPLE_HELP = {
  all: 'В каждом альбоме — развороты всех учеников по списку',
  others: 'Владелец уже был раньше, здесь — остальные одноклассники',
  owner: 'Один разворот хозяина альбома',
  off: 'Блок не выводится',
};
function plural(n, one, few, many) {
  return (
    n +
    ' ' +
    (n % 10 === 1 && n % 100 !== 11
      ? one
      : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20)
        ? few
        : many)
  );
}
function blockList(s) {
  return { ...MasterPlan.LIST_DEFAULT, ...(s?.list || {}) };
}
const coverSection = () => doc.sections.find(s => s.cover);
/* The block's type, drawn the same in its card and in the type dialog. */
const KIND_NAMES = {
  fixed: ['Общие развороты', 'Каждый разворот — по одному разу'],
  flow: ['Портреты по списку', 'Разворотов — сколько нужно списку'],
  repeat: ['Личные развороты', 'Повторяются для людей'],
};
const KIND_GLYPHS = {
  fixed: '<rect x="2.5" y="4.5" width="13" height="9" rx="1.2"/><path d="M9 4.5v9"/>',
  flow: '<rect x="2.8" y="3.4" width="3.4" height="4.4" rx=".7"/><rect x="7.3" y="3.4" width="3.4" height="4.4" rx=".7"/><rect x="11.8" y="3.4" width="3.4" height="4.4" rx=".7"/><rect x="2.8" y="10.2" width="3.4" height="4.4" rx=".7"/><rect x="7.3" y="10.2" width="3.4" height="4.4" rx=".7"/>',
  repeat: '<circle cx="9" cy="6.3" r="2.6"/><path d="M4.3 14.6c.6-2.5 2.4-3.8 4.7-3.8s4.1 1.3 4.7 3.8"/>',
};
function kindIcon(kind) {
  return `<svg viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${KIND_GLYPHS[kind] || KIND_GLYPHS.fixed}</svg>`;
}
/* A split block: the block that continues this one, and the block this one continues. */
const continuation = s => doc.sections.find(x => x.continues === s.id),
  partStart = s => doc.sections.find(x => x.id === s.continues);
function blockSummary(s) {
  if (s.cover) return 'Обложка · один разворот';
  const who =
    s.kind === 'flow'
      ? blockList(s).source === 'teachers'
        ? 'Учителя'
        : 'Ученики'
      : s.kind === 'repeat'
        ? PEOPLE_NAMES[s.people] || PEOPLE_NAMES.all
        : KIND_NAMES.fixed[0];
  if (s.continues) return `${who} · продолжение`;
  if (continuation(s)) return `${who} · первые ${plural(s.limit || 1, 'разворот', 'разворота', 'разворотов')}`;
  if (s.kind === 'flow') {
    const l = blockList(s);
    return `${who} · ${l.min}–${l.max} на странице`;
  }
  return who;
}
const pluralWord = (n, one, few, many) => plural(n, one, few, many).slice(String(n).length + 1);
function blockSegments(key, value, items, label) {
  return `<div class="segments block-segments" role="group" aria-label="${label}">${items.map(([id, name, title]) => `<button type="button" data-block="${key}" data-value="${id}" class="${value === id ? 'active' : ''}" aria-pressed="${value === id}"${title ? ` title="${esc(title)}"` : ''}>${name}</button>`).join('')}</div>`;
}
/* A setting reads as a question with answers; a short «i» next to it explains the rare case. */
function blockQuestion(label, key, value, items, tip) {
  return `<p class="block-label">${label}${tip ? infoTip(tip) : ''}</p>${blockSegments(key, value, items, label)}`;
}
/* Block settings live in their own dialog, like the layout settings: the card in the list stays short and drags. */
let blockPick = null;
function blockPicker(key, label, rows, extra = '') {
  const open = blockPick === key;
  return `<div class="pick-picker${extra}"><button type="button" class="pick-trigger" data-block-pick="${esc(key)}" aria-haspopup="menu" aria-expanded="${open}"><span>${esc(label)}</span>${SHEET_CARET}</button>${open ? `<div class="cell-sources pick-menu" role="menu">${rows.map(([value, text, on]) => `<button type="button" class="menu-row${on ? ' on' : ''}" role="menuitemradio" aria-checked="${on}" data-block-pick-value="${esc(value)}"><span>${esc(text)}</span>${on ? SHEET_TICK : ''}</button>`).join('')}</div>` : ''}</div>`;
}
/* Blocks a part may continue: earlier blocks of the same kind that nothing else continues yet. */
function partChoices(s) {
  const at = doc.sections.indexOf(s);
  return doc.sections.filter(
    (x, i) =>
      i < at &&
      x.kind === s.kind &&
      MasterPlan.splittable(x) &&
      (s.kind !== 'flow' || blockList(x).source === blockList(s).source) &&
      (!continuation(x) || continuation(x) === s),
  );
}
function blockSettings(s) {
  const [title, help] = KIND_NAMES[s.kind] || KIND_NAMES.fixed,
    from = partStart(s),
    next = continuation(s);
  let body = `<label class="block-name"><span class="block-label">Название</span><input data-block-name maxlength="100" value="${esc(s.name)}" aria-label="Название блока"></label>`;
  body += `<button type="button" class="block-type" data-block-type title="Изменить тип блока"><span class="block-type-icon">${kindIcon(s.kind)}</span><span class="block-type-copy"><strong>${title}</strong><small>${help}</small></span><svg class="block-type-change" viewBox="0 0 8 12" aria-hidden="true"><path d="M2 2l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg></button>`;
  const choices = MasterPlan.splittable(s) ? partChoices(s) : [];
  if (from || choices.length)
    body +=
      `<p class="block-label">С кого начать</p>` +
      blockPicker('continues', from ? `Где закончился «${from.name}»` : 'С начала списка', [
        ['', 'С начала списка', !from],
        ...choices.map(x => [x.id, `Где закончился «${x.name}»`, x === from]),
      ]);
  if (next) {
    const limit = s.limit || 1;
    body += `<p class="block-label">Сколько разворотов в этой части${infoTip(`Остальные — в блоке «${next.name}».`)}</p><div class="block-range"><label>до<input type="number" data-block-num="limit" min="1" max="100" value="${limit}" aria-label="Разворотов в этой части"></label><span>${pluralWord(limit, 'разворота', 'разворотов', 'разворотов')}</span></div>`;
  }
  if (s.kind === 'flow') {
    const l = blockList(s),
      target = s.target || 1,
      dense = target <= 1;
    if (!from)
      body += blockQuestion('Кого разместить', 'source', l.source, [
        ['students', 'Учеников'],
        ['teachers', 'Учителей'],
      ]);
    body += `<p class="block-label">Карточек на странице</p><div class="block-range"><label>от<input type="number" data-block-num="min" min="1" max="100" value="${l.min}" aria-label="Карточек на странице: от"></label><label>до<input type="number" data-block-num="max" min="1" max="100" value="${l.max}" aria-label="Карточек на странице: до"></label></div>`;
    body +=
      blockQuestion(
        'Если людей немного',
        'density',
        dense ? 'dense' : 'spread',
        [
          ['dense', 'Плотнее'],
          ['spread', 'Растянуть'],
        ],
        `Плотнее — меньше страниц, до ${l.max} карточек на каждой. Растянуть — фото крупнее, но не меньше ${l.min} на странице.`,
      ) +
      (dense
        ? ''
        : `<div class="block-range"><label>до<input type="number" data-block-num="target" min="1" max="100" value="${target}" aria-label="Растянуть до, разворотов в блоке"></label><span>${pluralWord(target, 'разворота', 'разворотов', 'разворотов')} в блоке</span></div>`);
    body += blockQuestion(
      `Если на странице меньше ${l.min}`,
      'strictMin',
      l.strictMin ? 'stop' : 'warn',
      [
        ['warn', 'Предупредить'],
        ['stop', 'Не выпускать'],
      ],
      'Не выпускать — заказ не выгрузится в PDF, пока его не поправят.',
    );
    if (l.source === 'teachers')
      body += blockQuestion(
        'Руководитель в виньетке',
        'excludeLead',
        l.excludeLead ? 'skip' : 'show',
        [
          ['show', 'Показывать'],
          ['skip', 'Не повторять'],
        ],
        'Не повторять — если в блоке уже есть его отдельный портрет.',
      );
  } else if (s.kind === 'repeat' && !from) {
    const mode = MasterPlan.PEOPLE.includes(s.people) ? s.people : 'all';
    body += `<p class="block-label">Для кого${infoTip('Портрет, имя и фото «героя разворота» — того, чей разворот сейчас печатается.')}</p><div class="block-people" role="radiogroup" aria-label="Для кого личные развороты">${[
      'all',
      'others',
      'owner',
    ]
      .concat(mode === 'off' ? ['off'] : [])
      .map(
        id =>
          `<button type="button" class="photo-choice${mode === id ? ' active' : ''}" role="radio" aria-checked="${mode === id}" data-block="people" data-value="${id}"><span class="photo-radio" aria-hidden="true"></span><span class="photo-choice-copy"><strong>${PEOPLE_NAMES[id]}</strong><small>${PEOPLE_HELP[id]}</small></span></button>`,
      )
      .join('')}</div>`;
  }
  if (s.kind === 'flow') body += blockTestClass(s);
  const size = doc.pageSize || [210, 280];
  body += `<p class="block-label">Развороты${s.kind === 'flow' ? infoTip(MasterPlan.ROLES.map(r => `${ROLE_NAMES[r]} — ${ROLE_HELP[r]}.`).join(' ')) : ''}</p><ol class="block-spreads">${s.spreads
    .map((sp, i) => {
      const role = MasterPlan.roleOf(sp);
      return `<li class="${i === view.spread ? 'current' : ''}"><button type="button" class="block-spread-thumb" data-goto-spread="${i}" aria-label="Открыть разворот ${i + 1}">${miniSpread(sp, s)}</button>${
        s.kind === 'flow'
          ? blockPicker(
              'role:' + sp.id,
              ROLE_NAMES[role],
              MasterPlan.ROLES.map(r => [r, ROLE_NAMES[r], r === role]),
              ' block-role-picker',
            )
          : `<span class="block-spread-no">${i + 1}</span>`
      }</li>`;
    })
    .join(
      '',
    )}<li><button type="button" class="block-spread-add" data-add-spread style="aspect-ratio:${2 * size[0]}/${size[1]}" title="Добавить разворот" aria-label="Добавить разворот">+</button></li></ol>`;
  body += planner
    .designIssues(s)
    .map(i => `<div class="issue ${i.severity}">${esc(i.text)}</div>`)
    .join('');
  return body;
}
function openBlockSettings(id = view.section) {
  const s = doc.sections.find(x => x.id === id);
  if (preview || !s || s.cover) return;
  if (view.section !== id) {
    view.section = id;
    view.spread = 0;
    view.side = 0;
    selected = [];
    render();
  }
  blockPick = null;
  const dialog = $('#block-settings');
  if (!dialog.open) dialog.showModal();
  renderBlockSettings();
}
/* The test class fills the vignettes on the canvas: change the count to see how the block spreads out. */
function blockTestClass(s) {
  const source = blockList(s).source,
    plan = plans.find(p => p.sectionId === s.id),
    spreads = Math.ceil((plan?.pages.length || 0) / 2),
    design = new Set(planner.designIssues(s).map(i => i.text)),
    own = /^(Минимум карточек|Минимальный кегль|По размерам фото)/,
    issues = (plan?.issues || []).filter(i => !design.has(i.text) && !own.test(i.text)),
    check = (flag, label) =>
      `<label class="check"><input type="checkbox" data-test-flag="${flag}"${view[flag] ? ' checked' : ''}>${label}</label>`;
  return (
    `<p class="block-label">Тестовый класс${infoTip('Виньетки на холсте заполняются этим классом. Меняйте число, чтобы увидеть, как разойдётся список.')}</p><div class="block-range"><label><input type="number" data-test-count="${source}" min="0" max="${source === 'teachers' ? 60 : 80}" value="${view[source]}" aria-label="Сколько ${source === 'teachers' ? 'учителей' : 'учеников'} в тестовом классе"></label><span>${source === 'teachers' ? pluralWord(view[source], 'учитель', 'учителя', 'учителей') : pluralWord(view[source], 'ученик', 'ученика', 'учеников')} → ${spreads} ${pluralWord(spreads, 'разворот', 'разворота', 'разворотов')}</span></div>` +
    `<div class="block-test-flags">${check('long', 'Длинное имя')}${check('missing', 'Нет портрета')}</div>` +
    issues.map(i => `<div class="issue ${i.severity}">${esc(i.text)}</div>`).join('')
  );
}
function renderBlockSettings() {
  const dialog = $('#block-settings');
  if (!dialog?.open) return;
  const s = section();
  if (s.cover) return dialog.close();
  const body = $('#block-settings-body'),
    scroll = body.scrollTop,
    active = body.contains(document.activeElement) ? document.activeElement : null,
    focus = active?.dataset.blockNum
      ? `[data-block-num="${active.dataset.blockNum}"]`
      : active?.dataset.testCount
        ? '[data-test-count]'
        : null;
  $('#block-settings-title').textContent = s.name;
  body.innerHTML = blockSettings(s);
  body.scrollTop = scroll;
  if (focus) body.querySelector(focus)?.focus();
}
/* Spreads with a vignette repeat; the others stay once before or after them. */
function assignRoles(s) {
  const withGrid = sp => sp.pages.some(MasterPlan.hasGrid),
    first = s.spreads.findIndex(withGrid);
  s.spreads.forEach((sp, i) => {
    sp.role = withGrid(sp) ? 'repeat' : first < 0 || i < first ? 'intro' : 'outro';
  });
}
function makeList(s) {
  if (s.kind !== 'flow') {
    s.kind = 'flow';
    assignRoles(s);
    s.target = s.target || 1;
  }
  s.list = blockList(s);
}
function blockSet(key, value) {
  if (preview) return;
  const current = section();
  if (current.cover) return;
  if (
    key === 'kind' &&
    value !== 'flow' &&
    current.kind === 'flow' &&
    current.spreads.some(sp => sp.pages.some(MasterPlan.hasGrid))
  )
    return notify('Сначала удалите виньетки: они работают только в блоке «по списку»', true);
  commit(() => {
    const s = section();
    if (key === 'name') {
      const name = String(value).trim().slice(0, 100);
      if (name) s.name = name;
      return;
    }
    if (key === 'kind') {
      if (value === s.kind) return;
      if (value === 'flow') makeList(s);
      else s.kind = value;
      if (value === 'repeat' && !MasterPlan.PEOPLE.includes(s.people)) s.people = 'all';
      return;
    }
    if (key === 'target') {
      s.target = clamp(Math.round(value) || 1, 1, 100);
      return;
    }
    if (key === 'density') {
      s.target = value === 'dense' ? 1 : Math.max(2, s.spreads.length);
      return;
    }
    if (key === 'limit') {
      s.limit = clamp(Math.round(value) || 1, 1, 100);
      return;
    }
    if (key === 'continues') {
      const from = doc.sections.find(x => x.id === value);
      if (!from) delete s.continues;
      else {
        s.continues = from.id;
        from.limit ??= partLimit(from);
      }
      return;
    }
    if (key === 'people') {
      s.people = value;
      return;
    }
    if (key === 'role') {
      const [id, role] = value;
      s.spreads.forEach(sp => {
        if (sp.id === id) sp.role = role;
        else if (role === 'last' && sp.role === 'last') sp.role = 'repeat';
      });
      return;
    }
    const list = (s.list = blockList(s));
    if (key === 'source') {
      list.source = value;
      if (value !== 'teachers') list.excludeLead = false;
      return;
    }
    if (key === 'min') {
      list.min = clamp(Math.round(value) || 1, 1, 100);
      if (list.max < list.min) list.max = list.min;
      return;
    }
    if (key === 'max') {
      list.max = clamp(Math.round(value) || 1, 1, 100);
      if (list.min > list.max) list.min = list.max;
      return;
    }
    if (key === 'strictMin') list.strictMin = value === 'stop';
    if (key === 'excludeLead') list.excludeLead = value === 'skip';
  });
}
/* Where the first part of a split block stops until the designer sets it: its own spreads of a list, ten personal spreads. */
function partLimit(s) {
  return s.kind === 'flow' ? Math.max(1, s.spreads.length) : 10;
}
/* «Split» makes the block that continues this one right after it, without the opening spreads of a list. */
function splitBlock(id) {
  if (preview) return;
  const i = doc.sections.findIndex(s => s.id === id),
    sec = doc.sections[i];
  if (!sec || !MasterPlan.splittable(sec) || continuation(sec)) return;
  commit(() => {
    const part = freshIds(sec);
    part.name = (sec.name + ' — продолжение').slice(0, 100);
    part.continues = sec.id;
    delete part.limit;
    if (part.kind === 'flow' && part.spreads.some(sp => MasterPlan.roleOf(sp) !== 'intro'))
      part.spreads = part.spreads.filter(sp => MasterPlan.roleOf(sp) !== 'intro');
    sec.limit = partLimit(sec);
    doc.sections.splice(i + 1, 0, part);
    view.section = part.id;
    view.spread = 0;
    view.side = 0;
    selected = [];
  });
  notify(`Блок разделён: «${sec.name}» и «${section().name}»`);
}
/* In a book the first inner page stands alone on the right and the last one on the left; those template pages are shaded. */
function bookMarks() {
  if (preview || doc.layout !== 'book') return [];
  const sec = section(),
    inner = doc.sections.filter(s => !s.cover),
    marks = [];
  if (sec.cover) return [];
  if (sec === inner[0] && view.spread === 0)
    marks.push([0, 'Не печатается: книга начинается с правой страницы']);
  if (sec === inner.at(-1) && sec.kind === 'fixed' && view.spread === sec.spreads.length - 1)
    marks.push([1, 'Не печатается: книга заканчивается левой страницей']);
  return marks.flatMap(([side, label]) => [
    new fabric.Rect({
      left: side * pageWidth(),
      top: 0,
      width: pageWidth(),
      height: pageHeight(),
      fill: 'rgba(240,237,244,.86)',
      stroke: '#cfc6d6',
      strokeWidth: 0.3,
      strokeDashArray: [2, 2],
      selectable: false,
      evented: false,
      excludeFromExport: true,
    }),
    new fabric.Textbox(label, {
      left: side * pageWidth() + pageWidth() * 0.12,
      top: pageHeight() / 2 - 6,
      width: pageWidth() * 0.76,
      fontSize: 4.6,
      fontFamily: 'Arial',
      fill: '#857d8e',
      textAlign: 'center',
      selectable: false,
      evented: false,
      excludeFromExport: true,
    }),
  ]);
}
/* «New block»: choose how it unfolds; it starts with a design that already follows the rule. */
let blockDraft = null;
const BLOCK_KINDS = [
  ['fixed', 'Общие развороты', 'Каждый разворот один раз. Для общих фото, начала и конца альбома.'],
  ['flow', 'Портреты по списку', 'Виньетки учеников или учителей. Разворотов столько, сколько нужно списку.'],
  [
    'repeat',
    'Личные развороты',
    'Повторяются для людей: для каждого ученика, для всех, кроме владельца, или только для владельца.',
  ],
];
const KIND_CHANGE = {
  fixed: 'Каждый разворот выведется один раз, в том же порядке. Дизайн разворотов не меняется.',
  flow: 'Развороты с виньеткой станут повторяемыми, остальные — открывающими или закрывающими.',
  repeat: 'Развороты будут повторяться для людей.',
};
const blockHasGrids = s => s.kind === 'flow' && s.spreads.some(sp => sp.pages.some(MasterPlan.hasGrid));
function openBlockDialog(change = false) {
  if (preview || (change && section().cover)) return;
  blockDraft = change
    ? { change: true, kind: section().kind }
    : {
        kind: 'flow',
        name: '',
        spreads: 2,
        empty: false,
        source: 'students',
        min: 4,
        max: 12,
        intro: false,
        last: true,
        people: 'all',
      };
  $('#block-title').textContent = change ? 'Тип блока' : 'Новый блок';
  $('#block-title').nextElementSibling.textContent = change
    ? 'Как блок раскладывается в альбоме. Дизайн разворотов сохранится.'
    : 'Выберите, как блок строится. Стартовый дизайн можно сразу менять.';
  $('#block-form [type=submit]').textContent = change ? 'Сменить тип' : 'Создать блок';
  $('#block-form .form-error').textContent = '';
  renderBlockDialog();
  $('#block-dialog').showModal();
}
function renderBlockDialog() {
  const d = blockDraft,
    segs = (key, items) =>
      `<div class="segments block-segments" role="group">${items.map(([id, name]) => `<button type="button" data-draft-choice="${key}" data-value="${id}" class="${d[key] === id ? 'active' : ''}" aria-pressed="${d[key] === id}">${name}</button>`).join('')}</div>`,
    check = (key, label) =>
      `<label class="check"><input type="checkbox" data-draft="${key}" ${d[key] ? 'checked' : ''}>${label}</label>`,
    name = `<label>Название<input data-draft="name" maxlength="100" value="${esc(d.name)}" placeholder="${d.kind === 'flow' ? (d.source === 'teachers' ? 'Наши учителя' : 'Наш класс') : d.kind === 'repeat' ? 'Личные развороты' : 'Общие фотографии'}"></label>`;
  let options = '';
  if (d.change) {
    const s = section();
    options =
      d.kind === s.kind
        ? '<p class="section-note">Блок уже такого типа.</p>'
        : blockHasGrids(s) && d.kind !== 'flow'
          ? '<div class="issue">В блоке есть виньетки, а они работают только в портретах по списку. Сначала удалите их.</div>'
          : `<p class="section-note">${KIND_CHANGE[d.kind]}</p>`;
  } else if (d.kind === 'fixed')
    options = `${name}<div class="block-pair"><span>Разворотов</span><label><input type="number" data-draft="spreads" min="1" max="10" value="${d.spreads}" aria-label="Разворотов"></label></div>${check('empty', 'Пустые развороты, без рамок для общих фото')}`;
  else if (d.kind === 'flow')
    options = `${name}<p class="block-label">Кого разместить</p>${segs('source', [
      ['students', 'Учеников'],
      ['teachers', 'Учителей'],
    ])}<div class="block-pair"><span>Карточек на странице</span><label>от<input type="number" data-draft="min" min="1" max="100" value="${d.min}" aria-label="Карточек на странице: от"></label><label>до<input type="number" data-draft="max" min="1" max="100" value="${d.max}" aria-label="Карточек на странице: до"></label></div>${check('intro', d.source === 'teachers' ? 'Открывающий разворот с портретом руководителя' : 'Открывающий разворот с заголовком')}${check('last', 'Последний неполный разворот: виньетка и общее фото')}`;
  else
    options = `${name}<p class="block-label">Для кого</p><div class="block-people">${['all', 'others', 'owner'].map(id => `<button type="button" class="photo-choice${d.people === id ? ' active' : ''}" data-draft-choice="people" data-value="${id}" aria-pressed="${d.people === id}"><span class="photo-radio" aria-hidden="true"></span><span class="photo-choice-copy"><strong>${PEOPLE_NAMES[id]}</strong><small>${PEOPLE_HELP[id]}</small></span></button>`).join('')}</div><p class="section-note">Слева — портрет и имя героя разворота, справа — гибкий коллаж из 1–4 общих фото с ним.</p>`;
  $('#block-body').innerHTML =
    `<div class="block-kinds" role="radiogroup" aria-label="Как строится блок">${BLOCK_KINDS.map(([id, title, help]) => `<button type="button" class="block-kind${d.kind === id ? ' active' : ''}" role="radio" aria-checked="${d.kind === id}" data-draft-choice="kind" data-value="${id}"><span class="block-kind-icon">${kindIcon(id)}</span><strong>${title}</strong><small>${help}</small></button>`).join('')}</div><div class="block-options">${options}</div>`;
}
$('#block-dialog').addEventListener('click', e => {
  const choice = e.target.closest('[data-draft-choice]');
  if (!choice) return;
  blockDraft[choice.dataset.draftChoice] = choice.dataset.value;
  renderBlockDialog();
});
$('#block-dialog').addEventListener('input', e => {
  const el = e.target,
    key = el.dataset.draft;
  if (!key) return;
  blockDraft[key] = el.type === 'checkbox' ? el.checked : el.type === 'number' ? Number(el.value) : el.value;
});
$('#block-form').onsubmit = e => {
  e.preventDefault();
  const d = blockDraft,
    error = $('#block-form .form-error');
  if (d.change) {
    const s = section();
    if (d.kind !== s.kind && blockHasGrids(s) && d.kind !== 'flow')
      return (error.textContent = 'Сначала удалите виньетки.');
    $('#block-dialog').close();
    if (d.kind !== s.kind) blockSet('kind', d.kind);
    return;
  }
  if (d.kind === 'flow' && !(d.min >= 1 && d.max >= d.min && d.max <= 100))
    return (error.textContent = 'Минимум карточек должен быть не больше максимума, от 1 до 100.');
  if (d.kind === 'fixed' && !(d.spreads >= 1 && d.spreads <= 10))
    return (error.textContent = 'Укажите от 1 до 10 разворотов.');
  const created = MasterDefaults.block(d.kind, {
      name: d.name.trim() || undefined,
      spreads: d.spreads,
      empty: d.empty,
      source: d.source,
      min: d.min,
      max: d.max,
      intro: d.intro,
      last: d.last,
      people: d.people,
    }),
    styles = new Set((doc.textStyles || []).map(style => style.id));
  created.spreads.forEach(sp =>
    sp.pages.forEach(p =>
      p.layers.forEach(l => {
        if (l.styleId && !styles.has(l.styleId)) delete l.styleId;
      }),
    ),
  );
  $('#block-dialog').close();
  commit(() => {
    const at = doc.sections.indexOf(section());
    doc.sections.splice(Math.max(at + 1, doc.sections[0]?.cover ? 1 : 0), 0, created);
    view.section = created.id;
    view.spread = 0;
    view.side = 0;
    selected = [];
  });
  notify(`Блок «${created.name}» добавлен`);
};
$('#sections').onclick = e => {
  if (e.target.closest('.section-rename')) return;
  const node = e.target.closest('[data-section]');
  if (!node) return;
  const id = node.dataset.section,
    more = e.target.closest('[data-block-menu-open]');
  if (more) {
    e.stopPropagation();
    openBlockMenu(more, id);
    return;
  }
  if (e.target.closest('[data-block-settings],[data-block-issues]')) {
    hideIssues();
    openBlockSettings(id);
    return;
  }
  view.section = id;
  view.spread = 0;
  view.side = 0;
  selected = [];
  render();
};
$('#sections').onkeydown = e => {
  if (e.key === 'Enter' && e.target.matches('[data-section]')) e.target.click();
};
$('#sections').addEventListener('dblclick', e => {
  if (e.target.closest('.section-card.active .section-name')) startRename();
});
{
  const dialog = $('#block-settings');
  let fromBackdrop = false;
  dialog.addEventListener('pointerdown', e => {
    fromBackdrop = e.target === dialog;
  });
  dialog.addEventListener('click', e => {
    if (e.target === dialog) {
      if (fromBackdrop) dialog.close();
      return;
    }
    const trigger = e.target.closest('[data-block-pick]'),
      value = e.target.closest('[data-block-pick-value]');
    if (trigger) {
      blockPick = blockPick === trigger.dataset.blockPick ? null : trigger.dataset.blockPick;
      renderBlockSettings();
      return;
    }
    if (value) {
      const key = blockPick;
      blockPick = null;
      if (key === 'continues') blockSet('continues', value.dataset.blockPickValue);
      else if (key?.startsWith('role:')) blockSet('role', [key.slice(5), value.dataset.blockPickValue]);
      else renderBlockSettings();
      return;
    }
    if (blockPick) {
      blockPick = null;
      renderBlockSettings();
    }
    const choice = e.target.closest('[data-block]');
    if (choice) return blockSet(choice.dataset.block, choice.dataset.value);
    if (e.target.closest('[data-block-type]')) return openBlockDialog(true);
    if (e.target.closest('[data-add-spread]')) {
      view.spread = section().spreads.length - 1;
      $('#add-spread').click();
      return;
    }
    const go = e.target.closest('[data-goto-spread]');
    if (go) {
      dialog.close();
      view.spread = Number(go.dataset.gotoSpread);
      view.side = 0;
      selected = [];
      render();
    }
  });
  dialog.addEventListener('input', e => {
    const el = e.target;
    if (!el.dataset.testCount || el.value === '' || !el.validity.valid) return;
    view[el.dataset.testCount] = Number(el.value);
    render();
  });
  dialog.addEventListener('change', e => {
    const el = e.target;
    if (el.dataset.testCount) {
      if (el.value === '' || !el.validity.valid) el.value = view[el.dataset.testCount];
      return;
    }
    if (el.dataset.testFlag) {
      view[el.dataset.testFlag] = el.checked;
      render();
      return;
    }
    if ('blockName' in el.dataset) {
      const name = el.value.trim();
      if (name && name !== section().name) blockSet('name', name);
      else el.value = section().name;
      return;
    }
    if (!el.dataset.blockNum) return;
    if (el.value === '' || !el.validity.valid) {
      el.reportValidity();
      return;
    }
    blockSet(el.dataset.blockNum, Number(el.value));
  });
}
let dragSection = null;
function clearSectionDrop() {
  $$('#sections .drop-before,#sections .drop-after').forEach(n =>
    n.classList.remove('drop-before', 'drop-after'),
  );
}
function sectionDropTarget(e) {
  const card = e.target.closest('[data-section]');
  if (!card || card.dataset.section === dragSection) return null;
  const s = doc.sections.find(x => x.id === card.dataset.section);
  const r = card.getBoundingClientRect();
  return { card, after: s?.cover || e.clientY > r.top + r.height / 2 };
}
$('#sections').addEventListener('dragstart', e => {
  const card = e.target.closest('[data-section][draggable]');
  if (!card || preview) return e.preventDefault();
  dragSection = card.dataset.section;
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', dragSection);
  requestAnimationFrame(() => card.classList.add('dragging'));
});
$('#sections').addEventListener('dragover', e => {
  if (!dragSection) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  const t = sectionDropTarget(e);
  clearSectionDrop();
  if (t) t.card.classList.add(t.after ? 'drop-after' : 'drop-before');
});
$('#sections').addEventListener('dragleave', e => {
  if (!$('#sections').contains(e.relatedTarget)) clearSectionDrop();
});
$('#sections').addEventListener('drop', e => {
  if (!dragSection) return;
  e.preventDefault();
  const t = sectionDropTarget(e),
    id = dragSection;
  clearSectionDrop();
  if (!t) return;
  commit(() => {
    const from = doc.sections.findIndex(s => s.id === id);
    const [moved] = doc.sections.splice(from, 1);
    let to = doc.sections.findIndex(s => s.id === t.card.dataset.section) + (t.after ? 1 : 0);
    if (doc.sections[0]?.cover) to = Math.max(1, to);
    doc.sections.splice(to, 0, moved);
  });
});
$('#sections').addEventListener('dragend', () => {
  dragSection = null;
  clearSectionDrop();
  $$('#sections .dragging').forEach(n => n.classList.remove('dragging'));
});
/* The issue mark on a block card shows its warnings on hover; a click opens the block settings. */
function showIssues(mark) {
  const block = doc.sections.find(s => s.id === mark.closest('[data-section]')?.dataset.section),
    issues = block ? planner.designIssues(block) : [];
  if (!issues.length) return;
  let pop = $('#issue-pop');
  if (!pop) {
    pop = document.createElement('div');
    pop.id = 'issue-pop';
    pop.className = 'issue-pop';
    pop.setAttribute('role', 'tooltip');
    document.body.append(pop);
  }
  const errors = issues.filter(i => i.severity === 'error').length,
    warnings = issues.length - errors,
    head = [
      errors && plural(errors, 'ошибка', 'ошибки', 'ошибок'),
      warnings && plural(warnings, 'предупреждение', 'предупреждения', 'предупреждений'),
    ]
      .filter(Boolean)
      .join(' · ');
  pop.innerHTML = `<strong>${head}</strong>${issues.map(i => `<p class="${i.severity}"><i></i><span>${esc(i.text)}</span></p>`).join('')}`;
  pop.hidden = false;
  const r = mark.getBoundingClientRect(),
    box = pop.getBoundingClientRect();
  let left = r.right + 10;
  if (left + box.width > window.innerWidth - 8) left = Math.max(8, r.left - box.width - 10);
  pop.style.left = left + 'px';
  pop.style.top = Math.max(8, Math.min(r.top - 12, window.innerHeight - box.height - 8)) + 'px';
}
function hideIssues() {
  const pop = $('#issue-pop');
  if (pop) pop.hidden = true;
}
['mouseover', 'focusin'].forEach(type =>
  $('#sections').addEventListener(type, e => {
    const mark = e.target.closest('[data-block-issues]');
    if (mark) showIssues(mark);
  }),
);
['mouseout', 'focusout'].forEach(type =>
  $('#sections').addEventListener(type, e => {
    const mark = e.target.closest('[data-block-issues]');
    if (mark && !mark.contains(e.relatedTarget)) hideIssues();
  }),
);
$('#sections').parentElement.addEventListener('scroll', hideIssues, { passive: true });
/* «⋯» on a block card: the rare actions stay out of the way of the thumbnail. */
const SPLIT_GLYPH =
  '<svg viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2.5" y="3" width="5" height="12" rx="1"/><rect x="10.5" y="3" width="5" height="12" rx="1"/></svg>';
function openBlockMenu(button, id) {
  const menu = $('#object-menu'),
    sec = doc.sections.find(s => s.id === id),
    solo = doc.sections.filter(s => !s.cover).length <= 1,
    row = (type, label, icon, enabled = true) =>
      `<button type="button" role="menuitem" data-block-menu="${type}"${enabled ? '' : ' disabled'}>${icon}<span>${label}</span></button>`;
  menu.dataset.block = id;
  const inner = doc.sections.filter(s => !s.cover),
    at = inner.indexOf(sec);
  menu.innerHTML =
    row('section-up', 'Выше', menuGlyph('up'), at > 0) +
    row('section-down', 'Ниже', menuGlyph('down'), at >= 0 && at < inner.length - 1) +
    '<hr>' +
    row('duplicate', 'Дублировать', menuGlyph('duplicate')) +
    (MasterPlan.splittable(sec) && !continuation(sec) ? row('split', 'Разделить блок', SPLIT_GLYPH) : '') +
    '<hr>' +
    row('delete', 'Удалить', menuGlyph('delete'), !solo);
  menu.hidden = false;
  const r = button.getBoundingClientRect(),
    box = menu.getBoundingClientRect();
  let top = r.bottom + 4;
  if (top + box.height > window.innerHeight - 8) top = Math.max(8, r.top - box.height - 4);
  menu.style.left = Math.max(8, Math.min(r.left, window.innerWidth - box.width - 8)) + 'px';
  menu.style.top = top + 'px';
  menu.style.transformOrigin = 'left top';
}
$('#object-menu').addEventListener('click', e => {
  const b = e.target.closest('[data-block-menu]');
  if (!b || b.disabled) return;
  const type = b.dataset.blockMenu,
    id = $('#object-menu').dataset.block;
  closeObjectMenu();
  if (type === 'duplicate' || type === 'delete') return sectionAction(type, id);
  if (type === 'split') return splitBlock(id);
  if (view.section !== id) {
    view.section = id;
    view.spread = 0;
    view.side = 0;
    selected = [];
    render();
  }
  if (type === 'section-up' || type === 'section-down') action(type);
});
/* The name is edited in place: Enter or leaving the field saves it, Esc keeps the old one. */
function startRename() {
  if (preview || section().cover) return;
  const card = $(`#sections [data-section="${view.section}"]`),
    title = card?.querySelector('.section-title');
  if (!title) return;
  card.draggable = false;
  const input = document.createElement('input');
  input.className = 'section-rename';
  input.value = section().name;
  input.maxLength = 100;
  input.setAttribute('aria-label', 'Название блока');
  title.replaceWith(input);
  input.focus();
  input.select();
  let done = false;
  const finish = keep => {
    if (done) return;
    done = true;
    const name = input.value.trim();
    if (keep && name && name !== section().name) blockSet('name', name);
    else renderNavigation();
  };
  input.onkeydown = e => {
    if (e.key === 'Enter') {
      e.preventDefault();
      finish(true);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      finish(false);
    }
  };
  input.onblur = () => finish(true);
}
function sectionAction(type, id) {
  if (preview) return;
  const i = doc.sections.findIndex(s => s.id === id),
    sec = doc.sections[i];
  if (!sec || sec.cover) return;
  if (type === 'delete') {
    if (doc.sections.filter(s => !s.cover).length <= 1)
      return notify('В комплектации должен остаться хотя бы один блок', true);
    commit(() => {
      doc.sections.splice(i, 1);
      if (view.section === id) {
        view.section = (doc.sections[i] || doc.sections[i - 1]).id;
        view.spread = 0;
        view.side = 0;
        selected = [];
      }
    });
    notify(`Блок «${sec.name}» удалён · ⌘Z вернёт`);
    return;
  }
  if (type === 'duplicate')
    commit(() => {
      const copy = freshIds(sec);
      copy.name = (sec.name + ' — копия').slice(0, 100);
      doc.sections.splice(i + 1, 0, copy);
      view.section = copy.id;
      view.spread = 0;
      view.side = 0;
      selected = [];
    });
}
