"""Studio-owned master documents and immutable published editions."""
from __future__ import annotations
import base64
from copy import deepcopy
from io import BytesIO
import json
import math
import re
from .photo_pick import RELAX_TEXT
RELAX_MESSAGES = set(RELAX_TEXT.values())
from PIL import Image
from fastapi import HTTPException
from pydantic import BaseModel, Field
from .layout_engine import canonical_hash, LayoutError
from .svg_draw import svg_is_safe
from . import auto_text
from . import general_meta as gm
from .vision import TAGS


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
      CREATE TABLE IF NOT EXISTS photo_categories (
        studio_id TEXT PRIMARY KEY, document TEXT NOT NULL);
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
    v2 = document.get('rulesVersion', 1) == 2
    check(document.get('rulesVersion', 1) in {1, 2}, 'Неизвестная версия правил макета')
    if v2:
        # Block rules live on blocks: list settings on list blocks, whom personal spreads are for on personal blocks.
        check(document.get('layout', 'spreads') in {'spreads', 'book'}, 'Неверная вёрстка альбома')
    else:
        check(document.get('personalMode') in {'all', 'owner', 'off'}, 'Неверный режим личных разворотов')
    size = document.get('pageSize', [210, 280])
    check(isinstance(size, list) and len(size) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 50 <= v <= 500 for v in size), 'Неверный размер макета')
    page_width, page_height = size
    sections = document.get('sections')
    check(isinstance(sections, list) and 1 <= len(sections) <= 30, 'Нужно от 1 до 30 разделов')
    ids = set()
    def identity(obj):
        key = obj.get('id')
        check(isinstance(key, str) and re.fullmatch(r'[\w-]{1,100}', key) and key not in ids, 'Идентификаторы должны быть уникальны')
        ids.add(key)
    def number(value, low, high):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and low <= value <= high
    def safety(value, width, height):
        check(isinstance(value, dict), 'Неверные линии безопасности')
        limit = min(width, height) / 2
        for key in ('safe', 'bleed', 'spine', 'gap'):
            check(number(value.get(key, 0), 0, limit if key != 'bleed' else 30), 'Неверные линии безопасности')
        check(value.get('safe', 0) + value.get('bleed', 0) < limit, 'Зона безопасности не помещается')
    # A book is printed page by page: bleed on the top, bottom and outer edge, a spine strip on the inner edge.
    def book_safety(value, width, height):
        check(isinstance(value, dict) and set(value) <= {'safe', 'bleed', 'outer', 'spine'}, 'Неверные линии безопасности книги')
        for key, high in (('safe', 60), ('bleed', 30), ('outer', 30), ('spine', 40)):
            check(number(value.get(key, 0), 0, high), 'Неверные линии безопасности книги')
        safe = value.get('safe', 0)
        check(value.get('outer', 0) + value.get('spine', 0) + 2 * safe < width and 2 * (value.get('bleed', 0) + safe) < height, 'Зона безопасности книги не помещается')
    # Thickness of one inner sheet sizes the cover spine to the book.
    if 'sheetThickness' in document:
        check(number(document['sheetThickness'], 0.02, 5), 'Толщина листа — от 0,02 до 5 мм')
    if 'safety' in document:
        safety(document['safety'], page_width, page_height)
        if 'book' in document['safety']:
            book_safety(document['safety']['book'], page_width, page_height)
    if 'photoRules' in document:
        rules = document['photoRules']
        check(isinstance(rules, dict) and set(rules) <= {'reuse', 'rhythm', 'chronology', 'mixShoots', 'posedFirst'}, 'Неверные правила общих фото')
        check(rules.get('reuse', 'album') in {'album', 'section', 'allow'}, 'Неверное правило повторов')
        check(all(isinstance(rules.get(k, True), bool) for k in ('rhythm', 'chronology', 'mixShoots', 'posedFirst')), 'Неверные правила общих фото')
    def filters(value, message):
        def subset(key, allowed, limit):
            items = value.get(key)
            check(items is None or (isinstance(items, list) and len(items) <= limit and len(set(items)) == len(items) and set(items) <= set(allowed)), message)
        subset('people', PEOPLE, 5); subset('buckets', gm.BUCKETS, 6); subset('scale', gm.SCALES, 5); subset('tags', TAGS, 12)
        check(value.get('style') in {None, 'posed', 'candid'} and value.get('quality') in {None, 'best', 'good'}, message)
    def pick(value, section):
        from .photo_pick import LEGACY_ROLES
        check(isinstance(value, dict), 'Неверный подбор общего фото')
        if 'category' in value:
            # Categories belong to the studio; an id it no longer has takes any photo (see photo_pick.resolve).
            check(set(value) <= {'category', 'who'} and isinstance(value['category'], str)
                  and re.fullmatch(r'[\w-]{1,40}', value['category']), 'Неизвестная категория общих фото')
            check(value.get('who') in {None, 'hero', 'owner'}, 'Неверное условие «кто на фото»')
            check(value.get('who') != 'hero' or section.get('kind') == 'repeat', 'Герой разворота есть только в личных разворотах')
            return
        check(set(value) <= {'role', 'buckets', 'include', 'scale', 'tags', 'style', 'quality'}, 'Неверный подбор общего фото')
        check(value.get('role', 'any') in LEGACY_ROLES, 'Неизвестная роль слота')
        filters(value, 'Неверный фильтр общего фото')
        check(value.get('include') in {None, 'owner', 'item'}, 'Неверное условие «кто на фото»')
        check(value.get('include') != 'item' or section.get('kind') == 'repeat', 'Герой разворота есть только в личных разворотах')
    from .photo_pick import PEOPLE
    def color(value):
        return isinstance(value, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', value)
    def image_data(value):
        try:
            header, content = value.split(',', 1)
            assert header in {'data:image/png;base64','data:image/jpeg;base64','data:image/webp;base64'}
            raw = base64.b64decode(content, validate=True)
            assert len(raw) <= 1_000_000
            with Image.open(BytesIO(raw)) as image:
                assert image.width * image.height <= 25_000_000
                image.verify()
        except Exception as exc:
            raise HTTPException(422, 'Повреждённое изображение или размер больше 1 МБ') from exc
    def font_data(value):
        try:
            header, content = str(value).split(',', 1)
            assert header in {'data:font/ttf;base64', 'data:font/otf;base64'}
            raw = base64.b64decode(content, validate=True)
            assert 80 <= len(raw) <= 1_500_000
            assert raw[:4] in {b'\x00\x01\x00\x00', b'OTTO', b'true', b'typ1'}
            if header == 'data:font/otf;base64':
                assert raw[:4] == b'OTTO'
            else:
                assert raw[:4] != b'OTTO'
        except Exception as exc:
            raise HTTPException(422, 'Повреждённый шрифт или файл больше 1,5 МБ') from exc
    fonts = document.get('fonts', [])
    check(isinstance(fonts, list) and len(fonts) <= 12, 'Можно сохранить не больше 12 шрифтов')
    known_fonts = {'Georgia', 'Arial', 'Times New Roman'}
    for font in fonts:
        check(isinstance(font, dict), 'Неверный шрифт')
        identity(font)
        check(isinstance(font.get('name'), str) and 0 < len(font['name'].strip()) <= 60, 'Неверное название шрифта')
        font_data(font.get('dataUrl'))
        known_fonts.add(font['id'])
    text_styles = document.get('textStyles', [])
    check(isinstance(text_styles, list) and len(text_styles) <= 50, 'Можно сохранить не больше 50 стилей текста')
    known_styles = set()
    for style in text_styles:
        check(isinstance(style, dict), 'Неверный стиль текста')
        identity(style)
        known_styles.add(style['id'])
        check(isinstance(style.get('name'), str) and 0 < len(style['name'].strip()) <= 60, 'Неверное название стиля')
        check(style.get('font') in known_fonts and number(style.get('fontSize'), 4, 120) and color(style.get('color')), 'Неверный стиль текста')
        check(style.get('align') in {'left', 'center', 'right', 'justify'}, 'Неверное выравнивание стиля')
        check(number(style.get('lineHeight'), 0.8, 3) and number(style.get('letterSpacing'), -20, 80), 'Неверные интервалы стиля')
        check(number(style.get('skew', 0), -30, 30), 'Неверный наклон стиля')
        check(style.get('textCase', '') in ('', *auto_text.CASES), 'Неверный регистр стиля')
        for flag in ('bold', 'italic', 'underline', 'strike'):
            check(isinstance(style.get(flag), bool), 'Неверное начертание стиля')
    for section in sections:
        check(isinstance(section, dict), 'Неверный раздел'); identity(section)
        if section.get('cover'):
            check(section is sections[0] and sum(bool(s.get('cover')) for s in sections) == 1, 'Обложка должна быть первой и единственной')
            check(section.get('kind') == 'fixed' and isinstance(section.get('spreads'), list) and len(section['spreads']) == 1, 'Обложка содержит один разворот')
            cover_size = section.get('pageSize')
            check(isinstance(cover_size, list) and len(cover_size) == 2 and all(number(v, 50, 500) for v in cover_size), 'Неверный размер обложки')
            page_width, page_height = cover_size
            safety(section.get('safety', {}), page_width, page_height)
        else:
            check('pageSize' not in section, 'Все внутренние страницы используют общий размер макета')
            page_width, page_height = size
        check(section.get('kind') in {'fixed', 'flow', 'repeat'}, 'Неверное правило раздела')
        check(isinstance(section.get('name'), str) and len(section['name']) <= 100, 'Неверное название раздела')
        check(number(section.get('target', 1), 1, 100), 'Неверный ориентир объёма')
        spreads = section.get('spreads')
        check(isinstance(spreads, list) and 1 <= len(spreads) <= 100, 'Нужно от 1 до 100 шаблонов разворотов')
        block_list = None
        if v2 and not section.get('cover'):
            if section['kind'] == 'flow':
                block_list = section.get('list')
                check(isinstance(block_list, dict) and set(block_list) <= {'source', 'min', 'max', 'strictMin', 'excludeLead'}, 'Нужны настройки списка блока')
                check(block_list.get('source') in {'students', 'teachers'}, 'Неверный список блока')
                check(number(block_list.get('min'), 1, 100) and number(block_list.get('max'), 1, 100) and block_list['min'] <= block_list['max'], 'Неверные границы карточек на странице')
                check(all(isinstance(block_list.get(k, False), bool) for k in ('strictMin', 'excludeLead')), 'Неверные настройки списка блока')
                check(sum(s.get('role') == 'last' for s in spreads if isinstance(s, dict)) <= 1, 'В блоке может быть один последний неполный разворот')
            if section['kind'] == 'repeat':
                check(section.get('people', 'all') in {'all', 'others', 'owner', 'off'}, 'Неверный выбор, для кого личные развороты')
            # A split block: the continuation names another block of the same kind and people; only a continued block has a limit.
            # Order is not checked here: a continuation dragged above its start is reported when the album is built.
            if 'continues' in section:
                start = next((s for s in sections if s is not section and isinstance(s, dict) and s.get('id') == section['continues']), None)
                same = start is not None and start.get('kind') == section['kind'] and (
                    section['kind'] == 'flow' and (start.get('list') or {}).get('source') == (block_list or {}).get('source')
                    or section['kind'] == 'repeat' and start.get('people', 'all') == section.get('people', 'all') in {'all', 'others'})
                check(same, 'Продолжение ссылается на неверный блок')
                check(sum(isinstance(s, dict) and s.get('continues') == section['continues'] for s in sections) == 1, 'У блока может быть одно продолжение')
            if 'limit' in section:
                check(isinstance(section['limit'], int) and not isinstance(section['limit'], bool) and 1 <= section['limit'] <= 100, 'Неверное число разворотов части')
                check(any(isinstance(s, dict) and s.get('continues') == section.get('id') for s in sections), 'Ограничение разворотов нужно только блоку с продолжением')
        grid_sources = set()
        for spread in spreads:
            check(isinstance(spread, dict), 'Неверный разворот'); identity(spread)
            check(spread.get('role', 'repeat') in {'intro', 'repeat', 'last', 'outro'}, 'Неверная роль разворота')
            check(isinstance(spread.get('pages'), list) and len(spread['pages']) == 2, 'В развороте две страницы')
            for side, page in enumerate(spread['pages']):
                check(isinstance(page, dict), 'Неверная страница'); identity(page)
                check(color(page.get('background')), 'Неверный цвет страницы')
                check(isinstance(page.get('layers'), list) and len(page['layers']) <= 100, 'Слишком много слоёв')
                check(sum(l.get('type') == 'grid' for l in page['layers'] if isinstance(l, dict)) <= 1, 'На странице допускается одна автовиньетка')
                for layer in page['layers']:
                    check(isinstance(layer, dict), 'Неверный слой'); identity(layer)
                    kind = layer.get('type')
                    check(kind in {'text', 'photo', 'rect', 'ellipse', 'line', 'grid', 'collage', 'svg'}, 'Неизвестный инструмент')
                    b = layer.get('box', {})
                    # Box is relative to its page; any layer but a vignette may cross the fold and hang past the
                    # spread edges (print cuts it), as long as part of it stays on the spread. A vignette stays inside its page.
                    # On the cover a layer may be pinned to the spine: «spine» keeps its offset from the spine centre and
                    # sits on the side that holds its centre; «wrap» runs over the spine on the back side and grows with it
                    # (its width excludes the spine).
                    pin = layer.get('pin')
                    check(pin is None or section.get('cover') and (pin == 'spine' and kind != 'grid' or pin == 'wrap' and side == 0 and kind in {'photo', 'rect', 'ellipse', 'line', 'svg'}), 'Неверная привязка к корешку')
                    left, right = (0, page_width) if kind == 'grid' else (-2 * page_width, 2 * page_width) if pin == 'spine' else (0, 2 * page_width) if pin == 'wrap' else (-side * page_width, (2 - side) * page_width)
                    limit = 2 * max(page_width, page_height)
                    check(isinstance(b, dict) and number(b.get('x'), left - limit, right) and number(b.get('y'), -limit, page_height) and all(number(b.get(k), .1, limit) for k in ('w', 'h')), 'Неверные размеры слоя')
                    if kind == 'grid':
                        check(b['x'] >= left - .01 and b['y'] >= -.01 and b['x'] + b['w'] <= right + .01 and b['y'] + b['h'] <= page_height + .01, 'Виньетка выходит за страницу')
                    else:
                        check(b['x'] < right and b['x'] + b['w'] > left and b['y'] < page_height and b['y'] + b['h'] > 0, 'Слой целиком за разворотом')
                    check(number(layer.get('opacity', 100), 0, 100), 'Неверная прозрачность')
                    check('z' not in layer or number(layer['z'], 0, 10000), 'Неверный порядок слоя')
                    check(number(layer.get('angle', 0), -180, 180), 'Неверный угол поворота')
                    check(all(isinstance(layer.get(k, False), bool) for k in ('flipX', 'flipY')), 'Неверное отражение')
                    check(number(layer.get('radius', 0), 0, 100), 'Неверный радиус')
                    check(number(layer.get('strokeWidth', 0), 0, 10), 'Неверная толщина обводки')
                    check(color(layer.get('stroke', '#333333')), 'Неверный цвет обводки')
                    if 'strokeDash' in layer:
                        check(layer['strokeDash'] in {'solid', 'dashed', 'dotted'}, 'Неверный штрих обводки')
                    if 'strokeAlign' in layer:
                        check(layer['strokeAlign'] in {'center', 'inside', 'outside'}, 'Неверное положение обводки')
                    if 'strokeCap' in layer:
                        check(layer['strokeCap'] in {'butt', 'round', 'square'}, 'Неверные концы обводки')
                    if 'strokeJoin' in layer:
                        check(layer['strokeJoin'] in {'miter', 'round', 'bevel'}, 'Неверные стыки обводки')
                    if 'strokeOn' in layer:
                        check(isinstance(layer['strokeOn'], bool), 'Неверная обводка')
                    if layer.get('shadow') is not None:
                        shadow = layer['shadow']
                        check(isinstance(shadow, dict) and color(shadow.get('color')) and number(shadow.get('offsetX', 0), -30, 30) and number(shadow.get('offsetY', 0), -30, 30) and number(shadow.get('blur', 0), 0, 40) and number(shadow.get('opacity', 40), 0, 100), 'Неверная тень')
                    if kind in {'rect','ellipse','line','svg'}:
                        check(color(layer.get('fill')), 'Неверная заливка')
                    if kind == 'svg':
                        check(svg_is_safe(layer.get('svg')), 'Неверный SVG')
                        check(layer.get('fillMode', 'original') in {'original', 'color', 'none'}, 'Неверная заливка SVG')
                        check(layer.get('strokeMode', 'original') in {'original', 'color', 'none'}, 'Неверная обводка SVG')
                    if kind in {'text','grid'}:
                        check(layer.get('font') in known_fonts, 'Неизвестный шрифт')
                        check(number(layer.get('fontSize'), 4, 120) and color(layer.get('color')), 'Неверный стиль текста')
                        for flag in ('bold', 'italic', 'underline', 'strike'):
                            if flag in layer:
                                check(isinstance(layer[flag], bool), 'Неверное начертание')
                        check(number(layer.get('lineHeight', 1.25), 0.8, 3), 'Неверный интерлиньяж')
                        check(number(layer.get('letterSpacing', 0), -20, 80), 'Неверный межбуквенный интервал')
                        check(number(layer.get('skew', 0), -30, 30), 'Наклон текста — от −30° до 30°')
                    if kind == 'text':
                        if layer.get('styleId'):
                            check(layer['styleId'] in known_styles, 'Неизвестный стиль текста')
                        check(isinstance(layer.get('text'), str) and len(layer['text']) <= 2000, 'Текст длиннее 2000 символов')
                        check('binding' not in layer and not auto_text.unknown(layer['text']), 'Неизвестные данные в тексте')
                        check(layer.get('align') in {'left','center','right','justify'}, 'Неверное выравнивание')
                        check(layer.get('valign', 'top') in {'top','middle','bottom'}, 'Неверное выравнивание по вертикали')
                        check(layer.get('textCase', '') in ('', *auto_text.CASES), 'Неверный регистр')
                        check(isinstance(layer.get('fit', False), bool), 'Неверная настройка рамки текста')
                    if kind == 'photo':
                        check(layer.get('source') in {'lead','owner','item','class','custom'}, 'Неверный источник фото')
                        if 'pick' in layer:
                            pick(layer['pick'], section)
                        check(all(number(layer.get(k,50),0,100) for k in ('cropX','cropY')), 'Неверное кадрирование')
                        check(number(layer.get('cropZoom',1),1,4), 'Неверный масштаб кадрирования')
                        if layer.get('dataUrl'):
                            image_data(layer['dataUrl'])
                    if kind == 'collage':
                        check(number(layer.get('gapX', 4), 0, 40) and number(layer.get('gapY', 4), 0, 40), 'Неверные зазоры коллажа')
                        if layer.get('flex') is not None:
                            flex = layer['flex']
                            check(isinstance(flex, dict) and set(flex) <= {'min', 'max'} and isinstance(flex.get('min'), int) and isinstance(flex.get('max'), int)
                                  and 1 <= flex['min'] <= flex['max'] <= 6, 'Гибкий коллаж: от 1 до 6 фото, минимум не больше максимума')
                            pick(layer.get('pick') or {'category': 'any'}, section)
                        check(isinstance(layer.get('gapLinked', True), bool), 'Неверная связь зазоров коллажа')
                        check(color(layer.get('fill', '#e6e1ea')), 'Неверная заливка коллажа')
                        rows = layer.get('rows')
                        check(isinstance(rows, list) and 1 <= len(rows) <= 8, 'В коллаже от 1 до 8 рядов')
                        leaves = 0
                        def check_cell(cell, depth=0):
                            nonlocal leaves
                            check(isinstance(cell, dict), 'Неверный кадр коллажа')
                            identity(cell)
                            check(depth <= 4, 'Слишком глубокое деление кадра')
                            if cell.get('split'):
                                check(cell.get('split') in {'h', 'v'}, 'Неверное деление кадра')
                                children = cell.get('cells')
                                check(isinstance(children, list) and 2 <= len(children) <= 8, 'В делении нужно от 2 до 8 кадров')
                                for child in children:
                                    check_cell(child, depth + 1)
                            else:
                                leaves += 1
                                check(cell.get('source', 'class') in {'lead', 'owner', 'item', 'class', 'custom'}, 'Неверный источник фото')
                                if 'pick' in cell:
                                    pick(cell['pick'], section)
                                check(all(number(cell.get(k, 50), 0, 100) for k in ('cropX', 'cropY')), 'Неверное кадрирование')
                                check(number(cell.get('cropZoom', 1), 1, 4), 'Неверный масштаб кадрирования')
                                if cell.get('dataUrl'):
                                    image_data(cell['dataUrl'])
                        for row in rows:
                            check(isinstance(row, list) and 1 <= len(row) <= 8, 'В ряду коллажа от 1 до 8 кадров')
                            for cell in row:
                                check_cell(cell)
                        check(1 <= leaves <= 48, 'Слишком много кадров коллажа')
                    if kind == 'grid':
                        check(section['kind'] == 'flow', 'Автовиньетка требует расширяемого раздела')
                        check(layer.get('source') in {'students','teachers'}, 'Неверный список виньеток')
                        check(isinstance(layer.get('showDetail', False), bool), 'Неверная настройка дополнительной подписи')
                        check(layer.get('detailFont', layer.get('font')) in known_fonts and number(layer.get('detailFontSize', 9), 4, 120) and color(layer.get('detailColor', layer.get('color'))), 'Неверный стиль дополнительной подписи')
                        check(layer.get('align', 'center') in {'left','center','right','justify'} and layer.get('detailAlign', 'center') in {'left','center','right','justify'}, 'Неверное выравнивание виньеток')
                        check(number(layer.get('detailLineHeight', 1.25), 0.8, 3) and number(layer.get('detailLetterSpacing', 0), -20, 80), 'Неверные интервалы дополнительной подписи')
                        for flag in ('detailBold','detailItalic','detailUnderline','detailStrike'):
                            if flag in layer: check(isinstance(layer[flag], bool), 'Неверное начертание дополнительной подписи')
                        grid_sources.add(layer['source'])
                        if block_list is not None:
                            check(layer['source'] == block_list['source'], 'Список виньетки должен совпадать со списком блока')
                        else:
                            check(number(layer.get('min'),1,100) and number(layer.get('max'),1,100) and layer['min'] <= layer['max'], 'Неверные границы виньеток')
                        check(number(layer.get('gap'),0,30) and number(layer.get('minPhotoWidth'),5,180), 'Неверные отступы или ширина фото')
                        check(number(layer.get('minPhotoWidth'),5,180) and number(layer.get('photoWidth', 85),5,180) and layer['minPhotoWidth'] <= layer.get('photoWidth', 85), 'Неверный диапазон ширины фото')
                        check(number(layer.get('photoNameGap',3),0,20) and number(layer.get('nameDetailGap',2),0,20), 'Неверное расстояние между фото и подписями')
                        check(number(layer.get('minFontSize'),4,layer['fontSize']), 'Неверный минимальный кегль')
        check(len(grid_sources) <= 1, 'В одном разделе нужен один источник виньеток')
    return document


def validate_categories(value):
    """The studio's photo categories: edits of built-ins and its own ones, plus removed built-ins («Любое» stays)."""
    from .photo_pick import CATEGORIES, PEOPLE
    def check(ok, message):
        if not ok:
            raise HTTPException(422, message)
    check(isinstance(value, dict) and set(value) <= {'items', 'removed'}, 'Неверные категории общих фото')
    removed, items = value.get('removed', []), value.get('items', [])
    check(isinstance(removed, list) and len(set(removed)) == len(removed)
          and all(isinstance(k, str) and k in CATEGORIES and k != 'any' for k in removed), 'Неверные удалённые категории')
    check(isinstance(items, list) and len(items) <= 60, 'Неверные категории общих фото')
    seen = set()
    for item in items:
        check(isinstance(item, dict) and set(item) <= {'id', 'name', 'people', 'scale', 'tags', 'style', 'quality'}, 'Неверная категория общих фото')
        check(isinstance(item.get('id'), str) and re.fullmatch(r'[\w-]{1,40}', item['id']) and item['id'] not in seen
              and item['id'] not in removed, 'Неверная категория общих фото')
        check(isinstance(item.get('name'), str) and 1 <= len(item['name'].strip()) <= 40, 'Название категории — от 1 до 40 символов')
        for key, allowed, limit in (('people', PEOPLE, 5), ('scale', gm.SCALES, 5), ('tags', TAGS, 12)):
            values = item.get(key)
            check(values is None or (isinstance(values, list) and len(values) <= limit and len(set(values)) == len(values)
                                     and set(values) <= set(allowed)), 'Неверный фильтр категории')
        check(item.get('style') in {None, 'posed', 'candid'} and item.get('quality') in {None, 'best', 'good'}, 'Неверный фильтр категории')
        seen.add(item['id'])
    return {'items': items, 'removed': removed}


def studio_categories(con, studio):
    """The studio's category list as stored (empty when it keeps the built-ins as they are)."""
    row = con.execute('SELECT document FROM photo_categories WHERE studio_id=?', (studio,)).fetchone()
    return json.loads(row['document']) if row else {'items': [], 'removed': []}


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


class PhotoPreview(BaseModel):
    document: dict
    students: int = Field(default=12, ge=1, le=60)
    teachers: int = Field(default=10, ge=0, le=40)
    owner: str = Field(default='s0', max_length=10)


class ClassPreview(BaseModel):
    document: dict
    order_id: str = Field(min_length=1, max_length=100)


class _FlatMeasurer:
    """Text is irrelevant for photo previews; everything fits."""
    def height(self, *args, **kwargs):
        return 0

    def width(self, *args, **kwargs):
        return 0

    def missing_glyphs(self, *args, **kwargs):
        return set()


def preview_photos(document, students, teachers, owner, categories=None):
    """Run the real picker on a synthetic shoot: what each automatic slot of the draft would receive."""
    from .master_layout import generate
    from .test_shoot import synthetic
    people = [{'id': f's{i}', 'first_name': 'Ученик', 'last_name': str(i + 1), 'quote': ''} for i in range(students)]
    staff = [{'id': f't{i}', 'first_name': 'Учитель', 'last_name': str(i + 1), 'school_subject': ''} for i in range(teachers)]
    entries, photos = synthetic(people)
    for person in people + staff:
        photos['portrait-' + person['id']] = {'width': 3000, 'height': 4000, 'path': ''}
    selections = [{'owner': ('student:' if p in people else 'teacher:') + p['id'], 'role': 'main_portrait', 'photo': 'portrait-' + p['id']} for p in people + staff]
    snapshot = {'schema_version': 2, 'order': {'id': 'preview', 'school': 'Школа № 5', 'city': 'Казань', 'class_name': '11 А', 'year': '2026', 'studio': ''},
                'students': people, 'teachers': staff, 'photos': photos, 'selections': selections, 'general': entries,
                'general_photos': [e['id'] for e in entries], 'master_assets': {}}
    if owner not in {p['id'] for p in people}:
        owner = people[0]['id']
    try:
        result = generate({'id': 'preview', 'version': 0, 'master': document, 'photoCategories': categories},
                          snapshot, _FlatMeasurer(), only_owner=owner)
    except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError) as exc:
        raise HTTPException(422, 'Не удалось построить превью: ' + str(exc)[:120]) from exc
    by_id = {e['id']: e for e in entries}
    slots = {}
    spreads = list(result['variant_spreads'].get('student:' + owner, {}).values()) + [result['covers'].get('student:' + owner) or {'elements': []}]
    for spread in spreads:
        for element in spread['elements']:
            if not element.get('slot'):
                continue
            match = re.match(r'^(?:cover|([\w-]+))\[student:[^\]]+\](?::(\d+))?/(\d)/(.+)$', element['key'])
            if not match:
                continue
            section = match.group(1) or next((s['id'] for s in document['sections'] if s.get('cover')), 'cover')
            page = int(match.group(2) or 0) * 2 + int(match.group(3))
            entry = by_id.get(element.get('photo'))
            info = result['photo_report']['slots'].get(element['slot'], {})
            item = {'candidates': info.get('candidates', 0), 'relaxed': info.get('relaxed', [])}
            if entry:
                w, h = photos[entry['id']]['width'], photos[entry['id']]['height']
                x, y, cw, ch = element['crop']
                item.update({'photo': entry['id'], 'size': [w, h], 'crop': [x / w, y / h, cw / w, ch / h], 'bucket': entry['bucket'],
                             'scale': entry['scale'], 'persons': [{'box': p['box'], 'face': p['face'], 'owner': p['subject'] == owner} for p in entry['persons']]})
            slots[f'{section}:{page}/{match.group(4)}'] = item
    return {'slots': slots, 'photos': len(entries),
            'issues': [i for i in result['issues'] if i['key'].startswith(('coverage', 'must')) or '[*]' in i['key'] or '[student:' in i['key'] and i['message'] in RELAX_MESSAGES]}


