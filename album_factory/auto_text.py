"""Auto text: static text with data chips such as ``{{school}} / {{class}} класс``.

The editor stores a text layer as one string; each chip is a ``{{field}}`` token. Fields are resolved
per album variant; shoot fields are resolved per spread after general photos are picked.
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
TOKEN = re.compile(r'\{\{([a-z.]+)\}\}')


def fields(text):
    return set(TOKEN.findall(text or ''))


def unknown(text):
    return fields(text) - FIELDS.keys()


def resolve(text, values):
    """Replace every chip with its value; a missing value leaves nothing behind."""
    return TOKEN.sub(lambda m: str(values.get(m.group(1)) or ''), text or '')


def shoot_date(value):
    """ISO date from the shoot form as the photographer reads it: 2020-09-27 → 27.09.2020."""
    parts = (value or '').split('-')
    return '.'.join(reversed(parts)) if len(parts) == 3 else value or ''
