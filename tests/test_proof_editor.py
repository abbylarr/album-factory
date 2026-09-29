"""Final layout editor: scoped edits, crop, hide, undo by override list, per-person review."""
from copy import deepcopy
import unittest

from PIL import Image

from album_factory import server as s
from album_factory.layout_workspace import measurer, wildcard
from album_factory.master_layout import generate
import test_master_templates
import test_server_v2


def snapshot(count=3):
    return {'students': [{'id': str(i), 'first_name': 'Ученик', 'last_name': str(i)} for i in range(count)],
            'teachers': [], 'order': {'class_name': '11А', 'year': '2026'},
            'photos': {f'p{i}': {'width': 1200, 'height': 1600, 'path': 'unused'} for i in range(count)},
            'selections': [{'owner': f'student:{i}', 'role': 'main_portrait', 'photo': f'p{i}'} for i in range(count)]}


def design():
    doc = test_master_templates.master()
    page = doc['sections'][1]['spreads'][0]['pages'][0]
    page['layers'] += [
        {'id': 'caption', 'type': 'text', 'box': {'x': 10, 'y': 10, 'w': 180, 'h': 20}, 'text': 'Общая подпись',
         'binding': 'static', 'font': 'Arial', 'fontSize': 14, 'color': '#333333', 'align': 'left'},
        {'id': 'me', 'type': 'photo', 'box': {'x': 10, 'y': 40, 'w': 90, 'h': 120}, 'source': 'owner'}]
    return doc


def elements(document, owner, suffix):
    return [e for spread in document['variant_spreads'][owner].values() for e in spread['elements'] if e['key'].endswith(suffix)]


class CompileTests(unittest.TestCase):
    def compile(self, overrides=()):
        return generate({'id': 'test', 'version': 1, 'master': design()}, snapshot(), measurer(), overrides)

    def test_common_elements_are_shared_and_accept_one_edit_for_all(self):
        doc = self.compile()
        caption = elements(doc, 'student:0', 'shared[student:0]:0/0/caption')[0]
        portrait = elements(doc, 'student:0', 'shared[student:0]:0/0/me')[0]
        self.assertEqual(caption['shared'], 3)
        self.assertNotIn('shared', portrait)
        card = elements(doc, 'student:0', '/card[student:1]/photo')[0]
        self.assertEqual(card['shared'], 3)
        self.assertEqual(wildcard(card['key']), card['key'].replace('students[student:0]', 'students[*]'))
        everyone = {'key': wildcard(caption['key']), 'type': 'text', 'value': 'Для всех', 'base': caption['shared_base']}
        mine = {'key': elements(doc, 'student:1', '/0/caption')[0]['key'], 'type': 'text', 'value': 'Только мне',
                'base': elements(doc, 'student:1', '/0/caption')[0]['base']}
        edited = self.compile([everyone, mine])
        self.assertEqual(elements(edited, 'student:0', '/0/caption')[0]['text'], 'Для всех')
        self.assertEqual(elements(edited, 'student:2', '/0/caption')[0]['text'], 'Для всех')
        self.assertEqual(elements(edited, 'student:1', '/0/caption')[0]['text'], 'Только мне')
        self.assertEqual(edited['overrides']['conflicts'], [])

    def test_crop_hide_and_photo_changed_conflict(self):
        doc = self.compile()
        portrait = elements(doc, 'student:0', '/0/me')[0]
        caption = elements(doc, 'student:0', '/0/caption')[0]
        crop = {'key': portrait['key'], 'type': 'crop', 'value': {'photo': 'p0', 'rect': [0.1, 0.2, 0.5, 0.5]}, 'base': portrait['base']}
        hide = {'key': caption['key'], 'type': 'hide', 'value': True, 'base': caption['base']}
        edited = self.compile([crop, hide])
        cropped = elements(edited, 'student:0', '/0/me')[0]
        self.assertEqual(cropped['crop'][:3], [120.0, 320.0, 600.0])
        self.assertAlmostEqual(cropped['crop'][2] / cropped['crop'][3], 90 / 120, places=3)
        self.assertTrue(elements(edited, 'student:0', '/0/caption')[0]['hidden'])
        self.assertFalse(elements(edited, 'student:1', '/0/caption')[0]['hidden'])
        stale = dict(crop, value={'photo': 'p1', 'rect': [0, 0, 1, 1]})
        conflicted = self.compile([stale])
        self.assertEqual(conflicted['overrides']['conflicts'][0]['type'], 'crop')
        self.assertEqual(elements(conflicted, 'student:0', '/0/me')[0]['crop'], portrait['crop'])


