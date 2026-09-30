"""Compile editable millimetre master documents into the existing layout format."""
from copy import deepcopy
import math
import re
from itertools import permutations
from .layout_engine import canonical_hash
from .master_plan import CARD_ZONES, ISSUES as PLAN_ISSUES, has_grid, list_plan, people as block_people, personal_take
from .photo_pick import Picker, RELAX_TEXT, GOOD_DPI, categories_of, entries_from, fit, resolve, rules_of
from .svg_draw import present_svg
from . import auto_text


ORDER = ('photo', 'crop', 'text', 'hide')
SPREAD_TYPES = ('spread_add', 'spread_remove', 'spread_move')
# Simple page grids for spreads added while proofing, on the 210 × 280 reference page.
BLANK_PAGES = {
    'blank': [],
    'full': [('photo', 0, 0, 210, 280)],
    'editorial': [('photo', 12, 12, 186, 218), ('text', 14, 240, 182, 26)],
    'diptych': [('photo', 10, 10, 93, 260), ('photo', 107, 10, 93, 260)],
    'grid': [('photo', 10, 10, 93, 128), ('photo', 107, 10, 93, 128), ('photo', 10, 142, 93, 128), ('photo', 107, 142, 93, 128)],
}
_OWNER = re.compile(r'\[student:[^\]]*\]')


def owner_wildcard(key):
    """Key of the same element in every album variant: only the owner of the spread is replaced."""
    spread, sep, rest = key.partition('/')
    return _OWNER.sub('[*]', spread) + sep + rest


def for_owner(key, owner_key):
    """Inverse of owner_wildcard for one album."""
    return key.replace('[*]', f'[{owner_key}]', 1) if key else key


def template_pages(master, source):
    """Master pages for a spread added in the final layout, or None when the source is unknown."""
    source = source or {}
    width, height = master.get('pageSize', [210, 280])
    if source.get('kind') == 'blank':
        pages = []
        styles = {style['id'] for style in master.get('textStyles', [])}
        for side in ('left', 'right'):
            layers = []
            for index, (kind, x, y, w, h) in enumerate(BLANK_PAGES.get(source.get(side)) or []):
                box = {'x': x * width / 210, 'y': y * height / 280, 'w': w * width / 210, 'h': h * height / 280}
                if kind == 'photo':
                    # Empty frames: the photographer fills a hand-made spread (e.g. parents) with chosen photos.
                    layers.append({'id': f'p{index}', 'type': 'photo', 'box': box, 'source': 'custom'})
                else:
                    layers.append({'id': f't{index}', 'type': 'text', 'box': box, 'text': 'Подпись',
                                   'font': 'Georgia', 'fontSize': 14, 'color': '#282a26', 'align': 'center',
                                   **({'styleId': 'text-caption'} if 'text-caption' in styles else {})})
            pages.append({'id': side, 'background': '#ffffff', 'layers': layers})
        return pages if all(side in BLANK_PAGES for side in (source.get('left'), source.get('right'))) else None
    section = next((s for s in master['sections'] if s['id'] == source.get('section') and not s.get('cover')), None)
    index = source.get('spread')
    if not section or not isinstance(index, int) or not 0 <= index < len(section['spreads']):
        return None
    pages = deepcopy(section['spreads'][index]['pages'])
    for page in pages:
        # An added spread has no class list and no repeated student: vignettes go, "this student" means the owner.
        page['layers'] = [l for l in page['layers'] if l['type'] != 'grid']
        for layer in page['layers']:
            if layer.get('source') == 'item':
                layer['source'] = 'owner'
            if layer.get('type') == 'text':
                layer['text'] = (layer.get('text') or '').replace('{{item.', '{{owner.')
    return pages


def collage_frames(layer):
    """Leaf rectangles inside a collage. Coordinates are local to the collage box."""
    box = layer['box']
    gap_x = float(layer.get('gapX', 4))
    gap_y = float(layer.get('gapY', 4))
    rows = layer.get('rows') or []
    frames = []
    if not rows or box['w'] <= 0 or box['h'] <= 0:
        return frames
    row_h = (box['h'] - gap_y * (len(rows) - 1)) / len(rows)
    def place(cell, x, y, w, h):
        if w < 0.2 or h < 0.2:
            return
        children = cell.get('cells') or []
        if cell.get('split') == 'h' and len(children) >= 2:
            gx = min(gap_x, w * 0.35)
            inner = (w - gx * (len(children) - 1)) / len(children)
            for index, child in enumerate(children):
                place(child, x + index * (inner + gx), y, inner, h)
        elif cell.get('split') == 'v' and len(children) >= 2:
            gy = min(gap_y, h * 0.35)
            inner = (h - gy * (len(children) - 1)) / len(children)
            for index, child in enumerate(children):
                place(child, x, y + index * (inner + gy), w, inner)
        else:
            frames.append({'cell': cell, 'x': x, 'y': y, 'w': w, 'h': h})
    for row_index, row in enumerate(rows):
        count = max(len(row), 1)
        cell_w = (box['w'] - gap_x * (count - 1)) / count
        y = row_index * (row_h + gap_y)
        for index, cell in enumerate(row):
            place(cell, index * (cell_w + gap_x), y, cell_w, row_h)
    return frames


def flex_frames(w, h, aspects, gap_x=4, gap_y=4):
    """Frames of a flexible collage, one per photo in the order of ``aspects`` (width / height).

    Rows or columns of one to three equal frames; the arrangement (and, up to four photos, the order) whose
    frames crop the photos least wins. Mirrors flexFrames in web/collage-core.js.
    """
    n = len(aspects)
    if not n or w <= 0 or h <= 0:
        return []
    shapes = []
    def compose(left, parts):
        if not left:
            shapes.append(parts)
            return
        for k in range(1, min(3, left) + 1):
            if len(parts) < 3:
                compose(left - k, parts + [k])
    compose(n, [])
    orders = list(permutations(range(n))) if n <= 4 else [tuple(range(n))]
    best = None
    for shape in shapes:
        for axis in ('rows', 'cols'):
            lines, out = len(shape), []
            for li, k in enumerate(shape):
                if axis == 'rows':
                    lh = (h - gap_y * (lines - 1)) / lines
                    fw = (w - gap_x * (k - 1)) / k
                    out += [{'x': i * (fw + gap_x), 'y': li * (lh + gap_y), 'w': fw, 'h': lh} for i in range(k)]
                else:
                    lw = (w - gap_x * (lines - 1)) / lines
                    fh = (h - gap_y * (k - 1)) / k
                    out += [{'x': li * (lw + gap_x), 'y': i * (fh + gap_y), 'w': lw, 'h': fh} for i in range(k)]
            if any(f['w'] < 1 or f['h'] < 1 for f in out):
                continue
            for order in orders:
                cost = 0
                for i, f in enumerate(out):
                    cost += abs(math.log((f['w'] / f['h']) / (aspects[order[i]] or 1.5)))
                if best is None or cost < best[0] - 1e-9:
                    best = (cost, out, order)
    if best is None:
        return []
    result = [None] * n
    for i, f in enumerate(best[1]):
        result[best[2][i]] = f
    return result


