"""School catalogue: studio-owned schools and teachers, class choice of teachers, layout use."""
from io import BytesIO
import unittest

from fastapi.testclient import TestClient
from PIL import Image

from album_factory import server as s
import test_server_v2
from test_master_templates import master


def jpeg(color='#aabbcc'):
    buffer = BytesIO()
    Image.new('RGB', (60, 80), color).save(buffer, 'JPEG')
    return buffer.getvalue()


class SchoolCatalogTests(unittest.TestCase):
    setUp = test_server_v2.V2Tests.setUp

    def school(self, name='МБОУ «Средняя общеобразовательная школа № 5»', city='Казань'):
        response = self.client.post('/api/schools', json={'name': name, 'city': city})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def teacher(self, school_id, last, first='Мария', patronymic='Ивановна', subject='Математика'):
        response = self.client.post(f'/api/schools/{school_id}/teachers', json={
            'last_name': last, 'first_name': first, 'patronymic': patronymic, 'subject': subject})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def order_for(self, school_id, **extra):
        created = self.client.post('/api/orders', json={'school_id': school_id, 'class_name': '11 А', 'copies': 10, **extra})
        self.assertEqual(created.status_code, 201, created.text)
        return created.json()['id']

    def portal(self, order_id, manage=False):
        data = self.client.post(f'/api/orders/{order_id}/client-link').json()
        base = '/client-api/' + data['url'].rsplit('/', 1)[1]
        guest = TestClient(self.client.app)
        guest.headers['origin'] = 'http://testserver'
        self.assertEqual(guest.post(base + '/enter', json={'pin': data['entry_pin']}).status_code, 200)
        if manage:
            self.assertEqual(guest.post(base + '/manage', json={'pin': data['manage_pin']}).status_code, 200)
        return guest, base

    def test_school_has_full_name_and_city_and_no_duplicates(self):
        school = self.school()
        self.assertEqual((school['name'], school['city']), ('МБОУ «Средняя общеобразовательная школа № 5»', 'Казань'))
        again = self.school(' мбоу «средняя общеобразовательная  школа № 5» ', 'казань')
        self.assertEqual(again['id'], school['id'])
        other_city = self.school(city='Уфа')
        self.assertNotEqual(other_city['id'], school['id'])
        self.assertEqual(len(self.client.get('/api/schools').json()), 2)
        clash = self.client.patch(f'/api/schools/{other_city["id"]}', json={'name': school['name'], 'city': 'Казань'})
        self.assertEqual(clash.status_code, 409)
        order = self.order_for(school['id'])
        renamed = self.client.patch(f'/api/schools/{school["id"]}', json={'name': 'Лицей № 5', 'city': 'Казань'})
        self.assertEqual(renamed.status_code, 200, renamed.text)
        detail = self.client.get(f'/api/orders/{order}').json()
        self.assertEqual((detail['school'], detail['school_id'], detail['school_city']), ('Лицей № 5', school['id'], 'Казань'))
        self.assertEqual(self.client.delete(f'/api/schools/{school["id"]}').status_code, 409)
        self.assertEqual(self.client.delete(f'/api/schools/{other_city["id"]}').status_code, 200)

    def test_teachers_and_portraits_belong_to_one_studio(self):
        school = self.school()
        teacher = self.teacher(school['id'], 'Петрова')
        self.assertEqual(teacher['name'], 'Петрова Мария Ивановна')
        self.assertEqual(self.client.post(f'/api/schools/{school["id"]}/teachers', json={'last_name': ' '}).status_code, 422)
        uploaded = self.client.put(f'/api/teachers/{teacher["id"]}/portrait', content=jpeg())
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        self.assertTrue(uploaded.json()['has_portrait'])
        self.assertEqual(self.client.get(f'/api/teachers/{teacher["id"]}/portrait/thumb').status_code, 200)
        self.assertEqual(self.client.put(f'/api/teachers/{teacher["id"]}/portrait', content=b'not an image').status_code, 415)
        listed = self.client.get(f'/api/schools/{school["id"]}').json()
        self.assertEqual([t['id'] for t in listed['teachers']], [teacher['id']])
        self.assertEqual(listed['teacher_count'], 1)

        other = TestClient(self.client.app)
        other.headers['origin'] = 'http://testserver'
        other.post('/api/register', json={'email': 'b@studio.test', 'password': 'secret-pass', 'studio_name': 'Вторая'})
        self.assertEqual(other.get('/api/schools').json(), [])
        self.assertEqual(other.get(f'/api/schools/{school["id"]}').status_code, 404)
        self.assertEqual(other.post(f'/api/schools/{school["id"]}/teachers', json={'last_name': 'Чужой'}).status_code, 404)
        self.assertEqual(other.patch(f'/api/teachers/{teacher["id"]}', json={'last_name': 'Чужой'}).status_code, 404)
        self.assertEqual(other.get(f'/api/teachers/{teacher["id"]}/portrait/full').status_code, 404)
        self.assertEqual(other.post('/api/orders', json={'school_id': school['id'], 'class_name': '1', 'copies': 1}).status_code, 404)
        # The same school name in another studio is a separate record.
        mine = other.post('/api/schools', json={'name': school['name'], 'city': 'Казань'}).json()
        self.assertNotEqual(mine['id'], school['id'])
        self.assertEqual(mine['teacher_count'], 0)

    def test_class_chooses_teachers_and_class_teacher(self):
        school = self.school()
        first = self.teacher(school['id'], 'Алексеева')
        lead = self.teacher(school['id'], 'Борисова', subject='Русский язык')
        skipped = self.teacher(school['id'], 'Власова')
        order = self.order_for(school['id'])
        guest, base = self.portal(order)
        view = guest.get(base + '/teachers').json()
        self.assertEqual([t['name'].split()[0] for t in view['teachers']], ['Алексеева', 'Борисова', 'Власова'])
        self.assertFalse(view['chosen'])
        self.assertNotIn('updated_by', view)
        choice = {'teacher_ids': [first['id'], lead['id']], 'class_teacher_id': lead['id']}
        self.assertEqual(guest.put(base + '/teachers', json=choice).status_code, 401)

        guest, base = self.portal(order, manage=True)
        self.assertEqual(guest.put(base + '/teachers', json={'teacher_ids': [first['id']], 'class_teacher_id': lead['id']}).status_code, 422)
        self.assertEqual(guest.put(base + '/teachers', json={'teacher_ids': ['missing']}).status_code, 422)
        saved = guest.put(base + '/teachers', json=choice)
        self.assertEqual(saved.status_code, 200, saved.text)
        body = saved.json()
        self.assertEqual(body['class_teacher_id'], lead['id'])
        self.assertEqual({t['id'] for t in body['teachers'] if t['selected']}, {first['id'], lead['id']})
        self.assertFalse(next(t for t in body['teachers'] if t['id'] == skipped['id'])['selected'])

        photographer = self.client.get(f'/api/orders/{order}/teachers').json()
        self.assertEqual((photographer['updated_by'], photographer['class_teacher_id']), ('client', lead['id']))
        with s.db() as con:
            from album_factory.school_catalog import snapshot_teachers
            ordered = snapshot_teachers(con, order)
        self.assertEqual([t['last_name'] for t in ordered], ['Борисова', 'Алексеева'])
        self.assertTrue(ordered[0]['is_class_teacher'])

        # A teacher chosen by an album leaves the catalogue but stays in that album.
        self.assertTrue(self.client.delete(f'/api/teachers/{first["id"]}').json()['archived'])
        self.assertTrue(self.client.delete(f'/api/teachers/{skipped["id"]}').json()['ok'])
        self.assertEqual(len(self.client.get(f'/api/schools/{school["id"]}').json()['teachers']), 1)
        with s.db() as con:
            self.assertEqual(len(snapshot_teachers(con, order)), 2)

        with s.db() as con:
            con.execute("UPDATE orders SET stage='print' WHERE id=?", (order,))
        self.assertEqual(guest.put(base + '/teachers', json={'teacher_ids': []}).status_code, 409)
        self.assertTrue(guest.get(base + '/teachers').json()['locked'])

    def test_teacher_photos_from_order_or_catalog_become_portraits(self):
        school = self.school()
        known = self.teacher(school['id'], 'Петрова')
        order = self.order_for(school['id'])
        from_order = self.client.post(f'/api/schools/{school["id"]}/teacher-photos?filename=IMG_1.jpg&order_id={order}', content=jpeg('#112233'))
        self.assertEqual(from_order.status_code, 201, from_order.text)
        again = self.client.post(f'/api/schools/{school["id"]}/teacher-photos?filename=copy.jpg', content=jpeg('#112233')).json()
        self.assertEqual((again['id'], again['duplicate']), (from_order.json()['id'], True))
        from_catalog = self.client.post(f'/api/schools/{school["id"]}/teacher-photos?filename=IMG_2.jpg', content=jpeg('#445566')).json()
        spare = self.client.post(f'/api/schools/{school["id"]}/teacher-photos?filename=IMG_3.jpg', content=jpeg('#778899')).json()
        pool = self.client.get(f'/api/schools/{school["id"]}/teacher-photos').json()
        self.assertEqual([p['filename'] for p in pool], ['IMG_1.jpg', 'IMG_2.jpg', 'IMG_3.jpg'])
        self.assertEqual(pool[0]['order_id'], order)
        self.assertEqual(self.client.get(f'/api/orders/{order}/teachers').json()['unsorted_photos'], 3)
        self.assertEqual(self.client.get(f'/api/teacher-photos/{spare["id"]}/thumb').status_code, 200)

        other_school = self.school(city='Уфа')
        other_order = self.order_for(other_school['id'])
        self.assertEqual(self.client.post(f'/api/schools/{school["id"]}/teacher-photos?filename=a.jpg&order_id={other_order}', content=jpeg()).status_code, 422)
        stranger = self.teacher(other_school['id'], 'Чужая')
        self.assertEqual(self.client.post(f'/api/teacher-photos/{spare["id"]}/assign', json={'teacher_id': stranger['id']}).status_code, 422)
        self.assertEqual(self.client.post(f'/api/teacher-photos/{spare["id"]}/assign', json={}).status_code, 422)

        assigned = self.client.post(f'/api/teacher-photos/{from_order.json()["id"]}/assign', json={'teacher_id': known['id']})
        self.assertEqual(assigned.status_code, 200, assigned.text)
        self.assertTrue(assigned.json()['has_portrait'])
        first_version = assigned.json()['portrait_version']
        created = self.client.post(f'/api/teacher-photos/{from_catalog["id"]}/assign', json={'teacher': {'last_name': 'Новикова', 'first_name': 'Ольга', 'subject': 'История'}})
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual((created.json()['name'], created.json()['subject']), ('Новикова Ольга', 'История'))
        self.assertTrue(created.json()['has_portrait'])
        # A newer photo replaces the portrait and the old files go away.
        replaced = self.client.post(f'/api/teacher-photos/{spare["id"]}/assign', json={'teacher_id': known['id']}).json()
        self.assertNotEqual(replaced['portrait_version'], first_version)
        self.assertFalse((s.DATA / 'photos' / (first_version + '.jpg')).exists())
        self.assertEqual(self.client.get(f'/api/teachers/{known["id"]}/portrait/full').status_code, 200)
        self.assertEqual(self.client.get(f'/api/schools/{school["id"]}/teacher-photos').json(), [])
        self.assertEqual(self.client.get(f'/api/teacher-photos/{spare["id"]}/thumb').status_code, 404)

        other = TestClient(self.client.app)
        other.headers['origin'] = 'http://testserver'
        other.post('/api/register', json={'email': 'c@studio.test', 'password': 'secret-pass', 'studio_name': 'Третья'})
        leftover = self.client.post(f'/api/schools/{school["id"]}/teacher-photos?filename=x.jpg', content=jpeg('#000000')).json()
        self.assertEqual(other.post(f'/api/schools/{school["id"]}/teacher-photos?filename=x.jpg', content=jpeg()).status_code, 404)
        self.assertEqual(other.get(f'/api/teacher-photos/{leftover["id"]}/full').status_code, 404)
        self.assertEqual(other.delete(f'/api/teacher-photos/{leftover["id"]}').status_code, 404)
        self.assertEqual(self.client.delete(f'/api/teacher-photos/{leftover["id"]}').status_code, 200)

    def test_order_without_catalog_school_cannot_choose(self):
        guest, base = self.portal(self.order, manage=True)
        view = guest.get(base + '/teachers').json()
        self.assertIsNone(view['school'])
        self.assertEqual(guest.put(base + '/teachers', json={'teacher_ids': []}).status_code, 409)

    def test_chosen_teachers_are_placed_in_master_layout(self):
        doc = master()
        teacher_grid = {'id': 'teacher-grid', 'type': 'grid', 'box': {'x': 16, 'y': 33, 'w': 178, 'h': 224}, 'source': 'teachers',
                        'min': 1, 'max': 12, 'gap': 5, 'minPhotoWidth': 32, 'font': 'Arial', 'fontSize': 12, 'minFontSize': 10,
                        'color': '#34332f', 'excludeLead': True, 'showDetail': True}
        lead_photo = {'id': 'lead-photo', 'type': 'photo', 'box': {'x': 20, 'y': 20, 'w': 80, 'h': 110}, 'source': 'lead'}
        lead_name = {'id': 'lead-name', 'type': 'text', 'box': {'x': 20, 'y': 140, 'w': 170, 'h': 20}, 'text': 'Классный руководитель',
                     'binding': 'lead.name', 'font': 'Arial', 'fontSize': 12, 'color': '#333333', 'align': 'left'}
        doc['sections'].insert(1, {'id': 'teachers', 'name': 'Учителя', 'kind': 'flow', 'target': 1, 'spreads': [
            {'id': 't1', 'pages': [{'id': 'tp1', 'background': '#ffffff', 'layers': [teacher_grid]},
                                   {'id': 'tp2', 'background': '#ffffff', 'layers': [lead_photo, lead_name]}]}]})
        draft = self.client.post('/api/master-templates', json={'document': doc})
        self.assertEqual(draft.status_code, 201, draft.text)
        school = self.school()
        colleague = self.teacher(school['id'], 'Алексеева', subject='Физика')
        lead = self.teacher(school['id'], 'Борисова', first='Анна', patronymic='Петровна')
        self.teacher(school['id'], 'Власова')
        self.client.put(f'/api/teachers/{lead["id"]}/portrait', content=jpeg('#113355'))
        order = self.order_for(school['id'], master_template_id=draft.json()['id'])
        saved = self.client.put(f'/api/orders/{order}/teachers', json={'teacher_ids': [colleague['id'], lead['id']], 'class_teacher_id': lead['id']})
        self.assertEqual(saved.status_code, 200, saved.text)
        generated = self.client.post(f'/api/orders/{order}/layout')
        self.assertEqual(generated.status_code, 200, generated.text)
        document = generated.json()['document']
        elements = [e for group in document['variant_spreads'].values() for spread in group.values() for e in spread['elements']]
        elements += [e for spread in document['shared_spreads'].values() for e in spread['elements']]
        texts = {e.get('text') for e in elements if e['type'] == 'text'}
        self.assertIn('Анна Петровна Борисова', texts)
        self.assertIn('Мария Ивановна Алексеева', texts)
        self.assertIn('Физика', texts)
        self.assertFalse(any('Власова' in (t or '') for t in texts))
        lead_frame = next(e for e in elements if e['key'].endswith('/lead-photo'))
        self.assertTrue(lead_frame['photo'].startswith('master-'))
        self.assertFalse(self.client.get(f'/api/orders/{order}/teachers').json()['layout_outdated'])
        self.client.put(f'/api/orders/{order}/teachers', json={'teacher_ids': [lead['id']], 'class_teacher_id': lead['id']})
        self.assertTrue(self.client.get(f'/api/orders/{order}/teachers').json()['layout_outdated'])


if __name__ == '__main__':
    unittest.main()
