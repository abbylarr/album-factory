"""Auto text: static text with data chips such as ``{{school|short}} / {{class|bare}} класс``.

The editor stores a text layer as one string; each chip is a ``{{field}}`` token, optionally with
modifiers after ``|``: a form of the value (short school name, class letter only, first name…) and a
letter case. Fields are resolved per album variant; shoot fields are resolved per spread after general
photos are picked. Mirrors web/auto-text.js.
"""
import re

FIELDS = {
    'owner.name': 'Имя владельца альбома',
    'owner.quote': 'Цитата владельца альбома',
    'item.name': 'Имя героя разворота',
    'item.quote': 'Цитата героя разворота',
    'lead.name': 'Имя руководителя',
    'lead.subject': 'Предмет руководителя',
    'school': 'Школа',
    'city': 'Город',
    'class': 'Класс',
    'year': 'Год выпуска',
    'shoot.title': 'Название съёмки',
    'shoot.date': 'Дата съёмки',
}
SHOOT_FIELDS = {'shoot.title', 'shoot.date'}
TOKEN = re.compile(r'\{\{([a-z.]+)((?:\|[a-z]+)*)\}\}')
CASES = ('upper', 'lower', 'title')
FORMS = {
    'name': ('first', 'last', 'initials'),
    'school': ('short',),
    'class': ('quotes', 'bare', 'letter', 'number'),
}


def kind(field):
    return 'name' if field.endswith('.name') else field


def fields(text):
    return {m.group(1) for m in TOKEN.finditer(text or '')}


def modifiers(raw):
    return [m for m in (raw or '').split('|') if m]


def unknown(text):
    """Tokens the editor cannot produce: unknown fields, unknown modifiers or two of one kind."""
    bad = set()
    for m in TOKEN.finditer(text or ''):
        field, mods = m.group(1), modifiers(m.group(2))
        forms = FORMS.get(kind(field), ())
        if (field not in FIELDS or any(mod not in CASES and mod not in forms for mod in mods)
                or sum(mod in CASES for mod in mods) > 1 or sum(mod in forms for mod in mods) > 1):
            bad.add(m.group(0))
    return bad


def apply_case(text, case):
    """Letter case of a whole text or one chip: upper, lower or every word capitalised."""
    text = text or ''
    if case == 'upper':
        return text.upper()
    if case == 'lower':
        return text.lower()
    if case == 'title':
        return re.sub(r'(^|[\s\-«"\'(])([^\W\d_])', lambda m: m.group(1) + m.group(2).upper(), text.lower())
    return text


def class_parts(value):
    """«11 «Б»», «11Б», «11-б» → ('11', 'Б'); anything else → ('', value)."""
    m = re.match(r'^\s*(\d+)\s*[-–]?\s*[«"„“\']?\s*(.*?)\s*[»"“”\']?\s*$', value or '')
    return (m.group(1), m.group(2)) if m else ('', (value or '').strip())


def person_name(person):
    """Name parts of a person record for the name chips."""
    person = person or {}
    return {'first': str(person.get('first_name') or ''), 'middle': str(person.get('patronymic') or ''),
            'last': str(person.get('last_name') or '')}


def format_value(field, raw, mods=()):
    """One chip's text: raw is a string, a name dict (first/middle/last) or a school dict (full/short)."""
    group = kind(field)
    form = next((m for m in mods if m in FORMS.get(group, ())), '')
    case = next((m for m in mods if m in CASES), '')
    if group == 'name' and isinstance(raw, dict):
        first, middle, last = raw.get('first', ''), raw.get('middle', ''), raw.get('last', '')
        if form == 'first':
            value = first
        elif form == 'last':
            value = last
        elif form == 'initials':
            value = ' '.join([p[0] + '.' for p in (first, middle) if p] + ([last] if last else []))
        else:
            value = ' '.join(p for p in (first, middle, last) if p)
    elif group == 'school' and isinstance(raw, dict):
        value = (raw.get('short') if form == 'short' else '') or raw.get('full') or ''
    else:
        value = '' if raw is None else str(raw)
        if group == 'class' and form:
            number, letter = class_parts(value)
            if number:
                value = {'quotes': f'{number} «{letter}»' if letter else number,
                         'bare': f'{number} {letter}'.strip(), 'letter': letter, 'number': number}[form]
    return apply_case(value, case)


def resolve(text, values):
    """Replace every chip with its value; a missing value leaves nothing behind."""
    return TOKEN.sub(lambda m: format_value(m.group(1), values.get(m.group(1)), modifiers(m.group(2))), text or '')


def shoot_date(value):
    """ISO date from the shoot form as the photographer reads it: 2020-09-27 → 27.09.2020."""
    parts = (value or '').split('-')
    return '.'.join(reversed(parts)) if len(parts) == 3 else value or ''
