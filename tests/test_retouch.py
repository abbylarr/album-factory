"""Real file replacement, scoping, review invalidation and original archive export."""
from io import BytesIO
import json
import unittest
import zipfile
from unittest.mock import patch
from PIL import Image
from album_factory import server as s, shoots, retouch
import test_server_v2


class RetouchTests(unittest.TestCase):
    setUp = test_server_v2.V2Tests.setUp
    photo = test_server_v2.V2Tests.photo

    def selected(self, filename='DSC00298.jpg', person='person', shoot_id=None):
        photo = self.photo(person=person)
        with s.db() as con:
            shoot_id = shoot_id or shoots.default_portrait(con, self.order)
            con.execute('UPDATE photos SET filename=?,shoot_id=? WHERE id=?', (filename, shoot_id, photo))
        result = self.client.put(f'/api/orders/{self.order}/persons/{person}/choice', json={'photo_id': photo})
        self.assertEqual(result.status_code, 200, result.text)
        return photo

    def upload(self, filename='DSC00298-Edit.jpg', order=None, body=None, shoot_id=None):
        if body is None:
            out = BytesIO()
            Image.new('RGB', (20, 20), 'red').save(out, 'JPEG')
            body = out.getvalue()
        return self.client.post(f'/api/orders/{order or self.order}/retouched',
                                params={'filename': filename, **({'shoot_id': shoot_id} if shoot_id else {})}, content=body)

    def test_replace_keeps_identity_original_quote_and_choice(self):
        photo = self.selected()
        original = (s.DATA / 'photos' / (photo+'.original')).read_bytes()
        with s.db() as con:
            con.execute("UPDATE client_selections SET first_name='Анна',last_name='Иванова',quote='Спасибо!' WHERE person_id='person'")
        response = self.upload()
        self.assertEqual(response.json()['status'], 'replaced')
        order = self.client.get(f'/api/orders/{self.order}').json()
        self.assertEqual(len(order['photos']), 1)
        self.assertTrue(order['photos'][0]['retouch_version'])
        self.assertEqual(order['retouch']['done'], 1)
        self.assertEqual(order['persons'][0]['quote'], 'Спасибо!')
        self.assertEqual(order['persons'][0]['choice_source'], 'photographer')
        self.assertEqual(order['persons'][0]['selected_photo_id'], photo)
        self.assertEqual((s.DATA/'photos'/(photo+'.original')).read_bytes(), original)
        self.assertNotEqual((s.DATA/'photos'/(photo+'.jpg')).read_bytes(), original)
        self.assertEqual(len(list((s.DATA/'photos').iterdir())), 3)

    def test_suffixes_and_named_archive_round_trip(self):
        self.selected()
        for name in ['DSC00298.jpg','DSC00298-Edit.jpg','DSC00298-Edit-2.jpg','DSC00298-2.jpg','DSC00298 copy.jpg','Анна Иванова — DSC00298-Edit.jpg']:
            self.assertEqual(self.upload(name).json()['status'], 'replaced', name)

    def test_unknown_and_unselected_are_not_imported(self):
        self.selected()
        other = self.photo()
        with s.db() as con:
            con.execute("UPDATE photos SET filename='DSC00300.jpg' WHERE id=?", (other,))
        self.assertEqual(self.upload('DSC00300-Edit.jpg').json()['status'], 'not_chosen')
        self.assertEqual(self.upload('no-pair.jpg').json()['status'], 'unknown')
        self.assertEqual(len(list((s.DATA/'photos').iterdir())), 6)

    def test_ambiguous_names_require_shoot_scope(self):
        first = self.selected()
        with s.db() as con:
            second_shoot = shoots.create(con, self.order, 'portrait', 'Вторая')
        second = self.selected(person='other', shoot_id=second_shoot)
        self.assertEqual(self.upload().json()['status'], 'ambiguous')
        self.assertEqual(self.upload(shoot_id=second_shoot).json()['photo_id'], second)
        with s.db() as con:
            self.assertIsNone(con.execute('SELECT 1 FROM photo_retouch WHERE photo_id=?', (first,)).fetchone())

    def test_exact_numeric_camera_filename_wins(self):
        self.selected('DSC00298.jpg')
        second = self.selected('DSC00298-2.jpg', person='other')
        self.assertEqual(self.upload('DSC00298-2.jpg').json()['photo_id'], second)

    def test_bad_image_does_not_damage_old_files(self):
        photo = self.selected()
        before = (s.DATA/'photos'/(photo+'.jpg')).read_bytes()
        self.assertEqual(self.upload(body=b'not a photo').status_code, 415)
        self.assertEqual((s.DATA/'photos'/(photo+'.jpg')).read_bytes(), before)
        self.assertEqual(len(list((s.DATA/'photos').iterdir())), 3)

    def test_print_lock_applies_to_replacement_and_choice(self):
        photo = self.selected()
        with s.db() as con:
            con.execute("UPDATE orders SET stage='print' WHERE id=?", (self.order,))
        self.assertEqual(self.upload().status_code, 409)
        self.assertEqual(self.client.put(f'/api/orders/{self.order}/persons/person/choice', json={'photo_id': photo}).status_code, 409)
        self.assertEqual(len(list((s.DATA/'photos').iterdir())), 3)

    def test_archive_contains_camera_bytes_and_names_and_todo(self):
        photo = self.selected()
        original = (s.DATA/'photos'/(photo+'.original')).read_bytes()
        self.upload()
        response = self.client.get(f'/api/orders/{self.order}/chosen/archive')
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(BytesIO(response.content)) as z:
            self.assertEqual(z.namelist(), ['Имя — DSC00298.jpg'])
            self.assertEqual(z.read(z.namelist()[0]), original)
        self.assertEqual(self.client.get(f'/api/orders/{self.order}/chosen/archive?todo=true').status_code, 409)
        with zipfile.ZipFile(BytesIO(self.client.get(f'/api/orders/{self.order}/chosen/archive?names=false').content)) as z:
            self.assertEqual(z.namelist(), ['DSC00298.jpg'])

    def layout(self, photo):
        snapshot = {'photos': {photo: {'path': str(s.DATA/'photos'/(photo+'.jpg')), 'width': 10, 'height': 10}}}
        document = {'revision':'old','issues':[], 'shared_spreads':{}, 'covers':{}, 'variants':[],
                    'variant_spreads':{'student:person':{'one':{'elements':[{'type':'photo','photo':photo,'width':10,'height':10,'crop':[1,2,5,6],'box':[1,2,30,40]}]}}}}
        with s.db() as con:
            con.execute('INSERT INTO order_layouts VALUES (?,?,?,?,?)', (self.order,json.dumps(snapshot),json.dumps(document),'[]',s.now()))
            con.execute("UPDATE orders SET stage='approval' WHERE id=?", (self.order,))
        return document

    def test_layout_keeps_boxes_and_updates_crop_resolution_and_revision(self):
        photo = self.selected()
        self.layout(photo)
        self.assertEqual(self.upload().json()['status'], 'replaced')
        with s.db() as con:
            row = con.execute('SELECT * FROM order_layouts WHERE order_id=?', (self.order,)).fetchone()
            doc = json.loads(row['document'])
            element = doc['variant_spreads']['student:person']['one']['elements'][0]
            self.assertEqual(element['box'], [1,2,30,40])
            self.assertEqual(element['crop'], [2,4,10,12])
            self.assertTrue(element['asset_version'])
            self.assertNotEqual(doc['revision'], 'old')
            self.assertEqual(con.execute('SELECT stage FROM orders WHERE id=?', (self.order,)).fetchone()[0], 'layout')

    def test_failure_rolls_back_derivatives_and_database(self):
        photo = self.selected()
        before = (s.DATA/'photos'/(photo+'.jpg')).read_bytes()
        with patch.object(retouch, 'update_layout', side_effect=RuntimeError('failed')), self.assertRaises(RuntimeError):
            self.upload()
        self.assertEqual((s.DATA/'photos'/(photo+'.jpg')).read_bytes(), before)
        with s.db() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM photo_retouch').fetchone()[0], 0)

    def test_publication_requires_explicit_unretouched_override(self):
        photo = self.selected()
        self.layout(photo)
        self.assertEqual(self.client.put(f'/api/orders/{self.order}/retouch',json={'mode':'retouch'}).status_code, 200)
        response = self.client.post(f'/api/orders/{self.order}/layout/publish')
        self.assertEqual(response.status_code,409)
        self.assertIn('Не обработано',response.text)
        with patch('album_factory.production.save_publication_source'):
            self.assertEqual(self.client.post(f'/api/orders/{self.order}/layout/publish?allow_unretouched=true').status_code,200)

    def test_foreign_order_and_shoot_cannot_replace(self):
        self.selected()
        self.assertEqual(self.upload(shoot_id='foreign').json()['status'], 'unknown')
        self.assertEqual(self.upload(order='missing').status_code, 404)
        self.assertEqual(len(list((s.DATA/'photos').iterdir())), 3)

    def test_general_photo_cannot_be_portrait_choice(self):
        photo = self.photo()
        with s.db() as con:
            shoot = shoots.create(con,self.order,'general','Общая')
            con.execute('UPDATE photos SET shoot_id=? WHERE id=?',(shoot,photo))
        self.assertEqual(self.client.put(f'/api/orders/{self.order}/persons/person/choice',json={'photo_id':photo}).status_code,409)

    def test_real_layout_review_invalidated_and_version_survives_rebuild(self):
        from album_factory.layout_workspace import fingerprints
        self.selected()
        self.selected('DSC00301.jpg', person='second')
        self.selected('DSC00302.jpg', person='third')
        response = self.client.post(f'/api/orders/{self.order}/layout', json={})
        self.assertEqual(response.status_code, 200, response.text)
        before = response.json()['document']
        self.assertEqual(self.upload().json()['status'], 'replaced')
        with s.db() as con:
            row = con.execute('SELECT document FROM order_layouts WHERE order_id=?', (self.order,)).fetchone()
            after = json.loads(row['document'])
        self.assertNotEqual(before['revision'], after['revision'])
        self.assertNotEqual(fingerprints(before), fingerprints(after))
        rebuilt = self.client.post(f'/api/orders/{self.order}/layout', json={})
        self.assertEqual(rebuilt.status_code, 200, rebuilt.text)
        self.assertIn('asset_version', json.dumps(rebuilt.json()['document']))
