"""Persist and edit generated proof layouts for local orders."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import base64
import json
import re
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import HTTPException
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel, Field

from .layout_engine import LayoutEngine, LayoutError, ReportLabMeasurer, canonical_hash, load_edition
from .layout_render import render_variant, variant_filename
from .master_layout import SPREAD_TYPES, owner_wildcard, template_pages
from .layout_custom import PAGE_TEMPLATES, add_spread, edit_element, merge_custom, remove_spread, set_page_template

FONT_DIR = Path('/System/Library/Fonts/Supplemental')
FAMILIES = {
    'main': ('Arial.ttf', 'Arial Bold.ttf', 'Arial Italic.ttf', 'Arial Bold Italic.ttf'),
    'display': ('Georgia.ttf', 'Georgia Bold.ttf', 'Georgia Italic.ttf', 'Georgia Bold Italic.ttf'),
    'times': ('Times New Roman.ttf', 'Times New Roman Bold.ttf', 'Times New Roman Italic.ttf', 'Times New Roman Bold Italic.ttf'),
}
STYLE_SUFFIX = ('', '-bold', '-italic', '-bolditalic')


def font_bundle(edition=None):
    fonts = {}
    for key, files in FAMILIES.items():
        regular = FONT_DIR / files[0]
        for suffix, name in zip(STYLE_SUFFIX, files):
            path = FONT_DIR / name
            fonts[key + suffix] = path if path.is_file() else regular
    master = edition.get('master') if isinstance(edition, dict) else None
    for font in (master or {}).get('fonts') or []:
        data = font.get('dataUrl') or ''
        if ',' not in data:
            continue
        fonts_bytes = base64.b64decode(data.split(',', 1)[1])
        for suffix in STYLE_SUFFIX:
            fonts['custom-' + font['id'] + suffix] = fonts_bytes
    return fonts


def measurer(edition=None):
    return ReportLabMeasurer(font_bundle(edition))


class Edit(BaseModel):
    key: str = Field(min_length=1, max_length=300)
    type: str
    value: str | None = None
    revision: str


class AddSpread(BaseModel):
    revision: str
    after_index: int = Field(ge=0)


class PageTemplate(BaseModel):
    revision: str
    template: str


class Revision(BaseModel):
    revision: str


class Operation(BaseModel):
    key: str = Field(min_length=1, max_length=300)
    type: Literal['photo', 'text', 'crop', 'hide', 'reset', 'spread_add', 'spread_remove', 'spread_move']
    value: Any = None
    scope: Literal['variant', 'all'] = 'variant'
    # With scope "all": leave other people's own edits of this element as they are.
    keep_exceptions: bool = False


class Operations(BaseModel):
    revision: str
    ops: list[Operation] = Field(min_length=1, max_length=50)


class OverrideList(BaseModel):
    revision: str
    overrides: list[dict] = Field(max_length=5000)


class Review(BaseModel):
    owner: str = Field(min_length=1, max_length=200)
    reviewed: bool


OVERRIDE_TYPES = ('photo', 'crop', 'text', 'hide')
TEXT_LIMIT = 300
# Bookkeeping fields do not change what is printed, so they stay out of review fingerprints.
META_FIELDS = {'base', 'shared_base', 'shared', 'overridden', 'slot'}
wildcard = owner_wildcard


def element_index(document):
    spreads = [*document.get('shared_spreads', {}).values(), *document.get('covers', {}).values(),
               *(spread for group in document.get('variant_spreads', {}).values() for spread in group.values())]
    return {e['key']: e for spread in spreads for e in spread['elements']}


def variant_spreads(document, owner):
    variant = next((v for v in document.get('variants') or [] if v.get('owner') == owner), None)
    if not variant:
        return []
    result = []
    for key in variant.get('sequence') or []:
        if str(key).startswith('cover['):
            result.append((document.get('covers') or {}).get(owner))
        else:
            result.append((document.get('shared_spreads') or {}).get(key) or
                          ((document.get('variant_spreads') or {}).get(owner) or {}).get(key))
    return [s for s in result if s]


def fingerprints(document):
    """What each variant prints. A review stays valid while its fingerprint is unchanged."""
    return {v['owner']: canonical_hash([[{k: value for k, value in e.items() if k not in META_FIELDS}
                                         for e in spread['elements']] for spread in variant_spreads(document, v['owner'])])
            for v in document.get('variants') or [] if v.get('owner')}


def _rect(value):
    rect = value.get('rect') if isinstance(value, dict) else None
    if not isinstance(rect, list) or len(rect) != 4 or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in rect):
        raise HTTPException(422, 'Кадр задаётся четырьмя числами')
    x, y, w, h = (float(v) for v in rect)
    if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 and 0 < h <= 1):
        raise HTTPException(422, 'Кадр выходит за пределы снимка')
    return [round(v, 6) for v in (x, y, w, h)]


_SPREAD_OWNER = re.compile(r'\[(student:[^\]]+)\]')


def spread_owner(key):
    match = _SPREAD_OWNER.search(key.split('/', 1)[0])
    return match.group(1) if match else None


def spread_operation(document, master, overrides, op):
    """Add, remove or move a spread for everyone or for the album the key belongs to."""
    if not master:
        raise HTTPException(422, 'Развороты можно менять в макетах, собранных из мастер-макета')
    sequences = [v['sequence'] for v in document.get('variants') or []]
    if not any(op.key in sequence for sequence in sequences):
        raise HTTPException(422, 'Разворот не найден. Обновите макет.')
    owner = None if op.scope == 'all' else spread_owner(op.key)
    if op.scope != 'all' and owner is None:
        raise HTTPException(422, 'Не удалось определить альбом разворота')
    target = wildcard(op.key) if op.scope == 'all' else op.key
    value = op.value if isinstance(op.value, dict) else {}
    if op.type == 'spread_add':
        title = str(value.get('title') or '').strip()[:80] or 'Новый разворот'
        source = value.get('source')
        if not isinstance(source, dict) or template_pages(master, source) is None:
            raise HTTPException(422, 'Выберите шаблон разворота')
        source = {k: source[k] for k in ('kind', 'section', 'spread', 'left', 'right') if k in source}
        ident = uuid.uuid4().hex[:10]
        return overrides + [{'key': 'spread:' + ident, 'type': 'spread_add', 'base': None,
                             'value': {'id': ident, 'title': title, 'source': source, 'after': target, 'owner': owner}}]
    if op.key.startswith('cover['):
        raise HTTPException(422, 'Обложку нельзя удалить или переставить')
    if op.type == 'spread_remove':
        added = next((o for o in overrides if o['type'] == 'spread_add' and
                      op.key.split('[', 1)[0] == 'x' + o['value']['id']), None)
        if added and added['value'].get('owner') == owner:
            # Removing a spread added here simply withdraws it together with its edits.
            prefix = 'x' + added['value']['id'] + '['
            return [o for o in overrides if o is not added and not o['key'].startswith(prefix)]
        return overrides + [{'key': 'spread:' + uuid.uuid4().hex[:10], 'type': 'spread_remove', 'base': None,
                             'value': {'target': target, 'owner': owner}}]
    after = value.get('after')
    if after is not None and not (isinstance(after, str) and any(after in sequence for sequence in sequences)):
        raise HTTPException(422, 'Место для разворота не найдено')
    if after is not None and op.scope == 'all':
        after = wildcard(after)
    return overrides + [{'key': 'spread:' + uuid.uuid4().hex[:10], 'type': 'spread_move', 'base': None,
                         'value': {'target': target, 'after': after, 'owner': owner}}]


def apply_operations(document, snapshot, overrides, ops, master=None):
    """Turn editor operations into the stored override list. Pure: the caller regenerates."""
    overrides = [dict(o) for o in overrides]
    index = element_index(document)
    for op in ops:
        if op.type in SPREAD_TYPES:
            overrides = spread_operation(document, master, overrides, op)
            continue
        element = index.get(op.key)
        if element is None:
            raise HTTPException(422, 'Элемент не найден. Обновите макет.')
        shared = op.scope == 'all'
        if shared and not element.get('shared'):
            raise HTTPException(422, 'Этот элемент отличается в вариантах: правка возможна только в одном варианте')
        target = wildcard(op.key) if shared else op.key
        base = element.get('shared_base') if shared else element.get('base')

        def drop(types):
            overrides[:] = [o for o in overrides if not (o['type'] in types and (
                o['key'] in (target, op.key) or (shared and not op.keep_exceptions and wildcard(o['key']) == target)))]

        if op.type == 'reset':
            # Resetting a shared edit leaves other people's own edits of this element alone.
            types = OVERRIDE_TYPES if op.value is None else {op.value} | ({'crop'} if op.value == 'photo' else set())
            overrides[:] = [o for o in overrides if not (o['type'] in types and o['key'] == target)]
            continue
        if op.type in ('photo', 'crop') and element['type'] != 'photo':
            raise HTTPException(422, 'Это не фоторамка')
        if op.type == 'text' and element['type'] != 'text':
            raise HTTPException(422, 'Это не текст')
        if op.type == 'photo':
            if op.value not in snapshot['photos']:
                raise HTTPException(422, 'Выберите фотографию этого заказа')
            drop({'photo', 'crop'})
            value = op.value
        elif op.type == 'crop':
            if not element.get('photo'):
                raise HTTPException(422, 'Сначала поставьте фото в рамку')
            drop({'crop'})
            value = {'photo': element['photo'], 'rect': _rect(op.value)}
        elif op.type == 'text':
            if not isinstance(op.value, str) or len(op.value) > TEXT_LIMIT:
                raise HTTPException(422, f'Текст должен быть не длиннее {TEXT_LIMIT} символов')
            drop({'text'})
            value = op.value
        else:
            if element['type'] not in ('text', 'photo') or not isinstance(op.value, bool):
                raise HTTPException(422, 'Скрыть можно только текст или фото')
            drop({'hide'})
            if not op.value:
                continue
            value = True
        overrides.append({'key': target, 'type': op.type, 'value': value, 'base': base})
    return overrides


def clean_spread(item):
    value, key = item.get('value'), item.get('key')
    def text(v, limit=300):
        return v is None or (isinstance(v, str) and 0 < len(v) <= limit)
    if not isinstance(key, str) or not key.startswith('spread:') or len(key) > 60 or not isinstance(value, dict) or not text(value.get('owner'), 200):
        raise HTTPException(422, 'Список правок повреждён')
    if item['type'] == 'spread_add':
        source = value.get('source')
        if not (isinstance(value.get('id'), str) and re.fullmatch(r'[0-9a-f]{1,32}', value['id']) and isinstance(source, dict)
                and text(value.get('after')) and isinstance(value.get('title', ''), str)):
            raise HTTPException(422, 'Список правок повреждён')
        clean = {'id': value['id'], 'title': value.get('title', '')[:80], 'after': value.get('after'), 'owner': value.get('owner'),
                 'source': {k: source[k] for k in ('kind', 'section', 'spread', 'left', 'right') if k in source}}
    else:
        if not (isinstance(value.get('target'), str) and text(value['target']) and text(value.get('after'))):
            raise HTTPException(422, 'Список правок повреждён')
        clean = {'target': value['target'], 'owner': value.get('owner')}
        if item['type'] == 'spread_move':
            clean['after'] = value.get('after')
    return {'key': key, 'type': item['type'], 'value': clean, 'base': None}


def clean_overrides(items, snapshot):
    """Validate a complete override list sent back by undo/redo."""
    result = []
    for item in items:
        key, kind, value, base = item.get('key'), item.get('type'), item.get('value'), item.get('base')
        if kind in SPREAD_TYPES:
            result.append(clean_spread(item))
            continue
        if not isinstance(key, str) or not 0 < len(key) <= 300 or kind not in OVERRIDE_TYPES or not (base is None or isinstance(base, str)):
            raise HTTPException(422, 'Список правок повреждён')
        if kind == 'photo' and value not in snapshot['photos']:
            raise HTTPException(422, 'Фотография из правки больше недоступна')
        if kind == 'crop':
            if not isinstance(value, dict) or not isinstance(value.get('photo'), str):
                raise HTTPException(422, 'Список правок повреждён')
            value = {'photo': value['photo'], 'rect': _rect(value)}
        if kind == 'text' and (not isinstance(value, str) or len(value) > TEXT_LIMIT):
            raise HTTPException(422, f'Текст должен быть не длиннее {TEXT_LIMIT} символов')
        if kind == 'hide':
            value = True
        result.append({'key': key, 'type': kind, 'value': value, 'base': base})
    return result


def init(con):
    con.execute('''CREATE TABLE IF NOT EXISTS order_layouts (
        order_id TEXT PRIMARY KEY REFERENCES orders(id) ON DELETE CASCADE,
        snapshot TEXT NOT NULL, document TEXT NOT NULL, overrides TEXT NOT NULL,
        generated_at TEXT NOT NULL)''')
    con.execute('''CREATE TABLE IF NOT EXISTS layout_reviews (
        order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
        owner TEXT NOT NULL, fingerprint TEXT NOT NULL, reviewed_at TEXT NOT NULL,
        PRIMARY KEY (order_id, owner))''')


def edition(root):
    return deepcopy(load_edition(root / 'examples/editions/editorial-v2.json'))


def general_entries(con, order_id):
    from .general_photos import snapshot_entries
    return snapshot_entries(con, order_id)


def snapshot_for(con, order, data, master=False):
    photos = {}
    for photo in data['photos']:
        if photo['status'] != 'ready':
            continue
        path = data['data_root'] / 'photos' / (photo['id'] + '.jpg')
        if not path.is_file():
            continue
        with Image.open(path) as image:
            width, height = image.size
        photos[photo['id']] = {'path': str(path), 'width': width, 'height': height}
    selected = {r['person_id']: dict(r) for r in con.execute('''SELECT s.* FROM client_selections s
        JOIN persons p ON p.id=s.person_id WHERE p.order_id=?''', (order['id'],))}
    students, selections = [], []
    for index, person in enumerate(data['persons'], 1):
        choices = [p for p in data['photos'] if p['person_id'] == person['id'] and p['id'] in photos and p['shoot_type'] == 'portrait']
        if not choices and not master:
            continue
        choice = selected.get(person['id'])
        chosen_id = choice['photo_id'] if choice and choice['photo_id'] in {p['id'] for p in choices} else choices[0]['id'] if choices else None
        name = (choice['first_name'] + ' ' + choice['last_name']) if choice else (person['name'] or f'Участник {index}')
        parts = name.strip().split(maxsplit=1)
        students.append({'id': person['id'], 'first_name': parts[0], 'last_name': parts[1] if len(parts)>1 else '', 'quote': choice['quote'] if choice else ''})
        if chosen_id is None:
            continue
        selections.append({'owner': 'student:' + person['id'], 'role': 'main_portrait', 'photo': chosen_id})
        alternate = next((p['id'] for p in choices if p['id'] != chosen_id), chosen_id)
        selections.append({'owner': 'student:' + person['id'], 'role': 'alt_portrait', 'photo': alternate})
    if not master and len(students) < 3:
        raise HTTPException(409, 'Для макета нужны портреты минимум трёх персон. Проверьте группы фотографий.')
    return {'schema_version': 2,
            'order': {'id': order['id'], 'school': order['school'], 'class_name': order['class_name'],
                      'year': str(datetime.now().year), 'studio': ''},
            'students': students, 'teachers': [], 'photos': photos, 'selections': selections,
            'general_photos': [p['id'] for p in data['photos'] if p['id'] in photos and p['shoot_type'] == 'general'],
            'general': [e for e in general_entries(con, order['id']) if e['id'] in photos],
            'teacher_variant': {'enabled': False}}


def read_layout(con, order_id):
    row = con.execute('SELECT * FROM order_layouts WHERE order_id=?', (order_id,)).fetchone()
    if row is None:
        raise HTTPException(404, 'Макет ещё не создан')
    return {'snapshot': json.loads(row['snapshot']), 'document': json.loads(row['document']),
            'overrides': json.loads(row['overrides']), 'generated_at': row['generated_at']}


def layout_status(con, order_id, document):
    current = fingerprints(document)
    publication = approval = None
    row = con.execute('SELECT revision,document,published_at FROM publications WHERE order_id=?', (order_id,)).fetchone()
    approved = con.execute('SELECT snapshot,approved_at FROM approvals WHERE order_id=? ORDER BY approved_at DESC LIMIT 1', (order_id,)).fetchone()
    if row:
        published = fingerprints(json.loads(row['document']))
        publication = {'revision': row['revision'], 'published_at': row['published_at'],
                       'current': row['revision'] == document.get('revision'),
                       'changed': sorted(owner for owner, value in current.items() if published.get(owner) != value)}
    if approved:
        approval = {'revision': json.loads(approved['snapshot']).get('revision'), 'approved_at': approved['approved_at']}
    reviews = {r['owner']: {'reviewed_at': r['reviewed_at'], 'current': current.get(r['owner']) == r['fingerprint']}
               for r in con.execute('SELECT owner,fingerprint,reviewed_at FROM layout_reviews WHERE order_id=?', (order_id,))}
    return {'publication': publication, 'approval': approval, 'reviews': reviews}


def install(app, s):
    def response(layout):
        document = layout['document']
        general = {e['id']: e for e in layout['snapshot'].get('general') or [] if not e.get('legacy')}
        return {'document': document, 'generated_at': layout['generated_at'],
                'overrides': layout.get('overrides') or [], 'status': layout.get('status'),
                'fonts': layout.get('fonts') or [], 'sections': layout.get('sections') or {},
                'shoots': layout.get('shoots') or [], 'templates': layout.get('templates') or [],
                'photos': [{'id': id, 'filename': p['filename'], 'shoot_type': p['shoot_type'],
                            'person_id': p['person_id'], 'shoot_id': p['shoot_id'],
                            'people': layout.get('people', {}).get(id, []),
                            **({k: general[id].get(k) for k in ('bucket', 'scale', 'style', 'quality', 'alt')} if id in general else {}),
                            'width': layout['snapshot']['photos'][id]['width'],
                            'height': layout['snapshot']['photos'][id]['height']}
                           for id, p in layout['photo_info'].items() if id in layout['snapshot']['photos']] + [
                    {'id': key, 'filename': 'Изображение мастер-макета', 'shoot_type': 'general', 'person_id': None,
                     'width': p['width'], 'height': p['height'], 'url': p['url']}
                    for key,p in layout['snapshot']['photos'].items() if p.get('url')]}

    def enrich(con, order_id, layout):
        layout['photo_info'] = {r['id']: dict(r) for r in con.execute('''SELECT p.id,p.filename,p.person_id,p.shoot_id,s.kind AS shoot_type
            FROM photos p LEFT JOIN shoots s ON s.id=p.shoot_id WHERE p.order_id=? AND p.status='ready' ORDER BY p.created_at,p.id''', (order_id,))}
        layout['shoots'] = [dict(r) for r in con.execute('SELECT id,title,kind FROM shoots WHERE order_id=? ORDER BY created_at,id', (order_id,))]
        # Who is on each general photo, from recognised faces: lets the editor offer "photos with this person".
        people = {}
        for r in con.execute('''SELECT DISTINCT f.photo_id,f.subject FROM photo_faces f JOIN photos p ON p.id=f.photo_id
                JOIN persons x ON x.id=f.subject WHERE p.order_id=? AND f.doubtful=0''', (order_id,)):
            people.setdefault(r['photo_id'], []).append(r['subject'])
        layout['people'] = people
        for photo_id in layout['photo_info']:
            if photo_id not in layout['snapshot']['photos']:
                path = s.DATA / 'photos' / (photo_id + '.jpg')
                if path.is_file():
                    with Image.open(path) as image:
                        width, height = image.size
                    layout['snapshot']['photos'][photo_id] = {'path': str(path), 'width': width, 'height': height}
        master = order_edition(con, order_id, s.ROOT).get('master') or {}
        layout['sections'] = {section['id']: section.get('name') or section['id'] for section in master.get('sections') or []}
        layout['sections']['extra'] = 'Добавленный разворот'
        layout['templates'] = [{'section': section['id'], 'name': section.get('name') or section['id'], 'spread': index,
                                'pages': [{'background': page.get('background'), 'layers': [
                                    {'type': l['type'], 'box': l['box'], 'text': l.get('text') if l['type'] == 'text' else None}
                                    for l in page['layers'] if not l.get('hidden') and l['type'] != 'grid']} for page in spread['pages']]}
                               for section in master.get('sections') or [] if not section.get('cover')
                               for index, spread in enumerate(section['spreads'])
                               # Vignettes need the class list, so a vignette-only spread would be added empty.
                               if any(l['type'] != 'grid' and not l.get('hidden') for page in spread['pages'] for l in page['layers'])]
        layout['fonts'] = [{'id': f.get('id'), 'name': f.get('name'), 'dataUrl': f.get('dataUrl')}
                           for f in master.get('fonts') or [] if f.get('id') and f.get('dataUrl')]
        layout['status'] = layout_status(con, order_id, layout['document'])
        return layout

    def save(con, order_id, layout, document, overrides):
        con.execute('UPDATE order_layouts SET snapshot=?,document=?,overrides=? WHERE order_id=?',
                    (json.dumps(layout['snapshot']), json.dumps(document), json.dumps(overrides), order_id))
        return response(enrich(con, order_id, {'snapshot': layout['snapshot'], 'document': document,
                                               'overrides': overrides, 'generated_at': layout['generated_at']}))

    def regenerate(con, order_id, layout, overrides):
        try:
            document = generate_document(order_edition(con, order_id, s.ROOT), layout['snapshot'], overrides)
            return merge_custom(document, layout['document'])
        except LayoutError as exc:
            raise HTTPException(409, str(exc)) from exc

    def current(con, order_id, revision):
        s.require_order(con, order_id)
        layout = enrich(con, order_id, read_layout(con, order_id))
        if revision != layout['document']['revision']:
            raise HTTPException(409, 'Макет изменился в другой вкладке. Обновите страницу.')
        return layout

    @app.post('/api/orders/{order_id}/layout/edits')
    def edit_operations(order_id: str, payload: Operations):
        with s.db() as con:
            layout = current(con, order_id, payload.revision)
            document = layout['document']
            custom = document.get('custom_positions', {})
            if any(op.key.split('/', 1)[0] in custom for op in payload.ops):
                # Legacy spreads added by hand keep their own storage and cannot be undone.
                if len(payload.ops) != 1 or payload.ops[0].type not in ('photo', 'text'):
                    raise HTTPException(422, 'В добавленном вручную развороте можно менять только фото и текст')
                op = payload.ops[0]
                if op.type == 'photo' and op.value not in layout['snapshot']['photos']:
                    raise HTTPException(422, 'Выберите фотографию этого заказа')
                if op.type == 'text' and (not isinstance(op.value, str) or len(op.value) > TEXT_LIMIT):
                    raise HTTPException(422, f'Текст должен быть не длиннее {TEXT_LIMIT} символов')
                try:
                    document = edit_element(document, op.key, op.type, op.value, layout['snapshot'], measurer())
                except (KeyError, StopIteration, ValueError) as exc:
                    raise HTTPException(422, str(exc) if isinstance(exc, ValueError) else 'Элемент не найден') from exc
                return save(con, order_id, layout, document, layout['overrides'])
            overrides = apply_operations(document, layout['snapshot'], layout['overrides'], payload.ops,
                                         order_edition(con, order_id, s.ROOT).get('master'))
            return save(con, order_id, layout, regenerate(con, order_id, layout, overrides), overrides)

    @app.put('/api/orders/{order_id}/layout/overrides')
    def replace_overrides(order_id: str, payload: OverrideList):
        with s.db() as con:
            layout = current(con, order_id, payload.revision)
            overrides = clean_overrides(payload.overrides, layout['snapshot'])
            return save(con, order_id, layout, regenerate(con, order_id, layout, overrides), overrides)

    @app.put('/api/orders/{order_id}/layout/reviews')
    def review_variant(order_id: str, payload: Review):
        with s.db() as con:
            s.require_order(con, order_id)
            document = read_layout(con, order_id)['document']
            prints = fingerprints(document)
            if payload.owner not in prints:
                raise HTTPException(404, 'Вариант не найден')
            if payload.reviewed:
                con.execute('''INSERT INTO layout_reviews VALUES (?,?,?,?) ON CONFLICT(order_id,owner) DO UPDATE SET
                    fingerprint=excluded.fingerprint,reviewed_at=excluded.reviewed_at''',
                            (order_id, payload.owner, prints[payload.owner], s.now()))
            else:
                con.execute('DELETE FROM layout_reviews WHERE order_id=? AND owner=?', (order_id, payload.owner))
            return {'status': layout_status(con, order_id, document)}

    @app.get('/api/orders/{order_id}/layout/publication')
    def published_layout(order_id: str):
        with s.db() as con:
            s.require_order(con, order_id)
            row = con.execute('SELECT revision,document,published_at FROM publications WHERE order_id=?', (order_id,)).fetchone()
            if row is None:
                raise HTTPException(404, 'Макет ещё не опубликован')
            return {'revision': row['revision'], 'published_at': row['published_at'], 'document': json.loads(row['document'])}

    @app.get('/api/orders/{order_id}/layout')
    def get_layout(order_id: str):
        with s.db() as con:
            s.require_order(con, order_id)
            layout = read_layout(con, order_id)
            if not layout['document'].get('master_template') and layout['document'].get('edition') != {'id': 'editorial', 'version': 2}:
                try:
                    document = LayoutEngine(edition(s.ROOT), measurer()).generate(layout['snapshot'], layout['overrides'])
                    document = merge_custom(document, layout['document'])
                except LayoutError as exc:
                    raise HTTPException(409, str(exc)) from exc
                con.execute('UPDATE order_layouts SET document=? WHERE order_id=?', (json.dumps(document), order_id))
                layout['document'] = document
            return response(enrich(con, order_id, layout))

    @app.post('/api/orders/{order_id}/layout')
    def generate_layout(order_id: str):
        with s.db() as con:
            order = dict(s.require_order(con, order_id))
            data = {'persons': [dict(r) for r in con.execute('SELECT id,name FROM persons WHERE order_id=? ORDER BY created_at,id', (order_id,))],
                    'photos': [dict(r) for r in con.execute('''SELECT p.id,p.person_id,p.status,s.kind AS shoot_type
                        FROM photos p LEFT JOIN shoots s ON s.id=p.shoot_id WHERE p.order_id=? ORDER BY p.created_at,p.id''', (order_id,))],
                    'data_root': s.DATA}
            selected_edition = order_edition(con, order_id, s.ROOT)
            snapshot = snapshot_for(con, order, data, master='master' in selected_edition)
            if 'master' in selected_edition:
                enrich_master_snapshot(con, order_id, snapshot, selected_edition, s.DATA)
            old = con.execute('SELECT overrides,document FROM order_layouts WHERE order_id=?', (order_id,)).fetchone()
            overrides = json.loads(old['overrides']) if old else []
            try:
                document = generate_document(selected_edition, snapshot, overrides)
                document = merge_custom(document, json.loads(old['document']) if old else None)
            except LayoutError as exc:
                raise HTTPException(409, str(exc)) from exc
            con.execute('''INSERT INTO order_layouts VALUES (?,?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET
                snapshot=excluded.snapshot,document=excluded.document,overrides=excluded.overrides,generated_at=excluded.generated_at''',
                (order_id, json.dumps(snapshot), json.dumps(document), json.dumps(overrides), s.now()))
            con.execute("UPDATE orders SET stage='layout' WHERE id=?", (order_id,))
            return response(enrich(con, order_id, {'snapshot': snapshot, 'document': document, 'overrides': overrides,
                                                   'generated_at': s.now()}))

    @app.put('/api/orders/{order_id}/layout/element')
    def edit_layout(order_id: str, payload: Edit):
        """Single-element edit kept for older pages; the editor uses /layout/edits."""
        if payload.type not in {'photo', 'text'}:
            raise HTTPException(422, 'Элемент не найден или тип правки неверен')
        return edit_operations(order_id, Operations(revision=payload.revision, ops=[
            Operation(key=payload.key, type=payload.type, value=payload.value)]))

    @app.post('/api/orders/{order_id}/layout/spreads')
    def create_spread(order_id: str, payload: AddSpread):
        with s.db() as con:
            s.require_order(con, order_id)
            layout = enrich(con, order_id, read_layout(con, order_id))
            document = layout['document']
            if payload.revision != document['revision']:
                raise HTTPException(409, 'Макет изменился. Обновите страницу.')
            if document['spread_count'] >= (1000 if document.get('master_template') else 30):
                raise HTTPException(409, 'Достигнут предел числа разворотов')
            key = 'custom:' + s.uid()
            add_spread(document, key, payload.after_index)
            con.execute('UPDATE order_layouts SET document=? WHERE order_id=?', (json.dumps(document), order_id))
            result = response(layout)
            result['added_spread'] = key
            return result

    @app.put('/api/orders/{order_id}/layout/spreads/{spread_key}/pages/{side}')
    def apply_page_template(order_id: str, spread_key: str, side: str, payload: PageTemplate):
        with s.db() as con:
            s.require_order(con, order_id)
            layout = enrich(con, order_id, read_layout(con, order_id))
            document = layout['document']
            if payload.revision != document['revision']:
                raise HTTPException(409, 'Макет изменился. Обновите страницу.')
            if spread_key not in document.get('custom_positions', {}) or side not in {'left', 'right'} or payload.template not in PAGE_TEMPLATES:
                raise HTTPException(422, 'Выберите страницу и шаблон нового разворота')
            set_page_template(document, spread_key, side, payload.template, layout['snapshot'])
            con.execute('UPDATE order_layouts SET document=? WHERE order_id=?', (json.dumps(document), order_id))
            return response(layout)

    @app.delete('/api/orders/{order_id}/layout/spreads/{spread_key}')
    def delete_spread(order_id: str, spread_key: str, payload: Revision):
        with s.db() as con:
            s.require_order(con, order_id)
            layout = enrich(con, order_id, read_layout(con, order_id))
            document = layout['document']
            if payload.revision != document['revision']:
                raise HTTPException(409, 'Макет изменился. Обновите страницу.')
            if spread_key not in document.get('custom_positions', {}):
                raise HTTPException(422, 'Можно удалить только добавленный разворот')
            remove_spread(document, spread_key)
            con.execute('UPDATE order_layouts SET document=? WHERE order_id=?', (json.dumps(document), order_id))
            return response(layout)

    @app.get('/api/orders/{order_id}/layout/pdf/{owner:path}')
    def pdf(order_id: str, owner: str):
        with s.db() as con:
            s.require_order(con, order_id)
            layout = read_layout(con, order_id)
            edition = order_edition(con, order_id, s.ROOT)
        document = layout['document']
        if owner not in {v['owner'] for v in document['variants']}:
            raise HTTPException(404, 'Вариант не найден')
        if any(i['level'] == 'error' for i in document['issues']):
            raise HTTPException(409, 'Исправьте ошибки макета перед экспортом')
        destination = s.DATA / 'layouts' / order_id / document['revision'] / (owner.replace(':', '-') + '.pdf')
        if not destination.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                render_variant(document, owner, layout['snapshot'], s.DATA,
                               measurer(edition), destination)
            except (LayoutError, OSError) as exc:
                raise HTTPException(409, 'Не удалось создать PDF: ' + str(exc)) from exc
        return FileResponse(destination, media_type='application/pdf', filename=variant_filename(1, next(v for v in document['variants'] if v['owner']==owner)))


def order_edition(con, order_id, root):
    row = con.execute('SELECT edition_json FROM order_terms WHERE order_id=?', (order_id,)).fetchone()
    if row and row['edition_json']:
        chosen = json.loads(row['edition_json'])
        if 'master' in chosen:
            return chosen
    return edition(root)


def generate_document(selected, snapshot, overrides):
    if 'master' in selected:
        from .master_layout import generate
        return generate(selected, snapshot, measurer(selected), overrides)
    return LayoutEngine(selected, measurer()).generate(snapshot, overrides)


def enrich_master_snapshot(con, order_id, snapshot, selected, data_root):
    import base64
    import hashlib
    from io import BytesIO
    from .master_templates import validate
    validate(selected['master'])
    snapshot['master_assets'] = {}
    def asset(raw):
        key = 'master-' + hashlib.sha256(raw).hexdigest()
        path = data_root / 'photos' / (key + '.jpg')
        with Image.open(BytesIO(raw)) as image:
            image.convert('RGB').save(path, 'JPEG', quality=95)
            width, height = image.size
        encoded = base64.b64encode(path.read_bytes()).decode()
        snapshot['photos'][key] = {'path':str(path),'width':width,'height':height,'url':'data:image/jpeg;base64,'+encoded}
        return key
    for section in selected['master']['sections']:
        for spread in section['spreads']:
            for page in spread['pages']:
                for layer in page['layers']:
                    if layer['type']=='photo' and layer.get('dataUrl'):
                        snapshot['master_assets'][layer['id']] = asset(base64.b64decode(layer['dataUrl'].split(',',1)[1]))
                    if layer['type']=='collage':
                        def walk(cell):
                            if cell.get('dataUrl'):
                                snapshot['master_assets'][cell['id']] = asset(base64.b64decode(cell['dataUrl'].split(',',1)[1]))
                            for child in cell.get('cells') or []:
                                walk(child)
                        for row in layer.get('rows') or []:
                            for cell in row:
                                walk(cell)
    terms = con.execute('SELECT school_id FROM order_terms WHERE order_id=?', (order_id,)).fetchone()
    if terms and terms['school_id']:
        for row in con.execute('SELECT * FROM teachers WHERE school_id=? ORDER BY id', (terms['school_id'],)):
            teacher = dict(row)
            snapshot['teachers'].append(teacher)
            if teacher['portrait_path']:
                path = (data_root / teacher['portrait_path']).resolve()
                if path.is_relative_to(data_root.resolve()) and path.is_file():
                    key = asset(path.read_bytes())
                    snapshot['selections'].append({'owner':'teacher:'+teacher['id'],'role':'main_portrait','photo':key})
