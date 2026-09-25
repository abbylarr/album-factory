"""Persist and edit generated proof layouts for local orders."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel, Field

from .layout_engine import LayoutEngine, LayoutError, ReportLabMeasurer, load_edition
from .layout_render import render_variant, variant_filename
from .layout_custom import PAGE_TEMPLATES, add_spread, edit_element, merge_custom, remove_spread, set_page_template

FONT = Path('/System/Library/Fonts/Supplemental/Arial.ttf')
DISPLAY_FONT = Path('/System/Library/Fonts/Supplemental/Georgia.ttf')


def measurer():
    return ReportLabMeasurer({'main': FONT, 'display': DISPLAY_FONT})


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


def init(con):
    con.execute('''CREATE TABLE IF NOT EXISTS order_layouts (
        order_id TEXT PRIMARY KEY REFERENCES orders(id) ON DELETE CASCADE,
        snapshot TEXT NOT NULL, document TEXT NOT NULL, overrides TEXT NOT NULL,
        generated_at TEXT NOT NULL)''')


def edition(root):
    return deepcopy(load_edition(root / 'examples/editions/editorial-v2.json'))


def snapshot_for(con, order, data):
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
        if not choices:
            continue
        choice = selected.get(person['id'])
        chosen_id = choice['photo_id'] if choice and choice['photo_id'] in {p['id'] for p in choices} else choices[0]['id']
        name = (choice['first_name'] + ' ' + choice['last_name']) if choice else (person['name'] or f'Участник {index}')
        parts = name.strip().split(maxsplit=1)
        students.append({'id': person['id'], 'first_name': parts[0], 'last_name': parts[1] if len(parts)>1 else '', 'quote': choice['quote'] if choice else ''})
        selections.append({'owner': 'student:' + person['id'], 'role': 'main_portrait', 'photo': chosen_id})
        alternate = next((p['id'] for p in choices if p['id'] != chosen_id), chosen_id)
        selections.append({'owner': 'student:' + person['id'], 'role': 'alt_portrait', 'photo': alternate})
    if len(students) < 3:
        raise HTTPException(409, 'Для макета нужны портреты минимум трёх персон. Проверьте группы фотографий.')
    return {'schema_version': 2,
            'order': {'id': order['id'], 'school': order['school'], 'class_name': order['class_name'],
                      'year': str(datetime.now().year), 'studio': ''},
            'students': students, 'teachers': [], 'photos': photos, 'selections': selections,
            'teacher_variant': {'enabled': False}}


def read_layout(con, order_id):
    row = con.execute('SELECT * FROM order_layouts WHERE order_id=?', (order_id,)).fetchone()
    if row is None:
        raise HTTPException(404, 'Макет ещё не создан')
    return {'snapshot': json.loads(row['snapshot']), 'document': json.loads(row['document']),
            'overrides': json.loads(row['overrides']), 'generated_at': row['generated_at']}


def install(app, s):
    def response(layout):
        document = layout['document']
        return {'document': document, 'generated_at': layout['generated_at'],
                'photos': [{'id': id, 'filename': p['filename'], 'shoot_type': p['shoot_type'],
                            'person_id': p['person_id'],
                            'width': layout['snapshot']['photos'][id]['width'],
                            'height': layout['snapshot']['photos'][id]['height']}
                           for id, p in layout['photo_info'].items() if id in layout['snapshot']['photos']]}

    def enrich(con, order_id, layout):
        layout['photo_info'] = {r['id']: dict(r) for r in con.execute('''SELECT p.id,p.filename,p.person_id,s.kind AS shoot_type
            FROM photos p LEFT JOIN shoots s ON s.id=p.shoot_id WHERE p.order_id=? AND p.status='ready' ''', (order_id,))}
        for photo_id in layout['photo_info']:
            if photo_id not in layout['snapshot']['photos']:
                path = s.DATA / 'photos' / (photo_id + '.jpg')
                if path.is_file():
                    with Image.open(path) as image:
                        width, height = image.size
                    layout['snapshot']['photos'][photo_id] = {'path': str(path), 'width': width, 'height': height}
        return layout

    @app.get('/api/orders/{order_id}/layout')
    def get_layout(order_id: str):
        with s.db() as con:
            s.require_order(con, order_id)
            layout = read_layout(con, order_id)
            if layout['document'].get('edition') != {'id': 'editorial', 'version': 2}:
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
            snapshot = snapshot_for(con, order, data)
            old = con.execute('SELECT overrides,document FROM order_layouts WHERE order_id=?', (order_id,)).fetchone()
            overrides = json.loads(old['overrides']) if old else []
            try:
                document = LayoutEngine(edition(s.ROOT), measurer()).generate(snapshot, overrides)
                document = merge_custom(document, json.loads(old['document']) if old else None)
            except LayoutError as exc:
                raise HTTPException(409, str(exc)) from exc
            con.execute('''INSERT INTO order_layouts VALUES (?,?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET
                snapshot=excluded.snapshot,document=excluded.document,overrides=excluded.overrides,generated_at=excluded.generated_at''',
                (order_id, json.dumps(snapshot), json.dumps(document), json.dumps(overrides), s.now()))
            con.execute("UPDATE orders SET stage='layout' WHERE id=?", (order_id,))
            return response(enrich(con, order_id, {'snapshot': snapshot, 'document': document, 'generated_at': s.now()}))

    @app.put('/api/orders/{order_id}/layout/element')
    def edit_layout(order_id: str, payload: Edit):
        with s.db() as con:
            s.require_order(con, order_id)
            layout = enrich(con, order_id, read_layout(con, order_id))
            if payload.revision != layout['document']['revision']:
                raise HTTPException(409, 'Макет изменился. Обновите страницу.')
            elements = {e['key']: e for spread in [*layout['document']['shared_spreads'].values(),
                *layout['document']['covers'].values(), *(v for group in layout['document']['variant_spreads'].values() for v in group.values())]
                for e in spread['elements']}
            element = elements.get(payload.key)
            if not element or payload.type not in {'photo', 'text'} or element['type'] != payload.type:
                raise HTTPException(422, 'Элемент не найден или тип правки неверен')
            if payload.type == 'photo' and payload.value not in layout['snapshot']['photos']:
                raise HTTPException(422, 'Выберите фотографию этого заказа')
            if payload.type == 'text' and (payload.value is None or len(payload.value) > 300):
                raise HTTPException(422, 'Текст должен быть не длиннее 300 символов')
            if payload.key.split('/', 1)[0] in layout['document'].get('custom_positions', {}):
                try:
                    document = edit_element(layout['document'], payload.key, payload.type,
                                            payload.value, layout['snapshot'], measurer())
                except (KeyError, StopIteration, ValueError) as exc:
                    raise HTTPException(422, str(exc) if isinstance(exc, ValueError) else 'Элемент не найден') from exc
                con.execute('UPDATE order_layouts SET document=? WHERE order_id=?', (json.dumps(document), order_id))
                return response(enrich(con, order_id, {'snapshot': layout['snapshot'], 'document': document,
                                                       'generated_at': layout['generated_at']}))
            overrides = [o for o in layout['overrides'] if o['key'] != payload.key]
            overrides.append({'key': payload.key, 'type': payload.type, 'value': payload.value, 'base': element['base']})
            try:
                document = LayoutEngine(edition(s.ROOT), measurer()).generate(layout['snapshot'], overrides)
                document = merge_custom(document, layout['document'])
            except LayoutError as exc:
                raise HTTPException(409, str(exc)) from exc
            con.execute('UPDATE order_layouts SET snapshot=?,document=?,overrides=? WHERE order_id=?',
                        (json.dumps(layout['snapshot']), json.dumps(document), json.dumps(overrides), order_id))
            return response(enrich(con, order_id, {'snapshot': layout['snapshot'], 'document': document, 'generated_at': layout['generated_at']}))

    @app.post('/api/orders/{order_id}/layout/spreads')
    def create_spread(order_id: str, payload: AddSpread):
        with s.db() as con:
            s.require_order(con, order_id)
            layout = enrich(con, order_id, read_layout(con, order_id))
            document = layout['document']
            if payload.revision != document['revision']:
                raise HTTPException(409, 'Макет изменился. Обновите страницу.')
            if document['spread_count'] >= 30:
                raise HTTPException(409, 'В альбоме уже 30 разворотов')
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
                               measurer(), destination)
            except (LayoutError, OSError) as exc:
                raise HTTPException(409, 'Не удалось создать PDF: ' + str(exc)) from exc
        return FileResponse(destination, media_type='application/pdf', filename=variant_filename(1, next(v for v in document['variants'] if v['owner']==owner)))
