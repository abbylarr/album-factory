"""Client selections persist and are scoped to an order's capability link."""
import unittest
import test_server_v2
from fastapi.testclient import TestClient


class ClientPortalTests(unittest.TestCase):
    setUp = test_server_v2.V2Tests.setUp
    photo = test_server_v2.V2Tests.photo

    def link(self, order=None):
        data = self.client.post(f'/api/orders/{order or self.order}/client-link').json()
        token = data['url'].rsplit('/', 1)[1]
        if data.get('entry_pin'):
            self.client.post('/client-api/' + token + '/enter', json={'pin': data['entry_pin']})
        return '/client-api/' + token

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
        self.assertEqual(self.client.put(base+'/persons/person', json=payload).status_code, 409)
        self.assertEqual(self.client.get(base).json()['persons'][0]['photo_id'], a)
        payload['photo_id'] = a
        payload['quote'] = 'Новая цитата'
        self.assertEqual(self.client.put(base+'/persons/person', json=payload).status_code, 200)
        self.client.post(f'/api/orders/{self.order}/move',json={'photo_ids':[a]})
        self.assertEqual(self.client.get(base).json()['completed'], 0)

    def test_photographer_person_exposes_valid_portrait_and_quote(self):
        first = self.photo()
        chosen = self.photo()
        def person():
            return self.client.get(f'/api/orders/{self.order}').json()['persons'][0]
        self.assertIsNone(person()['selected_photo_id'])
        self.assertEqual(person()['quote'], '')
        base = self.link()
        response = self.client.put(base+'/persons/person', json=dict(
            photo_id=chosen, first_name='Анна', last_name='Иванова', quote='Моя цитата'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(person()['selected_photo_id'], chosen)
        self.assertEqual(person()['quote'], 'Моя цитата')
        self.assertNotEqual(person()['selected_photo_id'], first)
        # An unavailable or reassigned portrait must not be shown as the student's choice.
        with test_server_v2.s.db() as con:
            con.execute("UPDATE photos SET status='error' WHERE id=?", (chosen,))
        self.assertIsNone(person()['selected_photo_id'])
        self.assertEqual(person()['quote'], '')
        with test_server_v2.s.db() as con:
            con.execute("UPDATE photos SET status='ready' WHERE id=?", (chosen,))
        self.client.post(f'/api/orders/{self.order}/move', json={'photo_ids':[chosen]})
        original = next(p for p in self.client.get(f'/api/orders/{self.order}').json()['persons'] if p['id']=='person')
        self.assertIsNone(original['selected_photo_id'])
        self.assertEqual(original['quote'], '')

    def test_scope_and_validation(self):
        photo = self.photo()
        base = self.link()
        other = self.client.post('/api/orders', json=dict(school_city='Казань', school='Другая', class_name='1', copies=1)).json()['id']
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
        self.assertEqual(guest.get(base).status_code, 401)
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

    def test_codes_stay_visible_and_can_be_reissued(self):
        url = f'/api/orders/{self.order}/client-link'
        self.assertIsNone(self.client.get(url).json()['url'])
        first = self.client.post(url).json()
        self.assertRegex(first['entry_pin'], r'^\d{4}$')
        again = self.client.get(url).json()
        self.assertEqual((again['entry_pin'], again['manage_pin']), (first['entry_pin'], first['manage_pin']))
        self.assertEqual(self.client.post(url).json()['entry_pin'], first['entry_pin'])
        fresh = self.client.post(f'/api/orders/{self.order}/client-codes/reset').json()
        self.assertEqual(fresh['url'], first['url'])
        token = fresh['url'].rsplit('/', 1)[1]
        other = TestClient(self.client.app)
        other.headers['origin'] = 'http://testserver'
        self.assertEqual(other.post(f'/client-api/{token}/enter', json={'pin': fresh['entry_pin']}).status_code, 200)
        from album_factory import server as s
        with s.db() as con:
            con.execute('DELETE FROM order_codes WHERE order_id=?', (self.order,))
        lost = self.client.get(url).json()
        self.assertTrue(lost['pins_lost'])
        self.assertIsNone(lost['entry_pin'])

    def test_message_templates_save_and_reset(self):
        base = self.client.get('/api/message-templates').json()
        self.assertIn('{код_входа}', base['class']['body'])
        self.assertIn('{код_управления}', base['manager']['body'])
        self.assertFalse(base['class']['custom'])
        saved = self.client.put('/api/message-templates/class', json={'body': 'Привет, {класс}! {ссылка}'}).json()
        self.assertTrue(saved['custom'])
        self.assertEqual(self.client.get('/api/message-templates').json()['class']['body'], 'Привет, {класс}! {ссылка}')
        self.client.put('/api/message-templates/class', json={'body': ''})
        self.assertFalse(self.client.get('/api/message-templates').json()['class']['custom'])
        self.assertEqual(self.client.put('/api/message-templates/other', json={'body': 'x'}).status_code, 404)

    def test_deletion_and_schema_restart(self):
        from album_factory import server as s
        photo = self.photo()
        base = self.link()
        self.client.put(base+'/persons/person',json=dict(photo_id=photo, first_name='Анна', last_name='Иванова'))
        s.init_db()
        self.assertEqual(self.client.get(base).json()['completed'], 1)
        self.assertEqual(self.client.delete(f'/api/orders/{self.order}').status_code, 200)
        self.assertEqual(self.client.get(base).status_code, 404)


class LayoutCorrectionTests(unittest.TestCase):
    setUp = test_server_v2.V2Tests.setUp
    photo = test_server_v2.V2Tests.photo

    def publish(self, revision):
        import json
        from album_factory import server as s
        document = {"revision": revision, "spread_size_mm": [200, 100],
                    "variants": [{"owner": "class", "name": "11А", "sequence": ["a", "b"]}],
                    "shared_spreads": {"a": {"key": "a", "section": "students", "elements": []},
                                       "b": {"key": "b", "section": "moments", "elements": []}},
                    "covers": {}, "variant_spreads": {}}
        with s.db() as con:
            con.execute("INSERT OR REPLACE INTO order_layouts VALUES (?,?,?,?,?)", (self.order, "{}", json.dumps(document), "[]", s.now()))
        self.assertEqual(self.client.post(f"/api/orders/{self.order}/layout/publish").status_code, 200)

    def test_customer_sends_and_photographer_resolves_corrections(self):
        photo = self.photo()
        data = self.client.post(f'/api/orders/{self.order}/client-link').json()
        token = data['url'].rsplit('/', 1)[1]
        base = '/client-api/' + token
        self.client.post(base + '/enter', json={'pin': data['entry_pin']})
        self.client.put(base + '/persons/person', json=dict(photo_id=photo, first_name='Ана', last_name='Иванова'))
        detail = self.client.get(base).json()
        self.assertEqual((detail['stage'], detail['manager']), ('selection', False))
        name_fix = dict(person_id='person', first_name='Анна', last_name='Иванова')
        self.assertEqual(self.client.post(base + '/corrections/name', json=name_fix).status_code, 401)
        self.client.post(base + '/manage', json={'pin': data['manage_pin']})
        self.assertTrue(self.client.get(base).json()['manager'])
        self.assertEqual(self.client.post(base + '/corrections/name', json=name_fix).status_code, 409)
        self.publish('rev-1')
        self.assertEqual(self.client.get(base).json()['stage'], 'approval')
        self.assertEqual(self.client.post(base + '/corrections/name', json=name_fix).status_code, 201)
        spread = self.client.post(base + '/corrections/spread', json=dict(variant='class', index=1, comment='Поменять фото'))
        self.assertEqual(spread.status_code, 201)
        self.assertEqual(self.client.post(base + '/corrections/spread', json=dict(variant='class', index=5, comment='x')).status_code, 404)
        self.assertEqual(self.client.post(base + '/corrections/spread', json=dict(variant='class', index=0, comment=' ')).status_code, 422)
        fixes = self.client.get(base).json()['corrections']
        self.assertEqual([(f['kind'], f['old_name'], f['new_name']) for f in fixes][0], ('name', 'Ана Иванова', 'Анна Иванова'))
        self.assertEqual(fixes[1]['spread_label'], 'Разворот 2 из 2')
        self.assertEqual(self.client.get(base).json()['persons'][0]['first_name'], 'Анна')
        order = self.client.get(f'/api/orders/{self.order}').json()
        self.assertEqual(order['corrections_open'], 2)
        listing = next(o for o in self.client.get('/api/orders').json() if o['id'] == self.order)
        self.assertEqual(listing['corrections_open'], 2)
        summary = self.client.get(base + '/summary').json()
        self.assertEqual(self.client.post(base + '/approve', json={'hash': summary['hash']}).status_code, 409)
        self.assertEqual(self.client.delete(base + '/corrections/' + fixes[1]['id']).status_code, 200)
        self.assertEqual(self.client.post(f"/api/orders/{self.order}/corrections/{fixes[0]['id']}/resolve").status_code, 200)
        self.assertEqual(self.client.get(f'/api/orders/{self.order}').json()['corrections_open'], 0)
        self.client.post(base + '/corrections/spread', json=dict(variant='class', index=0, comment='Ещё'))
        self.publish('rev-2')
        self.assertEqual(self.client.get(base).json()['corrections'], [])
        self.client.post(base + '/manage/logout')
        self.assertFalse(self.client.get(base).json()['manager'])

    def test_sent_marks(self):
        base = f'/api/orders/{self.order}'
        self.assertEqual(self.client.post(base + '/client-sent/class').status_code, 409)
        self.client.post(base + '/client-link')
        self.assertEqual(self.client.post(base + '/client-sent/other').status_code, 404)
        first = self.client.post(base + '/client-sent/class').json()['sent']['class']
        self.assertEqual(self.client.post(base + '/client-sent/class').json()['sent']['class'], first)
        self.assertEqual(set(self.client.get(base + '/client-link').json()['sent']), {'class'})
        self.assertEqual(self.client.post(base + '/client-codes/reset').json()['sent'], {})

    def test_people_progress_lists_everyone(self):
        people = self.client.get(f'/api/orders/{self.order}').json()['client_people']
        self.assertTrue(all(set(p) == {'id', 'done', 'name', 'photo_id'} for p in people))
