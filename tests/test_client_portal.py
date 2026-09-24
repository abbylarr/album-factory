"""Client selections persist and are scoped to an order's capability link."""
import unittest
import test_server_v2
from fastapi.testclient import TestClient


class ClientPortalTests(unittest.TestCase):
    setUp = test_server_v2.V2Tests.setUp
    photo = test_server_v2.V2Tests.photo

    def link(self, order=None):
        url = self.client.post(f'/api/orders/{order or self.order}/client-link').json()['url']
        return '/client-api/' + url.rsplit('/', 1)[1]

    def test_save_reload_and_replace(self):
        a = self.photo()
        b = self.photo()
        base = self.link()
        self.assertEqual(base, self.link())
        payload = dict(photo_id=a, first_name=' Анна ', last_name='Иванова', quote='Моя цитата')
        self.assertEqual(self.client.put(base+'/persons/person', json=payload).status_code, 200)
        saved = self.client.get(base).json()
        self.assertEqual(saved['completed'], 1)
        self.assertEqual(saved['persons'][0]['first_name'], 'Анна')
        self.assertEqual(saved['persons'][0]['quote'], 'Моя цитата')
        payload['photo_id'] = b
        self.client.put(base+'/persons/person', json=payload)
        self.assertEqual(self.client.get(base).json()['persons'][0]['photo_id'], b)
        self.client.post(f'/api/orders/{self.order}/move',json={'photo_ids':[b]})
        self.assertEqual(self.client.get(base).json()['completed'], 0)

    def test_scope_and_validation(self):
        photo = self.photo()
        base = self.link()
        other = self.client.post('/api/orders', json=dict(school='Другая', class_name='1', copies=1)).json()['id']
        other_photo = self.photo(order=other, person='other')
        payload = dict(photo_id=other_photo, first_name='Анна', last_name='Иванова')
        self.assertEqual(self.client.put(base+'/persons/person', json=payload).status_code, 409)
        self.assertEqual(self.client.get(base+f'/photos/{other_photo}/thumb').status_code, 404)
        self.assertEqual(self.client.get('/client-api/invalid').status_code, 404)
        payload.update(photo_id=photo, first_name=' ')
        self.assertEqual(self.client.put(base+'/persons/person', json=payload).status_code, 422)
        payload.update(first_name='Анна', quote='я'*301)
        self.assertEqual(self.client.put(base+'/persons/person', json=payload).status_code, 422)
        guest = TestClient(self.client.app)
        self.assertEqual(guest.get(base).status_code, 200)
        self.assertEqual(guest.get('/api/orders').status_code, 401)
        self.assertEqual(guest.put(base+'/persons/person', json=payload).status_code, 403)

    def test_photographer_progress_tracks_valid_saved_choices(self):
        def progress():
            detail=self.client.get(f'/api/orders/{self.order}').json()['client_progress']
            listing=next(o for o in self.client.get('/api/orders').json() if o['id']==self.order)['client_progress']
            self.assertEqual(detail,listing)
            return detail
        self.assertEqual(progress()['status'],'not_opened')
        a=self.photo(person='a'); b=self.photo(person='b')
        base=self.link()
        self.assertEqual(progress()['status'],'waiting')
        self.client.put(base+'/persons/a',json=dict(photo_id=a,first_name='Анна',last_name='Иванова'))
        self.assertEqual((progress()['status'],progress()['completed'],progress()['total'],progress()['percent']),('in_progress',1,2,50))
        self.client.put(base+'/persons/b',json=dict(photo_id=b,first_name='Борис',last_name='Иванов'))
        self.assertEqual(progress()['status'],'complete')
        self.client.post(f'/api/orders/{self.order}/move',json={'photo_ids':[a],'person_id':'b'})
        self.assertEqual(progress()['total'],1)
        self.assertEqual(progress()['completed'],1)
        # Moving a selected image out of a still-existing person invalidates it.
        c=self.photo(person='b')
        self.client.post(f'/api/orders/{self.order}/move',json={'photo_ids':[b]})
        self.assertEqual(progress()['completed'],0)
        self.assertEqual(progress()['status'],'waiting')

    def test_empty_open_cabinet_is_not_complete(self):
        self.link()
        progress=self.client.get(f'/api/orders/{self.order}').json()['client_progress']
        self.assertEqual((progress['status'],progress['total'],progress['percent']),('waiting',0,0))

    def test_deletion_and_schema_restart(self):
        from album_factory import server as s
        photo = self.photo()
        base = self.link()
        self.client.put(base+'/persons/person',json=dict(photo_id=photo, first_name='Анна', last_name='Иванова'))
        s.init_db()
        self.assertEqual(self.client.get(base).json()['completed'], 1)
        self.assertEqual(self.client.delete(f'/api/orders/{self.order}').status_code, 200)
        self.assertEqual(self.client.get(base).status_code, 404)
