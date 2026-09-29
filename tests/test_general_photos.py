"""General shoot pipeline on isolated data with a fake vision model."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from album_factory import server as s
from album_factory.test_shoot import _person
from album_factory.vision import pack

RNG = np.random.default_rng(11)
IDENTITY = {k: v / np.linalg.norm(v) for k, v in zip(('anna', 'boris', 'vera'), RNG.normal(size=(3, 128)))}


def near(key, seed):
    v = IDENTITY[key] + np.random.default_rng(seed).normal(scale=.02, size=128)
    return v / np.linalg.norm(v)


class FakeVision:
    """Each upload is named after the people on it, e.g. ``anna+boris.jpg``; ``x`` is a stranger."""
    features = {'faces': True, 'expressions': True, 'bodies': True, 'scene': False}

    def __init__(self, names):
        self.names = names

    def analyze(self, path, original=None):
        people = self.names[Path(path).stem]
        faces, bodies = [], []
        for i, key in enumerate(people):
            f, b = _person(.2 + .6 * i / max(1, len(people) - 1) if len(people) > 1 else .5, .3, .12, 1.5)
            f['px'] = 480
            f['embedding'] = pack(near(key, hash(path) % 1000 + i) if key in IDENTITY else RNG.normal(size=128) / 11.3)
            faces.append(f); bodies.append(b)
        return {'size': [6000, 4000], 'taken_at': f'2026-05-14T10:00:{len(self.names) % 50:02d}', 'faces': faces, 'bodies': bodies,
                'exposure': {'mean': .5, 'high': 0, 'low': 0}, 'sharp': 400, 'thumb': None, 'clip': None}


class GeneralPhotoTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        data = patch.object(s, 'DATA', Path(tmp.name)); data.start(); self.addCleanup(data.stop)
        worker = patch.object(s.executor, 'submit'); worker.start(); self.addCleanup(worker.stop)
        self.client = TestClient(s.app); self.client.__enter__(); self.addCleanup(self.client.__exit__, None, None, None)
        self.client.get('/v2'); self.client.headers['origin'] = 'http://testserver'
        self.order = self.client.post('/api/orders', json={'school_city':'Казань', 'school': 'Школа', 'class_name': '9 А', 'copies': 1}).json()['id']
        with s.db() as con:
            portraits = self.client.post(f'/api/orders/{self.order}/shoots', json={'kind': 'portrait', 'title': 'Портреты'}).json()['id']
            for key in IDENTITY:
                con.execute('INSERT INTO persons VALUES (?,?,?,?)', (key, self.order, key.title(), s.now()))
                con.execute('''INSERT INTO photos (id,order_id,filename,sha,status,person_id,embedding,created_at,shoot_id)
                    VALUES (?,?,?,?,?,?,?,?,?)''', ('portrait-' + key, self.order, key + '.jpg', key, 'ready', key, json.dumps(IDENTITY[key].tolist()), s.now(), portraits))
        self.shoot = self.client.post(f'/api/orders/{self.order}/shoots', json={'kind': 'general', 'title': 'День'}).json()['id']
        self.names = {}

    def upload(self, name, people, color='red'):
        buf = io.BytesIO(); Image.new('RGB', (60, 40), color).save(buf, format='JPEG')
        response = self.client.post(f'/api/orders/{self.order}/photos', params={'filename': name + '.jpg', 'shoot_id': self.shoot}, content=buf.getvalue())
        self.assertEqual(response.status_code, 201, response.text)
        self.names[response.json()['id']] = people
        return response.json()['id']

    def process(self):
        with patch.object(s, 'vision', FakeVision(self.names)):
            s.process_pending()

    def review(self):
        response = self.client.get(f'/api/orders/{self.order}/shoots/{self.shoot}/general')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_analysis_links_portrait_persons_and_feeds_the_layout(self):
        pair = self.upload('pair', ['anna', 'boris'])
        group = self.upload('group', ['anna', 'boris', 'vera', 'x'], 'blue')
        self.process()
        order = self.client.get(f'/api/orders/{self.order}').json()
        self.assertEqual({p['status'] for p in order['photos'] if p['shoot_id'] == self.shoot}, {'ready'})
        self.assertEqual(len(order['persons']), 3)  # general photos never create persons
        data = self.review()
        photos = {p['id']: p for p in data['photos']}
        self.assertEqual(photos[pair]['subjects'], ['anna', 'boris'])
        self.assertEqual(photos[pair]['bucket'], 'pair')
        self.assertEqual(photos[group]['count'], 4)
        self.assertEqual({p['id']: p['count'] for p in data['persons']}, {'anna': 2, 'boris': 2, 'vera': 1})
        self.assertEqual(len(data['clusters']), 1)  # the stranger waits for review
        with s.db() as con:
            from album_factory.general_photos import snapshot_entries
            entries = {e['id']: e for e in snapshot_entries(con, self.order)}
        self.assertEqual(entries[group]['subjects'], ['anna', 'boris', 'vera'])
        self.assertIsNotNone(entries[group]['safe_box'])

    def test_photographer_decisions_survive_reanalysis(self):
        photo = self.upload('solo', ['x'])
        self.process()
        stranger = self.review()['clusters'][0]['faces'][0]['id']
        linked = self.client.put(f'/api/orders/{self.order}/general/faces', json={'face_ids': [stranger], 'action': 'person', 'person_id': 'vera'})
        self.assertEqual(linked.status_code, 200, linked.text)
        self.assertEqual(self.review()['photos'][0]['subjects'], ['vera'])
        flags = self.client.put(f'/api/orders/{self.order}/general/flags', json={'photo_ids': [photo], 'flag': 'hero', 'value': True})
        self.assertEqual(flags.status_code, 200)
        self.assertEqual(self.client.post(f'/api/orders/{self.order}/shoots/{self.shoot}/reanalyze').json()['queued'], 1)
        self.process()
        data = self.review()
        self.assertEqual(data['photos'][0]['subjects'], ['vera'])
        self.assertTrue(data['photos'][0]['flags']['hero'])
        detail = self.client.get(f'/api/orders/{self.order}/general/{photo}').json()
        self.assertEqual(detail['faces'][0]['source'], 'manual')
        crop = self.client.get(f'/media/face/{detail["faces"][0]["id"]}/crop')
        self.assertEqual(crop.status_code, 200)
        self.assertEqual(crop.headers['content-type'], 'image/jpeg')

    def test_excluded_photos_leave_the_layout_and_errors_are_scoped(self):
        keep = self.upload('keep', ['anna'])
        drop = self.upload('drop', ['boris'], 'green')
        self.process()
        self.assertEqual(self.client.put(f'/api/orders/{self.order}/general/flags', json={'photo_ids': [drop], 'flag': 'excluded', 'value': True}).status_code, 200)
        with s.db() as con:
            from album_factory.general_photos import snapshot_entries
            self.assertEqual([e['id'] for e in snapshot_entries(con, self.order)], [keep])
        self.assertEqual(self.client.put(f'/api/orders/{self.order}/general/flags', json={'photo_ids': ['portrait-anna'], 'flag': 'hero', 'value': True}).status_code, 404)
        self.assertEqual(self.client.put(f'/api/orders/{self.order}/general/best', json={'photo_id': keep}).status_code, 409)
        twice = self.client.put(f'/api/orders/{self.order}/general/faces', json={'face_ids': [f'{keep}-0', f'{keep}-0'], 'action': 'stranger'})
        self.assertEqual(twice.status_code, 200)
        other = self.client.post('/api/orders', json={'school_city':'Казань', 'school': 'Другая', 'class_name': 'Б', 'copies': 1}).json()['id']
        self.assertEqual(self.client.get(f'/api/orders/{other}/shoots/{self.shoot}/general').status_code, 404)
        self.assertEqual(self.client.post(f'/api/orders/{self.order}/delete-photos', json={'photo_ids': [keep]}).status_code, 200)
        with s.db() as con:
            self.assertIsNone(con.execute('SELECT 1 FROM photo_faces WHERE photo_id=?', (keep,)).fetchone())

    def test_general_photos_from_before_the_analysis_are_queued_once(self):
        with s.db() as con:
            con.execute('''INSERT INTO photos (id,order_id,filename,sha,status,created_at,shoot_id) VALUES (?,?,?,?,?,?,?)''',
                        ('legacy', self.order, 'old.jpg', 'old', 'ready', s.now(), self.shoot))
        s.init_db()
        with s.db() as con:
            self.assertEqual(con.execute("SELECT status FROM photos WHERE id='legacy'").fetchone()[0], 'pending')
            self.assertEqual(con.execute("SELECT status FROM photos WHERE id='portrait-anna'").fetchone()[0], 'ready')

    def test_failed_analysis_is_retryable(self):
        photo = self.upload('broken', ['anna'])
        class Broken:
            features = {}
            def analyze(self, *args):
                raise ValueError('boom')
        with patch.object(s, 'vision', Broken()):
            s.process_pending()
        order = self.client.get(f'/api/orders/{self.order}').json()
        self.assertEqual(next(p for p in order['photos'] if p['id'] == photo)['status'], 'error')
        self.client.post(f'/api/orders/{self.order}/retry', params={'shoot_id': self.shoot})
        self.process()
        self.assertEqual(self.review()['photos'][0]['subjects'], ['anna'])


if __name__ == '__main__':
    unittest.main()