def select_order_master(con, order_id, template_id):
    """Freeze the chosen saved master for this order, without publishing an offer."""
    from .mvp import _studio
    row = con.execute('SELECT * FROM master_templates WHERE id=? AND studio_id=?', (template_id, _studio())).fetchone()
    if row is None:
        raise HTTPException(404, 'Мастер-макет не найден')
    master = validate(json.loads(row['document']))
    document = {'id': f'master-{template_id}-r{row["revision"]}', 'version': row['revision'],
                'master': master, 'capacity': {'students': [1, 1000], 'teachers': [0, 1000]},
                'photoCategories': studio_categories(con, _studio())}
    con.execute('UPDATE order_terms SET edition_json=?, edition_id=NULL, offer_id=NULL WHERE order_id=?',
                (json.dumps(document), order_id))
    con.execute('UPDATE orders SET master_template_id=? WHERE id=?', (template_id, order_id))
    # The album price belongs to the chosen package, not to the order form.
    package = con.execute('SELECT p.name,p.price,d.name AS design_name FROM master_packages p JOIN designs d ON d.id=p.design_id WHERE p.template_id=?', (template_id,)).fetchone()
    if package is not None:
        con.execute('UPDATE orders SET price=? WHERE id=?', (package['price'], order_id))
        con.execute('UPDATE order_terms SET offer_title=?, offer_price=? WHERE order_id=?',
                    (f"{package['design_name']} · {package['name']}", package['price'], order_id))


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
    @app.post('/api/master-templates/photo-preview')
    def photo_preview(payload: PhotoPreview):
        with s.db() as con:
            categories = studio_categories(con, _studio())
        return preview_photos(payload.document, payload.students, payload.teachers, payload.owner, categories)
    # Photo categories are the studio's: one list for every design and package.
    @app.get('/api/photo-categories')
    def photo_categories():
        with s.db() as con:
            return studio_categories(con, _studio())
    @app.put('/api/photo-categories')
    def save_photo_categories(payload: dict):
        value = validate_categories(payload)
        with s.db() as con:
            if value['items'] or value['removed']:
                con.execute('INSERT OR REPLACE INTO photo_categories VALUES (?,?)', (_studio(), json.dumps(value)))
            else:
                con.execute('DELETE FROM photo_categories WHERE studio_id=?', (_studio(),))
        return value

    @app.get('/api/preview-classes')
    def preview_classes():
        # Classes are orders; a class is ready when every student has a portrait and a filled form and the class has general photos.
        from . import mvp
        from .client_portal import progress_by_order
        studio = mvp.studio_ctx.get()
        where, args = ('WHERE EXISTS (SELECT 1 FROM order_membership m WHERE m.order_id=o.id AND m.studio_id=?)', (studio,)) if studio is not None else ('', ())
        with s.db() as con:
            rows = con.execute(f'''SELECT o.id,o.school,o.class_name,o.graduation_year,o.stage,
              (SELECT COUNT(*) FROM persons p WHERE p.order_id=o.id) AS students,
              (SELECT COUNT(*) FROM persons p WHERE p.order_id=o.id AND EXISTS (SELECT 1 FROM photos f LEFT JOIN shoots h ON h.id=f.shoot_id
                 WHERE f.person_id=p.id AND f.status='ready' AND COALESCE(h.kind,'portrait')='portrait')) AS with_portrait,
              (SELECT COUNT(*) FROM photos f JOIN shoots h ON h.id=f.shoot_id WHERE f.order_id=o.id AND h.kind='general' AND f.status='ready') AS general,
              (SELECT COUNT(*) FROM photos f WHERE f.order_id=o.id AND f.status IN ('pending','processing')) AS pending
              FROM orders o {where} ORDER BY o.created_at DESC''', args).fetchall()
            progress = progress_by_order(con)
        result = []
        for row in rows:
            item = dict(row, forms=progress[row['id']]['completed'])
            missing = []
            if not item['students']:
                missing.append('нет учеников')
            elif item['with_portrait'] < item['students']:
                missing.append(f"нет портретов у {item['students'] - item['with_portrait']} из {item['students']} учеников")
            if item['pending']:
                missing.append('фотографии ещё обрабатываются')
            if item['students'] and item['forms'] < item['students']:
                missing.append(f"анкеты заполнили {item['forms']} из {item['students']}")
            if not item['general']:
                missing.append('нет общих фотографий')
            item['missing'] = missing
            item['ready'] = not missing
            result.append(item)
        return result

    @app.post('/api/master-templates/{key}/class-preview')
    def class_preview(key: str, payload: ClassPreview):
        # Builds the album from the unsaved draft and a real class without storing anything in the order.
        from .layout_workspace import enrich_master_snapshot, generate_document, order_data, snapshot_for
        master = validate(payload.document)
        edition = {'id': 'class-preview', 'version': 0, 'master': master}
        with s.db() as con:
            owned(con, key)
            edition['photoCategories'] = studio_categories(con, _studio())
            order = dict(s.require_order(con, payload.order_id))
            snapshot = snapshot_for(con, order, order_data(con, payload.order_id, s.DATA), master=True)
            if not snapshot['students']:
                raise HTTPException(409, 'В классе нет учеников')
            enrich_master_snapshot(con, payload.order_id, snapshot, edition, s.DATA)
        try:
            document = generate_document(edition, snapshot, [])
        except (LayoutError, KeyError, TypeError, ValueError, IndexError, ZeroDivisionError) as exc:
            raise HTTPException(409, 'Не удалось построить предпросмотр: ' + str(exc)[:160]) from exc
        return {'document': document,
                'photos': [{'id': k, 'width': p['width'], 'height': p['height'], **({'url': p['url']} if p.get('url') else {})}
                           for k, p in snapshot['photos'].items()]}

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
            document = {'id': edition_id, 'version': row['revision'], 'master': master, 'capacity': {'students': [1,1000], 'teachers': [0,1000]},
                        'photoCategories': studio_categories(con, _studio())}
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
        packages = []
        for p in con.execute('SELECT p.*,m.revision,m.updated_at,m.document FROM master_packages p JOIN master_templates m ON m.id=p.template_id WHERE p.design_id=? ORDER BY m.updated_at,p.template_id', (row['id'],)):
            package = dict(p)
            document = json.loads(package.pop('document'))
            sections = [x for x in document.get('sections', []) if not x.get('cover')]
            package['summary'] = {'page_size': document.get('pageSize'), 'sections': [x.get('name', '') for x in sections],
                                  'spreads': sum(len(x.get('spreads', [])) for x in sections)}
            packages.append(package)
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

    @app.post('/api/designs/{key}/duplicate', status_code=201)
    def duplicate_design(key: str):
        with s.db() as con:
            source = design_owned(con,key)
            copy_id = s.uid()
            con.execute('INSERT INTO designs VALUES (?,?,?,?)', (copy_id,_studio(),source['name']+' (копия)',s.now()))
            for p in con.execute('SELECT p.*,m.document FROM master_packages p JOIN master_templates m ON m.id=p.template_id WHERE p.design_id=? ORDER BY m.updated_at,p.template_id', (key,)).fetchall():
                template_id = s.uid()
                con.execute('INSERT INTO master_templates VALUES (?,?,?,?,?)', (template_id,_studio(),p['document'],1,s.now()))
                con.execute('INSERT INTO master_packages VALUES (?,?,?,?)', (template_id,copy_id,p['name'],p['price']))
            for b in con.execute('SELECT * FROM design_blocks WHERE design_id=? ORDER BY rowid', (key,)).fetchall():
                con.execute('INSERT INTO design_blocks VALUES (?,?,?,?)', (s.uid(),copy_id,b['name'],b['document']))
            return design_result(con,design_owned(con,copy_id))

    @app.delete('/api/designs/{key}')
    def delete_design(key: str):
        # Orders keep their frozen edition copy, so removing the source design never changes them.
        with s.db() as con:
            design_owned(con,key)
            templates = [r['template_id'] for r in con.execute('SELECT template_id FROM master_packages WHERE design_id=?', (key,))]
            con.execute('DELETE FROM design_blocks WHERE design_id=?', (key,))
            con.execute('DELETE FROM master_packages WHERE design_id=?', (key,))
            con.executemany('DELETE FROM master_templates WHERE id=?', [(t,) for t in templates])
            con.execute('DELETE FROM designs WHERE id=?', (key,))
        return {'deleted': key}

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
        section = payload.section
        v2 = isinstance(section, dict) and ('list' in section or 'people' in section or any(isinstance(sp, dict) and 'role' in sp for sp in section.get('spreads') or []))
        validate({'schemaVersion':1,'name':payload.name,**({'rulesVersion':2} if v2 else {'personalMode':'all'}),'sections':[section]})
        with s.db() as con:
            design_owned(con,key)
            block_id=s.uid()
            con.execute('INSERT INTO design_blocks VALUES (?,?,?,?)', (block_id,key,payload.name.strip(),json.dumps(payload.section)))
            return {'id':block_id}