class ApiTests(unittest.TestCase):
    setUp = test_server_v2.V2Tests.setUp

    def make_order(self, count=3):
        draft = self.client.post('/api/master-templates', json={'document': design()}).json()
        pub = self.client.post(f'/api/master-templates/{draft["id"]}/publish', json={'revision': 1}).json()
        order = self.client.post('/api/orders', json={'school': 'Тест', 'class_name': '9Б', 'copies': 1,
                                                      'offer_id': pub['offer_id']}).json()['id']
        shoot = s.uid()
        with s.db() as con:
            con.execute('INSERT INTO shoots (id,order_id,title,kind,created_at) VALUES (?,?,?,?,?)',
                        (shoot, order, 'Портреты', 'portrait', s.now()))
            for index in range(count):
                person, photo = f'person{index}', s.uid()
                con.execute('INSERT INTO persons VALUES (?,?,?,?)', (person, order, f'Ученик {index}', f'2026-01-01T00:00:0{index}'))
                con.execute('''INSERT INTO photos (id,order_id,filename,sha,status,person_id,created_at,shoot_id)
                    VALUES (?,?,?,?,?,?,?,?)''', (photo, order, photo + '.jpg', photo, 'ready', person, s.now(), shoot))
                Image.new('RGB', (1800, 2400), '#d6d8d4').save(s.DATA / 'photos' / (photo + '.jpg'))
        created = self.client.post(f'/api/orders/{order}/layout')
        self.assertEqual(created.status_code, 200, created.text)
        return order, created.json()

    def test_scoped_edit_undo_review_and_publication_status(self):
        order, data = self.make_order()
        path = f'/api/orders/{order}/layout'
        doc = data['document']
        self.assertEqual([i for i in doc['issues'] if i['level'] == 'error'], [])
        caption = elements(doc, 'student:person0', '/0/caption')[0]
        self.assertEqual(data['status']['reviews'], {})
        reviewed = self.client.put(path + '/reviews', json={'owner': 'student:person1', 'reviewed': True})
        self.assertTrue(reviewed.json()['status']['reviews']['student:person1']['current'])
        self.assertEqual(self.client.post(path + '/publish').status_code, 200)

        refused = self.client.post(path + '/edits', json={'revision': doc['revision'], 'ops': [
            {'key': elements(doc, 'student:person0', '/0/me')[0]['key'], 'type': 'text', 'value': 'x', 'scope': 'all'}]})
        self.assertEqual(refused.status_code, 422)
        stale = self.client.post(path + '/edits', json={'revision': 'old', 'ops': [{'key': caption['key'], 'type': 'hide', 'value': True}]})
        self.assertEqual(stale.status_code, 409)

        edited = self.client.post(path + '/edits', json={'revision': doc['revision'], 'ops': [
            {'key': caption['key'], 'type': 'text', 'value': 'Выпуск 2026', 'scope': 'all'}]})
        self.assertEqual(edited.status_code, 200, edited.text)
        result = edited.json()
        self.assertEqual(len(result['overrides']), 1)
        self.assertEqual({e['text'] for owner in ('student:person0', 'student:person2')
                          for e in elements(result['document'], owner, '/0/caption')}, {'Выпуск 2026'})
        status = result['status']
        self.assertFalse(status['reviews']['student:person1']['current'])
        self.assertFalse(status['publication']['current'])
        self.assertEqual(len(status['publication']['changed']), 3)

        undone = self.client.put(path + '/overrides', json={'revision': result['document']['revision'], 'overrides': []})
        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertEqual(undone.json()['document']['revision'], doc['revision'])
        self.assertTrue(undone.json()['status']['publication']['current'])
        self.assertTrue(undone.json()['status']['reviews']['student:person1']['current'])
        published = self.client.get(path + '/publication').json()
        self.assertEqual(published['revision'], doc['revision'])

    def test_photo_replacement_crop_and_validation(self):
        order, data = self.make_order()
        path = f'/api/orders/{order}/layout'
        doc = data['document']
        frame = elements(doc, 'student:person0', '/0/me')[0]
        other = next(p['id'] for p in data['photos'] if p['person_id'] == 'person1')
        replaced = self.client.post(path + '/edits', json={'revision': doc['revision'], 'ops': [
            {'key': frame['key'], 'type': 'photo', 'value': other}]}).json()
        cropped = self.client.post(path + '/edits', json={'revision': replaced['document']['revision'], 'ops': [
            {'key': frame['key'], 'type': 'crop', 'value': {'rect': [0, 0, 0.5, 0.5]}}]})
        self.assertEqual(cropped.status_code, 200, cropped.text)
        after = elements(cropped.json()['document'], 'student:person0', '/0/me')[0]
        self.assertEqual(after['photo'], other)
        self.assertEqual(after['crop'][:2], [0, 0])
        self.assertEqual([o['type'] for o in cropped.json()['overrides']], ['photo', 'crop'])
        # A new photo drops the old crop so the stored list never carries a stale frame.
        again = self.client.post(path + '/edits', json={'revision': cropped.json()['document']['revision'], 'ops': [
            {'key': frame['key'], 'type': 'photo', 'value': frame['photo']}]}).json()
        self.assertEqual([o['type'] for o in again['overrides']], ['photo'])
        reset = self.client.post(path + '/edits', json={'revision': again['document']['revision'], 'ops': [
            {'key': frame['key'], 'type': 'reset'}]}).json()
        self.assertEqual(reset['overrides'], [])
        for bad in ({'rect': [0, 0, 2, 1]}, {'rect': [0, 0]}, None):
            response = self.client.post(path + '/edits', json={'revision': reset['document']['revision'], 'ops': [
                {'key': frame['key'], 'type': 'crop', 'value': bad}]})
            self.assertEqual(response.status_code, 422, bad)
        broken = self.client.put(path + '/overrides', json={'revision': reset['document']['revision'],
                                                            'overrides': [{'key': frame['key'], 'type': 'photo', 'value': 'nope'}]})
        self.assertEqual(broken.status_code, 422)

    def test_publication_is_blocked_by_errors(self):
        order, data = self.make_order()
        path = f'/api/orders/{order}/layout'
        caption = elements(data['document'], 'student:person0', '/0/caption')[0]
        long = self.client.post(path + '/edits', json={'revision': data['document']['revision'], 'ops': [
            {'key': caption['key'], 'type': 'text', 'value': 'Очень длинная подпись ' * 12, 'scope': 'all'}]})
        self.assertEqual(long.status_code, 200, long.text)
        self.assertTrue(any(i['level'] == 'error' for i in long.json()['document']['issues']))
        self.assertEqual(self.client.post(path + '/publish').status_code, 409)
        self.assertEqual(self.client.put(path + '/reviews', json={'owner': 'student:nobody', 'reviewed': True}).status_code, 404)


if __name__ == '__main__':
    unittest.main()
