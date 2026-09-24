"""V2 regressions use an isolated database and synthetic images only."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from PIL import Image
from album_factory import server as s


class V2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_patch = patch.object(s, 'DATA', Path(self.tmp.name))
        self.data_patch.start()
        self.addCleanup(self.data_patch.stop)
        self.worker_patch = patch.object(s.executor, 'submit')
        self.worker_patch.start()
        self.addCleanup(self.worker_patch.stop)
        self.client = TestClient(s.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.client.get('/v2')
        self.client.headers['origin'] = 'http://testserver'
        self.order = self.client.post('/api/orders', json={'school':'Тест', 'class_name':'9Б', 'copies':20}).json()['id']

    def photo(self, order=None, status='ready', uncertain=0, person='person'):
        pid = s.uid()
        order = order or self.order
        with s.db() as con:
            if person:
                con.execute('INSERT OR IGNORE INTO persons VALUES (?,?,?,?)', (person, order, 'Имя', s.now()))
            con.execute('INSERT INTO photos (id,order_id,filename,sha,status,person_id,uncertain,created_at) VALUES (?,?,?,?,?,?,?,?)', (pid,order,'a.jpg',pid,status,person,uncertain,s.now()))
        for suffix in ['.original','.jpg','.thumb.jpg']:
            Image.new('RGB',(10,10)).save(s.DATA/'photos'/(pid+suffix),format='JPEG')
        return pid

    def test_both_versions_and_session(self):
        self.assertEqual(self.client.get('/v2').status_code,200)
        old=self.client.get('/').text
        self.assertIn('/static/app.js',old)
        self.assertIn('/v2',old)
        self.assertIn('/static/v2.js',self.client.get('/v2').text)
        self.assertEqual(self.client.get('/api/orders').status_code,200)

    def test_review_counters_and_cover(self):
        photo=self.photo(uncertain=1)
        self.assertEqual(self.client.get('/api/orders').json()[0]['review_count'],1)
        self.assertEqual(self.client.put(f'/api/orders/{self.order}/cover',json={'photo_ids':[photo]}).status_code,200)
        self.assertEqual(self.client.get('/api/orders').json()[0]['cover_id'],photo)
        self.client.post(f'/api/orders/{self.order}/confirm-photos',json={'photo_ids':[photo]})
        self.assertEqual(self.client.get('/api/orders').json()[0]['review_count'],0)

    def test_delete_cleans_files_person_and_cover(self):
        photo=self.photo()
        self.client.put(f'/api/orders/{self.order}/cover',json={'photo_ids':[photo]})
        response=self.client.post(f'/api/orders/{self.order}/delete-photos',json={'photo_ids':[photo]})
        self.assertEqual(response.status_code,200)
        detail=self.client.get(f'/api/orders/{self.order}').json()
        self.assertEqual(detail['photos'],[])
        self.assertEqual(detail['persons'],[])
        self.assertIsNone(detail['cover_id'])
        self.assertEqual(list((s.DATA/'photos').iterdir()),[])

    def test_cross_order_deletion_is_atomic(self):
        a=self.photo()
        other=self.client.post('/api/orders',json={'school':'Другая','class_name':'1А','copies':1}).json()['id']
        b=self.photo(order=other,person='other')
        result=self.client.post(f'/api/orders/{self.order}/delete-photos',json={'photo_ids':[a,b]})
        self.assertEqual(result.status_code,404)
        self.assertEqual(len(self.client.get(f'/api/orders/{self.order}').json()['photos']),1)
        self.assertEqual(self.client.put(f'/api/orders/{self.order}/cover',json={'photo_ids':[b]}).status_code,404)

    def test_delete_order_and_pending_photo(self):
        self.photo(status='pending',person=None)
        self.assertEqual(self.client.delete(f'/api/orders/{self.order}').status_code,200)
        self.assertEqual(self.client.get(f'/api/orders/{self.order}').status_code,404)
        self.assertEqual(list((s.DATA/'photos').iterdir()),[])

    def test_eta_requires_measurements(self):
        self.photo(status='pending',person=None)
        detail=self.client.get(f'/api/orders/{self.order}').json()
        self.assertIsNone(detail['processing']['eta_seconds'])
        with s.db() as con:
            for n in range(3):
                con.execute('INSERT INTO processing_times VALUES (?,?,?)',(str(n),10,s.now()))
        self.assertEqual(self.client.get(f'/api/orders/{self.order}').json()['processing']['eta_seconds'],10)

    def test_worker_does_not_recreate_deleted_photo_person(self):
        import numpy as np
        photo=self.photo(status='pending',person=None)
        class Engine:
            def extract(inner, pixels):
                s.delete_photos(self.order,s.PhotoIds(photo_ids=[photo]))
                return 'ready', [1.0,0.0]
        with patch.object(s,'engine',Engine()):
            s.process_pending()
        detail=self.client.get(f'/api/orders/{self.order}').json()
        self.assertEqual(detail['photos'],[])
        self.assertEqual(detail['persons'],[])

    def test_confirmation_rejects_changed_target(self):
        photo=self.photo(uncertain=1)
        path=f'/api/orders/{self.order}/confirm-photos'
        response=self.client.post(path,json={'photo_ids':[photo],'expected_persons':{photo:'wrong'}})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.client.get(f'/api/orders/{self.order}').json()['photos'][0]['uncertain'],1)
        self.assertEqual(self.client.post(path,json={'photo_ids':[photo],'expected_persons':{photo:'person'}}).status_code,200)

    def test_mutations_require_same_origin(self):
        self.client.headers['origin']='http://elsewhere'
        self.assertEqual(self.client.delete(f'/api/orders/{self.order}').status_code,403)

if __name__ == '__main__':
    unittest.main()
