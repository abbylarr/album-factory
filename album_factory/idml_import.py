"""InDesign (IDML) → master layout draft.

IDML is a zip of XML: spreads with frames, parent (master) pages, stories and styles. The importer keeps the
geometry and look of every frame, then guesses what each frame means for the album:

* a photo frame's source comes from the folder of its linked file (portraits, teachers, anything else is a
  general photo);
* spreads built from the same portrait page become one personal block (the other page turns into a flexible
  collage), a page of equal photo cards becomes a vignette, the rest stay fixed spreads;
* texts that change from spread to spread become name and quote chips; school lines, years and dates become
  chips by pattern.

Everything the importer could not carry over or had to guess goes into a short report for the photographer.
"""
from __future__ import annotations

import base64
import io
import math
import re
import struct
import uuid
import zipfile
from collections import Counter
from urllib.parse import unquote
import xml.etree.ElementTree as ET

from .master_plan import PHOTO_RATIOS

PT = 25.4 / 72  # mm per point
PKG = '{http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging}'
FRAME_TAGS = {'Rectangle', 'Oval', 'Polygon', 'GraphicLine', 'TextFrame', 'Group'}
GRAPHIC_TAGS = {'Image', 'PDF', 'EPS', 'ImportedPage', 'WMF', 'PICT', 'SVG'}
SURNAME = re.compile(r'(ов|ев|ёв|ин|ын|ова|ева|ёва|ина|ына|ский|цкий|ская|цкая|ко|ук|юк|их|ых|ая|ий|ой|ич|ер|ман)$', re.I)


class ImportError_(ValueError):
    pass


def uid():
    return uuid.uuid4().hex


# --- geometry ---------------------------------------------------------------------

def matrix(value):
    try:
        m = [float(v) for v in (value or '1 0 0 1 0 0').split()]
        return m if len(m) == 6 else [1, 0, 0, 1, 0, 0]
    except ValueError:
        return [1, 0, 0, 1, 0, 0]


def mul(outer, inner):
    """Transform that applies `inner`, then `outer`."""
    a, b, c, d, e, f = outer
    A, B, C, D, E, F = inner
    return [a * A + c * B, b * A + d * B, a * C + c * D, b * C + d * D, a * E + c * F + e, b * E + d * F + f]


def invert(m):
    a, b, c, d, e, f = m
    det = a * d - b * c or 1e-9
    return [d / det, -b / det, -c / det, a / det, (c * f - d * e) / det, (b * e - a * f) / det]


def apply(m, x, y):
    return m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]


