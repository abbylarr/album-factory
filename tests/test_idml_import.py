"""InDesign import: a small synthetic IDML with a shoot spread, personal spreads and a teachers spread."""
import base64
import io
import unittest
import zipfile

from album_factory.idml_import import ImportError_, font_names, import_idml
from album_factory.master_templates import validate
import test_server_v2

MM = 72 / 25.4
W, H = 200 * MM, 280 * MM  # page size in points
NS = 'xmlns:idPkg="http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging"'


def frame(tag, key, x, y, w, h, inner='', **attrs):
    """A frame in spread coordinates (mm): the spine is x=0, the top edge y=0."""
    x, y, w, h = (v * MM for v in (x, y, w, h))
    extra = ''.join(f' {k}="{v}"' for k, v in attrs.items())
    points = ''.join(f'<PathPointType Anchor="{px} {py}"/>' for px, py in ((x, y), (x, y + h), (x + w, y + h), (x + w, y)))
    return (f'<{tag} Self="{key}" ItemTransform="1 0 0 1 0 0"{extra}><Properties><PathGeometry><GeometryPathType><PathPointArray>'
            f'{points}</PathPointArray></GeometryPathType></PathGeometry></Properties>{inner}</{tag}>')


def photo(key, x, y, w, h, link):
    return frame('Rectangle', key, x, y, w, h, f'<Image Self="{key}i"><Link Self="{key}l" LinkResourceURI="file:/Volumes/Work/{link}"/></Image>',
                 ContentType='GraphicType')


def text(key, x, y, w, h):
    return frame('TextFrame', key, x, y, w, h, ParentStory='s' + key, PreviousTextFrame='n')


def story(key, value, size=12, font='Open Sans', style='Regular', **attrs):
    extra = ''.join(f' {k}="{v}"' for k, v in attrs.items())
    return (f'<idPkg:Story {NS}><Story Self="s{key}"><ParagraphStyleRange AppliedParagraphStyle="ParagraphStyle/$ID/NormalParagraphStyle">'
            f'<CharacterStyleRange PointSize="{size}" FontStyle="{style}"{extra}><Properties><AppliedFont type="string">{font}</AppliedFont></Properties>'
            f'<Content>{value}</Content></CharacterStyleRange></ParagraphStyleRange></Story></idPkg:Story>')


def page(key, side, master='n'):
    x = -W if side == 0 else 0
    return f'<Page Self="{key}" AppliedMaster="{master}" GeometricBounds="0 0 {H} {W}" ItemTransform="1 0 0 1 {x} 0"/>'


