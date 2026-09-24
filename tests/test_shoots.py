"""Shoot migration, upload routing and batch boundaries on isolated data."""
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from fastapi.testclient import TestClient
from album_factory import server as s


class ShootTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data = patch.object(s, 'DATA', Path(tmp.name)); data.start(); self.addCleanup(data.stop)
        worker = patch.object(s.executor, 'submit'); worker.start(); self.addCleanup(worker.stop)
        self.client = TestClient(s.app)
        self.client.__enter__(); self.addCleanup(self.client.__exit__, None, None, None)
        self.client.get('/v2'); self.client.headers['origin'] = 'http://testserver'
        self.order = self.client.post('/api/orders', json={'school':'Тест','class_name':'А','copies':1}).json()['id']

    def shoot(self, kind='portrait'):
        response = self.client.post(f'/api/orders/{self.order}/shoots', json={'kind':kind,'title':'Съёмка'})
        self.assertEqual(response.status_code, 201)
        return response.json()['id']

    def upload(self, shoot_id=None, color='red'):
        buf=io.BytesIO(); Image.new('RGB',(20,20),color).save(buf,format='JPEG')
        return self.client.post(f'/api/orders/{self.order}/photos', params={'filename':'DSC001.jpg', **({'shoot_id':shoot_id} if shoot_id else {})}, content=buf.getvalue())

    def detail(self):
        return self.client.get(f'/api/orders/{self.order}').json()

    def test_general_only_does_not_create_persons_or_review(self):
        self.assertEqual(self.detail()['shoots'], [])
        shoot = self.shoot('general')
        self.assertEqual(self.upload(shoot).status_code, 201)
        with patch.object(s, 'FaceEngine', side_effect=AssertionError('No recognition for general photos')):
            s.process_pending()
        order=self.detail()
        self.assertEqual(len(order['shoots']),1)
        self.assertEqual(order['persons'],[])
        self.assertEqual(order['photos'][0]['status'],'ready')
        self.assertEqual(order['photos'][0]['shoot_type'],'general')
        self.assertEqual(self.client.get('/api/orders').json()[0]['review_count'],0)
        photo=order['photos'][0]['id']
        self.assertEqual(self.client.post(f'/api/orders/{self.order}/move',json={'photo_ids':[photo]}).status_code,409)
        self.assertEqual(self.client.delete(f'/api/orders/{self.order}').status_code,200)

    def test_migration_preserves_photo_and_assignment_and_is_idempotent(self):
        with s.db() as con:
            con.execute('INSERT INTO persons VALUES (?,?,?,?)',('person',self.order,'Анна',s.now()))
            con.execute("INSERT INTO photos (id,order_id,filename,sha,status,person_id,uncertain,created_at) VALUES (?,?,?,?,?,?,?,?)",('old',self.order,'old.jpg','old','ready','person',1,s.now()))
        s.init_db(); s.init_db()
        order=self.detail()
        self.assertEqual(len(order['shoots']),1)
        self.assertEqual(order['shoots'][0]['kind'],'portrait')
        self.assertEqual(order['photos'][0]['person_id'],'person')
        self.assertEqual(order['photos'][0]['uncertain'],1)
        self.assertEqual(order['photos'][0]['shoot_id'],order['shoots'][0]['id'])

    def test_upload_validation_duplicates_and_legacy_destination(self):
        self.assertEqual(self.upload('missing').status_code,404)
        self.assertEqual(self.upload().status_code,201)
        portrait=self.detail()['shoots'][0]['id']
        self.assertTrue(self.upload(portrait).json()['duplicate'])
        general=self.shoot('general')
        self.assertEqual(self.upload(general).status_code,409)
        other=self.client.post('/api/orders',json={'school':'Другая','class_name':'Б','copies':1}).json()['id']
        response=self.client.post(f'/api/orders/{other}/photos',params={'filename':'a.jpg','shoot_id':portrait},content=b'x')
        self.assertEqual(response.status_code,404)
        self.assertEqual(self.client.post(f'/api/orders/{self.order}/shoots',json={'kind':'general','title':'  '}).status_code,422)

    def test_worker_batches_are_scoped_to_shoot(self):
        a,b=self.shoot(),self.shoot()
        self.upload(a,'red');self.upload(b,'blue')
        batches=[]
        def process(server,rows,engine):
            batches.append({r['shoot_id'] for r in rows})
            with s.db() as con:
                con.executemany("UPDATE photos SET status='ready' WHERE id=?",[(r['id'],) for r in rows])
        with patch.object(s,'engine',object()),patch.object(s,'process_v3_batch',process):
            s.process_pending()
        self.assertEqual(len(batches),2)
        self.assertIn({a},batches); self.assertIn({b},batches)