def placement(element, transform):
    """Centre, unrotated size (pt) and angle of a frame under `transform`."""
    points = [tuple(map(float, p.get('Anchor').split())) for p in element.iter('PathPointType') if p.get('Anchor')]
    if not points:
        return None
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    cx, cy = apply(transform, (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    sx, sy = math.hypot(transform[0], transform[1]), math.hypot(transform[2], transform[3])
    angle = math.degrees(math.atan2(transform[1], transform[0]))
    angle = round((angle + 180) % 360 - 180, 2)
    return {'cx': cx, 'cy': cy, 'w': (max(xs) - min(xs)) * sx, 'h': (max(ys) - min(ys)) * sy, 'angle': 0 if abs(angle) < .05 else angle}


def bounds(item):
    """Axis-aligned bounds (mm) of an item on its page."""
    b = item['box']
    if not item.get('angle'):
        return b['x'], b['y'], b['x'] + b['w'], b['y'] + b['h']
    r = math.radians(item['angle'])
    w = abs(b['w'] * math.cos(r)) + abs(b['h'] * math.sin(r))
    h = abs(b['w'] * math.sin(r)) + abs(b['h'] * math.cos(r))
    cx, cy = b['x'] + b['w'] / 2, b['y'] + b['h'] / 2
    return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2


def covers(top, below, tolerance=0.6):
    a, b = bounds(top), bounds(below)
    return a[0] - tolerance <= b[0] and a[1] - tolerance <= b[1] and a[2] + tolerance >= b[2] and a[3] + tolerance >= b[3]


# --- colours and fonts -------------------------------------------------------------

def hex_color(r, g, b):
    return '#%02x%02x%02x' % tuple(max(0, min(255, round(v))) for v in (r, g, b))


class Swatches:
    def __init__(self, root):
        self.colors, self.gradients = {}, {}
        for el in root.iter('Color'):
            self.colors[el.get('Self')] = el
        for el in root.iter('Gradient'):
            self.gradients[el.get('Self')] = el
        self.unsupported = set()

    def color(self, ref, tint=None):
        """#rrggbb for a swatch reference, None for no colour."""
        if not ref or ref.endswith('/None') or ref == 'n':
            return None
        if ref == 'Color/Paper':
            value = '#ffffff'
        elif ref in ('Color/Black', 'Color/Registration'):
            value = '#000000'
        elif ref in self.gradients:
            stops = [s.get('StopColor') for s in self.gradients[ref].iter('GradientStop')]
            self.unsupported.add('градиенты заменены первым цветом')
            return self.color(stops[0]) if stops else None
        else:
            el = self.colors.get(ref)
            if el is None:
                return None
            values = [float(v) for v in (el.get('ColorValue') or '0 0 0 100').split()]
            space = el.get('Space')
            if space == 'RGB' and len(values) >= 3:
                value = hex_color(*values[:3])
            elif space == 'LAB' and len(values) >= 3:
                value = lab_to_hex(*values[:3])
            else:
                c, m, y, k = (values + [0, 0, 0, 0])[:4]
                value = hex_color(*(255 * (1 - v / 100) * (1 - k / 100) for v in (c, m, y)))
        if tint not in (None, '', '-1', -1):
            t = float(tint) / 100
            rgb = [int(value[i:i + 2], 16) for i in (1, 3, 5)]
            value = hex_color(*(255 - (255 - v) * t for v in rgb))
        return value


def lab_to_hex(l, a, b):
    y = (l + 16) / 116
    x, z = a / 500 + y, y - b / 200
    f = lambda t: t ** 3 if t ** 3 > 0.008856 else (t - 16 / 116) / 7.787
    x, y, z = 0.95047 * f(x), f(y), 1.08883 * f(z)
    rgb = [3.2406 * x - 1.5372 * y - 0.4986 * z, -0.9689 * x + 1.8758 * y + 0.0415 * z, 0.0557 * x - 0.2040 * y + 1.0570 * z]
    g = lambda v: 1.055 * v ** (1 / 2.4) - 0.055 if v > 0.0031308 else 12.92 * v
    return hex_color(*(255 * g(max(0, v)) for v in rgb))


def font_names(raw):
    """Family and subfamily from a TTF/OTF name table (typographic names preferred)."""
    try:
        count = struct.unpack('>H', raw[4:6])[0]
        for i in range(count):
            tag, _, offset, _ = struct.unpack('>4sIII', raw[12 + i * 16:28 + i * 16])
            if tag != b'name':
                continue
            _, n, strings = struct.unpack('>HHH', raw[offset:offset + 6])
            names = {}
            for j in range(n):
                platform, encoding, _, name_id, length, start = struct.unpack('>6H', raw[offset + 6 + j * 12:offset + 18 + j * 12])
                data = raw[offset + strings + start:offset + strings + start + length]
                text = data.decode('utf-16-be', 'ignore') if platform in (0, 3) else data.decode('latin-1', 'ignore')
                if name_id in (1, 2, 16, 17) and text and (name_id not in names or platform == 3):
                    names[name_id] = text
            return names.get(16) or names.get(1) or '', names.get(17) or names.get(2) or ''
    except (struct.error, IndexError):
        pass
    return '', ''


def family_key(name):
    return re.sub(r'\(.*?\)|[^0-9a-zа-яё]', '', (name or '').lower())


# --- stories ------------------------------------------------------------------------

STYLE_ATTRS = ('PointSize', 'FontStyle', 'FillColor', 'FillTint', 'Tracking', 'Capitalization', 'Skew', 'Justification', 'Underline', 'StrikeThru')


class Styles:
    def __init__(self, root):
        self.paragraph = {el.get('Self'): el for el in root.iter('ParagraphStyle')}
        self.character = {el.get('Self'): el for el in root.iter('CharacterStyle')}

    def resolve(self, table, ref, depth=0):
        el = table.get(ref)
        if el is None or depth > 10:
            return {}
        props = el.find('Properties')
        based = props.find('BasedOn') if props is not None else None
        out = self.resolve(table, based.text, depth + 1) if based is not None and based.text else {}
        out.update(attributes(el))
        return out


def attributes(el):
    out = {k: el.get(k) for k in STYLE_ATTRS if el.get(k) is not None}
    props = el.find('Properties')
    if props is not None:
        font, leading = props.find('AppliedFont'), props.find('Leading')
        if font is not None and font.text:
            out['AppliedFont'] = font.text
        if leading is not None and leading.text and leading.text != 'Auto':
            out['Leading'] = leading.text
    return out


def story_runs(story, styles):
    """Text of a story and its runs with resolved attributes."""
    runs, text = [], []
    for para in story.iter('ParagraphStyleRange'):
        base = styles.resolve(styles.paragraph, para.get('AppliedParagraphStyle'))
        base.update(attributes(para))
        for char in para.iter('CharacterStyleRange'):
            attrs = dict(base)
            attrs.update(styles.resolve(styles.character, char.get('AppliedCharacterStyle')))
            attrs.update(attributes(char))
            chunk = ''
            for child in char:
                if child.tag == 'Content':
                    chunk += child.text or ''
                elif child.tag == 'Br':
                    chunk += '\n'
            if chunk:
                runs.append((chunk, attrs))
                text.append(chunk)
    return ''.join(text).replace(' ', '\n').replace('﻿', '').strip('\n'), runs


# --- text chips -----------------------------------------------------------------------

def is_upper(text):
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def case_mod(sample, text_case):
    return '|upper' if is_upper(sample) and text_case != 'upper' else ''


def pattern_chips(text, text_case=''):
    """School line, class and year, and shoot dates by pattern. Returns new text and found chip names."""
    found = []
    out = text
    if re.search(r'выпуск', text, re.I):
        out, n = re.subn(r'\b(19|20)\d{2}\b', '{{year}}', out)
        if n:
            found.append('год выпуска')
    m = re.search(r'(\d{1,2})\s*[«"]?([А-ЯЁа-яё])[»"]?\s+(класс)', out, re.I)
    if m:
        mod = case_mod(m.group(2), text_case)
        out = out[:m.start()] + '{{class|number}}{{class|letter' + mod + '}} ' + m.group(3) + out[m.end():]
        found.append('класс')
        parts = out.split('/')
        if len(parts) > 1 and '{{' not in parts[0] and re.search(r'школ|лице|гимнази|№|\d', parts[0], re.I):
            lead = parts[0]
            name = lead.strip()
            out = lead[:len(lead) - len(lead.lstrip())] + '{{school|short' + case_mod(name, text_case) + '}}' + lead[len(lead.rstrip()):] + '/' + '/'.join(parts[1:])
            found.append('школа')
    if re.fullmatch(r'\s*\d{1,2}\.\d{1,2}\.\d{4}\s*', out):
        out = '{{shoot.date}}'
        found.append('дата съёмки')
    return out, found


def name_chip(sample, prefix, text_case=''):
    words = sample.split()
    mod = case_mod(sample, text_case)
    if len(words) >= 2 and SURNAME.search(words[0].strip(',.')) and not SURNAME.search(words[-1].strip(',.')):
        return '{{%s.name|last%s}} {{%s.name|first%s}}' % (prefix, mod, prefix, mod)
    return '{{%s.name%s}}' % (prefix, mod)


# --- reading ---------------------------------------------------------------------------

class Reader:
    def __init__(self, data: bytes, fonts: list[dict] | None = None):
        try:
            self.zip = zipfile.ZipFile(io.BytesIO(data))
            design = self.xml('designmap.xml')
        except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
            raise ImportError_('Это не файл IDML. В InDesign: Файл → Сохранить как → InDesign Markup (IDML).') from exc
        self.design = design
        self.notes: list[tuple[str, str]] = []
        prefs = self.xml('Resources/Preferences.xml')
        doc = prefs.find('.//DocumentPreference')
        margin = prefs.find('.//MarginPreference')
        self.page_w = round(float(doc.get('PageWidth')) * PT, 1)
        self.page_h = round(float(doc.get('PageHeight')) * PT, 1)
        self.facing = doc.get('FacingPages') != 'false'
        bleed = [float(doc.get(k, 0)) for k in ('DocumentBleedTopOffset', 'DocumentBleedBottomOffset', 'DocumentBleedOutsideOrRightOffset')]
        self.bleed = round(max(bleed) * PT, 1)
        self.margin = round(min(float(margin.get(k, 0)) for k in ('Top', 'Bottom', 'Left', 'Right')) * PT, 1) if margin is not None else 5
        self.swatches = Swatches(self.xml('Resources/Graphic.xml'))
        self.styles = Styles(self.xml('Resources/Styles.xml'))
        self.stories = {}
        for name in self.zip.namelist():
            if name.startswith('Stories/'):
                story = self.xml(name).find('Story')
                if story is not None:
                    self.stories[story.get('Self')] = story_runs(story, self.styles)
        self.masters = {}
        for el in design.findall(PKG + 'MasterSpread'):
            spread = self.xml(el.get('src')).find('MasterSpread')
            self.masters[spread.get('Self')] = spread
        self.spreads = [self.xml(el.get('src')).find('Spread') for el in design.findall(PKG + 'Spread')]
        self.hidden_layers = {l.get('Self') for l in design.findall('Layer') if l.get('Visible') == 'false' or l.get('Printable') == 'false'}
        self.name = (design.get('Name') or 'Макет из InDesign').removesuffix('.indd').strip()[:80] or 'Макет из InDesign'
        self.font_files = {}
        for font in fonts or []:
            try:
                header, payload = font['dataUrl'].split(',', 1)
                raw = base64.b64decode(payload)
            except (KeyError, ValueError):
                continue
            if len(raw) > 1_500_000:
                self.notes.append(('warning', f'Шрифт «{font.get("name", "")}» больше 1,5 МБ — не загружен.'))
                continue
            family, sub = font_names(raw)
            key = family_key(family or font.get('name', ''))
            regular = sub.lower() in ('regular', 'book', 'roman', 'normal')
            if key and (key not in self.font_files or regular):
                self.font_files[key] = {'name': family or font.get('name', 'Шрифт'), 'dataUrl': font['dataUrl'], 'regular': regular}
        self.used_fonts: dict[str, str] = {}
        self.missing_fonts: set[str] = set()
        self.effects = False

    def xml(self, name):
        return ET.fromstring(self.zip.read(name))

    # frames of a spread, parent pages included
    def pages_of(self, spread):
        pages = []
        for page in spread.findall('Page'):
            m = matrix(page.get('ItemTransform'))
            top, left, bottom, right = (float(v) for v in page.get('GeometricBounds').split())
            x0, y0 = apply(m, left, top)
            x1, y1 = apply(m, right, bottom)
            pages.append({'el': page, 'x': min(x0, x1), 'y': min(y0, y1), 'w': abs(x1 - x0), 'h': abs(y1 - y0), 'm': m})
        return sorted(pages, key=lambda p: p['x'])

    def frames(self, container, transform, out, hidden=False):
        for el in container:
            if el.tag not in FRAME_TAGS:
                continue
            if el.get('Visible') == 'false' or el.get('ItemLayer') in self.hidden_layers or hidden:
                continue
            t = mul(transform, matrix(el.get('ItemTransform')))
            if el.tag == 'Group':
                self.frames(el, t, out)
            else:
                out.append((el, t))
        return out

    def master_items(self, page, depth):
        master = self.masters.get(page['el'].get('AppliedMaster'))
        if master is None or depth > 4 or page['el'].get('ShowMasterItems') == 'false':
            return []
        overridden = set((page['el'].get('OverrideList') or '').split()[0::2])
        master_pages = self.pages_of(master)
        index = min(len(master_pages) - 1, 1 if page.get('side', 0) and len(master_pages) > 1 else 0)
        mp = master_pages[index]
        to_page = mul(mul(page['m'], matrix(page['el'].get('MasterPageTransform'))), invert(mp['m']))
        mp['side'] = page.get('side', 0)
        items = [(el, mul(to_page, t)) for el, t in self.master_items(mp, depth + 1)]
        for el, t in self.frames(master, [1, 0, 0, 1, 0, 0], []):
            if el.get('Self') in overridden:
                continue
            at = placement(el, t)
            if at is None or not (mp['x'] - 1 <= at['cx'] <= mp['x'] + mp['w'] + 1):
                continue
            items.append((el, mul(to_page, t)))
        return items

    # one frame → one layer ------------------------------------------------------------
    def font(self, family):
        key = family_key(family)
        if key in self.font_files:
            self.used_fonts.setdefault(key, 'font-' + uid()[:12])
            return self.used_fonts[key]
        if family:
            self.missing_fonts.add(family)
        return 'Arial'

    def layer(self, el, t, spread_origin):
        at = placement(el, t)
        if at is None or at['w'] < .5 and at['h'] < .5:
            return None
        w, h = at['w'] * PT, at['h'] * PT
        cx, cy = (at['cx'] - spread_origin[0]) * PT, (at['cy'] - spread_origin[1]) * PT
        base = {'id': uid(), 'box': {'x': round(cx - w / 2, 2), 'y': round(cy - h / 2, 2), 'w': round(max(w, .1), 2), 'h': round(max(h, .1), 2)},
                'opacity': 100, 'angle': at['angle'], 'name': el.get('Name') if el.get('Name') and not el.get('Name').startswith('<') and el.get('Name') != '$ID/' else ''}
        opacity = el.find('.//TransparencySetting/BlendingSetting')
        if opacity is not None and opacity.get('Opacity'):
            base['opacity'] = round(float(opacity.get('Opacity')))
        if el.find('.//DropShadowSetting[@Mode="Drop"]') is not None or el.find('.//FeatherSetting[@Mode="Standard"]') is not None:
            self.effects = True
        stroke_weight = float(el.get('StrokeWeight') or 0)
        stroke = self.swatches.color(el.get('StrokeColor'), el.get('StrokeTint'))
        if stroke and stroke_weight > 0:
            base.update(strokeOn=True, stroke=stroke, strokeWidth=round(min(stroke_weight * PT, 10), 2))
        if el.get('CornerOption') in ('RoundedCorner', 'InverseRoundedCorner') and el.get('CornerRadius'):
            base['radius'] = round(min(float(el.get('CornerRadius')) * PT, 100), 2)
        if el.tag == 'TextFrame':
            return self.text_layer(el, base)
        graphic = next((c for c in el.iter() if c.tag in GRAPHIC_TAGS), None)
        if graphic is not None:
            link = graphic.find('Link')
            uri = unquote(link.get('LinkResourceURI', '')) if link is not None else ''
            return {**base, 'type': 'photo', 'cropX': 50, 'cropY': 50, 'link': uri, 'name': base['name'] or uri.rsplit('/', 1)[-1]}
        fill = self.swatches.color(el.get('FillColor'), el.get('FillTint'))
        if el.tag == 'GraphicLine':
            return {**base, 'type': 'line', 'fill': stroke or '#000000'} if stroke else None
        if el.get('ContentType') == 'GraphicType' and not fill:
            return {**base, 'type': 'photo', 'cropX': 50, 'cropY': 50, 'link': ''}
        if not fill and not base.get('strokeOn'):
            return None
        return {**base, 'type': 'ellipse' if el.tag == 'Oval' else 'rect', 'fill': fill or '#ffffff', **({} if fill else {'opacity': base['opacity']})}

    def text_layer(self, el, base):
        if el.get('PreviousTextFrame') not in (None, 'n'):
            return None
        text, runs = self.stories.get(el.get('ParentStory'), ('', []))
        if not text.strip():
            return None
        weight = Counter()
        for chunk, attrs in runs:
            weight[tuple(sorted(attrs.items()))] += len(chunk.strip())
        attrs = dict(weight.most_common(1)[0][0]) if weight else {}
        if len(weight) > 1:
            self.notes.append(('info', 'mixed'))
        size = float(attrs.get('PointSize') or 12)
        style = (attrs.get('FontStyle') or 'Regular').lower()
        leading = attrs.get('Leading')
        prefs = el.find('TextFramePreference')
        valign = {'CenterAlign': 'middle', 'BottomAlign': 'bottom'}.get(prefs.get('VerticalJustification') if prefs is not None else '', 'top')
        align = attrs.get('Justification') or 'LeftAlign'
        text_case = 'upper' if attrs.get('Capitalization') == 'AllCaps' else ''
        layer = {**base, 'type': 'text', 'text': text[:2000], 'font': self.font(attrs.get('AppliedFont', '')),
                 'fontSize': round(min(max(size, 4), 120), 2), 'color': self.swatches.color(attrs.get('FillColor', 'Color/Black'), attrs.get('FillTint')) or '#000000',
                 'align': 'center' if 'Center' in align else 'right' if 'Right' in align and 'Justified' not in align else 'justify' if 'Justified' in align else 'left',
                 'valign': valign, 'bold': any(w in style for w in ('bold', 'black', 'heavy', 'semibold')),
                 'italic': 'italic' in style or 'oblique' in style, 'underline': attrs.get('Underline') == 'true', 'strike': attrs.get('StrikeThru') == 'true',
                 'lineHeight': round(min(max(float(leading) / size, .8), 3), 3) if leading else 1.2,
                 'letterSpacing': round(min(max(float(attrs.get('Tracking') or 0) / 10, -20), 80), 1)}
        if text_case:
            layer['textCase'] = text_case
        if attrs.get('Skew') and abs(float(attrs['Skew'])) >= .5:
            layer['skew'] = round(min(max(float(attrs['Skew']), -30), 30), 1)
        layer.pop('strokeOn', None); layer.pop('stroke', None); layer.pop('strokeWidth', None); layer.pop('radius', None)
        layer['font_family'] = attrs.get('AppliedFont', '')
        return layer


# --- page model ---------------------------------------------------------------------------

def photo_kind(layer):
    link = (layer.get('link') or '').lower()
    if 'учител' in link or 'педагог' in link or 'teacher' in link:
        return 'teacher'
    if 'портрет' in link or 'portrait' in link:
        return 'portrait'
    return 'general'


def area(layer):
    return layer['box']['w'] * layer['box']['h']


def clean(layers, page_w, page_h, bleed):
    """Drop frames hidden under an opaque frame above them; a full-page fill at the bottom becomes the background."""
    kept = []
    for i, layer in enumerate(layers):
        hidden = any(covers(top, layer) for top in layers[i + 1:]
                     if top['type'] in ('photo', 'rect') and top.get('opacity', 100) == 100 and not top.get('angle')
                     and (top['type'] == 'photo' or top.get('fill')))
        if not hidden:
            kept.append(layer)
    background = '#ffffff'
    edge = {'box': {'x': .5, 'y': .5, 'w': page_w - 1, 'h': page_h - 1}}
    while kept and kept[0]['type'] == 'rect' and not kept[0].get('strokeOn') and kept[0].get('opacity', 100) == 100 and covers(kept[0], edge):
        background = kept.pop(0)['fill']
    return kept, background


def signature(layers, kinds=('photo', 'text')):
    # photos by their frame, texts by where they start: a longer quote does not make another layout
    return tuple(sorted((l['type'], round(l['box']['x'] / 3), round(l['box']['y'] / 3)) + ((round(l['box']['w'] / 3), round(l['box']['h'] / 3)) if l['type'] == 'photo' else ())
                        for l in layers if l['type'] in kinds))


def portrait_page(layers, page_w, page_h):
    """A page built around one large portrait with texts: the personal or lead page."""
    portraits = [l for l in layers if l['type'] == 'photo' and photo_kind(l) in ('portrait', 'teacher') and area(l) > .3 * page_w * page_h]
    return portraits[0] if len(portraits) == 1 and any(l['type'] == 'text' for l in layers) else None


def card_grid(layers):
    """Equal photo cards with texts under/over them: a vignette page."""
    photos = [l for l in layers if l['type'] == 'photo' and not l.get('angle')]
    groups = Counter((round(l['box']['w']), round(l['box']['h'])) for l in photos)
    if not groups:
        return None
    (w, h), count = groups.most_common(1)[0]
    if count < 4:
        return None
    cards = [l for l in photos if (round(l['box']['w']), round(l['box']['h'])) == (w, h)]
    kinds = Counter(photo_kind(l) for l in cards)
    texts = [l for l in layers if l['type'] == 'text']
    def nearest(card, pool, under):
        # the closest text right under (or over) the photo that shares its column
        b, best = card['box'], None
        for t in pool:
            tb = t['box']
            overlap = min(b['x'] + b['w'], tb['x'] + tb['w']) - max(b['x'], tb['x'])
            gap = tb['y'] - (b['y'] + b['h']) if under else b['y'] - (tb['y'] + tb['h'])
            if overlap >= .5 * min(b['w'], tb['w']) and -.5 <= gap <= 8 and (best is None or gap < best[0]):
                best = (gap, t)
        return best[1] if best else None
    below = [(card, t) for card in cards if (t := nearest(card, texts, True))]
    names = {id(t) for _, t in below}
    above = [(card, t) for card in cards if (t := nearest(card, [x for x in texts if id(x) not in names], False))]
    if len(below) < count * .6:
        return None
    return {'cards': cards, 'below': below, 'above': above, 'source': 'teachers' if kinds['teacher'] >= kinds['portrait'] else 'students'}


class Draft:
    def __init__(self, reader: Reader):
        self.r = reader
        self.report: list[dict] = []
        self.chips = Counter()
        self.personal = []

    def note(self, level, text):
        self.report.append({'level': level, 'text': text})

    def read_spreads(self):
        r = self.r
        W, H = r.page_w, r.page_h
        spreads = []
        for index, spread in enumerate(r.spreads):
            pages = r.pages_of(spread)
            if not pages:
                continue
            if len(pages) == 1:
                side = 1 if pages[0]['x'] >= -1 or index == 0 else 0
                pages[0]['side'] = side
                x0 = pages[0]['x'] - side * W / PT
            else:
                for i, p in enumerate(pages[:2]):
                    p['side'] = i
                x0 = pages[0]['x']
            # parent page items first (below the spread's own frames); each page takes its side of the parent spread
            items = []
            for p in pages:
                items += r.master_items(p, 0)
            items += r.frames(spread, [1, 0, 0, 1, 0, 0], [])
            y0 = pages[0]['y']
            sides = [[], []]
            for el, t in items:
                layer = r.layer(el, t, (x0, y0))
                if layer is None:
                    continue
                b = layer['box']
                cx = b['x'] + b['w'] / 2
                side = 0 if cx < W else 1
                b['x'] = round(b['x'] - side * W, 2)
                x, y, x1, y1 = bounds(layer)
                if x1 < -side * W - r.bleed or x > (2 - side) * W + r.bleed or y1 < -r.bleed or y > H + r.bleed:
                    continue
                sides[side].append(layer)
            pages_out = []
            for side in (0, 1):
                layers, background = clean(sides[side], W, H, r.bleed)
                pages_out.append({'layers': layers, 'background': background})
            spreads.append(pages_out)
        return spreads

    # classification --------------------------------------------------------------------
    def classify(self, spreads):
        W, H = self.r.page_w, self.r.page_h
        kinds = []
        for pages in spreads:
            grid = [card_grid(p['layers']) for p in pages]
            portrait = [portrait_page(p['layers'], W, H) for p in pages]
            if any(grid):
                kinds.append(('list', grid, portrait))
            elif any(p is not None and photo_kind(p) == 'portrait' for p in portrait):
                kinds.append(('personal', grid, portrait))
            else:
                kinds.append(('fixed', grid, portrait))
        return kinds

    def build(self):
        r = self.r
        W = r.page_w
        spreads = self.read_spreads()
        kinds = self.classify(spreads)
        book = len(spreads) > 1 and not spreads[0][0]['layers'] and not spreads[-1][1]['layers']
        sections, run = [], []

        def flush():
            if run:
                sections.append(self.fixed_block(run, len([s for s in sections if s['kind'] == 'fixed'])))
                run.clear()

        i = 0
        personal_parts = []
        while i < len(spreads):
            kind = kinds[i][0]
            if kind == 'fixed':
                run.append(spreads[i]); i += 1
                continue
            flush()
            j = i
            while j < len(spreads) and kinds[j][0] == kind:
                j += 1
            if kind == 'list':
                for k in range(i, j):
                    sections.append(self.list_block(spreads[k], kinds[k]))
            else:
                part = self.personal_block(spreads[i:j], kinds[i:j])
                personal_parts.append((part, j - i))
                sections.append(part)
            i = j
        flush()
        # interrupted personal spreads: one block split into parts that continue each other
        template = personal_parts[0][0] if personal_parts else None
        for (part, count), (following, _) in zip(personal_parts, personal_parts[1:]):
            part['limit'] = count
            following['continues'] = part['id']
            following['spreads'] = [self.copy_spread(s) for s in template['spreads']]
            following['name'] = template['name'] + ' (продолжение)'
        if self.personal:
            total = sum(n for n, *_ in self.personal)
            low = min(l for n, l, _, _ in self.personal if n)
            high = max(h for n, _, h, _ in self.personal if n)
            other = sum(o for *_, o in self.personal)
            parts = f' в {len(personal_parts)} частях' if len(personal_parts) > 1 else ''
            self.note('info', f'Личные развороты ({total}) — один блок{parts}, вторая страница — гибкий коллаж на {low}–{high} фото.')
            if other:
                self.note('warning', f'{other} личных разворота с другой вёрсткой (например, без цитаты) сведены к основной.')

        fonts = [{'id': fid, 'name': r.font_files[key]['name'], 'dataUrl': r.font_files[key]['dataUrl']} for key, fid in r.used_fonts.items()]
        styles = self.text_styles(sections)
        document = {'schemaVersion': 1, 'rulesVersion': 2, 'layout': 'book' if book else 'spreads', 'name': r.name,
                    'pageSize': [W, r.page_h],
                    'safety': {'safe': min(r.margin, round(min(W, r.page_h) / 2 - r.bleed - 1, 1)), 'bleed': r.bleed, 'spine': 0, 'gap': 0,
                               'book': {'safe': 3, 'bleed': 7.5, 'outer': 3, 'spine': 10}},
                    'fonts': fonts[:12], 'textStyles': styles,
                    'sections': [self.cover(W, r.page_h)] + sections}
        for section in sections:
            for spread in section['spreads']:
                for page in spread['pages']:
                    for layer in page['layers']:
                        layer.pop('link', None)
                        layer.pop('font_family', None)
                        if not layer.get('name'):
                            layer.pop('name', None)
                        if layer['type'] == 'photo':
                            layer['name'] = layer.get('name') or 'Фото'
                        if not layer.get('angle'):
                            layer.pop('angle', None)
        self.summary_notes(sections, book)
        return document

    # blocks --------------------------------------------------------------------------------
    def cover(self, w, h):
        return {'id': uid(), 'name': 'Обложка', 'cover': True, 'kind': 'fixed', 'pageSize': [min(w + 6, 500), min(h + 6, 500)],
                'safety': {'safe': 8, 'bleed': 3, 'spine': 8, 'gap': 2}, 'spreads': [self.spread([], [])]}

    def spread(self, left, right, backgrounds=('#ffffff', '#ffffff'), role=None):
        out = {'id': uid(), 'pages': [{'id': uid(), 'background': backgrounds[0], 'layers': left}, {'id': uid(), 'background': backgrounds[1], 'layers': right}]}
        if role:
            out['role'] = role
        return out

    def copy_spread(self, spread):
        import copy
        clone = copy.deepcopy(spread)
        def fresh(obj):
            if isinstance(obj, dict):
                if 'id' in obj:
                    obj['id'] = uid()
                for v in obj.values():
                    fresh(v)
            elif isinstance(obj, list):
                for v in obj:
                    fresh(v)
        fresh(clone)
        return clone

    def general_photo(self, layer, personal=False):
        layer.update(source='class', pick={'category': 'any', **({'who': 'hero'} if personal else {})})
        return layer

    def fixed_block(self, run, index):
        names = ('Начало', 'Общие развороты')
        spreads = []
        for pages in run:
            texts = [l for p in pages for l in p['layers'] if l['type'] == 'text']
            has_date = False
            for t in texts:
                t['text'], found = pattern_chips(t['text'], t.get('textCase', ''))
                self.chips.update(found)
                has_date = has_date or 'дата съёмки' in found
            if has_date:
                others = [t for t in texts if '{{' not in t['text']]
                if others:
                    title = max(others, key=lambda t: t['fontSize'])
                    title['text'] = '{{shoot.title' + case_mod(title['text'], title.get('textCase', '')) + '}}'
                    self.chips.update(['название съёмки'])
            for p in pages:
                for l in p['layers']:
                    if l['type'] == 'photo':
                        kind = photo_kind(l)
                        if kind == 'portrait':
                            l['source'] = 'owner'
                        elif kind == 'teacher':
                            l['source'] = 'lead'
                        else:
                            self.general_photo(l)
            spreads.append(self.spread(pages[0]['layers'], pages[1]['layers'], (pages[0]['background'], pages[1]['background'])))
        name = names[0] if index == 0 else names[1] + ('' if index == 1 else f' {index}')
        return {'id': uid(), 'name': name, 'kind': 'fixed', 'spreads': spreads}

    def list_block(self, pages, kind):
        _, grids, portraits = kind
        side = 0 if grids[0] else 1
        g = grids[side]
        page = pages[side]
        cards = g['cards']
        below = {id(c): t for c, t in g['below']}
        above = {id(c): t for c, t in g['above']}
        xs = sorted({round(c['box']['x'], 1) for c in cards})
        pw = cards[0]['box']['w']
        gaps = [b - a - pw for a, b in zip(xs, xs[1:]) if b - a - pw > 0]
        names = [below[id(c)] for c in cards if id(c) in below]
        details = [above[id(c)] for c in cards if id(c) in above]
        area_items = cards + names + details
        x0 = min(l['box']['x'] for l in area_items); y0 = min(l['box']['y'] for l in area_items)
        x1 = max(l['box']['x'] + l['box']['w'] for l in area_items); y1 = max(l['box']['y'] + l['box']['h'] for l in area_items)
        name_style = names[0]
        rows = len({round(c['box']['y']) for c in cards})
        cols = max(Counter(round(c['box']['y']) for c in cards).values())
        grid = {'id': uid(), 'type': 'grid', 'name': 'Виньетки учителей' if g['source'] == 'teachers' else 'Виньетки учеников',
                'box': {'x': round(max(x0, 0), 2), 'y': round(max(y0, 0), 2), 'w': round(min(x1, self.r.page_w) - max(x0, 0), 2), 'h': round(min(y1, self.r.page_h) - max(y0, 0), 2)},
                'source': g['source'], 'gap': round(min(gaps) if gaps else 5, 1), 'minPhotoWidth': round(max(5, pw * .6), 1), 'photoWidth': round(min(pw, 180), 1),
                'photoNameGap': round(min(max(names[0]['box']['y'] - (cards[0]['box']['y'] + cards[0]['box']['h']), 0), 20), 1) if names else 3,
                'nameDetailGap': 2, 'font': name_style['font'], 'fontSize': name_style['fontSize'], 'minFontSize': round(max(4, name_style['fontSize'] * .75), 1),
                'color': name_style['color'], 'align': 'center', 'lineHeight': name_style['lineHeight'], 'letterSpacing': name_style['letterSpacing'],
                'bold': name_style['bold'], 'italic': name_style['italic'], 'styleGroup': g['source'], 'opacity': 100}
        if name_style.get('skew'):
            grid['skew'] = name_style['skew']
        if details:
            d = details[0]
            grid.update(showDetail=True, detailFont=d['font'], detailFontSize=d['fontSize'], detailColor=d['color'], detailBold=d['bold'],
                        detailItalic=d['italic'], detailLineHeight=d['lineHeight'], detailLetterSpacing=d['letterSpacing'], detailAt='above')
        ratio = pw / cards[0]['box']['h'] if cards[0]['box']['h'] else .75
        near = min(PHOTO_RATIOS, key=lambda r: abs(r - ratio))
        if abs(near - ratio) / near < .03 and near != .75:
            grid['photoRatio'] = near
        used = {id(l) for l in area_items}
        rest = [l for l in page['layers'] if id(l) not in used]
        for l in rest:
            if l['type'] == 'text':
                l['text'], found = pattern_chips(l['text'], l.get('textCase', ''))
                self.chips.update(found)
            if l['type'] == 'photo':
                self.general_photo(l)
        grid_page = rest + [grid]
        other = pages[1 - side]
        lead = portraits[1 - side]
        other_layers = other['layers']
        if lead is not None and g['source'] == 'teachers':
            other_layers = self.lead_page(other_layers, lead)
        else:
            for l in other_layers:
                if l['type'] == 'photo':
                    self.general_photo(l)
        repeat_grid = self.copy_spread({'x': [grid]})['x'][0]
        pages_out = (other_layers, grid_page) if side == 1 else (grid_page, other_layers)
        backgrounds = (pages[0]['background'], pages[1]['background'])
        intro = self.spread(*pages_out, backgrounds, role='intro')
        repeat = self.spread([self.copy_spread({'x': [repeat_grid]})['x'][0]], [repeat_grid], (page['background'], page['background']), role='repeat')
        capacity = rows * cols
        teachers = g['source'] == 'teachers'
        self.note('info', f'{"Учителя" if teachers else "Ученики"} — автовиньетка, до {capacity} на странице.')
        return {'id': uid(), 'name': 'Наши учителя' if teachers else 'Наш класс', 'kind': 'flow', 'target': 1,
                'list': {'source': g['source'], 'min': 1, 'max': max(1, min(capacity, 100)), 'strictMin': False, 'excludeLead': teachers and lead is not None},
                'spreads': [intro, repeat]}

    def lead_page(self, layers, lead):
        lead['source'] = 'lead'
        texts = sorted((l for l in layers if l['type'] == 'text'), key=lambda l: -l['fontSize'])
        if texts:
            name = texts[0]
            name['text'] = name_chip(name['text'], 'lead', name.get('textCase', ''))
            self.chips.update(['имя руководителя'])
        for t in texts[1:]:
            m = re.match(r'(.*руководител\w*\s*,\s*)(.+)$', t['text'], re.I | re.S)
            if m:
                t['text'] = m.group(1) + '{{lead.subject' + case_mod(m.group(2), t.get('textCase', '')) + '}}'
                self.chips.update(['предмет руководителя'])
            else:
                t['text'], found = pattern_chips(t['text'], t.get('textCase', ''))
                self.chips.update(found)
                if not found and len(t['text']) > 12:
                    self.note('warning', f'Текст «{t["text"][:40]}» у руководителя оставлен как есть — проверьте.')
        for l in layers:
            if l['type'] == 'photo' and l is not lead:
                self.general_photo(l)
        return layers

    def personal_block(self, run, kinds):
        W, H = self.r.page_w, self.r.page_h
        sides = Counter(0 if k[2][0] is not None and photo_kind(k[2][0]) == 'portrait' else 1 for k in kinds)
        side = sides.most_common(1)[0][0]
        instances = [pages for pages, k in zip(run, kinds) if k[2][side] is not None]
        variants = Counter(signature(p[side]['layers']) for p in instances)
        main_sig = variants.most_common(1)[0][0]
        base = next(p for p in instances if signature(p[side]['layers']) == main_sig)
        others = len(run) - variants[main_sig]
        portrait_layers = base[side]['layers']
        portrait = portrait_page(portrait_layers, W, H)
        portrait['source'] = 'item'
        portrait['name'] = 'Портрет ученика'
        # texts that differ between students are their data: the largest is the name, the next the quote
        texts = [l for l in portrait_layers if l['type'] == 'text']
        same = [p for p in instances if signature(p[side]['layers']) == main_sig]
        def text_at(pages, layer):
            for l in pages[side]['layers']:
                if l['type'] == 'text' and abs(l['box']['x'] - layer['box']['x']) < 3 and abs(l['box']['y'] - layer['box']['y']) < 3:
                    return l['text']
            return None
        varying = [t for t in texts if len({text_at(p, t) for p in same}) > 1] if len(same) > 1 else []
        if not varying and texts:
            varying = sorted(texts, key=lambda t: -t['fontSize'])[:2]
        varying.sort(key=lambda t: -t['fontSize'])
        for n, t in enumerate(varying):
            if n == 0:
                t['text'] = name_chip(t['text'], 'item', t.get('textCase', ''))
                self.chips.update(['имя ученика'])
            elif n == 1:
                t['text'] = '{{item.quote' + ('|upper' if all(is_upper(text_at(p, t) or '') for p in same) and t.get('textCase') != 'upper' else '') + '}}'
                self.chips.update(['цитата ученика'])
        for t in texts:
            if t not in varying:
                t['text'], found = pattern_chips(t['text'], t.get('textCase', ''))
                self.chips.update(found)
        for l in portrait_layers:
            if l['type'] == 'photo' and l is not portrait:
                self.general_photo(l, personal=True)
        # the other page: its photos become one flexible collage over their area
        counts, boxes = [], []
        for pages in run:
            photos = [l for l in pages[1 - side]['layers'] if l['type'] == 'photo']
            if photos:
                counts.append(len(photos))
                boxes += [bounds(l) for l in photos]
        base_other = base[1 - side]
        non_photo = [l for l in base_other['layers'] if l['type'] != 'photo']
        for t in non_photo:
            if t['type'] == 'text':
                t['text'], found = pattern_chips(t['text'], t.get('textCase', ''))
                self.chips.update(found)
        other_layers = non_photo
        if counts:
            x0 = max(min(b[0] for b in boxes), -self.r.bleed); y0 = max(min(b[1] for b in boxes), -self.r.bleed)
            x1 = min(max(b[2] for b in boxes), W + self.r.bleed); y1 = min(max(b[3] for b in boxes), H + self.r.bleed)
            gap = self.typical_gap(run, 1 - side)
            low, high = max(1, min(counts)), min(6, max(counts))
            pick = {'category': 'any', 'who': 'hero'}
            collage = {'id': uid(), 'type': 'collage', 'name': 'Гибкий коллаж', 'box': {'x': round(x0, 2), 'y': round(y0, 2), 'w': round(x1 - x0, 2), 'h': round(y1 - y0, 2)},
                       'opacity': 100, 'fill': '#e6e1ea', 'gapX': gap, 'gapY': gap, 'gapLinked': True, 'flex': {'min': low, 'max': max(low, high)}, 'pick': pick,
                       'rows': [[{'id': uid(), 'source': 'class', 'pick': dict(pick), 'cropX': 50, 'cropY': 50}]]}
            other_layers = non_photo + [collage]
            self.personal.append((len(run), low, max(low, high), 0))
        if others:
            self.personal.append((0, 0, 0, others))
        pages_out = (portrait_layers, other_layers) if side == 0 else (other_layers, portrait_layers)
        backgrounds = (base[0]['background'], base[1]['background'])
        return {'id': uid(), 'name': 'Личные развороты', 'kind': 'repeat', 'people': 'all',
                'spreads': [self.spread(*pages_out, backgrounds)]}

    def typical_gap(self, run, side):
        gaps = []
        for pages in run:
            photos = sorted((bounds(l) for l in pages[side]['layers'] if l['type'] == 'photo'))
            for a in photos:
                for b in photos:
                    if a is b:
                        continue
                    if b[0] >= a[2] and min(a[3], b[3]) > max(a[1], b[1]):
                        gaps.append(b[0] - a[2])
                    if b[1] >= a[3] and min(a[2], b[2]) > max(a[0], b[0]):
                        gaps.append(b[1] - a[3])
        gaps = [g for g in gaps if 0 <= g <= 40]
        return round(min(Counter(round(g) for g in gaps).most_common(1)[0][0], 40), 1) if gaps else 4

    # text styles: identical looks share one style ------------------------------------------------
    def text_styles(self, sections):
        keys = ('font', 'fontSize', 'color', 'align', 'bold', 'italic', 'underline', 'strike', 'lineHeight', 'letterSpacing')
        groups: dict[tuple, list] = {}
        for section in sections:
            for spread in section['spreads']:
                for page in spread['pages']:
                    for l in page['layers']:
                        if l['type'] == 'text':
                            look = tuple(l.get(k) for k in keys) + (l.get('skew', 0), l.get('textCase', ''))
                            groups.setdefault(look, []).append(l)
        styles, taken = [], Counter()
        for look, layers in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            if len(styles) >= 50:
                break
            role = self.role(layers)
            taken[role] += 1
            name = role if taken[role] == 1 else f'{role} {taken[role]}'
            style = {'id': 'style-' + uid()[:12], 'name': name, **dict(zip(keys, look[:len(keys)]))}
            if look[-2]:
                style['skew'] = look[-2]
            if look[-1]:
                style['textCase'] = look[-1]
            styles.append(style)
            for l in layers:
                l['styleId'] = style['id']
        return styles

    @staticmethod
    def role(layers):
        text = ' '.join(l['text'] for l in layers)
        for chip, name in (('.name', 'Имя'), ('quote', 'Цитата'), ('shoot.title', 'Заголовок'), ('shoot.date', 'Дата'),
                           ('school', 'Строка школы'), ('subject', 'Должность')):
            if chip in text:
                return name
        return 'Текст'

    def summary_notes(self, sections, book):
        r = self.r
        if r.missing_fonts:
            self.note('warning', 'Нет файлов шрифтов: ' + ', '.join(sorted(r.missing_fonts)) + ' — пока Arial. Добавьте файлы TTF/OTF.')
        if r.swatches.unsupported:
            self.note('info', 'Цвета: ' + ', '.join(sorted(r.swatches.unsupported)) + '.')
        if r.effects:
            self.note('info', 'Тени и растушёвка из InDesign не переносятся.')
        for level, text in r.notes:
            if level == 'warning':
                self.note(level, text)
        if self.chips:
            self.note('info', 'Чипы: ' + ', '.join(sorted(self.chips)) + '.')
        if book:
            self.note('info', 'Вёрстка «как книга».')
        self.note('info', 'Источники фото угаданы по папкам — проверьте.')


def import_idml(data: bytes, fonts: list[dict] | None = None):
    """IDML bytes (+ optional TTF/OTF data URLs) → (master document, report)."""
    reader = Reader(data, fonts)
    draft = Draft(reader)
    document = draft.build()
    summary = {'spreads': len(reader.spreads), 'blocks': len(document['sections']) - 1,
               'page_size': document['pageSize'], 'fonts': len(document['fonts'])}
    return document, {'summary': summary, 'items': draft.report}
