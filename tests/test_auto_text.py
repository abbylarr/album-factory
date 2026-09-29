"""Auto text chips, the spread's shoot and faux italic."""
from copy import deepcopy
import unittest

from album_factory.layout_workspace import measurer
from album_factory.master_layout import generate
from album_factory.master_templates import _FlatMeasurer
from album_factory.test_shoot import synthetic
import test_server_v2
from test_master_rules_v2 import master, page, photo, snapshot


def text(key, value, **extra):
    return {'id': key, 'type': 'text', 'box': {'x': 10, 'y': 10, 'w': 150, 'h': 20}, 'text': value,
            'font': 'Arial', 'fontSize': 12, 'color': '#333333', 'align': 'left', **extra}


def texts(result, owner, suffix):
    return [e['text'] for s in result['variant_spreads'][owner].values() for e in s['elements'] if e['key'].endswith('/' + suffix)]


class AutoTextTests(unittest.TestCase):
    def test_chips_take_order_and_person_data(self):
        doc = master()
        doc['sections'][0]['spreads'][0]['pages'][0]['layers'] = [
            text('line', '{{school}} / {{class}} класс / выпуск {{year}}'),
            text('owner', '{{owner.name}}: {{owner.quote}}', skew=13)]
        snap = snapshot(3, 2)
        snap['order'] = {'class_name': '9А', 'year': '2021', 'school': '46 лицей', 'city': 'Томск'}
        snap['students'][0]['quote'] = 'Умные мысли преследуют меня'
        result = generate({'id': 'a', 'version': 1, 'master': doc}, snap, measurer())
        self.assertEqual(texts(result, 'student:s0', 'line'), ['46 лицей / 9А класс / выпуск 2021'])
        self.assertEqual(texts(result, 'student:s0', 'owner'), ['Ученик 0: Умные мысли преследуют меня'])
        self.assertEqual(texts(result, 'student:s1', 'owner'), ['Ученик 1: '], 'no quote prints nothing')
        element = next(e for s in result['variant_spreads']['student:s0'].values() for e in s['elements'] if e['key'].endswith('/owner'))
        self.assertEqual(element['skew'], 13)

    def test_shoot_chips_follow_the_photos_on_the_spread(self):
        people = [{'id': f's{i}', 'first_name': 'Ученик', 'last_name': str(i)} for i in range(6)]
        entries, photos = synthetic(people)
        shoots = {'test-shoot-a': {'title': 'Никольская сопка', 'date': '2020-09-27'}, 'test-shoot-b': {'title': 'Деревенька', 'date': ''}}
        doc = master()
        doc['sections'] = [{'id': 'trip', 'name': 'Съёмки', 'kind': 'fixed', 'spreads': [
            {'id': f't{i}', 'pages': [page(f'l{i}', [photo('shot', 'class', {'category': 'any'})]), page(f'r{i}', [text('title', '{{shoot.title}} {{shoot.date}}')])]}
            for i in range(2)]}]
        snap = {**snapshot(6, 0), 'students': people, 'photos': photos, 'general': entries,
                'general_photos': [e['id'] for e in entries], 'shoots': shoots}
        result = generate({'id': 's', 'version': 1, 'master': doc}, snap, _FlatMeasurer(), only_owner='s0')
        shoot_of = {e['id']: e['shoot'] for e in entries}
        for spread in result['variant_spreads']['student:s0'].values():
            placed = next(e for e in spread['elements'] if e['key'].endswith('/shot'))
            title = next(e for e in spread['elements'] if e['key'].endswith('/title'))
            shoot = shoots[shoot_of[placed['photo']]]
            expected = shoot['title'] + (' 27.09.2020' if shoot['date'] else ' ')
            self.assertEqual(title['text'], expected)


class AutoTextValidationTests(unittest.TestCase):
    setUp = test_server_v2.V2Tests.setUp

    def post(self, layer):
        doc = master()
        doc['sections'][0]['spreads'][0]['pages'][0]['layers'] = [layer]
        return self.client.post('/api/master-templates', json={'document': doc})

    def test_chips_and_skew_are_checked(self):
        self.assertEqual(self.post(text('t', '{{school}} {{shoot.title}}', skew=-12)).status_code, 201)
        self.assertEqual(self.post(text('t', 'Школа {{principal}}')).status_code, 422)
        self.assertEqual(self.post(text('t', 'x', skew=45)).status_code, 422)
        self.assertEqual(self.post(text('t', 'x', binding='static')).status_code, 422, 'the old field is gone')


class FauxItalicTests(unittest.TestCase):
    def test_every_line_leans_around_its_own_baseline(self):
        from io import BytesIO
        from reportlab.pdfgen import canvas
        pdf = canvas.Canvas(BytesIO(), pageCompression=0)
        paragraph = measurer().paragraph('Старовойтов\nМакар', 'main', 16, 18, skew=13)
        paragraph.wrap(200, 1000)
        paragraph.drawOn(pdf, 10, 10)
        code = pdf.getpdfdata().decode('latin-1')
        self.assertIn('1 0 .230868 1', code)
        self.assertNotIn('T*', code, 'T* would step along the slanted axis')
        self.assertIn('4.155627 -18.000000 Td', code)


if __name__ == '__main__':
    unittest.main()
