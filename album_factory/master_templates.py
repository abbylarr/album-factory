"""Studio-owned master documents and immutable published editions."""
from __future__ import annotations
import base64
from copy import deepcopy
from io import BytesIO
import json
import math
import re
from PIL import Image
from fastapi import HTTPException
from pydantic import BaseModel, Field
from .layout_engine import canonical_hash, LayoutError


def init(con):
    con.execute('''CREATE TABLE IF NOT EXISTS master_templates (
        id TEXT PRIMARY KEY, studio_id TEXT NOT NULL, document TEXT NOT NULL,
        revision INTEGER NOT NULL, updated_at TEXT NOT NULL)''')

    con.executescript('''
      CREATE TABLE IF NOT EXISTS designs (
        id TEXT PRIMARY KEY, studio_id TEXT NOT NULL, name TEXT NOT NULL, created_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS master_packages (
        template_id TEXT PRIMARY KEY REFERENCES master_templates(id),
        design_id TEXT NOT NULL REFERENCES designs(id), name TEXT NOT NULL, price INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE IF NOT EXISTS design_blocks (
        id TEXT PRIMARY KEY, design_id TEXT NOT NULL REFERENCES designs(id), name TEXT NOT NULL, document TEXT NOT NULL);
    ''')
    for row in con.execute('SELECT * FROM master_templates WHERE id NOT IN (SELECT template_id FROM master_packages)').fetchall():
        design_id = 'design-' + row['id']
        con.execute('INSERT OR IGNORE INTO designs VALUES (?,?,?,?)', (design_id,row['studio_id'],json.loads(row['document'])['name'],row['updated_at']))
        con.execute('INSERT INTO master_packages VALUES (?,?,?,?)', (row['id'],design_id,'Основная',0))


