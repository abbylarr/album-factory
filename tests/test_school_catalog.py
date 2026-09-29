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
        self.assertEqual(len(self.client.get('/api/schools').json()), 3)
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
        photos = [p for group in pool['groups'] for p in group['photos']]
        self.assertEqual([p['filename'] for p in photos], ['IMG_1.jpg', 'IMG_2.jpg', 'IMG_3.jpg'])
        self.assertEqual((photos[0]['order_id'], photos[0]['status'], pool['pending']), (order, 'pending', 3))
        self.assertEqual(self.client.get(f'/api/orders/{order}/teachers').json()['unsigned_groups'], 3)
        self.assertEqual(self.client.get(f'/api/teacher-photos/{spare["id"]}/thumb').status_code, 200)

        other_school = self.school(city='Уфа')
        other_order = self.order_for(other_school['id'])
        self.assertEqual(self.client.post(f'/api/schools/{school["id"]}/teacher-photos?filename=a.jpg&order_id={other_order}', content=jpeg()).status_code, 422)
        stranger = self.teacher(other_school['id'], 'Чужая')
        self.assertEqual(self.client.post(f'/api/teacher-photos/{spare["id"]}/assign', json={'teacher_id': stranger['id']}).status_code, 422)
        self.assertEqual(self.client.post(f'/api/teacher-photos/{spare["id"]}/assign', json={}).status_code, 422)

        with s.db() as con:
            con.execute("UPDATE teacher_photos SET status='ready' WHERE school_id=?", (school['id'],))
        assigned = self.client.post(f'/api/teacher-photos/{from_order.json()["id"]}/assign', json={'teacher_id': known['id']})
        self.assertEqual(assigned.status_code, 200, assigned.text)
        self.assertTrue(assigned.json()['has_portrait'])
        first_version = assigned.json()['portrait_version']
        created = self.client.post(f'/api/teacher-photos/{from_catalog["id"]}/assign', json={'teacher': {'last_name': 'Новикова', 'first_name': 'Ольга', 'subject': 'История'}})
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual((created.json()['name'], created.json()['subject']), ('Новикова Ольга', 'История'))
        self.assertTrue(created.json()['has_portrait'])
        # A newer photo replaces the portrait; earlier files remain available for undo.
        replaced = self.client.post(f'/api/teacher-photos/{spare["id"]}/assign', json={'teacher_id': known['id']}).json()
        self.assertNotEqual(replaced['portrait_version'], first_version)
        self.assertTrue((s.DATA / 'photos' / (first_version + '.jpg')).exists())
        self.assertEqual(self.client.get(f'/api/teachers/{known["id"]}/portrait/full').status_code, 200)
        self.assertEqual(self.client.get(f'/api/schools/{school["id"]}/teacher-photos').json()['groups'], [])
        self.assertEqual(self.client.get(f'/api/teacher-photos/{spare["id"]}/thumb').status_code, 404)

        other = TestClient(self.client.app)
        other.headers['origin'] = 'http://testserver'
        other.post('/api/register', json={'email': 'c@studio.test', 'password': 'secret-pass', 'studio_name': 'Третья'})
        leftover = self.client.post(f'/api/schools/{school["id"]}/teacher-photos?filename=x.jpg', content=jpeg('#000000')).json()
        self.assertEqual(other.post(f'/api/schools/{school["id"]}/teacher-photos?filename=x.jpg', content=jpeg()).status_code, 404)
        self.assertEqual(other.get(f'/api/teacher-photos/{leftover["id"]}/full').status_code, 404)
        self.assertEqual(other.delete(f'/api/teacher-photos/{leftover["id"]}').status_code, 404)
        self.assertEqual(self.client.delete(f'/api/teacher-photos/{leftover["id"]}').status_code, 200)

    def test_class_signs_teacher_photo_and_other_frames_are_hidden(self):
        from album_factory.school_catalog import group_pending

        class ColourFaces:
            """Stands in for face embeddings: frames of one colour are one person."""
            def extract(self, pixels):
                mean = pixels.reshape(-1, 3).mean(axis=0)
                return 'ready', list(mean / (sum(v * v for v in mean) ** .5))

        school = self.school()
        order = self.order_for(school['id'])
        waiting = self.teacher(school['id'], 'Петрова', first='Анна')
        pictured = self.teacher(school['id'], 'Сидорова')
        self.client.put(f'/api/teachers/{pictured["id"]}/portrait', content=jpeg('#00ff00'))
        upload = lambda name, colour: self.client.post(f'/api/schools/{school["id"]}/teacher-photos?filename={name}&order_id={order}', content=jpeg(colour)).json()['id']
        red = [upload('r1.jpg', '#ff0000'), upload('r2.jpg', '#fd0101'), upload('r3.jpg', '#fb0202')]
        blue = [upload('b1.jpg', '#0000ff'), upload('b2.jpg', '#0101fd')]
        group_pending(s, ColourFaces())
        pool = self.client.get(f'/api/schools/{school["id"]}/teacher-photos').json()
        self.assertEqual(sorted(sorted(p['id'] for p in g['photos']) for g in pool['groups']), sorted([sorted(red), sorted(blue)]))
        self.assertEqual(pool['pending'], 0)

        # Any pupil (or the teacher) with the entry code can sign; no manage code needed.
        guest, base = self.portal(order)
        view = guest.get(base + '/teacher-photos').json()
        self.assertEqual(len(view['groups']), 2)
        self.assertEqual([t['name'] for t in view['teachers']], ['Петрова Анна Ивановна'])
        self.assertEqual(guest.get(base + f'/teacher-photos/{red[1]}/thumb').status_code, 200)
        self.assertEqual(guest.get(base + '/').json()['teachers']['unsigned'], 2)
        self.assertEqual(guest.post(base + f'/teacher-photos/{red[1]}/sign', json={'teacher_id': pictured['id']}).status_code, 409)
        self.assertEqual(guest.post(base + f'/teacher-photos/{red[1]}/sign', json={'teacher': {'last_name': 'Иванов'}}).status_code, 422)
        signed = guest.post(base + f'/teacher-photos/{red[1]}/sign', json={'teacher_id': waiting['id']})
        self.assertEqual(signed.status_code, 200, signed.text)
        for photo_id in red:
            self.assertTrue((s.DATA / 'photos' / f'tphoto-{photo_id}.jpg').exists())
        catalog = {t['id']: t for t in self.client.get(f'/api/schools/{school["id"]}').json()['teachers']}
        self.assertEqual((catalog[waiting['id']]['has_portrait'], catalog[waiting['id']]['portrait_by']), (True, 'client'))
        self.assertEqual(guest.post(base + f'/teacher-photos/{red[0]}/sign', json={'teacher_id': waiting['id']}).status_code, 404)

        # A teacher missing from the catalogue signs themselves in.
        me = guest.post(base + f'/teacher-photos/{blue[0]}/sign', json={'teacher': {'last_name': 'Орлов', 'first_name': 'Игорь', 'subject': 'Физкультура'}})
        self.assertEqual(me.status_code, 200, me.text)
        self.assertEqual(me.json()['name'], 'Орлов Игорь')
        self.assertEqual(guest.get(base + '/teacher-photos').json()['groups'], [])
        self.assertTrue((s.DATA / 'photos' / f'tphoto-{blue[1]}.jpg').exists())

        # The photographer can still replace a portrait the class chose.
        again = upload('new.jpg', '#ffff00')
        group_pending(s, ColourFaces())
        replaced = self.client.post(f'/api/teacher-photos/{again}/assign', json={'teacher_id': waiting['id']}).json()
        self.assertEqual(replaced['portrait_by'], 'photographer')

        # Grouping can be fixed by hand: split a frame out, then put it back.
        first, second = upload('x1.jpg', '#123456'), upload('x2.jpg', '#654321')
        with s.db() as con:
            con.execute("UPDATE teacher_photos SET status='ready' WHERE id IN (?,?)", (first, second))
        joined = self.client.post(f'/api/teacher-photos/{second}/move', json={'group_id': first})
        self.assertEqual(joined.json()['group_id'], first)
        self.assertEqual(len(self.client.get(f'/api/schools/{school["id"]}/teacher-photos').json()['groups']), 1)
        alone = self.client.post(f'/api/teacher-photos/{second}/move', json={}).json()
        self.assertNotEqual(alone['group_id'], first)
        self.assertEqual(self.client.post(f'/api/teacher-photos/{second}/move', json={'group_id': 'missing'}).status_code, 404)

    def test_order_without_catalog_school_cannot_choose(self):
        # Simulate an order created before the catalogue existed.
        with s.db() as con:
            con.execute("UPDATE order_terms SET school_id=NULL WHERE order_id=?", (self.order,))
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

    def test_city_required_and_long_school_name_reaches_cover(self):
        missing = self.client.post('/api/orders', json={'school': 'Новая', 'class_name': '11А', 'copies': 1})
        self.assertEqual(missing.status_code, 422)
        self.assertEqual(self.client.post('/api/schools', json={'name': 'Новая', 'city': '   '}).status_code, 422)
        name = 'Средняя общеобразовательная школа ' + 'А' * 100
        doc = master()
        layers = doc['sections'][1]['spreads'][0]['pages'][0]['layers']
        for index, binding in enumerate(('school', 'city')):
            layers.append({'id': binding, 'type': 'text', 'box': {'x': 10, 'y': 10 + index * 80, 'w': 180, 'h': 70},
                           'text': '', 'binding': binding, 'font': 'Arial', 'fontSize': 12, 'color': '#333333', 'align': 'left'})
        design = self.client.post('/api/master-templates', json={'document': doc})
        self.assertEqual(design.status_code, 201, design.text)
        response = self.client.post('/api/orders', json={'school': name, 'school_city': '  Нижний   Новгород ', 'class_name': '11А', 'copies': 1, 'master_template_id': design.json()['id']})
        self.assertEqual(response.status_code, 201, response.text)
        order_id = response.json()['id']
        order = self.client.get(f'/api/orders/{order_id}').json()
        school = self.client.get(f'/api/schools/{order["school_id"]}').json()
        self.assertEqual((school['name'], school['city'], order['school_city']), (name, 'Нижний Новгород', 'Нижний Новгород'))
        again = self.client.post('/api/orders', json={'school': name.lower(), 'school_city': 'нижний новгород', 'class_name': '11Б', 'copies': 1}).json()['id']
        self.assertEqual(self.client.get(f'/api/orders/{again}').json()['school_id'], school['id'])
        layout = self.client.post(f'/api/orders/{order_id}/layout')
        self.assertEqual(layout.status_code, 200, layout.text)
        document = layout.json()['document']
        spreads = list(document['shared_spreads'].values()) + [sp for variant in document['variant_spreads'].values() for sp in variant.values()]
        texts = [e.get('text') for spread in spreads for e in spread['elements']]
        self.assertIn(name, texts)
        self.assertIn('Нижний Новгород', texts)

    def test_school_change_is_confirmed_atomic_and_blocked_after_print(self):
        from album_factory.school_catalog import snapshot_teachers
        a, b = self.school('Школа А'), self.school('Школа Б', 'Уфа')
        teacher = self.teacher(a['id'], 'Первая')
        order = self.order_for(a['id'])
        self.client.put(f'/api/orders/{order}/teachers', json={'teacher_ids': [teacher['id']], 'class_teacher_id': teacher['id']})
        change = {'school_id': b['id'], 'class_name': '11Б', 'graduation_year': 2027}
        self.assertEqual(self.client.patch(f'/api/orders/{order}', json=change).status_code, 409)
        self.assertEqual(self.client.get(f'/api/orders/{order}').json()['school_id'], a['id'])
        change['confirm_school_change'] = True
        self.assertEqual(self.client.patch(f'/api/orders/{order}', json=change).status_code, 200)
        with s.db() as con:
            self.assertEqual(snapshot_teachers(con, order), [])
        view = self.client.get(f'/api/orders/{order}/teachers').json()
        self.assertFalse(view['chosen'])
        self.assertEqual(self.client.get(f'/api/orders/{order}').json()['school_city'], 'Уфа')
        for stage in ('print', 'delivery', 'archive'):
            with s.db() as con:
                con.execute('UPDATE orders SET stage=? WHERE id=?', (stage, order))
            change['school_id'] = a['id']
            self.assertEqual(self.client.patch(f'/api/orders/{order}', json=change).status_code, 409)

    def test_archived_selection_survives_saving_and_can_be_restored(self):
        school = self.school()
        teacher = self.teacher(school['id'], 'Архивная')
        order = self.order_for(school['id'])
        self.client.put(f'/api/teachers/{teacher["id"]}/portrait', content=jpeg())
        choice = {'teacher_ids': [teacher['id']], 'class_teacher_id': teacher['id']}
        self.client.put(f'/api/orders/{order}/teachers', json=choice)
        self.client.delete(f'/api/teachers/{teacher["id"]}')
        guest, base = self.portal(order, manage=True)
        view = guest.get(base+'/teachers').json()
        self.assertTrue(view['teachers'][0]['archived'])
        self.assertTrue(view['teachers'][0]['selected'])
        self.assertEqual(guest.get(base+f'/teachers/{teacher["id"]}/portrait').status_code, 200)
        self.assertEqual(guest.put(base+'/teachers', json=choice).status_code, 200)
        fresh_order = self.order_for(school['id'])
        self.assertEqual(self.client.put(f'/api/orders/{fresh_order}/teachers', json=choice).status_code, 422)
        self.assertEqual(self.client.post(f'/api/teachers/{teacher["id"]}/restore').status_code, 200)

    def test_teacher_changes_mark_layout_outdated_but_noop_save_does_not(self):
        school = self.school()
        teacher = self.teacher(school['id'], 'Иванова')
        design = self.client.post('/api/master-templates', json={'document': master()}).json()['id']
        order = self.order_for(school['id'], master_template_id=design)
        choice = {'teacher_ids': [teacher['id']]}
        self.client.put(f'/api/orders/{order}/teachers', json=choice)
        def generate():
            response = self.client.post(f'/api/orders/{order}/layout')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertFalse(self.client.get(f'/api/orders/{order}/teachers').json()['layout_outdated'])
        generate()
        self.client.put(f'/api/orders/{order}/teachers', json=choice)
        self.assertFalse(self.client.get(f'/api/orders/{order}/teachers').json()['layout_outdated'])
        self.client.patch(f'/api/teachers/{teacher["id"]}', json={'last_name': 'Исправленная', 'subject': 'Физика'})
        self.assertTrue(self.client.get(f'/api/orders/{order}/teachers').json()['layout_outdated'])
        generate()
        self.client.put(f'/api/teachers/{teacher["id"]}/portrait', content=jpeg())
        self.assertTrue(self.client.get(f'/api/orders/{order}/teachers').json()['layout_outdated'])
        generate()
        self.client.patch(f'/api/schools/{school["id"]}', json={'name': 'Новое название', 'city': 'Москва'})
        self.assertTrue(self.client.get(f'/api/orders/{order}/teachers').json()['layout_outdated'])
        generate()
        with s.db() as con:
            con.execute("UPDATE orders SET stage='print' WHERE id=?", (order,))
        self.client.patch(f'/api/schools/{school["id"]}', json={'name': 'Ещё название', 'city': 'Казань'})
        saved = self.client.get(f'/api/orders/{order}').json()
        self.assertEqual((saved['school'], saved['school_city']), ('Новое название', 'Москва'))

    def test_subject_is_local_to_class_and_duplicate_teacher_rejected(self):
        from album_factory.school_catalog import snapshot_teachers
        school = self.school()
        teacher = self.teacher(school['id'], 'Семёнова')
        duplicate = self.client.post(f'/api/schools/{school["id"]}/teachers', json={'last_name': ' семенова ', 'first_name': 'Мария', 'patronymic': 'Ивановна'})
        self.assertEqual(duplicate.status_code, 409)
        orders = [self.order_for(school['id']) for _ in range(2)]
        for order, subject in zip(orders, ['Алгебра', 'Геометрия']):
            response = self.client.put(f'/api/orders/{order}/teachers', json={'teacher_ids': [teacher['id']], 'subjects': {teacher['id']: subject}})
            self.assertEqual(response.status_code, 200, response.text)
            with s.db() as con:
                self.assertEqual(snapshot_teachers(con, order)[0]['school_subject'], subject)
        self.assertEqual(self.client.get(f'/api/schools/{school["id"]}').json()['teachers'][0]['subject'], 'Математика')

    def test_assignment_undo_restores_frames_and_dedup_survives_signing(self):
        school = self.school()
        teacher = self.teacher(school['id'], 'Отмена')
        self.client.put(f'/api/teachers/{teacher["id"]}/portrait', content=jpeg('#123456'))
        old = self.client.get(f'/api/teachers/{teacher["id"]}/portrait/full').content
        photos = [self.client.post(f'/api/schools/{school["id"]}/teacher-photos?filename={i}.jpg', content=jpeg(color)).json()['id'] for i, color in enumerate(('#ff0000', '#fa0101'))]
        with s.db() as con:
            con.execute("UPDATE teacher_photos SET status='ready',group_id=? WHERE school_id=?", (photos[0], school['id']))
        response = self.client.post(f'/api/teacher-photos/{photos[0]}/assign', json={'teacher_id': teacher['id']})
        self.assertEqual(response.status_code, 200, response.text)
        event = response.json()['assignment_id']
        repeated = self.client.post(f'/api/schools/{school["id"]}/teacher-photos?filename=copy.jpg', content=jpeg('#ff0000'))
        self.assertTrue(repeated.json()['duplicate'])
        self.assertEqual(self.client.get(f'/api/schools/{school["id"]}/teacher-photos').json()['groups'], [])
        self.assertEqual(self.client.post(f'/api/teacher-assignments/{event}/undo').status_code, 200)
        self.assertEqual(self.client.get(f'/api/teachers/{teacher["id"]}/portrait/full').content, old)
        groups = self.client.get(f'/api/schools/{school["id"]}/teacher-photos').json()['groups']
        self.assertEqual({p['id'] for p in groups[0]['photos']}, set(photos))
        self.assertEqual(self.client.post(f'/api/teacher-assignments/{event}/undo').status_code, 409)

    def test_merge_preserves_order_subject_and_lead(self):
        school = self.school()
        source, target = self.teacher(school['id'], 'Дубль'), self.teacher(school['id'], 'Основная')
        order = self.order_for(school['id'])
        self.client.put(f'/api/orders/{order}/teachers', json={'teacher_ids': [source['id']], 'class_teacher_id': source['id'], 'subjects': {source['id']: 'Алгебра'}})
        response = self.client.post(f'/api/teachers/{source["id"]}/merge', json={'target_id': target['id']})
        self.assertEqual(response.status_code, 200, response.text)
        view = self.client.get(f'/api/orders/{order}/teachers').json()
        selected = [t for t in view['teachers'] if t['selected']]
        self.assertEqual([(t['id'], t['subject'], t['is_class_teacher']) for t in selected], [(target['id'], 'Алгебра', True)])


    def test_migration_keeps_city_and_fingerprints_existing_portraits(self):
        school = self.school()
        teacher = self.teacher(school['id'], 'Старая')
        order = self.order_for(school['id'])
        self.client.put(f'/api/teachers/{teacher["id"]}/portrait', content=jpeg('#334455'))
        with s.db() as con:
            con.execute('DELETE FROM teacher_uploads')
            con.execute('ALTER TABLE orders DROP COLUMN school_city')
        s.init_db()
        s.init_db()
        self.assertEqual(self.client.get(f'/api/orders/{order}').json()['school_city'], 'Казань')
        duplicate = self.client.post(f'/api/schools/{school["id"]}/teacher-photos?filename=old.jpg', content=jpeg('#334455'))
        self.assertTrue(duplicate.json()['duplicate'])
        self.assertEqual(self.client.get(f'/api/schools/{school["id"]}/teacher-photos').json()['groups'], [])

    def test_undo_and_merge_are_scoped_to_studio_and_latest_portrait(self):
        school = self.school()
        teacher = self.teacher(school['id'], 'Первая')
        target = self.teacher(school['id'], 'Вторая')
        photo = self.client.post(f'/api/schools/{school["id"]}/teacher-photos?filename=a.jpg', content=jpeg()).json()['id']
        self.assertEqual(self.client.post(f'/api/teacher-photos/{photo}/assign', json={'teacher_id': teacher['id']}).status_code, 409)
        with s.db() as con:
            con.execute("UPDATE teacher_photos SET status='ready' WHERE id=?", (photo,))
        event = self.client.post(f'/api/teacher-photos/{photo}/assign', json={'teacher_id': teacher['id']}).json()['assignment_id']
        other = TestClient(self.client.app)
        other.headers['origin'] = 'http://testserver'
        other.post('/api/register', json={'email': 'isolated@studio.test', 'password': 'secret-pass', 'studio_name': 'Другая'})
        self.assertEqual(other.post(f'/api/teacher-assignments/{event}/undo').status_code, 404)
        self.assertEqual(other.post(f'/api/teachers/{teacher["id"]}/merge', json={'target_id': target['id']}).status_code, 404)
        self.assertEqual(other.post(f'/api/teachers/{teacher["id"]}/restore').status_code, 404)
        self.client.put(f'/api/teachers/{teacher["id"]}/portrait', content=jpeg('#abcdef'))
        self.assertEqual(self.client.post(f'/api/teacher-assignments/{event}/undo').status_code, 409)
        order = self.order_for(school['id'])
        self.client.put(f'/api/orders/{order}/teachers', json={'teacher_ids': [teacher['id']]})
        with s.db() as con:
            con.execute("UPDATE orders SET stage='print' WHERE id=?", (order,))
        self.assertEqual(self.client.post(f'/api/teachers/{teacher["id"]}/merge', json={'target_id': target['id']}).status_code, 409)

    def test_edit_duplicate_teacher_and_wrong_city_are_rejected(self):
        school = self.school()
        first, second = self.teacher(school['id'], 'Первая'), self.teacher(school['id'], 'Вторая')
        response = self.client.patch(f'/api/teachers/{second["id"]}', json={key: first[key] for key in ('last_name','first_name','patronymic','subject')})
        self.assertEqual(response.status_code, 409)
        bad = self.client.post('/api/orders', json={'school_id': school['id'], 'school_city': 'Уфа', 'class_name': '11А', 'copies': 1})
        self.assertEqual(bad.status_code, 409)
        self.assertEqual(self.client.get(f'/api/schools/{school["id"]}').json()['city'], 'Казань')
        with s.db() as con:
            con.execute("UPDATE schools SET city='' WHERE id=?", (school['id'],))
        missing = self.client.post('/api/orders', json={'school_id': school['id'], 'class_name': '11А', 'copies': 1})
        self.assertEqual(missing.status_code, 422)
        fixed = self.client.post('/api/orders', json={'school_id': school['id'], 'school_city': 'Казань', 'class_name': '11А', 'copies': 1})
        self.assertEqual(fixed.status_code, 201)
        self.assertEqual(self.client.get(f'/api/schools/{school["id"]}').json()['city'], 'Казань')


if __name__ == '__main__':
    unittest.main()
