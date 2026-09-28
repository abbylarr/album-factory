"""Choose general photos for master-layout slots.

A slot names a category (preset filters the designer may edit or add to) and
who must be on the photo: the hero of a personal spread, the album owner or
anyone. Shared slots (the same in every variant) are filled once, the rarest
first; per-owner slots are filled per variant from what is left. When nothing
fits, a hero slot first tries its category's fallbacks (what a designer would
take instead), then filters relax in a fixed order; each step is reported.
"""
from __future__ import annotations

from . import general_meta as gm

PEOPLE = ('none', 'solo', 'few', 'subgroup', 'class')
FIELDS = ('people', 'include', 'scale', 'tags', 'style', 'quality')
FILTERS = ('people', 'scale', 'tags', 'style', 'quality')
# Built-in categories. The designer may override filters and names per master (``photoCategories``).
CATEGORIES = {
    'any': {'name': 'Любое', 'filters': {}},
    'class': {'name': 'Весь класс', 'filters': {'people': ['class'], 'style': 'posed'}},
    'subgroup': {'name': 'Подгруппа', 'filters': {'people': ['subgroup'], 'style': 'posed'}},
    'few': {'name': 'Вдвоём-втроём', 'filters': {'people': ['few']}, 'prefer': ['smile'], 'fallback': ['candid', 'dup']},
    'solo': {'name': 'Один', 'filters': {'people': ['solo']}, 'fallback': ['candid_close', 'few', 'dup']},
    'candid': {'name': 'Репортаж', 'filters': {'style': 'candid'}, 'fallback': ['small', 'dup']},
    'wide': {'name': 'Общий план', 'filters': {'scale': ['wide']}},
    'empty': {'name': 'Без людей', 'filters': {'people': ['none']}},
}
# What a hero slot takes when its category has nothing: replacement filters and whether it takes series doubles
# (the best frame of a posed group is kept for shared spreads).
FALLBACKS = {
    'candid': ({'style': 'candid'}, False),
    'candid_close': ({'style': 'candid', 'scale': ['close', 'medium']}, False),
    'few': ({'people': ['few']}, False),
    'dup': ({'people': ['subgroup']}, True),
}
# Slots saved before categories: role presets and bucket names of the first analysis version.
LEGACY_ROLES = {
    'any': {}, 'hero': {'scale': ['medium', 'full', 'wide'], 'quality': 'best', 'prefer': ['hero']},
    'class_photo': {'people': ['class'], 'style': 'posed'}, 'life': {'people': ['few', 'subgroup'], 'style': 'candid'},
    'friends': {'include': 'owner', 'people': ['few', 'subgroup'], 'scale': ['close', 'medium'], 'prefer': ['smile']},
    'me_in_class': {'include': 'owner', 'people': ['subgroup', 'class']}, 'with_item': {'include': 'item'},
    'close_up': {'people': ['solo', 'few'], 'scale': ['close']}, 'atmosphere': {'people': ['none'], 'scale': ['detail', 'wide']},
}
LEGACY_BUCKETS = {'none': ['none'], 'solo': ['solo'], 'pair': ['few'], 'small_group': ['few', 'subgroup'], 'group': ['subgroup'], 'class': ['class']}
WHO = {'hero': 'item', 'owner': 'owner'}
RELAX = ('quality', 'scale', 'people', 'style', 'tags', 'include', 'any', 'cut')
RELAX_TEXT = {
    'fallback': 'Снимков нужной категории с героем разворота нет — взят похожий кадр с ним',
    'dup': 'Для героя разворота взят дубль групповой фотографии',
    'small': 'Герой разворота на снимке мелко — крупнее кадров с ним нет',
    'include': 'Нет подходящих общих фото с нужным учеником — поставлено фото без него',
    'any': 'Под категорию слота нет фото — поставлено любое общее фото',
    'cut': 'Нет снимка подходящей ориентации — кадрирование обрезает людей',
    'reuse': 'Общих фото не хватает — снимок повторяется',
}
DEFAULT_RULES = {'reuse': 'album', 'coverageMin': 1, 'coverageMax': 0, 'rhythm': True, 'chronology': True, 'mixShoots': True, 'posedFirst': True}
MIN_DPI, GOOD_DPI, VISIBLE_FACE_MM, HERO_FACE_MM = 120, 200, 4.0, 6.0


def people_of(entry):
    """How many people a photo shows, in the terms of categories."""
    count = entry.get('count') or 0
    if entry.get('bucket') == 'none' or not count:
        return 'none'
    if entry.get('bucket') == 'class':
        return 'class'
    return 'solo' if count == 1 else 'few' if count <= 3 else 'subgroup'