def validate(document):
    """Reject malformed geometry and executable/remote asset references at the boundary."""
    def check(ok, message):
        if not ok:
            raise HTTPException(422, message)
    check(isinstance(document, dict), 'Нужен документ мастер-макета')
    check(len(json.dumps(document)) <= 8_000_000, 'Макет превышает 8 МБ')
    check(document.get('schemaVersion') == 1, 'Неизвестная версия мастер-макета')
    check(isinstance(document.get('name'), str) and 0 < len(document['name'].strip()) <= 80, 'Укажите название до 80 символов')
    check(document.get('personalMode') in {'all', 'owner', 'off'}, 'Неверный режим личных разворотов')
    sections = document.get('sections')
    check(isinstance(sections, list) and 1 <= len(sections) <= 30, 'Нужно от 1 до 30 разделов')
    ids = set()
    def identity(obj):
        key = obj.get('id')
        check(isinstance(key, str) and re.fullmatch(r'[\w-]{1,100}', key) and key not in ids, 'Идентификаторы должны быть уникальны')
        ids.add(key)
    def number(value, low, high):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and low <= value <= high
    def color(value):
        return isinstance(value, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', value)
    for section in sections:
        check(isinstance(section, dict), 'Неверный раздел'); identity(section)
        check(section.get('kind') in {'fixed', 'flow', 'repeat'}, 'Неверное правило раздела')
        check(isinstance(section.get('name'), str) and len(section['name']) <= 100, 'Неверное название раздела')
        check(number(section.get('target', 1), 1, 100), 'Неверный ориентир объёма')
        spreads = section.get('spreads')
        check(isinstance(spreads, list) and 1 <= len(spreads) <= 100, 'Нужно от 1 до 100 шаблонов разворотов')
        grid_sources = set()
        for spread in spreads:
            check(isinstance(spread, dict), 'Неверный разворот'); identity(spread)
            check(isinstance(spread.get('pages'), list) and len(spread['pages']) == 2, 'В развороте две страницы')
            for page in spread['pages']:
                check(isinstance(page, dict), 'Неверная страница'); identity(page)
                check(color(page.get('background')), 'Неверный цвет страницы')
                check(isinstance(page.get('layers'), list) and len(page['layers']) <= 100, 'Слишком много слоёв')
                check(sum(l.get('type') == 'grid' for l in page['layers'] if isinstance(l, dict)) <= 1, 'На странице допускается одна автовиньетка')
                for layer in page['layers']:
                    check(isinstance(layer, dict), 'Неверный слой'); identity(layer)
                    kind = layer.get('type')
                    check(kind in {'text', 'photo', 'rect', 'ellipse', 'line', 'grid'}, 'Неизвестный инструмент')
                    b = layer.get('box', {})
                    check(isinstance(b, dict) and all(number(b.get(k), 0 if k in 'xy' else .1, 280) for k in ('x','y','w','h')), 'Неверные размеры слоя')
                    check(b['x'] + b['w'] <= 210.01 and b['y'] + b['h'] <= 280.01, 'Слой выходит за страницу')
                    check(number(layer.get('opacity', 100), 0, 100), 'Неверная прозрачность')
                    check(number(layer.get('angle', 0), -180, 180), 'Неверный угол поворота')
                    check(number(layer.get('radius', 0), 0, 100), 'Неверный радиус')
                    check(number(layer.get('strokeWidth', 0), 0, 10), 'Неверная толщина обводки')
                    check(color(layer.get('stroke', '#333333')), 'Неверный цвет обводки')
                    if kind in {'rect','ellipse','line'}:
                        check(color(layer.get('fill')), 'Неверная заливка')
                    if kind in {'text','grid'}:
                        check(layer.get('font') in {'Georgia','Arial','Times New Roman'}, 'Неизвестный шрифт')
                        check(number(layer.get('fontSize'), 4, 120) and color(layer.get('color')), 'Неверный стиль текста')
                    if kind == 'text':
                        check(isinstance(layer.get('text'), str) and len(layer['text']) <= 2000, 'Текст длиннее 2000 символов')
                        check(layer.get('binding') in {'static','owner.name','item.name','lead.name','class','year'}, 'Неверное поле текста')
                        check(layer.get('align') in {'left','center','right'}, 'Неверное выравнивание')
                    if kind == 'photo':
                        check(layer.get('source') in {'lead','owner','item','class','custom'}, 'Неверный источник фото')
                        check(all(number(layer.get(k,50),0,100) for k in ('cropX','cropY')), 'Неверное кадрирование')
                        if layer.get('dataUrl'):
                            try:
                                header, content = layer['dataUrl'].split(',', 1)
                                assert header in {'data:image/png;base64','data:image/jpeg;base64','data:image/webp;base64'}
                                raw = base64.b64decode(content, validate=True)
                                assert len(raw) <= 1_000_000
                                with Image.open(BytesIO(raw)) as image:
                                    assert image.width * image.height <= 25_000_000
                                    image.verify()
                            except Exception as exc:
                                raise HTTPException(422, 'Повреждённое изображение или размер больше 1 МБ') from exc
                    if kind == 'grid':
                        check(section['kind'] == 'flow', 'Автовиньетка требует расширяемого раздела')
                        check(layer.get('source') in {'students','teachers'}, 'Неверный список виньеток')
                        grid_sources.add(layer['source'])
                        check(number(layer.get('min'),1,100) and number(layer.get('max'),1,100) and layer['min'] <= layer['max'], 'Неверные границы виньеток')
                        check(number(layer.get('gap'),0,30) and number(layer.get('minPhotoWidth'),5,180), 'Неверные отступы или ширина фото')
                        check(number(layer.get('minFontSize'),4,layer['fontSize']), 'Неверный минимальный кегль')
        check(len(grid_sources) <= 1, 'В одном разделе нужен один источник виньеток')
    return document


class Save(BaseModel):
    document: dict
    revision: int | None = None


class DesignInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    package_name: str = Field(default='Основная', min_length=1, max_length=80)
    price: int = Field(default=0, ge=0, le=1_000_000)
    document: dict


class PackageInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    price: int = Field(default=0, ge=0, le=1_000_000)
    source_id: str


class PackageEdit(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    price: int = Field(ge=0, le=1_000_000)
    revision: int


class BlockInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    section: dict


class Publish(BaseModel):
    revision: int
    price: int | None = Field(default=None, ge=0, le=1_000_000)


def install(app, s):
    from .mvp import _studio
    def owned(con, key):
        row = con.execute('SELECT * FROM master_templates WHERE id=? AND studio_id=?', (key, _studio())).fetchone()
        if row is None:
            raise HTTPException(404, 'Мастер-макет не найден')
        return row
    def result(con, row):
        meta = con.execute('SELECT p.*,d.name AS design_name FROM master_packages p JOIN designs d ON d.id=p.design_id WHERE p.template_id=?', (row['id'],)).fetchone()
        return {'id': row['id'], 'document': json.loads(row['document']), 'revision': row['revision'], 'updated_at': row['updated_at'], 'package': dict(meta) if meta else None}
    @app.get('/api/master-templates')
    def listing():
        with s.db() as con:
            return [result(con, r) for r in con.execute('SELECT * FROM master_templates WHERE studio_id=? ORDER BY updated_at DESC', (_studio(),))]
    @app.post('/api/master-templates', status_code=201)
    def create(payload: Save):
        validate(payload.document)
        key = s.uid()
        with s.db() as con:
            con.execute('INSERT INTO master_templates VALUES (?,?,?,?,?)', (key, _studio(), json.dumps(payload.document), 1, s.now()))
            design_id = s.uid()
            con.execute('INSERT INTO designs VALUES (?,?,?,?)', (design_id,_studio(),payload.document['name'],s.now()))
            con.execute('INSERT INTO master_packages VALUES (?,?,?,0)', (key,design_id,'Основная'))
            return result(con, owned(con, key))
    @app.post('/api/master-templates/validate')
    def validate_import(payload: Save):
        validate(payload.document)
        return {'valid': True}
    @app.get('/api/master-templates/{key}')
    def get(key: str):
        with s.db() as con:
            return result(con, owned(con, key))
    @app.put('/api/master-templates/{key}')
    def save(key: str, payload: Save):
        validate(payload.document)
        with s.db() as con:
            owned(con, key)
            changed = con.execute('UPDATE master_templates SET document=?,revision=revision+1,updated_at=? WHERE id=? AND revision=?', (json.dumps(payload.document), s.now(), key, payload.revision)).rowcount
            if not changed:
                raise HTTPException(409, 'Черновик изменён в другой вкладке. Скачайте свои правки и откройте серверную версию.')
            return result(con, owned(con, key))
    @app.post('/api/master-templates/{key}/publish', status_code=201)
    def publish(key: str, payload: Publish):
        with s.db() as con:
            row = owned(con, key)
            if row['revision'] != payload.revision:
                raise HTTPException(409, 'Сначала сохраните актуальный черновик')
            master = validate(json.loads(row['document']))
            package = con.execute('SELECT p.*,d.name AS design_name FROM master_packages p JOIN designs d ON d.id=p.design_id WHERE template_id=?', (key,)).fetchone()
            price = package['price'] if package else (payload.price or 0)
            # Legacy API callers may set the initial offer price; package UI saves it beforehand.
            if payload.price is not None: price = payload.price
            title = (package['design_name'] + ' · ' + package['name']) if package else master['name']
            edition_id = f'master-{key}-r{row["revision"]}'
            document = {'id': edition_id, 'version': row['revision'], 'master': master, 'capacity': {'students': [1,1000], 'teachers': [0,1000]}}
            con.execute('INSERT OR IGNORE INTO editions VALUES (?,?,1)', (edition_id, json.dumps(document)))
            offer = con.execute('SELECT id FROM offers WHERE studio_id=? AND edition_id=?', (_studio(), edition_id)).fetchone()
            offer_id = offer['id'] if offer else s.uid()
            if not offer:
                con.execute('INSERT INTO offers VALUES (?,?,?,?,?,1)', (offer_id,_studio(),edition_id,f'{title} · v{row["revision"]}',price))
            return {'edition_id': edition_id, 'offer_id': offer_id, 'version': row['revision']}

    def design_owned(con, key):
        row = con.execute('SELECT * FROM designs WHERE id=? AND studio_id=?', (key,_studio())).fetchone()
        if row is None: raise HTTPException(404, 'Дизайн не найден')
        return row

    def design_result(con, row):
        packages = [dict(p) for p in con.execute('SELECT p.*,m.revision,m.updated_at FROM master_packages p JOIN master_templates m ON m.id=p.template_id WHERE p.design_id=? ORDER BY m.updated_at,p.template_id', (row['id'],))]
        blocks = [{'id':b['id'],'name':b['name'],'section':json.loads(b['document'])} for b in con.execute('SELECT * FROM design_blocks WHERE design_id=? ORDER BY rowid', (row['id'],))]
        return {**dict(row),'packages':packages,'blocks':blocks}

    @app.get('/api/designs')
    def designs():
        with s.db() as con:
            return [design_result(con,r) for r in con.execute('SELECT * FROM designs WHERE studio_id=? ORDER BY created_at DESC', (_studio(),))]

    @app.post('/api/designs', status_code=201)
    def create_design(payload: DesignInput):
        validate(payload.document)
        if not payload.name.strip() or not payload.package_name.strip(): raise HTTPException(422,'Название не может быть пустым')
        key, template_id = s.uid(), s.uid()
        with s.db() as con:
            con.execute('INSERT INTO designs VALUES (?,?,?,?)', (key,_studio(),payload.name.strip(),s.now()))
            con.execute('INSERT INTO master_templates VALUES (?,?,?,?,?)', (template_id,_studio(),json.dumps(payload.document),1,s.now()))
            con.execute('INSERT INTO master_packages VALUES (?,?,?,?)', (template_id,key,payload.package_name.strip(),payload.price))
            return design_result(con,design_owned(con,key))

    @app.get('/api/designs/{key}')
    def get_design(key: str):
        with s.db() as con: return design_result(con,design_owned(con,key))

    @app.post('/api/designs/{key}/packages', status_code=201)
    def copy_package(key: str, payload: PackageInput):
        if not payload.name.strip(): raise HTTPException(422,'Укажите название комплектации')
        with s.db() as con:
            design_owned(con,key)
            source = con.execute('SELECT m.* FROM master_templates m JOIN master_packages p ON p.template_id=m.id WHERE p.design_id=? AND m.id=?', (key,payload.source_id)).fetchone()
            if source is None: raise HTTPException(404,'Исходная комплектация не найдена в этом дизайне')
            template_id=s.uid()
            con.execute('INSERT INTO master_templates VALUES (?,?,?,?,?)', (template_id,_studio(),source['document'],1,s.now()))
            con.execute('INSERT INTO master_packages VALUES (?,?,?,?)', (template_id,key,payload.name.strip(),payload.price))
            return {'template_id':template_id,'design_id':key}

    @app.put('/api/master-templates/{key}/package')
    def edit_package(key: str, payload: PackageEdit):
        if not payload.name.strip(): raise HTTPException(422,'Укажите название комплектации')
        with s.db() as con:
            owned(con,key)
            changed=con.execute('UPDATE master_templates SET revision=revision+1,updated_at=? WHERE id=? AND revision=?', (s.now(),key,payload.revision)).rowcount
            if not changed: raise HTTPException(409,'Комплектация изменилась. Обновите страницу.')
            con.execute('UPDATE master_packages SET name=?,price=? WHERE template_id=?', (payload.name.strip(),payload.price,key))
            return {'revision':payload.revision+1}

    @app.post('/api/designs/{key}/blocks', status_code=201)
    def save_block(key: str, payload: BlockInput):
        validate({'schemaVersion':1,'name':payload.name,'personalMode':'all','sections':[payload.section]})
        with s.db() as con:
            design_owned(con,key)
            block_id=s.uid()
            con.execute('INSERT INTO design_blocks VALUES (?,?,?,?)', (block_id,key,payload.name.strip(),json.dumps(payload.section)))
            return {'id':block_id}
