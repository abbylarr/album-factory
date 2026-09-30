"""«Создать макет»: general shoots can be left out, and a build waits for uploads and analysis."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from album_factory import server as s


class LayoutQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for target in (patch.object(s, 'DATA', Path(self.tmp.name)), patch.object(s.executor, 'submit')):
            target.start()
            self.addCleanup(target.stop)
        self.client = TestClient(s.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.client.get('/v2')
        self.client.headers['origin'] = 'http://testserver'
        self.order = self.client.post('/api/orders', json={'school_city': 'Казань', 'school': 'Школа', 'class_name': '9 А', 'copies': 3}).json()['id']
        self.portraits = self.shoot('portrait')

    def shoot(self, kind):
        return self.client.post(f'/api/orders/{self.order}/shoots', json={'kind': kind, 'title': kind}).json()['id']

    def photo(self, shoot_id, person_id=None, status='ready'):
        photo_id = s.uid()
        with s.db() as con:
            if person_id:
                con.execute('INSERT INTO persons VALUES (?,?,?,?)', (person_id, self.order, person_id, s.now()))
            con.execute('''INSERT INTO photos (id,order_id,filename,sha,status,person_id,created_at,shoot_id)
                VALUES (?,?,?,?,?,?,?,?)''', (photo_id, self.order, photo_id + '.jpg', photo_id, status, person_id, s.now(), shoot_id))
        Image.new('RGB', (2400, 3300), '#d6d8d4').save(s.DATA / 'photos' / (photo_id + '.jpg'))
        return photo_id

    def class_portraits(self):
        for i in range(3):
            self.photo(self.portraits, f'student-{i}')

    def layout(self):
        with s.db() as con:
            row = con.execute('SELECT snapshot FROM order_layouts WHERE order_id=?', (self.order,)).fetchone()
        return json.loads(row['snapshot']) if row else None

    def order_body(self):
        return self.client.get(f'/api/orders/{self.order}').json()

    def test_switched_off_shoot_stays_out_of_the_layout(self):
        self.class_portraits()
        walk, party = self.shoot('general'), self.shoot('general')
        kept, dropped = self.photo(walk), self.photo(party)
        switched = self.client.put(f'/api/orders/{self.order}/shoots/{party}/in-layout', json={'value': False})
        self.assertEqual(switched.status_code, 200, switched.text)
        self.assertEqual({x['id']: x['in_layout'] for x in self.order_body()['shoots']}[party], 0)
        self.assertEqual(self.client.post(f'/api/orders/{self.order}/layout').status_code, 200)
        snapshot = self.layout()
        self.assertIn(kept, snapshot['general_photos'])
        self.assertNotIn(dropped, snapshot['general_photos'])
        self.assertEqual(set(snapshot['shoots']), {walk})
        portrait = self.client.put(f'/api/orders/{self.order}/shoots/{self.portraits}/in-layout', json={'value': False})
        self.assertEqual(portrait.status_code, 422)

    def test_queued_build_waits_for_analysis_of_included_shoots(self):
        self.class_portraits()
        walk, party = self.shoot('general'), self.shoot('general')
        waiting = self.photo(walk, status='pending')
        self.photo(party, status='pending')
        self.client.put(f'/api/orders/{self.order}/shoots/{party}/in-layout', json={'value': False})
        queued = self.client.post(f'/api/orders/{self.order}/layout/queue', json={})
        self.assertEqual(queued.status_code, 200, queued.text)
        self.assertFalse(queued.json()['built'])
        self.assertEqual(queued.json()['queue']['pending'], 1)
        self.assertEqual(self.order_body()['layout_queue']['pending'], 1)
        self.assertIsNone(self.layout())
        with s.db() as con:
            con.execute("UPDATE photos SET status='ready' WHERE id=?", (waiting,))
        with patch.object(s, 'process_v3_batch'), patch('album_factory.general_photos.process_batch'):
            s.process_pending()  # the shoot left out still has a pending photo; it must not hold the build
        self.assertIsNotNone(self.layout())
        self.assertIsNone(self.order_body()['layout_queue'])

    def test_build_waits_until_the_browser_finishes_uploading(self):
        self.class_portraits()
        queued = self.client.post(f'/api/orders/{self.order}/layout/queue', json={'uploading': True}).json()
        self.assertFalse(queued['built'])
        self.assertTrue(queued['queue']['uploading'])
        done = self.client.patch(f'/api/orders/{self.order}/layout/queue', json={'uploading': False}).json()
        self.assertTrue(done['built'])
        self.assertIsNone(done['queue'])
        self.assertIsNotNone(self.layout())

    def test_failed_build_keeps_the_reason_and_can_be_cancelled(self):
        self.photo(self.portraits, 'student-0')
        queued = self.client.post(f'/api/orders/{self.order}/layout/queue', json={}).json()
        self.assertFalse(queued['built'])
        self.assertIn('минимум трёх', queued['queue']['error'])
        self.assertEqual(self.client.delete(f'/api/orders/{self.order}/layout/queue').status_code, 200)
        self.assertIsNone(self.order_body()['layout_queue'])

    def test_worker_builds_as_the_studio_that_owns_the_order(self):
        from album_factory import layout_queue, mvp
        self.class_portraits()
        with s.db() as con:
            studio = con.execute('SELECT studio_id FROM order_membership WHERE order_id=?', (self.order,)).fetchone()['studio_id']
            con.execute("INSERT INTO layout_queue (order_id,uploading,queued_at) VALUES (?,0,?)", (self.order, s.now()))
        seen = []
        real = __import__('album_factory.layout_workspace', fromlist=['build_layout']).build_layout
        def build(con, server, order_id, master):
            seen.append(mvp.studio_ctx.get())
            return real(con, server, order_id, master)
        with patch('album_factory.layout_workspace.build_layout', build):
            self.assertEqual(layout_queue.run_ready(s), [self.order])  # no request: the worker thread
        self.assertEqual(seen, [studio])
        self.assertIsNone(mvp.studio_ctx.get())

    def test_deleting_the_order_drops_its_queue(self):
        self.client.post(f'/api/orders/{self.order}/layout/queue', json={'uploading': True})
        self.assertEqual(self.client.delete(f'/api/orders/{self.order}').status_code, 200)
        with s.db() as con:
            self.assertIsNone(con.execute('SELECT 1 FROM layout_queue WHERE order_id=?', (self.order,)).fetchone())


if __name__ == '__main__':
    unittest.main()