def categories_of(master):
    """Built-in categories with the master's edits applied, then its own categories."""
    result = {key: {**value, 'filters': dict(value['filters'])} for key, value in CATEGORIES.items()}
    for item in (master or {}).get('photoCategories') or []:
        base = result.get(item['id'], {})
        result[item['id']] = {**base, 'name': item.get('name') or base.get('name', ''),
                              'filters': {k: item.get(k) for k in FILTERS if item.get(k)}}
    return result


def resolve(pick, categories=None):
    """Constraints of a slot: category filters, who must be on it, preferences and fallbacks."""
    pick = pick or {}
    categories = categories or CATEGORIES
    result = {**{k: None for k in FIELDS}, 'prefer': [], 'fallback': []}
    if 'category' in pick or 'role' not in pick:
        key = pick.get('category') if pick.get('category') in categories else 'any'
        category = categories[key]
        result.update({k: v or None for k, v in category['filters'].items()})
        result.update(category=key, prefer=list(category.get('prefer', [])), fallback=list(category.get('fallback', [])),
                      include=WHO.get(pick.get('who')))
        return result
    role = pick['role'] if pick['role'] in LEGACY_ROLES else 'any'
    result.update(LEGACY_ROLES[role]); result['category'] = role
    for key in ('include', 'scale', 'tags', 'style', 'quality'):
        if key in pick:
            result[key] = pick[key] or None
    if 'buckets' in pick:
        result['people'] = sorted({p for b in pick['buckets'] or [] for p in LEGACY_BUCKETS.get(b, [])}, key=PEOPLE.index) or None
    return result


def rules_of(master):
    return {**DEFAULT_RULES, **(master.get('photoRules') or {})}


def fit(entry, aspect, width, height, cut=False):
    """Largest crop of the slot aspect keeping the safe box, placed on the subject.

    None if heads would be cut, unless ``cut`` allows centring on them anyway.
    """
    if aspect >= width / height:
        cw, ch = width, width / aspect
    else:
        cw, ch = height * aspect, height
    safe = _px(entry.get('safe_box'), width, height)
    subject = _px(entry.get('subject_box'), width, height)
    if safe and (safe[2] > cw * 1.001 or safe[3] > ch * 1.001):
        if not cut:
            return None
        subject = safe
        safe = None
    x = (subject[0] + subject[2] / 2 if subject else width / 2) - cw / 2
    if safe:
        x = min(max(x, safe[0] + safe[2] - cw), safe[0])
    x = min(max(x, 0), width - cw)
    if subject and subject[3] <= ch:
        y = subject[1] + subject[3] / 2 - ch / 2
    elif safe:
        y = safe[1] - ch * .08
    else:
        y = (height - ch) / 2
    if safe:
        y = min(y, safe[1] - min(ch * .06, safe[1]))
        y = max(y, safe[1] + safe[3] - ch)
    y = min(max(y, 0), height - ch)
    return [round(x, 2), round(y, 2), round(cw, 2), round(ch, 2)]


def _px(box, width, height):
    return [box[0] * width, box[1] * height, box[2] * width, box[3] * height] if box else None


def _persons(entry):
    return [{'box': p['box'], 'face': p.get('face'), 'body': p['box'] if p.get('kp') else None,
             'kp': p.get('kp') or {}, 'subject': p.get('subject')} for p in entry.get('persons') or []]


def view(entry, crop, size, slot_mm):
    """Scale and printed face sizes of an entry inside a crop."""
    width, height = size
    norm = (crop[0] / width, crop[1] / height, crop[2] / width, crop[3] / height)
    persons = _persons(entry)
    faces = {}
    for p in persons:
        if p['subject'] and p['face'] and _centre_in(p['face'], norm):
            faces[p['subject']] = p['face'][3] / norm[3] * slot_mm[1]
    return {'scale': gm.photo_scale(persons, norm) if persons else 'detail', 'faces': faces,
            'dpi': crop[3] / (slot_mm[1] / 25.4)}


def _centre_in(box, crop):
    x, y = box[0] + box[2] / 2, box[1] + box[3] / 2
    return crop[0] <= x <= crop[0] + crop[2] and crop[1] <= y <= crop[1] + crop[3]