def build_idml():
    stories, spreads = {}, []
    def spread(key, items):
        spreads.append((key, f'<idPkg:Spread {NS}><Spread Self="{key}" ItemTransform="1 0 0 1 0 0">{page(key + "a", 0)}{page(key + "b", 1)}{"".join(items)}</Spread></idPkg:Spread>'))
    # a shoot spread: full-bleed photo, a title and its date
    stories['t1'] = story('t1', 'НИКОЛЬСКАЯ СОПКА', 40, 'Bebas Neue', 'Bold', Skew='13')
    stories['d1'] = story('d1', '27.09.2020', 10)
    spread('g1', [photo('g1p', -200, 0, 200, 280, 'Школа/Сопка/DSC1.jpg'), text('t1', -185, 15, 120, 30), text('d1', -185, 50, 60, 6),
                  photo('g1q', 15, 15, 170, 250, 'Школа/Сопка/DSC2.jpg')])
    # personal spreads: the same portrait page, other names and quotes, 2–3 photos on the right
    people = [('Старовойтов Макар', 'Умные мысли'), ('Иванова Анна', 'Живи ярко'), ('Петров Илья', 'Вперёд')]
    for n, (name, quote) in enumerate(people):
        stories[f'n{n}'] = story(f'n{n}', name, 60, 'Bebas Neue', 'Bold', FillColor='Color/Paper', Skew='13')
        stories[f'q{n}'] = story(f'q{n}', quote, 12, Capitalization='AllCaps')
        stories[f'l{n}'] = story(f'l{n}', '46 ЛИЦЕЙ / 9А класс / ВЫПУСК 2021', 8)
        right = [photo(f'r{n}a', 15, 15, 170, 120, 'Школа/Океан/A.jpg'), photo(f'r{n}b', 15, 145, 80, 120, 'Школа/Океан/B.jpg')]
        if n:
            right.append(photo(f'r{n}c', 105, 145, 80, 120, 'Школа/Океан/C.jpg'))
        spread(f'p{n}', [frame('Rectangle', f'w{n}', -200, 0, 200, 280, FillColor='Color/Paper', StrokeWeight='0'),
                         photo(f'pp{n}', -185, 15, 170, 230, f'Школа/Портреты/Экспорт/P{n}.jpg'),
                         text(f'n{n}', -182, 200, 110, 40), text(f'q{n}', -182, 250, 90, 12), text(f'l{n}', -198, 150, 100, 4)] + right)
    # teachers: the lead on the left, cards with names under and subjects over the photos on the right
    stories['lead'] = story('lead', 'Нестеренко Екатерина Владимировна', 40)
    stories['role'] = story('role', 'Классный руководитель, русский язык', 12)
    items = [photo('lp', -185, 15, 170, 250, 'Школа/Учителя/Экспорт/L.jpg'), text('lead', -180, 30, 150, 30), text('role', -180, 20, 100, 6)]
    for i in range(6):
        x, y = 15 + (i % 3) * 62, 30 + (i // 3) * 95
        stories[f'tn{i}'] = story(f'tn{i}', f'Учитель {i} Иванович', 12)
        stories[f'ts{i}'] = story(f'ts{i}', 'Физика', 9)
        items += [photo(f'tp{i}', x, y, 54, 66, f'Школа/Учителя/Экспорт/T{i}.jpg'), text(f'tn{i}', x, y + 68, 54, 10), text(f'ts{i}', x, y - 6, 54, 5)]
    spread('tt', items)
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as z:
        z.writestr('designmap.xml', f'<Document {NS} Name="Тест.indd">' + ''.join(f'<idPkg:Spread src="Spreads/{k}.xml"/>' for k, _ in spreads) + '</Document>')
        z.writestr('Resources/Preferences.xml', f'<idPkg:Preferences {NS}><DocumentPreference PageWidth="{W}" PageHeight="{H}" FacingPages="true" '
                   f'DocumentBleedTopOffset="{3 * MM}" DocumentBleedBottomOffset="{3 * MM}" DocumentBleedOutsideOrRightOffset="{3 * MM}"/>'
                   f'<MarginPreference Top="{15 * MM}" Bottom="{15 * MM}" Left="{15 * MM}" Right="{15 * MM}"/></idPkg:Preferences>')
        z.writestr('Resources/Graphic.xml', f'<idPkg:Graphic {NS}><Color Self="Color/Black" Space="CMYK" ColorValue="0 0 0 100"/></idPkg:Graphic>')
        z.writestr('Resources/Styles.xml', f'<idPkg:Styles {NS}><RootParagraphStyleGroup><ParagraphStyle Self="ParagraphStyle/$ID/NormalParagraphStyle" PointSize="12"/></RootParagraphStyleGroup></idPkg:Styles>')
        for key, xml in spreads:
            z.writestr(f'Spreads/{key}.xml', xml)
        for key, xml in stories.items():
            z.writestr(f'Stories/Story_{key}.xml', xml)
    return data.getvalue()


def layers(section):
    return [l for spread in section['spreads'] for page in spread['pages'] for l in page['layers']]


class IdmlImportTests(unittest.TestCase):
    def setUp(self):
        self.document, self.report = import_idml(build_idml())

    def test_document_is_valid_and_keeps_the_format(self):
        validate(self.document)
        self.assertEqual(self.document['pageSize'], [200.0, 280.0])
        self.assertEqual(self.document['safety']['bleed'], 3.0)
        self.assertEqual(self.document['name'], 'Тест')
        self.assertEqual([s['kind'] for s in self.document['sections']], ['fixed', 'fixed', 'repeat', 'flow'])

    def test_shoot_spread_gets_shoot_chips(self):
        shared = self.document['sections'][1]
        texts = sorted(l['text'] for l in layers(shared) if l['type'] == 'text')
        self.assertEqual(texts, ['{{shoot.date}}', '{{shoot.title|upper}}'], 'typed in capitals')
        title = next(l for l in layers(shared) if l.get('text') == '{{shoot.title|upper}}')
        style = next(s for s in self.document['textStyles'] if s['id'] == title['styleId'])
        self.assertEqual((style['skew'], style['bold']), (13.0, True))
        self.assertTrue(all(l['source'] == 'class' for l in layers(shared) if l['type'] == 'photo'))

    def test_personal_spreads_become_one_block(self):
        personal = self.document['sections'][2]
        self.assertEqual(len(personal['spreads']), 1)
        items = layers(personal)
        texts = {l['text'] for l in items if l['type'] == 'text'}
        self.assertIn('{{item.name|last}} {{item.name|first}}', texts, 'surname first, as in the layout')
        self.assertIn('{{item.quote}}', texts)
        self.assertIn('{{school|short|upper}} / {{class|number}}{{class|letter|upper}} класс / ВЫПУСК {{year}}', texts)
        self.assertEqual([l['source'] for l in items if l['type'] == 'photo'], ['item'])
        collage = next(l for l in items if l['type'] == 'collage')
        self.assertEqual(collage['flex'], {'min': 2, 'max': 3})
        self.assertEqual(collage['pick']['who'], 'hero')
        self.assertFalse(any(l['type'] == 'rect' for l in items), 'the white cover-up became the page background')

    def test_teacher_cards_become_a_vignette_with_the_lead(self):
        teachers = self.document['sections'][3]
        self.assertEqual(teachers['list']['source'], 'teachers')
        self.assertEqual(teachers['list']['max'], 6)
        self.assertEqual([s['role'] for s in teachers['spreads']], ['intro', 'repeat'])
        intro = teachers['spreads'][0]
        grid = next(l for l in intro['pages'][1]['layers'] if l['type'] == 'grid')
        self.assertEqual((grid['photoWidth'], grid['gap'], grid['showDetail']), (54.0, 8.0, True))
        left = intro['pages'][0]['layers']
        self.assertEqual([l['source'] for l in left if l['type'] == 'photo'], ['lead'])
        self.assertIn('Классный руководитель, {{lead.subject}}', [l['text'] for l in left if l['type'] == 'text'])

    def test_report_names_missing_fonts(self):
        warnings = [i['text'] for i in self.report['items'] if i['level'] == 'warning']
        self.assertTrue(any('Bebas Neue' in w and 'Open Sans' in w for w in warnings))

    def test_not_an_idml(self):
        with self.assertRaises(ImportError_):
            import_idml(b'not a zip')

    def test_font_family_is_read_from_the_file(self):
        name = 'Test Sans'.encode('utf-16-be')
        record = (3, 1, 0x409, 1, len(name), 0)
        table = bytes.fromhex('0000') + (1).to_bytes(2, 'big') + (18).to_bytes(2, 'big') + b''.join(v.to_bytes(2, 'big') for v in record) + name
        raw = b'\x00\x01\x00\x00' + (1).to_bytes(2, 'big') + b'\x00' * 6 + b'name' + b'\x00' * 4 + (28).to_bytes(4, 'big') + len(table).to_bytes(4, 'big') + table
        self.assertEqual(font_names(raw)[0], 'Test Sans')


class IdmlEndpointTests(unittest.TestCase):
    setUp = test_server_v2.V2Tests.setUp

    def test_import_returns_a_saveable_draft(self):
        payload = {'file': 'data:application/octet-stream;base64,' + base64.b64encode(build_idml()).decode(), 'fonts': []}
        response = self.client.post('/api/master-templates/import-idml', json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        created = self.client.post('/api/designs', json={'name': 'Из InDesign', 'document': response.json()['document']})
        self.assertEqual(created.status_code, 201, created.text)
        bad = self.client.post('/api/master-templates/import-idml', json={'file': base64.b64encode(b'nope').decode()})
        self.assertEqual(bad.status_code, 422)


if __name__ == '__main__':
    unittest.main()
