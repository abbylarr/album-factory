"""How blocks of a master layout unfold into spreads (rulesVersion 2).

Mirrors web/master-plan-core.js, which the editor uses for its preview; tests/test_master_plan_parity.py keeps
them equal. A block is fixed (every spread once), a list (vignettes of students or teachers) or personal (its
spreads repeat per person). Spreads of a list block have roles: intro and outro appear once, repeat spreads cycle
while people remain, and the last spread replaces a repeat spread the list would fill only partly.
A list or personal block may be split into parts with other blocks between them: a part stops after ``limit``
spreads, and the block whose ``continues`` names it takes the people from where it stopped.
"""
from __future__ import annotations

import math

ROLES = ('intro', 'repeat', 'last', 'outro')
PEOPLE = ('all', 'others', 'owner', 'off')
LIST_DEFAULT = {'source': 'students', 'min': 4, 'max': 12, 'strictMin': False, 'excludeLead': False}


def role_of(spread):
    return spread.get('role') if spread.get('role') in ROLES else 'repeat'


def has_grid(page):
    return any(layer.get('type') == 'grid' for layer in page.get('layers') or [])


def grid_pages(spread):
    return sum(1 for page in spread.get('pages') or [] if has_grid(page))


def distribute(n, parts):
    if parts <= 0:
        return []
    base, extra = divmod(n, parts)
    return [base + (1 if i < extra else 0) for i in range(parts)]


def list_plan(section, n, cap):
    """Spreads of a list block and which part of the list each page shows (see master-plan-core.js)."""
    settings = {**LIST_DEFAULT, **(section.get('list') or {})}
    minimum = max(1, int(settings.get('min') or 1))
    spreads = section.get('spreads') or []
    issues = []

    def pick(role):
        return [s for s in spreads if role_of(s) == role]
    intro, repeat, outro = pick('intro'), pick('repeat'), pick('outro')
    last = next(iter(pick('last')), None)
    if not any(grid_pages(s) for s in spreads):
        return _finish([(s, 0) for s in spreads], [], ['no-grid'], 0)
    if not cap:
        return _finish([(s, 0) for s in intro + repeat[:1] + outro], [], ['no-fit'], 0)
    fixed = sum(grid_pages(s) for s in intro + outro)
    cycle_has_grid = any(grid_pages(s) for s in repeat)
    target = max(1, math.floor(float(section.get('target') or len(spreads)) + 0.5))  # Math.round in the editor
    preferred = fixed
    if repeat:
        for i in range(target - len(intro) - len(outro)):
            preferred += grid_pages(repeat[i % len(repeat)])
    preferred = max(1, preferred)
    pages = max(math.ceil(n / cap), min(preferred, max(1, n // minimum))) if n else 1
    pages = max(pages, fixed)
    whole = pages
    limit = part_limit(section)
    if n and limit and cycle_has_grid:
        room = fixed
        for i in range(limit - len(intro) - len(outro)):
            room += grid_pages(repeat[i % len(repeat)])
        pages = min(pages, max(room, fixed, 1))
    cut = pages < whole
    middle, rest, turn = [], pages - fixed, 0
    while rest > 0:
        if not cycle_has_grid:
            room = grid_pages(last) if last else 0
            if last:
                middle.append((last, room))
            if room < rest:
                issues.append('no-repeat')
            pages = fixed + room
            break
        spread = repeat[turn % len(repeat)]
        turn += 1
        grids = grid_pages(spread)
        if not grids:
            middle.append((spread, 0))
            continue
        if rest >= grids:
            middle.append((spread, grids))
            rest -= grids
            continue
        if last and grid_pages(last) >= rest:
            middle.append((last, grid_pages(last)))
            pages += grid_pages(last) - rest
        else:
            middle.append((spread, rest))
            issues.append('half')
        break
    counts = [0] if not n else distribute(n, whole)[:pages] if cut else distribute(n, max(pages, 1))
    if n and any(c < minimum for c in counts):
        issues.append('below-min')
    if n and any(c > cap for c in counts):
        issues.append('overflow')
    return _finish([(s, grid_pages(s)) for s in intro] + middle + [(s, grid_pages(s)) for s in outro], counts, issues, sum(counts))


def _finish(sequence, counts, issues, taken):
    part, spreads = 0, []
    for spread, take in sequence:
        used, pages = 0, []
        for page in spread['pages']:
            if not has_grid(page) or used >= take or part >= len(counts):
                pages.append({'page': page['id'], 'part': None})
                continue
            used += 1
            pages.append({'page': page['id'], 'part': part})
            part += 1
        spreads.append({'spread': spread['id'], 'role': role_of(spread), 'pages': pages})
    return {'spreads': spreads, 'counts': counts, 'taken': taken, 'issues': issues}


def part_limit(section):
    return max(0, math.floor(float(section.get('limit') or 0) + 0.5))  # Math.round in the editor


def personal_take(section, n):
    """How many of n people a part of a split personal block takes: whole people, as many as fit in its spreads."""
    limit, per = part_limit(section), max(1, len(section.get('spreads') or []))
    return min(n, max(1, limit // per)) if limit else n


def people(section, students, owner):
    """Ids whose personal spreads a block shows in the album of ``owner``, in list order."""
    mode = section.get('people') if section.get('people') in PEOPLE else 'all'
    if mode == 'off':
        return []
    if mode == 'owner':
        return [owner] if owner in students else []
    if mode == 'others':
        return [s for s in students if s != owner]
    return list(students)


ISSUES = {
    'no-grid': ('warning', 'В блоке «по списку» нет виньетки — развороты выводятся по одному разу'),
    'no-fit': ('error', 'Виньетки не помещаются в область. Увеличьте область или уменьшите фото.'),
    'no-repeat': ('error', 'Список не помещается: добавьте разворот с ролью «Повторяемый»'),
    'half': ('warning', 'Список закончился на середине разворота — добавьте шаблон «Последний неполный»'),
    'below-min': ('warning', 'Карточек на странице меньше заданного минимума'),
    'overflow': ('error', 'Карточки не помещаются на страницу'),
    'parts-order': ('error', 'Продолжение списка стоит раньше его начала'),
}