class Picker:
    def __init__(self, entries, photos, rules, students, categories=None):
        self.entries = [e for e in entries if e['id'] in photos]
        self.photos = photos
        self.rules = {**DEFAULT_RULES, **rules}
        self.categories = categories or CATEGORIES
        self.students = [s['id'] for s in students]
        self.shoots = len({e.get('shoot') for e in self.entries if e.get('shoot')})
        timed = sorted(self.entries, key=lambda e: (e.get('taken_at') or '', e.get('sequence', 0), e['id']))
        self.rank = {e['id']: i / max(1, len(timed) - 1) for i, e in enumerate(timed)}
        self.coverage = {s: 0 for s in self.students}
        self.report = {'slots': {}, 'coverage': {}, 'unplaced': []}
        self._cache = {}

    def size(self, entry):
        meta = self.photos[entry['id']]
        return meta['width'], meta['height']

    def evaluate(self, entry, slot, c):
        """(crop, view) when the entry satisfies constraints ``c`` for the slot, else None."""
        key = (entry['id'], slot['aspect_key'], slot['mm'][1], bool(c.get('cut')))
        if key not in self._cache:
            width, height = self.size(entry)
            crop = fit(entry, slot['mm'][0] / slot['mm'][1], width, height, bool(c.get('cut')))
            self._cache[key] = (crop, view(entry, crop, (width, height), slot['mm']) if crop else None)
        crop, seen = self._cache[key]
        if entry.get('legacy'):
            return (crop, seen) if crop and (c.get('any') or not any(c[k] for k in FIELDS)) else None
        if not crop or seen['dpi'] < MIN_DPI:
            return None
        if c.get('any'):
            return crop, seen
        if entry.get('defect') == 'reject' or bool(entry.get('alt')) != bool(c.get('alt')):
            return None  # series doubles only where a double is asked for
        if c['quality'] == 'best' and entry['quality'] < .6:
            return None
        if c['quality'] == 'good' and entry.get('defect'):
            return None
        if c['people'] and people_of(entry) not in c['people']:
            return None
        if c['style'] and entry.get('style') and entry['style'] != c['style']:
            return None
        if c['tags'] and not set(entry.get('tags') or ()) & set(c['tags']):
            return None
        target = slot.get('target') if c['include'] else None
        if c['include']:
            face = seen['faces'].get(target, 0) if target else 0
            # The hero should be one of the main faces, not a dot in the crowd, unless nothing else is left.
            need = VISIBLE_FACE_MM if c.get('small') else max(HERO_FACE_MM, .6 * max(seen['faces'].values(), default=0))
            if face < need:
                return None
        if c['scale'] and seen['scale'] not in c['scale']:
            return None
        return crop, seen

    def score(self, entry, slot, seen, c, coverage, placed):
        score = entry.get('quality', .4)
        flags = entry.get('flags') or {}
        if flags.get('must_use'):
            score += 1.0
        if flags.get('hero'):
            score += .35 if 'hero' in c['prefer'] else .05
        if 'smile' in c['prefer'] and entry.get('smile') is not None:
            score += .2 * entry['smile']
        low, high = self.rules['coverageMin'], self.rules['coverageMax']
        for subject, mm in seen['faces'].items():
            if mm < VISIBLE_FACE_MM or subject not in coverage:
                continue
            if coverage[subject] < low:
                score += .25
            elif high and coverage[subject] >= high:
                score -= .3
        for other in placed.get(slot['spread'], []):
            if self.rules['rhythm']:
                if other['series'] and other['series'] == entry.get('series'):
                    score -= .6
                if other['scale'] == seen['scale']:
                    score -= .15
            if self.rules['mixShoots'] and self.shoots > 1 and other.get('shoot') and other['shoot'] == entry.get('shoot'):
                score -= .3
        if self.rules['posedFirst'] and not c['style'] and entry.get('style') in ('posed', 'candid'):
            late = slot.get('section_rank', .5)
            score += .6 * (1 - late if entry['style'] == 'posed' else late)
        if self.rules['chronology']:
            score -= .25 * abs(self.rank[entry['id']] - slot['rank'])
        if seen['dpi'] < GOOD_DPI:
            score -= .2
        return score

    def steps(self, c):
        """Constraint sets to try in order, each labelled with what was given up (None — nothing)."""
        yield None, c
        if c['include']:
            for name in c['fallback']:
                if name == 'small':
                    yield 'small', {**c, 'small': True}
                elif name in FALLBACKS:
                    filters, alt = FALLBACKS[name]
                    yield ('dup' if alt else 'fallback'), {**c, **{k: None for k in FILTERS}, **filters, 'alt': alt}
            c = {**c, 'small': True}
        for step in RELAX:
            if step in ('any', 'cut'):
                c = {**c, step: True}
            elif not c.get(step):
                continue
            else:
                c = {**c, step: None}
            yield step, c
        yield 'reuse', c

    def assign(self, slots):
        """Fill slots in place: slot['result'] = {photo, crop, relaxed, candidates}."""
        count = max(1, len(slots) - 1)
        for index, slot in enumerate(slots):
            slot['rank'] = min(1.0, slot.get('order', index) / max(1, slot.get('total', count)))
        by_section = {}
        for slot in slots:
            by_section.setdefault(slot['section'], set()).add(slot.get('order', 0))
        for slot in slots:
            orders = sorted(by_section[slot['section']])
            slot['section_rank'] = orders.index(slot.get('order', 0)) / max(1, len(orders) - 1)
        shared = {}
        for slot in slots:
            if not slot['personal']:
                shared.setdefault(slot['ident'], []).append(slot)
        used, placed = set(), {}
        self._fill([group[0] for group in shared.values()], used, placed, self.coverage, section_used={})
        for group in shared.values():
            for slot in group[1:]:
                slot['result'] = group[0].get('result')
        self.report['coverage'] = dict(self.coverage)
        owners = {}
        for slot in slots:
            if slot['personal']:
                owners.setdefault(slot['owner'], []).append(slot)
        shared_used = {s['result']['photo'] for s in slots if not s['personal'] and s.get('result')}
        for owner, items in owners.items():
            coverage = dict(self.coverage)
            self._fill(items, set(shared_used), {k: list(v) for k, v in placed.items()}, coverage, section_used={})
            self.report['coverage'][owner] = coverage.get(owner, 0)
        must = {e['id'] for e in self.entries if (e.get('flags') or {}).get('must_use')}
        self.report['unplaced'] = sorted(must - {s['result']['photo'] for s in slots if s.get('result')})
        return self.report

    def _fill(self, slots, used, placed, coverage, section_used):
        strict = {}
        for slot in slots:
            c = resolve(slot['pick'], self.categories)
            strict[slot['ident']] = sum(1 for e in self.entries if self.evaluate(e, slot, c))
        order = sorted(slots, key=lambda s: ('hero' not in resolve(s['pick'], self.categories)['prefer'], strict[s['ident']], s.get('order', 0)))
        for slot in order:
            c0 = resolve(slot['pick'], self.categories)
            relaxed, choice = [], None
            for step, c in self.steps(c0):
                if step and step not in relaxed:
                    relaxed.append(step)
                blocked = set() if step == 'reuse' or self.rules['reuse'] == 'allow' else (
                    used if self.rules['reuse'] == 'album' else section_used.setdefault(slot['section'], set()))
                best = None
                for entry in self.entries:
                    if entry['id'] in blocked:
                        continue
                    found = self.evaluate(entry, slot, c)
                    if not found:
                        continue
                    value = self.score(entry, slot, found[1], c, coverage, placed) - (.3 if entry['id'] in used else 0)
                    if best is None or value > best[0] or (value == best[0] and entry['id'] < best[1]['id']):
                        best = (value, entry, found)
                if best:
                    choice = best
                    break
                if step in ('fallback', 'dup', 'small'):
                    relaxed.remove(step)  # alternatives, not cumulative: only the one that worked is reported
            report = {'candidates': strict[slot['ident']], 'relaxed': relaxed}
            if choice:
                _, entry, (crop, seen) = choice
                slot['result'] = {'photo': entry['id'], 'crop': crop, 'dpi': round(seen['dpi']), 'scale': seen['scale'], **report}
                used.add(entry['id'])
                section_used.setdefault(slot['section'], set()).add(entry['id'])
                placed.setdefault(slot['spread'], []).append({'series': entry.get('series'), 'scale': seen['scale'], 'shoot': entry.get('shoot')})
                for subject, mm in seen['faces'].items():
                    if mm >= VISIBLE_FACE_MM and subject in coverage:
                        coverage[subject] += 1
            else:
                slot['result'] = None
            ranked = sorted((e for e in self.entries if not e.get('legacy') and self.evaluate(e, slot, c0)),
                            key=lambda e: -e.get('quality', 0))[:24]
            self.report['slots'][slot['ident']] = {**report, 'ranked': [e['id'] for e in ranked]}


def entries_from(snapshot):
    """Snapshot general entries; legacy snapshots only list photo ids."""
    if snapshot.get('general') is not None:
        return snapshot['general']
    return [{'id': pid, 'legacy': True, 'sequence': i} for i, pid in enumerate(snapshot.get('general_photos', []))]