def card_frame(layer):
    """Sizes of a vignette card that do not depend on the photo width. Mirrors cardFrame in web/master-planner.js.

    Each caption sits in a zone around the photo (above, below, left, right) or over it; one zone stacks name first."""
    ratio = float(layer.get('photoRatio') or .75)
    gap = float(layer.get('photoNameGap', 3))
    between = float(layer.get('nameDetailGap', 2))
    side = float(layer.get('captionWidth') or 40)
    name_h = layer['fontSize']*.3528*float(layer.get('lineHeight') or 1.25)*2
    detail_h = layer.get('detailFontSize', 9)*.3528*float(layer.get('detailLineHeight') or 1.25)*2 if layer.get('showDetail') else 0
    zone_of = lambda key: layer.get(key) if layer.get(key) in CARD_ZONES else 'below'
    texts = [('name', zone_of('nameAt'), name_h)] + ([('detail', zone_of('detailAt'), detail_h)] if layer.get('showDetail') else [])
    zones = {}
    for zone in CARD_ZONES:
        items = [t for t in texts if t[1] == zone]
        zones[zone] = sum(t[2] for t in items) + between*(len(items)-1) if items else 0
    return dict(ratio=ratio, gap=gap, between=between, side=side, name_h=name_h, detail_h=detail_h, texts=texts, zones=zones,
                top=zones['above']+gap if zones['above'] else 0, bottom=zones['below']+gap if zones['below'] else 0,
                left=side+gap if zones['left'] else 0, right=side+gap if zones['right'] else 0,
                side_h=max(zones['left'], zones['right']))


def card_parts(photo_w, frame):
    """Photo and caption boxes [x, y, w, h] in card coordinates; caption boxes reserve two lines. Mirrors cardParts."""
    f = frame
    photo_h = photo_w/f['ratio']
    body = max(photo_h, f['side_h'])
    pad = min(f['gap'], photo_w/4)
    parts = {'photo': [f['left'], f['top'], photo_w, photo_h]}
    zones = {}
    for zone in CARD_ZONES:
        items = [t for t in f['texts'] if t[1] == zone]
        if not items:
            continue
        h = f['zones'][zone]
        x, w = f['left'], photo_w
        if zone == 'above':
            y = 0
        elif zone == 'below':
            y = f['top']+body+f['gap']
        elif zone == 'over':
            x, w, y = f['left']+pad, max(1, photo_w-2*pad), f['top']+photo_h-pad-h
        else:
            x, w, y = (0 if zone == 'left' else f['left']+photo_w+f['gap']), f['side'], f['top']+max(0, (photo_h-h)/2)
        for key, _, text_h in items:
            parts[key] = [x, y, w, text_h]
            zones[key] = zone
            y += text_h+f['between']
    return dict(w=f['left']+photo_w+f['right'], h=f['top']+body+f['bottom'], photo_h=photo_h, parts=parts, zones=zones)


def geometry(count, layer):
    best = None
    gap = float(layer['gap'])
    frame = card_frame(layer)
    for cols in range(1, min(6, count) + 1):
        rows = math.ceil(count / cols)
        slot_w = (layer['box']['w'] - (cols-1)*gap) / cols
        slot_h = (layer['box']['h'] - (rows-1)*gap) / rows
        room = slot_h-frame['top']-frame['bottom']
        if room < frame['side_h']:
            continue
        pw = min(slot_w-frame['left']-frame['right'], room*frame['ratio'], float(layer.get('photoWidth') or 85))
        if pw < layer['minPhotoWidth']:
            continue
        card = card_parts(pw, frame)
        offset_x = (layer['box']['w'] - cols*card['w'] - (cols-1)*gap)/2
        offset_y = (layer['box']['h'] - rows*card['h'] - (rows-1)*gap)/2
        score = pw*pw*count - (cols*rows-count)*pw*.01
        if best is None or score > best['score']:
            best = dict(score=score, cols=cols, cell_w=card['w'], cell_h=card['h'],
                        photo_w=pw, photo_h=card['photo_h'], parts=card['parts'], zones=card['zones'],
                        name_h=frame['name_h'], detail_h=frame['detail_h'], photo_name_gap=frame['gap'],
                        name_detail_gap=frame['between'], offset_x=offset_x, offset_y=offset_y)
    return best


