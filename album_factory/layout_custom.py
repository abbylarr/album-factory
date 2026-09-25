"""Editable, shared spreads added after automatic album composition."""
from copy import deepcopy

from .layout_engine import auto_crop, canonical_hash

PAGE_TEMPLATES = {
    'blank': {'label': 'Пустая', 'photos': [], 'caption': None},
    'full': {'label': 'Во всю страницу', 'photos': [[0, 0, 210, 280]], 'caption': None},
    'editorial': {'label': 'Фото и подпись', 'photos': [[12, 12, 186, 218]], 'caption': [14, 240, 182, 26]},
    'diptych': {'label': 'Два фото', 'photos': [[10, 10, 93, 260], [107, 10, 93, 260]], 'caption': None},
    'grid': {'label': 'Сетка 2×2', 'photos': [[10, 10, 93, 128], [107, 10, 93, 128],
                                            [10, 142, 93, 128], [107, 142, 93, 128]], 'caption': None},
}


def revision(document):
    document['revision'] = canonical_hash({k: v for k, v in document.items() if k != 'revision'})
    return document


def merge_custom(document, previous):
    positions = previous.get('custom_positions', {}) if previous else {}
    if not positions:
        return document
    document['custom_positions'] = deepcopy(positions)
    for key, position in sorted(positions.items(), key=lambda item: item[1]):
        spread = previous['shared_spreads'].get(key)
        if not spread:
            continue
        document['shared_spreads'][key] = deepcopy(spread)
        for variant in document['variants']:
            variant['sequence'].insert(min(max(1, position), len(variant['sequence'])), key)
        document['spread_count'] += 1
        document['page_count'] += 2
    return revision(document)


def add_spread(document, key, after_index):
    count = len(document['variants'][0]['sequence'])
    position = min(max(after_index + 1, 1), count)
    positions = document.setdefault('custom_positions', {})
    for old in positions:
        if positions[old] >= position:
            positions[old] += 1
    positions[key] = position
    document['shared_spreads'][key] = {
        'key': key, 'section': 'custom', 'template': 'custom',
        'page_templates': {'left': 'blank', 'right': 'blank'}, 'elements': [],
    }
    for variant in document['variants']:
        variant['sequence'].insert(position, key)
    document['spread_count'] += 1
    document['page_count'] += 2
    return revision(document)


def remove_spread(document, key):
    positions = document['custom_positions']
    position = positions.pop(key)
    for old in positions:
        if positions[old] > position:
            positions[old] -= 1
    document['shared_spreads'].pop(key)
    for variant in document['variants']:
        variant['sequence'].remove(key)
    document['spread_count'] -= 1
    document['page_count'] -= 2
    return revision(document)


def set_page_template(document, key, side, template, snapshot):
    if template not in PAGE_TEMPLATES or side not in {'left', 'right'}:
        raise ValueError('Unknown page template')
    spread = document['shared_spreads'][key]
    prefix = f'{key}/{side}/'
    previous = {e['key']: e for e in spread['elements'] if e['key'].startswith(prefix)}
    memory = spread.setdefault('page_memory', {}).setdefault(side, {})
    for element in previous.values():
        memory[element['key'][len(prefix):]] = element.get('photo') if element['type'] == 'photo' else element.get('text', '')
    spread['elements'] = [e for e in spread['elements'] if not e['key'].startswith(prefix)]
    offset = 0 if side == 'left' else 210
    spec = PAGE_TEMPLATES[template]
    for index, box in enumerate(spec['photos'], 1):
        shifted = [box[0] + offset, *box[1:]]
        element_key = prefix + f'photo{index}'
        photo = previous.get(element_key, {}).get('photo') or memory.get(f'photo{index}')
        meta = snapshot['photos'].get(photo)
        spread['elements'].append({
            'key': element_key, 'type': 'photo', 'box': shifted, 'photo': photo if meta else None,
            'base': None, 'source': None, 'mask': 'rect', 'required': False,
            'crop': auto_crop(meta['width'], meta['height'], shifted[2], shifted[3]) if meta else None,
        })
    if spec['caption']:
        box = spec['caption']
        key_caption = prefix + 'caption'
        text = previous.get(key_caption, {}).get('text', memory.get('caption', ''))
        spread['elements'].append({
            'key': key_caption, 'type': 'text', 'box': [box[0] + offset, *box[1:]],
            'text': text, 'base': '', 'font': 'display', 'align': 'left', 'valign': 'top',
            'color': '#202A27', 'size': 15, 'leading': 18, 'overflow': False,
        })
    spread['page_templates'][side] = template
    return revision(document)


def edit_element(document, key, kind, value, snapshot, measurer):
    spread_key = key.split('/', 1)[0]
    spread = document['shared_spreads'][spread_key]
    element = next(e for e in spread['elements'] if e['key'] == key)
    if kind == 'photo':
        element['photo'] = value
        meta = snapshot['photos'][value]
        element['crop'] = auto_crop(meta['width'], meta['height'], element['box'][2], element['box'][3])
    else:
        element['text'] = value
        size = 15
        while size > 8 and measurer.height(value, element['font'], size, size * 1.2, element['box'][2]) > element['box'][3]:
            size -= .5
        element['size'], element['leading'] = size, size * 1.2
        element['overflow'] = measurer.height(value, element['font'], size, size * 1.2, element['box'][2]) > element['box'][3]
        if element['overflow']:
            raise ValueError('Подпись не помещается на странице. Сократите текст.')
    side = key.split('/', 2)[1]
    name = key.rsplit('/', 1)[-1]
    spread.setdefault('page_memory', {}).setdefault(side, {})[name] = value
    return revision(document)
