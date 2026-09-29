"""Order pipeline stages, manual moves and deleting a whole shoot."""
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from fastapi.testclient import TestClient
from album_factory import server as s


class OrderStageTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data = patch.object(s, 'DATA', Path(tmp.name)); data.start(); self.addCleanup(data.stop)
        worker = patch.object(s.executor, 'submit'); worker.start(); self.addCleanup(worker.stop)
        self.client = TestClient(s.app)
        self.client.__enter__(); self.addCleanup(self.client.__exit__, None, None, None)
        self.client.get('/v2'); self.client.headers['origin'] = 'http://testserver'
        self.order = self.client.post('/api/orders', json={'school_city':'Казань', 'school': 'Тест', 'class_name': 'А', 'copies': 1}).json()['id']

    def stage(self):
        return self.client.get(f'/api/orders/{self.order}').json()['stage']

    def shoot(self, **extra):
        response = self.client.post(f'/api/orders/{self.order}/shoots', json={'kind': 'portrait', 'title': 'Портреты', **extra})
        self.assertEqual(response.status_code, 201)
        return response.json()['id']

    def upload(self, shoot_id, color='red'):
        buf = io.BytesIO(); Image.new('RGB', (20, 20), color).save(buf, format='JPEG')
        response = self.client.post(f'/api/orders/{self.order}/photos', params={'filename': color + '.jpg', 'shoot_id': shoot_id}, content=buf.getvalue())
        self.assertEqual(response.status_code, 201)
        return response.json()['id']

    def set_stage(self, stage):
        with s.db() as con:
            con.execute('UPDATE orders SET stage=? WHERE id=?', (stage, self.order))

    def test_new_order_moves_to_photos_on_first_upload_only(self):
        self.assertEqual(self.stage(), 'new')
        shoot = self.shoot()
        self.upload(shoot)
        self.assertEqual(self.stage(), 'photos')
        self.set_stage('layout')
        self.upload(shoot, 'blue')
        self.assertEqual(self.stage(), 'layout')

    def test_client_link_opens_forms(self):
        self.upload(self.shoot())
        self.client.post(f'/api/orders/{self.order}/client-link')
        self.assertEqual(self.stage(), 'forms')

    def test_manual_moves_only_after_print(self):
        self.assertEqual(self.client.post(f'/api/orders/{self.order}/stage', json={'stage': 'delivery'}).status_code, 409)
        self.set_stage('print')
        self.assertEqual(self.client.post(f'/api/orders/{self.order}/stage', json={'stage': 'delivery'}).status_code, 200)
        self.assertEqual(self.client.post(f'/api/orders/{self.order}/stage', json={'stage': 'archive'}).status_code, 200)
        self.assertEqual(self.stage(), 'archive')
        self.assertEqual(self.client.post(f'/api/orders/{self.order}/stage', json={'stage': 'photos'}).status_code, 409)
        self.assertEqual(self.client.post(f'/api/orders/{self.order}/stage', json={'stage': 'unknown'}).status_code, 422)

    def test_legacy_stages_are_migrated(self):
        with s.db() as con:
            con.execute("UPDATE orders SET stage='upload' WHERE id=?", (self.order,))
            con.execute("UPDATE order_terms SET workflow='client_approved' WHERE order_id=?", (self.order,))
        s.init_db()
        self.assertEqual(self.stage(), 'approval')

    def test_shoot_rename_and_date(self):
        shoot = self.shoot(shot_on='2026-09-20')
        self.assertEqual(self.client.patch(f'/api/orders/{self.order}/shoots/{shoot}', json={'title': 'Улица', 'shot_on': '2026-09-21'}).status_code, 200)
        saved = self.client.get(f'/api/orders/{self.order}').json()['shoots'][0]
        self.assertEqual((saved['title'], saved['shot_on']), ('Улица', '2026-09-21'))
        self.assertEqual(self.client.patch(f'/api/orders/{self.order}/shoots/{shoot}', json={'title': 'Улица', 'shot_on': '21.09'}).status_code, 422)

    def test_delete_shoot_removes_its_photos_only(self):
        first, second = self.shoot(), self.shoot()
        gone, kept = self.upload(first), self.upload(second, 'green')
        response = self.client.delete(f'/api/orders/{self.order}/shoots/{first}')
        self.assertEqual(response.json(), {'deleted': 1})
        order = self.client.get(f'/api/orders/{self.order}').json()
        self.assertEqual([x['id'] for x in order['shoots']], [second])
        self.assertEqual([p['id'] for p in order['photos']], [kept])
        self.assertFalse((s.DATA / 'photos' / (gone + '.original')).exists())
        self.assertTrue((s.DATA / 'photos' / (kept + '.original')).exists())
        self.assertEqual(self.client.delete(f'/api/orders/{self.order}/shoots/{first}').status_code, 404)

    def test_list_reports_approval_flag(self):
        self.assertFalse(self.client.get('/api/orders').json()[0]['approved'])

    def test_stage_time_changes_only_with_stage(self):
        first = self.client.get('/api/orders').json()[0]['stage_at']
        self.assertTrue(first)
        shoot = self.shoot()
        self.upload(shoot)
        moved = self.client.get('/api/orders').json()[0]['stage_at']
        self.assertGreater(moved, first)
        self.upload(shoot, 'blue')
        self.assertEqual(self.client.get('/api/orders').json()[0]['stage_at'], moved)


if __name__ == '__main__':
    unittest.main()