def pages_for(section, master, snapshot, owner, issue):
    pages = [p for s in section['spreads'] for p in s['pages']]
    if section['kind'] == 'repeat':
        records = snapshot['students'] if master['personalMode'] == 'all' else [owner] if master['personalMode'] == 'owner' else []
        return [(p, person, None, 0) for person in records for p in pages]
    grids = [p for p in pages if any(l['type']=='grid' for l in p['layers'])]
    if not grids:
        return [(p, None, None, 0) for p in pages]
    settings = next(l for l in grids[0]['layers'] if l['type']=='grid')
    records = snapshot[settings['source']][:]
    if settings['source']=='teachers' and settings.get('excludeLead') and any(l['type']=='photo' and not l.get('hidden') and l['source']=='lead' for p in pages for l in p['layers']):
        records = records[1:]
    # Every page template must accommodate every balanced part.
    all_settings = [l for p in grids for l in p['layers'] if l['type']=='grid']
    capacity = min(max((n for n in range(1, int(l['max'])+1) if geometry(n,l)), default=0) for l in all_settings)
    if not capacity:
        issue('error', section['id'], 'Виньетки не помещаются в область. Увеличьте область или уменьшите фото.')
        return [(p,None,[],0) for p in pages]
    preferred = max(1,int(section.get('target', len(section['spreads'])))*2-(len(pages)-len(grids)))
    n = len(records)
    slots = max(math.ceil(n/capacity), min(preferred,max(1,n//int(settings['min'])))) if n else 1
    counts = [n//slots+(i<n%slots) for i in range(slots)]
    if n and min(counts)<settings['min']:
        issue('error' if settings.get('strictMin') else 'warning',section['id'],'Карточек на странице меньше заданного минимума')
    chunks, offset = [], 0
    for count in counts:
        chunks.append(records[offset:offset+count]); offset += count
    result, used, insert_at = [], 0, 0
    for p in pages:
        if p not in grids:
            result.append((p,None,None,0))
        elif used < slots:
            result.append((p,None,chunks[used],max(counts))); used += 1; insert_at = len(result)
    while used < slots:
        result.insert(insert_at,(grids[-1],None,chunks[used],max(counts))); used += 1; insert_at += 1
    return result


def list_capacity(section):
    """Cards that fit on the tightest vignette page of a list block (rulesVersion 2)."""
    settings = section.get('list') or {}
    grids = [l for s in section['spreads'] for p in s['pages'] for l in p['layers'] if l['type'] == 'grid']
    if not grids:
        return 0
    return min(max((n for n in range(1, int(settings.get('max', 12)) + 1) if geometry(n, l)), default=0) for l in grids)


def blocks_pages(section, snapshot, owner, issue, lists=None):
    """Pages of one block for the album of ``owner`` (rulesVersion 2): (page, person, records, layout_count).

    ``lists`` carries split lists from block to block: list block id → (its people, how many are placed by its end).
    A block that continues another takes the people from where that one stopped."""
    lists = {} if lists is None else lists
    pages = {p['id']: p for s in section['spreads'] for p in s['pages']}
    if section.get('cover') or section['kind'] == 'fixed':
        return [(p, None, None, 0) for s in section['spreads'] for p in s['pages']]
    start, source = 0, section.get('continues')
    if source:
        if source not in lists:
            issue(PLAN_ISSUES['parts-order'][0], section['id'], PLAN_ISSUES['parts-order'][1])
            return []
        records, start = lists[source]
    if section['kind'] == 'repeat':
        by_id = {s['id']: s for s in snapshot['students']}
        if not source:
            records = block_people(section, [s['id'] for s in snapshot['students']], owner['id'] if owner else None)
        ids = records[start:start + personal_take(section, len(records) - start)]
        lists[section['id']] = (records, start + len(ids))
        return [(p, by_id[i], None, 0) for i in ids for s in section['spreads'] for p in s['pages']]
    settings = section['list']
    if not source:
        records = snapshot[settings['source']][:]
        if settings['source'] == 'teachers' and settings.get('excludeLead') and any(
                l['type'] == 'photo' and not l.get('hidden') and l['source'] == 'lead' for p in pages.values() for l in p['layers']):
            records = records[1:]
    rest = records[start:]
    if source and not rest:
        lists[section['id']] = (records, start)
        return []
    plan = list_plan(section, len(rest), list_capacity(section))
    lists[section['id']] = (records, start + plan['taken'])
    records = rest
    for code in plan['issues']:
        level, message = PLAN_ISSUES[code]
        if code == 'below-min' and settings.get('strictMin'):
            level = 'error'
        issue(level, section['id'], message)
    chunks, offset = [], 0
    for count in plan['counts']:
        chunks.append(records[offset:offset + count])
        offset += count
    layout_count = max(plan['counts'], default=0)
    result = []
    for spread in plan['spreads']:
        for item in spread['pages']:
            page = pages[item['page']]
            if item['part'] is not None:
                result.append((page, None, chunks[item['part']], layout_count))
            else:
                result.append((page, None, [] if has_grid(page) else None, 0))
    return result


def _legacy_assign(slots, general):
    """Snapshots saved before photo analysis keep their original order: round robin, restarted per variant."""
    counters = {}
    for slot in slots:
        index = counters.get(slot['owner'], 0)
        photo = general[index % len(general)] if general else None
        if photo or not slot.get('cell_fill'):
            counters[slot['owner']] = index + 1
        slot['result'] = {'photo': photo, 'crop': None, 'relaxed': [], 'dpi': GOOD_DPI} if photo else None
    return {'slots': {}, 'coverage': {}, 'unplaced': []}


SPINE_BOARD, SPINE_MIN = 3.5, 8  # the cover boards add to the block; spines come in whole even millimetres


def cover_spine(master, sheets):
    """Spine width of the cover for a block of this many sheets.

    With a sheet thickness the spine is the block plus the cover boards, rounded up to even millimetres;
    without one it is the fixed width set on the cover."""
    thickness = master.get('sheetThickness')
    if not thickness:
        cover = next((s for s in master['sections'] if s.get('cover')), None)
        return float((cover or {}).get('safety', {}).get('spine', 0) or 0)
    return float(max(SPINE_MIN, 2 * math.ceil(round(SPINE_BOARD + sheets * thickness, 2) / 2)))


def cover_box(layer, side, width, spine):
    """Place of a cover layer on the unfolded cover «back · spine · front» (x and width, mm)."""
    b = layer['box']
    if layer.get('pin') == 'spine':
        return width + spine / 2 + b['x'], b['w']
    if layer.get('pin') == 'wrap':
        return b['x'], b['w'] + spine
    return b['x'] + side * (width + spine), b['w']


def generate(edition, snapshot, measurer, overrides=(), only_owner=None):
    master = edition['master']
    page_width, page_height = master.get('pageSize', [210, 280])
    issues, variants, groups, plans, covers = [], [], {}, [], {}
    seen = set()
    def issue(level, key, message):
        if (level,key,message) not in seen:
            seen.add((level,key,message)); issues.append({'level':level,'code':'master','key':key,'message':message})
    students = snapshot['students']
    owners = students or [{'id':'class','first_name':'Общий','last_name':'альбом'}]
    if only_owner:
        owners = [o for o in owners if o['id'] == only_owner] or owners[:1]
    selections = {(s['owner'],s['role']):s['photo'] for s in snapshot['selections']}
    entries = entries_from(snapshot)
    entry_by_id = {e['id']: e for e in entries}
    slots = []
    def fit_text(e):
        """«Shrink to fit»: explicit lines never wrap; the whole text shrinks by one factor until the widest
        line and all lines fit the frame, so a first and last name on two lines keep one size."""
        if not hasattr(measurer, 'width') or not e['text'].strip():
            return
        w, h = e['box'][2], e['box'][3]
        ratio = e['leading'] / e['size']
        def fits(size):
            return (measurer.width(e['text'], e['font'], size, e.get('letterSpacing') or 0) <= w * .995
                    and measurer.height(e['text'], e['font'], size, size * ratio, 100000, e.get('letterSpacing') or 0) <= h + .1)
        size = e['size']
        if fits(size):
            return
        wide = measurer.width(e['text'], e['font'], size, e.get('letterSpacing') or 0)
        tall = measurer.height(e['text'], e['font'], size, size * ratio, 100000, e.get('letterSpacing') or 0)
        size = max(2, math.floor(size * min(w * .995 / max(wide, .01), h / max(tall, .01)) * 10) / 10)
        while size > 2 and not fits(size):
            size = round(size - .1, 1)
        e['size'], e['leading'] = size, round(size * ratio, 3)
    def name(person):
        return ' '.join(str(person[k]) for k in ('first_name','patronymic','last_name') if person.get(k)) if person else ''
    def photo_for(person):
        if not person:
            return None
        return selections.get(('student:'+person['id'],'main_portrait')) or selections.get(('teacher:'+person['id'],'main_portrait'))
    def crop(photo, b, x=50, y=50, zoom=1):
        meta = snapshot['photos'][photo]; w,h=meta['width'],meta['height']; ratio=b[2]/b[3]
        entry = entry_by_id.get(photo)
        if entry and not entry.get('legacy') and (x, y, zoom) == (50, 50, 1):
            placed = fit(entry, ratio, w, h)
            if placed:
                return placed
        cw,ch = (h*ratio,h) if w/h>ratio else (w,w/ratio)
        zoom = max(1, min(float(zoom), 4))
        cw,ch = cw/zoom,ch/zoom
        return [(w-cw)*x/100,(h-ch)*y/100,cw,ch]
    def font_key(layer):
        raw = layer.get('font')
        base = {'Georgia':'display','Arial':'main','Times New Roman':'times'}.get(raw) or 'custom-'+str(raw)
        bold, italic = bool(layer.get('bold')), bool(layer.get('italic'))
        if bold and italic: return base+'-bolditalic'
        if bold: return base+'-bold'
        if italic: return base+'-italic'
        return base
    applied, conflicts = [], []
    structure = [o for o in overrides if o['type'] in SPREAD_TYPES]
    overrides = [o for o in overrides if o['type'] not in SPREAD_TYPES]
    removed = set()
    overrides_by_key = {}
    for override in overrides:
        overrides_by_key.setdefault(override['key'], []).append(override)
    found = set()
    categories = categories_of(edition.get('photoCategories'))
    shared_bases = {}
    def apply_override(e, override, shared):
        """One manual edit on a compiled element. Returns a conflict reason or None."""
        base = e.get('shared_base') if shared else e['base']
        kind, value = override['type'], override.get('value')
        if override.get('base') != base:
            return 'Исходный элемент изменился'
        if kind == 'text' and e['type'] == 'text' and isinstance(value, str):
            e['text'] = value
        elif kind == 'photo' and e['type'] == 'photo' and value in snapshot['photos']:
            e['photo'] = value; e['crop'] = crop(value, e['box'])
        elif kind == 'crop' and e['type'] == 'photo' and e.get('photo') and isinstance(value, dict):
            if value.get('photo') != e['photo']:
                return 'Фото в рамке изменилось, кадр не применён'
            e['crop'] = manual_crop(e['photo'], e['box'], value['rect'])
        elif kind == 'hide' and e['type'] in ('text', 'photo'):
            e['hidden'] = True
        else:
            return 'Правка не подходит элементу'
        return None
    def manual_crop(photo, box, rect):
        meta = snapshot['photos'][photo]; w, h = meta['width'], meta['height']
        x, y, cw = (float(v) for v in rect[:3])
        aspect = box[2] / box[3]
        crop_w = min(cw * w, h * aspect); crop_h = crop_w / aspect
        left = min(max(x * w, 0), w - crop_w); top = min(max(y * h, 0), h - crop_h)
        return [round(left, 2), round(top, 2), round(crop_w, 2), round(crop_h, 2)]
    def slot_for(key, spread_key, bounds, pick, section, owner, item):
        c = resolve(pick, categories)
        target = owner['id'] if c['include'] == 'owner' else item['id'] if c['include'] == 'item' and item else None
        shared_key = re.sub(r'\[student:[^\]]*\]', '[*]', key)
        personal = c['include'] == 'owner'
        return {'key': key, 'ident': key if personal else shared_key + (f'|{target}' if target else ''), 'personal': personal,
                'owner': owner['id'], 'target': target, 'pick': pick, 'mm': [bounds[2], bounds[3]],
                'aspect_key': round(bounds[2] / bounds[3], 3), 'section': section['id'],
                'spread': spread_key if personal else re.sub(r'\[student:[^\]]*\]', '[*]', spread_key)}
    v2 = master.get('rulesVersion') == 2
    book = v2 and master.get('layout') == 'book'
    flex_groups = []
    late_texts = []  # texts with shoot chips wait until the spread's general photos are picked
    def build_spread(section, spread_key, pair, owner, owner_key, counter, page_width, page_height, index=0, spine=0, blanks=frozenset()):
        """Compile one spread (two master pages) for one album owner."""
        elements=[]; appearance={}
        # Stacking: both pages of one design spread follow its `z` order (see spreadStack in the editor);
        # pages paired from different spreads keep the left page under the right one.
        ids = [p['id'] for p, *_ in pair if p is not None]
        one_spread = bool(ids) and any(all(i in {p['id'] for p in sp['pages']} for i in ids) for sp in section.get('spreads', []))
        stack = {}; current = [(0, -1, -1, -1)]
        def add(e, inherit_effects=True, slot=None, late=None):
            e.update(appearance if inherit_effects else {key: appearance[key] for key in ('angle', 'rotation_center')})
            e.setdefault('hidden',False)
            stack[id(e)] = current[0]
            elements.append(e)
            if late is not None:
                late_texts.append((e, *late, finish, spread_key))
            elif slot is not None:
                slot['element'] = e; slot['order'] = counter[0]; counter[0] += 1; slot['in_spread'] = spread_key
                slot['finish'] = finish; slots.append(slot)
            else:
                finish(e)
        def finish(e):
            e['base']=canonical_hash(e)
            wild=owner_wildcard(e['key'])
            if wild!=e['key']:
                # Common spreads compile to the same element for every owner; a shared
                # fingerprint lets one edit apply to all variants at once.
                e['shared_base']=canonical_hash({**e,'base':None,'key':wild})
                shared_bases.setdefault(wild,[]).append(e)
            exact=overrides_by_key.get(e['key'],[])
            kinds={o['type'] for o in exact}
            chosen=[(o,False) for o in exact]+[(o,True) for o in overrides_by_key.get(wild,[]) if wild!=e['key'] and o['type'] not in kinds]
            chosen.sort(key=lambda item: ORDER.index(item[0]['type']) if item[0]['type'] in ORDER else len(ORDER))
            for override,shared in chosen:
                found.add(override['key'])
                reason=apply_override(e,override,shared)
                if reason:
                    conflicts.append({'key':override['key'],'type':override['type'],'reason':reason,'target':e['key']})
                else:
                    applied.append(e['key'])
                    e.setdefault('overridden',[]).append({'type':override['type'],'scope':'all' if shared else 'variant'})
            if e.get('hidden'):
                return
            if e['type']=='photo' and not e['photo']:
                issue('error',e['key'],'Не выбрано обязательное фото')
            if e['type']=='photo' and e['photo'] and e.get('overridden') and e.get('crop'):
                dpi=e['crop'][2]/(e['box'][2]/25.4)
                if dpi<GOOD_DPI:
                    issue('warning',e['key'],f'После правки разрешение около {math.floor(dpi)} dpi — ниже {GOOD_DPI}')
            if e['type']=='text' and e.get('textCase'):
                e['text']=auto_text.apply_case(e['text'],e['textCase'])
            if e['type']=='text' and e.get('fit'):
                fit_text(e)
            elif e['type']=='text' and measurer.height(e['text'],e['font'],e['size'],e['leading'],e['box'][2], e.get('letterSpacing') or 0) > e['box'][3]+.1:
                issue('error',e['key'],'Текст выходит за границы рамки')
        blank_sides = []
        # Both page backgrounds go first: an object may cross the fold and must not be covered by the next page.
        # On the cover each side's background also fills its half of the spine.
        gap = spine if section.get('cover') else 0
        for side,(page, *_) in enumerate(pair):
            if page is not None and (section['id'], index + side) not in blanks:
                add({'key':f'{spread_key}/{side}/background','type':'rect','box':[side*(page_width+gap/2),0,page_width+gap/2,page_height],'fill':page['background']})
        painted_spine = gap > 0 and bool(section.get('spineColor'))
        if painted_spine:
            current[0] = (2, -1, -1, -1)
            add({'key':f'{spread_key}/spine','type':'rect','box':[page_width,0,gap,page_height],'fill':section['spineColor']})
        for side,(page, item, records, layout_count) in enumerate(pair):
            if (section['id'], index + side) in blanks:
                blank_sides.append(side); continue
            if page is None: continue
            appearance={}
            prefix=f'{spread_key}/{side}'
            lead = snapshot['teachers'][0] if snapshot['teachers'] else None
            styles = {style['id']: style for style in master.get('textStyles', [])}
            for position, layer in enumerate(page['layers']):
                if layer.get('hidden'): continue
                z = layer.get('z') if one_spread and isinstance(layer.get('z'), (int, float)) else math.inf
                # Spine-pinned shapes can be ordinary artwork crossing the fold.
                # Designated text and legacy rotated spine titles go above its paint.
                spine_text = layer['type'] == 'text' and layer.get('pin') == 'spine' and (
                    layer.get('spineContent') is True or 'spineContent' not in layer and abs(layer.get('angle', 0)) == 90)
                band = 3 if painted_spine and spine_text else 1
                current[0] = (band, z, side, position)
                if layer['type'] == 'grid' and v2 and section.get('list'):
                    layer = {**layer, 'source': section['list']['source']}
                if layer.get('type') == 'text' and layer.get('styleId') in styles:
                    layer = {**layer, **{key: value for key, value in styles[layer['styleId']].items() if key not in {'id', 'name'}}}
                b=layer['box']; x, w = cover_box(layer, side, page_width, spine) if section.get('cover') else (b['x']+side*page_width, b['w'])
                bounds=[x,b['y'],w,b['h']]; key=prefix+'/'+layer['id']
                common={'key':key,'box':bounds,'opacity':layer.get('opacity',100)}
                stroke_width = 0 if layer.get('strokeOn') is False else (layer.get('strokeWidth') or (0.4 if layer.get('strokeOn') is True or layer.get('strokeMode') == 'color' else 0))
                appearance={'angle':layer.get('angle',0),'rotation_center':[bounds[0]+bounds[2]/2,bounds[1]+bounds[3]/2], 'radius':layer.get('radius',0),'stroke':layer.get('stroke','#333333'),'strokeWidth':stroke_width}
                for flip in ('flipX','flipY'):
                    if layer.get(flip) and layer['type'] not in ('grid','collage'): appearance[flip]=True
                if layer.get('strokeDash') not in (None, 'solid'): appearance['strokeDash']=layer['strokeDash']
                if layer.get('strokeAlign') in ('outside','inside'): appearance['strokeAlign']=layer['strokeAlign']
                if layer.get('strokeCap') in ('round','square'): appearance['strokeCap']=layer['strokeCap']
                if layer.get('strokeJoin') in ('round','bevel'): appearance['strokeJoin']=layer['strokeJoin']
                if layer.get('strokeOpacity') not in (None, 100): appearance['strokeOpacity']=layer['strokeOpacity']
                if isinstance(layer.get('shadow'), dict): appearance['shadow']=layer['shadow']
                font=font_key(layer)
                def text_element(key, bounds, value, size):
                    leading=size*float(layer.get('lineHeight') or 1.25)
                    element={'key':key,'type':'text','box':bounds,'text':value,'font':font,'size':size,'leading':leading,'align':layer.get('align','center'),'valign':'top','color':layer['color'],'opacity':layer.get('opacity',100)}
                    if layer.get('letterSpacing'): element['letterSpacing']=layer['letterSpacing']
                    if layer.get('underline'): element['underline']=True
                    if layer.get('strike'): element['strike']=True
                    if layer.get('skew'): element['skew']=layer['skew']
                    return element
                def frame_text(element):
                    """A master text frame: its letter case, vertical alignment and auto-shrink travel with the element."""
                    element['valign']=layer.get('valign') if layer.get('valign') in ('middle','bottom') else 'top'
                    if layer.get('textCase') in auto_text.CASES: element['textCase']=layer['textCase']
                    if layer.get('fit'): element['fit']=True
                    return element
                def photo_element(key,bounds,photo):
                    return {'key':key,'type':'photo','box':bounds,'photo':photo,'crop':crop(photo,bounds,layer.get('cropX',50),layer.get('cropY',50),layer.get('cropZoom',1)) if photo else None,'mask':'rect','required':True,'opacity':layer.get('opacity',100)}
                if layer['type']=='text':
                    order=snapshot['order']
                    values={'owner.name':auto_text.person_name(owner),'owner.quote':owner.get('quote',''),'item.name':auto_text.person_name(item),'item.quote':(item or {}).get('quote',''),
                            'lead.name':auto_text.person_name(lead),'lead.subject':(lead or {}).get('school_subject',''),'school':{'full':order.get('school',''),'short':order.get('school_short','')},'city':order.get('city',''),
                            'class':order['class_name'],'year':order['year']}
                    element=frame_text(text_element(key,bounds,auto_text.resolve(layer['text'],values),layer['fontSize']))
                    late=(layer['text'],values) if auto_text.fields(layer['text'])&auto_text.SHOOT_FIELDS else None
                    add(element, late=late)
                elif layer['type']=='photo':
                    source=layer['source']
                    if source=='class':
                        add(photo_element(key,bounds,None), slot={**slot_for(key,spread_key,bounds,layer.get('pick'),section,owner,item),
                            'crop_pref':(layer.get('cropX',50),layer.get('cropY',50),layer.get('cropZoom',1))})
                        continue
                    elif source=='custom': photo=snapshot.get('master_assets',{}).get(layer['id'])
                    else: photo=photo_for({'owner':owner,'item':item,'lead':lead}.get(source))
                    add(photo_element(key,bounds,photo))
                elif layer['type']=='collage' and layer.get('flex'):
                    # Flexible collage: one slot per possible photo; slots past the minimum take only photos
                    # that fit without concessions, and the frames are laid out once the photos are known.
                    flex = layer['flex']; low = int(flex.get('min', 1)); high = int(flex.get('max', 4))
                    gx, gy = float(layer.get('gapX', 4)), float(layer.get('gapY', 4))
                    cols = math.ceil(math.sqrt(high)); rows = math.ceil(high / cols)
                    approx = [bounds[0], bounds[1], max((bounds[2] - gx * (cols - 1)) / cols, 1), max((bounds[3] - gy * (rows - 1)) / rows, 1)]
                    flex_group = {'origin': bounds, 'gap': (gx, gy), 'elements': elements, 'slots': []}
                    flex_groups.append(flex_group)
                    for i in range(high):
                        cell_key = f'{key}/flex{i}'
                        slot = {**slot_for(cell_key, spread_key, approx, layer.get('pick'), section, owner, item),
                                'optional': i >= low, 'flex': flex_group, 'crop_pref': (50, 50, 1)}
                        flex_group['slots'].append(slot)
                        add({'key': cell_key, 'box': list(approx), 'opacity': layer.get('opacity', 100), 'type': 'photo', 'photo': None, 'crop': None, 'mask': 'rect', 'required': True}, slot=slot)
                elif layer['type']=='collage':
                    for frame in collage_frames(layer):
                        cell=frame['cell']
                        fb=[bounds[0]+frame['x'], bounds[1]+frame['y'], frame['w'], frame['h']]
                        source=cell.get('source','class')
                        slot={'key':key+'/'+cell['id'],'box':fb,'opacity':layer.get('opacity',100)}
                        if source=='class':
                            add({**slot,'type':'photo','photo':None,'crop':None,'mask':'rect','required':True},
                                slot={**slot_for(slot['key'],spread_key,fb,cell.get('pick'),section,owner,item),'cell_fill':layer.get('fill','#e6e1ea'),'crop_pref':(cell.get('cropX',50),cell.get('cropY',50),cell.get('cropZoom',1))})
                            continue
                        elif source=='custom':
                            photo=snapshot.get('master_assets',{}).get(cell['id'])
                        else:
                            photo=photo_for({'owner':owner,'item':item,'lead':lead}.get(source))
                        if photo:
                            add({**slot,'type':'photo','photo':photo,'crop':crop(photo,fb,cell.get('cropX',50),cell.get('cropY',50),cell.get('cropZoom',1)),'mask':'rect','required':True})
                        else:
                            add({**slot,'type':'rect','fill':layer.get('fill','#e6e1ea')})
                elif layer['type']=='grid':
                    if not records: continue
                    geo=geometry(layout_count,layer)
                    if not geo:
                        issue('error',key,'Виньетки не помещаются'); continue
                    frame_style={key:appearance[key] for key in ('stroke','strokeWidth','strokeDash','strokeAlign','strokeCap','strokeJoin','strokeOpacity') if key in appearance}
                    # Corners, stroke and shadow belong to each portrait, not to the vignette area.
                    photo_style={'radius':layer.get('radius',0),**frame_style}
                    if isinstance(layer.get('shadow'),dict): photo_style.update(shadow=layer['shadow'],shadowGroup=key)
                    cols=geo['cols']; cw=geo['cell_w']; ch=geo['cell_h']; pw=geo['photo_w']; parts=geo['parts']; zones=geo['zones']
                    size=layer['fontSize']; leading=float(layer.get('lineHeight') or 1.25)
                    # Shared reduction for the complete source, not individual cards.
                    all_people=snapshot[layer['source']]
                    while size>layer['minFontSize'] and any(measurer.height(name(p),font,size,size*leading,parts['name'][2]*.97, layer.get('letterSpacing') or 0)>geo['name_h']+.1 for p in all_people): size=max(layer['minFontSize'],size-.5)
                    detail_style={'font':layer.get('detailFont',layer['font']),'bold':layer.get('detailBold',False),'italic':layer.get('detailItalic',False)}
                    detail_size=layer.get('detailFontSize',9); detail_leading=detail_size*layer.get('detailLineHeight',1.25)
                    for i,person in enumerate(records):
                        x=bounds[0]+geo['offset_x']+(i%cols)*(cw+layer['gap']); y=bounds[1]+geo['offset_y']+(i//cols)*(ch+layer['gap'])
                        pk=key+'/card['+('student:' if layer['source']=='students' else 'teacher:')+person['id']+']'
                        px,py=parts['photo'][:2]
                        add({**photo_element(pk+'/photo',[x+px,y+py,pw,geo['photo_h']],photo_for(person)),**photo_style},False)
                        detail=(person.get('quote','') if layer['source']=='students' else person.get('school_subject','')) if layer.get('showDetail') else ''
                        nx,ny,nw,_=parts['name']
                        name_height=measurer.height(name(person),font,size,size*leading,nw,layer.get('letterSpacing') or 0)
                        dx=dy=dw=detail_height=None
                        if detail:
                            dx,dy,dw,_=parts['detail']
                            detail_height=measurer.height(detail,font_key(detail_style),detail_size,detail_leading,dw,layer.get('detailLetterSpacing') or 0)
                        # Captions of one zone hug each other; over the photo they rest on its bottom edge.
                        pad=min(geo['photo_name_gap'],pw/4); floor=py+geo['photo_h']-pad
                        if detail and zones['detail']=='over': dy=floor-detail_height
                        if zones['name']=='over': ny=(dy-geo['name_detail_gap'] if detail and zones['detail']=='over' else floor)-name_height
                        elif detail and zones['detail']==zones['name']: dy=ny+name_height+geo['name_detail_gap']
                        add(text_element(pk+'/name',[x+nx,y+ny,nw,geo['name_h']],name(person),size),False)
                        if detail:
                            detail_element={'key':pk+'/detail','type':'text','box':[x+dx,y+dy,dw,geo['detail_h']],'text':detail,'font':font_key(detail_style),'size':detail_size,'leading':detail_leading,'align':layer.get('detailAlign','center'),'valign':'top','color':layer.get('detailColor',layer['color']),'opacity':layer.get('opacity',100)}
                            if layer.get('detailLetterSpacing'): detail_element['letterSpacing']=layer['detailLetterSpacing']
                            if layer.get('detailUnderline'): detail_element['underline']=True
                            if layer.get('detailStrike'): detail_element['strike']=True
                            add(detail_element,False)
                elif layer['type']=='svg':
                    add({**common,'type':'svg','svg':present_svg(layer['svg'], layer),'fill':layer.get('fill','#29282d')})
                else:
                    add({**common,'type':layer['type'],'fill':layer['fill']})
        elements.sort(key=lambda e: stack.get(id(e), (0, -1, -1, -1)))
        spread={'key':spread_key,'section':'cover' if section.get('cover') else section['id'],'elements':elements}
        if blank_sides:
            spread['blank'] = blank_sides
        return spread
    def place(sequence, key, after, owner_key):
        anchor = for_owner(after, owner_key)
        if anchor in sequence:
            sequence.insert(sequence.index(anchor) + 1, key)
        else:
            sequence.insert(1 if sequence and sequence[0].startswith('cover[') else 0, key) if after is None else sequence.append(key)
    def restructure(owner, owner_key, sequence, group, counter):
        """Spreads added, removed or moved by the photographer, for everyone or one album."""
        width, height = master.get('pageSize', [210, 280])
        for op in structure:
            value = op.get('value') or {}
            if value.get('owner') not in (None, owner_key):
                continue
            if op['type'] == 'spread_add':
                pages = template_pages(master, value.get('source'))
                if pages is None:
                    if owner is owners[0]:
                        conflicts.append({'key': op['key'], 'type': op['type'], 'reason': 'Шаблон разворота больше недоступен'})
                    continue
                key = f"x{value['id']}[{owner_key}]:0"
                spread = build_spread({'id': 'extra', 'kind': 'fixed'}, key, [(page, None, None, 0) for page in pages],
                                      owner, owner_key, counter, width, height)
                spread.update(section='extra', title=value.get('title') or 'Новый разворот', added=op['key'])
                group[key] = spread
                place(sequence, key, value.get('after'), owner_key)
            else:
                key = for_owner(value.get('target'), owner_key)
                if key not in sequence or key.startswith('cover['):
                    continue
                sequence.remove(key)
                if op['type'] == 'spread_remove':
                    group.pop(key, None); removed.add(key)
                else:
                    place(sequence, key, value.get('after'), owner_key)
    for owner in owners:
        owner_key = 'student:'+owner['id']; group = {}; sequence=[]; counter=[0]
        planned, lists = [], {}
        for section in master['sections']:
            pages = blocks_pages(section,snapshot,owner,issue,lists) if v2 else pages_for(section,master,snapshot,owner,issue)
            if len(pages)%2:
                pages.append((None,None,None,0))
            if len(pages)>2000:
                raise ValueError('Раздел превышает 1000 разворотов')
            planned.append((section, pages))
        inner_spreads = sum(len(pages) // 2 for section, pages in planned if not section.get('cover'))
        # A layflat spread is one sheet; a book printed page by page has two pages to a sheet.
        spine = cover_spine(master, inner_spreads - 1 if book and inner_spreads else inner_spreads)
        # A book starts on a right page and ends on a left one: the outer pages of the inner block are not printed.
        blanks = set()
        inner = [(section['id'], len(pages)) for section, pages in planned if not section.get('cover') and pages]
        if book and inner:
            blanks = {(inner[0][0], 0), (inner[-1][0], inner[-1][1] - 1)}
        for section, pages in planned:
            page_width, page_height = section.get('pageSize', master.get('pageSize', [210, 280])) if section.get('cover') else master.get('pageSize', [210, 280])
            if owner is owners[0]:
                plans.append({'section':section['id'],'spreads':len(pages)//2})
            for index in range(0,len(pages),2):
                spread_key=f'cover[{owner_key}]' if section.get('cover') else f'{section["id"]}[{owner_key}]:{index//2}'
                sequence.append(spread_key)
                spread=build_spread(section,spread_key,pages[index:index+2],owner,owner_key,counter,page_width,page_height,index,spine,blanks)
                if section.get('cover'):
                    spread['size_mm'] = [2*page_width+spine, page_height]; spread['spine_mm'] = spine
                    covers[owner_key] = spread
                else:
                    group[spread_key] = spread
        restructure(owner, owner_key, sequence, group, counter)
        groups[owner_key]=group
        variants.append({'owner':owner_key,'name':name(owner),'kind':'student','sequence':sequence})
    if removed:
        slots[:] = [slot for slot in slots if slot['in_spread'] not in removed]
        issues[:] = [i for i in issues if str(i['key']).split('/', 1)[0] not in removed]
        late_texts[:] = [t for t in late_texts if t[4] not in removed]
    if 'general' in snapshot:
        report = Picker(entries, snapshot['photos'], rules_of(master), students, categories).assign(slots)
    else:
        report = _legacy_assign(slots, snapshot.get('general_photos', []))
    for flex_group in flex_groups:
        # Keep the required frames and the optional ones that found a photo, then lay them out by the photos' shapes.
        keep = [slot for slot in flex_group['slots'] if slot.get('result') or not slot['optional']]
        for slot in flex_group['slots']:
            if slot not in keep:
                slot['dropped'] = True
                flex_group['elements'].remove(slot['element'])
        aspects = []
        for slot in keep:
            meta = snapshot['photos'].get(slot['result']['photo']) if slot.get('result') else None
            aspects.append(meta['width'] / meta['height'] if meta and meta.get('height') else 1.5)
        ox, oy, ow, oh = flex_group['origin']
        for slot, frame in zip(keep, flex_frames(ow, oh, aspects, *flex_group['gap'])):
            slot['element']['box'] = [ox + frame['x'], oy + frame['y'], frame['w'], frame['h']]
            if slot.get('result'):
                slot['result'] = {**slot['result'], 'crop': None}
    for slot in slots:
        if slot.get('dropped'):
            continue
        e, result = slot['element'], slot.get('result')
        if 'general' in snapshot:
            e['slot'] = slot['ident']  # legacy snapshots keep their element fingerprints
        if not result and slot.get('cell_fill') and 'general' not in snapshot:
            e.update({'type': 'rect', 'fill': slot['cell_fill']}); e.pop('photo'); e.pop('crop'); e.pop('mask'); e.pop('required')
        if result:
            e['photo'], e['crop'] = result['photo'], result['crop'] or crop(result['photo'], e['box'], *slot.get('crop_pref', (50, 50, 1)))
            for step in result['relaxed']:
                if step in RELAX_TEXT:
                    issue('warning', slot['ident'], RELAX_TEXT[step])
            if result['dpi'] < GOOD_DPI:
                issue('warning', slot['ident'], f'Разрешение снимка в слоте {result["dpi"]} dpi — ниже 200')
        slot['finish'](e)
    shoots = snapshot.get('shoots', {})
    for e, template, values, finish, spread_key in late_texts:
        # The spread's shoot is the one most of its placed general photos come from; ties go to the first placed.
        counts = {}
        for slot in slots:
            result = slot.get('result')
            shoot = entry_by_id.get(result['photo'], {}).get('shoot') if result and not slot.get('dropped') and slot['key'].startswith(spread_key + '/') else None
            if shoot in shoots:
                counts[shoot] = counts.get(shoot, 0) + 1
        shoot = shoots[max(counts, key=counts.get)] if counts else {}
        e['text'] = auto_text.resolve(template, {**values, 'shoot.title': shoot.get('title', ''), 'shoot.date': auto_text.shoot_date(shoot.get('date', ''))})
        finish(e)
    for student in students:
        if 'general' in snapshot and entries and not report['coverage'].get(student['id']):
            issue('warning', 'coverage:' + student['id'], f'{name(student)}: нет на общих фото альбома')
    for photo in report['unplaced']:
        issue('warning', 'must:' + photo, 'Обязательное фото не поместилось ни в один слот')
    for key in overrides_by_key.keys()-found:
        for override in overrides_by_key[key]:
            conflicts.append({'key':key,'type':override['type'],'reason':'Элемент отсутствует в новой генерации'})
    for wild, elements in shared_bases.items():
        elements = [e for e in elements if e['key'].split('/', 1)[0] not in removed]
        if len(elements) > 1 and len({e['shared_base'] for e in elements}) == 1:
            for e in elements:
                e['shared'] = len(elements)
    count=max(len(v['sequence']) for v in variants)
    inner_width, inner_height = master.get('pageSize', [210, 280])
    document={'schema_version':1,'master_template':True,'edition':{'id':edition['id'],'version':edition['version']},'input_hash':canonical_hash(snapshot),'spread_count':count,'page_count':count*2-(2 if book and count>1 else 0),'spread_size_mm':[2*inner_width,inner_height],'cover_size_mm':next(iter(covers.values()))['size_mm'] if covers else None,'covers':covers,'shared_spreads':{},'variant_spreads':groups,'variants':variants,'plan':plans,'issues':issues,'overrides':{'applied':applied,'conflicts':conflicts},'photo_report':report}
    if book:
        document['layout'] = 'book'
    document['print'] = {'files': 'pages' if book else 'spreads', 'dpi': 300}
    for spread in [*covers.values(), *(s for group in groups.values() for s in group.values())]:
        for element in spread['elements']:
            version = snapshot.get('photos', {}).get(element.get('photo'), {}).get('version')
            if version:
                element['asset_version'] = version
    document['revision']=canonical_hash(document)
    return document
