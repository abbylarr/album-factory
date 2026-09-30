"""Production exports must match the published document, recipients and frozen assets."""
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import unittest
import zipfile
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from pypdf import PdfReader
from album_factory import server as s
import test_server_v2


def control_design():
    def page(key, layers=()):
        return {'id': key, 'background': '#faf8f2', 'layers': list(layers)}
    def text(key, value, box, size=14):
        return {'id': key, 'type': 'text', 'box': dict(zip(('x','y','w','h'), box)), 'text': value,
                'font': 'Arial', 'fontSize': size, 'color': '#263b4b', 'align': 'left'}
    portrait = {'id': 'portrait', 'type': 'photo', 'box': {'x': 12, 'y': 42, 'w': 96, 'h': 100}, 'source': 'owner'}
    return {'schemaVersion': 1, 'name': 'Контроль производства', 'personalMode': 'all', 'pageSize': [120, 160], 'sections': [
        {'id': 'cover', 'name': 'Обложка', 'kind': 'fixed', 'cover': True, 'pageSize': [120, 160], 'spreads': [{'id': 'c', 'pages': [
            page('back', [text('class', '9Б · 2026', [14, 24, 94, 24], 22)]),
            page('front', [text('title', 'НАШ КЛАСС', [12, 12, 100, 25], 22), {**portrait, 'id': 'cover-portrait'}])]}]},
        {'id': 'personal', 'name': 'Личные', 'kind': 'repeat', 'spreads': [{'id': 'p', 'pages': [
            page('left', [text('name', '{{owner.name}}', [12, 16, 96, 20], 18), portrait]),
            page('right', [text('caption', 'СОГЛАСОВАНО', [12, 32, 96, 22], 18), text('quote', '{{owner.quote}}', [12, 70, 96, 30])])]}]}]}


class ProductionExportTests(unittest.TestCase):
    setUp = test_server_v2.V2Tests.setUp

    def control_order(self):
        draft = self.client.post('/api/master-templates', json={'document': control_design()})
        self.assertEqual(draft.status_code, 201, draft.text)
        pub = self.client.post(f"/api/master-templates/{draft.json()['id']}/publish", json={'revision': 1})
        self.assertEqual(pub.status_code, 201, pub.text)
        order = self.client.post('/api/orders', json={'school_city': 'Казань', 'school': 'Контрольный лицей', 'class_name': '9Б',
                                                      'copies': 3, 'graduation_year': 2026, 'offer_id': pub.json()['offer_id']})
        self.assertEqual(order.status_code, 201, order.text)
        self.order = order.json()['id']
        shoot = self.client.post(f'/api/orders/{self.order}/shoots', json={'kind': 'portrait', 'title': 'Контрольные портреты'}).json()['id']
        people, photos = [], []
        for index, color in enumerate(('#ca784b', '#5182a0', '#729365')):
            image = Image.new('RGB', (1200, 1600), color)
            draw = ImageDraw.Draw(image); draw.rectangle((140, 220, 1060, 1380), outline='#faf8f2', width=30)
            draw.ellipse((400, 400, 800, 800), fill='#f4d3a5')
            body = BytesIO(); image.save(body, 'JPEG', quality=95)
            uploaded = self.client.post(f'/api/orders/{self.order}/photos', params={'filename': f'control-{index}.jpg', 'shoot_id': shoot},
                                        content=body.getvalue(), headers={'content-type': 'image/jpeg'})
            self.assertEqual(uploaded.status_code, 201, uploaded.text)
            photo = uploaded.json()['id']; photos.append(photo)
            # Synthetic cards have no faces: replace worker recognition only, then use the real manual grouping API.
            with s.db() as con:
                con.execute("UPDATE photos SET status='ready' WHERE id=?", (photo,))
            moved = self.client.post(f'/api/orders/{self.order}/move', json={'photo_ids': [photo]})
            self.assertEqual(moved.status_code, 200, moved.text)
            people.append(moved.json()['person_id'])
        link = self.client.post(f'/api/orders/{self.order}/client-link').json()
        base = '/client-api/'+link['url'].rsplit('/', 1)[1]
        self.client.post(base+'/enter', json={'pin': link['entry_pin']})
        for index, (person, photo) in enumerate(zip(people, photos)):
            response = self.client.put(base+'/persons/'+person, json={'photo_id': photo, 'first_name': ['Анна','Борис','Вера'][index],
                'last_name': 'Тестовая', 'quote': 'Наш выпуск 2026'})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(self.client.post(base+'/persons/'+person+'/submit').status_code, 200)
        generated = self.client.post(f'/api/orders/{self.order}/layout')
        self.assertEqual(generated.status_code, 200, generated.text)
        document = generated.json()['document']
        self.assertFalse([i for i in document['issues'] if i['level']=='error'])
        self.assertEqual(self.client.post(f'/api/orders/{self.order}/layout/publish').status_code, 200)
        self.client.post(base+'/manage', json={'pin': link['manage_pin']})
        summary = self.client.get(base+'/summary').json()
        saved = self.client.put(base+'/summary', json={'allocations': summary['allocations'], 'paid_total': 3,
                                                      'delivery': {'mode': 'personal', 'recipient': 'Ирина Контрольная'}})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(self.client.post(base+'/approve', json={'hash': saved.json()['hash']}).status_code, 200)
        return base, document, people, photos

    def authorize(self, owner):
        response = self.client.post(f'/api/orders/{self.order}/production', json={'gift_owner': owner})
        self.assertEqual(response.status_code, 200, response.text)
        exported = self.client.get(f'/api/orders/{self.order}/export')
        self.assertEqual(exported.status_code, 200, exported.text)
        return exported.json()

    def test_end_to_end_real_pdf_jpeg_bundle_and_download_access(self):
        _, document, people, _ = self.control_order()
        manifest = self.authorize('student:'+people[0])
        self.assertEqual(manifest['total'], 4)
        self.assertEqual(len(manifest['files']), 4)
        self.assertEqual(manifest['revision'], document['revision'])
        for row in manifest['files']:
            pdf = self.client.get(f"/api/orders/{self.order}/export/files/{row['name']}")
            self.assertEqual(pdf.status_code, 200)
            reader = PdfReader(BytesIO(pdf.content))
            self.assertEqual(len(reader.pages), len(next(v for v in document['variants'] if v['owner']==row['owner'])['sequence']))
            self.assertTrue(any(page.images for page in reader.pages))
            text = ''.join(page.extract_text() for page in reader.pages)
            self.assertIn('СОГЛАСОВАНО', text)
            self.assertNotIn('{owner.', text)
            self.assertIn('Тестовая', text)
            jpeg = self.client.get(f"/api/orders/{self.order}/export/files/{row['jpeg_name']}")
            with zipfile.ZipFile(BytesIO(jpeg.content)) as archive:
                self.assertIn('cover.jpg', archive.namelist())
                for name in archive.namelist():
                    with Image.open(BytesIO(archive.read(name))) as image:
                        self.assertEqual(image.mode, 'RGB')
                        self.assertAlmostEqual(image.info['dpi'][0], 300, delta=1)
                        self.assertTrue(image.info.get('icc_profile'))
        bundle = self.client.get(f'/api/orders/{self.order}/export/download')
        self.assertEqual(bundle.status_code, 200)
        with zipfile.ZipFile(BytesIO(bundle.content)) as archive:
            self.assertIn('manifest.json', archive.namelist())
            self.assertEqual(json.loads(archive.read('manifest.json'))['total'], 4)
            self.assertEqual(len(archive.namelist()), 9)
        self.assertEqual(self.client.get(f'/api/orders/{self.order}/export').json(), manifest)
        other = TestClient(s.app); other.headers['origin']='http://testserver'
        other.post('/api/register', json={'email':'print@other.test','password':'secret-pass','studio_name':'Другие'})
        self.assertEqual(other.get(f'/api/orders/{self.order}/export/download').status_code, 404)
        self.assertEqual(self.client.get(f'/api/orders/{self.order}/export/files/manifest.json').status_code, 404)

    def test_every_mutation_is_blocked_and_read_uses_frozen_source(self):
        _, document, people, photos = self.control_order()
        manifest = self.authorize('student:'+people[0])
        revision = document['revision']
        key = next(e['key'] for group in document['variant_spreads'].values() for spread in group.values() for e in spread['elements'] if e['type']=='text')
        path = f'/api/orders/{self.order}/layout'
        requests = [('post', path+'/edits', {'revision':revision,'ops':[{'key':key,'type':'text','value':'ПОДМЕНА'}]}),
                    ('put', path+'/overrides', {'revision':revision,'overrides':[]}),
                    ('post', path, {}), ('put',path+'/element',{'revision':revision,'key':key,'type':'text','value':'ПОДМЕНА'}),
                    ('post',path+'/spreads',{'revision':revision,'after_index':0}),
                    ('put',path+'/spreads/custom/pages/left',{'revision':revision,'template':'blank'}),
                    ('delete',path+'/spreads/custom',{'revision':revision}),
                    ('put',path+'/reviews',{'owner':'student:'+people[0],'reviewed':True}), ('post',path+'/publish',{})]
        for stage in ('print', 'delivery', 'archive', 'layout'):
            with s.db() as con:
                con.execute('UPDATE orders SET stage=? WHERE id=?',(stage,self.order))
            for method, url, payload in requests:
                with self.subTest(stage=stage,endpoint=url):
                    self.assertEqual(self.client.request(method,url,json=payload).status_code,409)
        with s.db() as con:
            self.assertEqual(json.loads(con.execute('SELECT document FROM order_layouts WHERE order_id=?',(self.order,)).fetchone()[0]),document)
            changed = deepcopy(document); changed['revision']='tampered-draft'
            con.execute('UPDATE order_layouts SET document=? WHERE order_id=?',(json.dumps(changed),self.order))
        (s.DATA/'photos'/f'{photos[0]}.jpg').unlink()
        viewed=self.client.get(path).json()
        self.assertEqual(viewed['document']['revision'],revision)
        self.assertTrue(viewed['status']['locked'])
        self.assertFalse([i for i in viewed['document']['issues'] if i['level']=='error'])
        self.assertEqual(self.client.get(viewed['photos'][0]['url']).status_code,200)
        self.assertEqual(self.client.get(path+'/pdf/student:'+people[0]).content,
                         self.client.get(f"/api/orders/{self.order}/export/files/{next(r for r in manifest['files'] if r['owner']=='student:'+people[0])['name']}").content)
        self.assertEqual(self.client.get(path+'/print/student:'+people[0]).status_code,200)

    def test_export_uses_publication_even_if_draft_changes_before_authorization(self):
        _, document, people, _=self.control_order()
        with s.db() as con:
            changed=deepcopy(document);changed['revision']='unapproved'
            for group in changed['variant_spreads'].values():
                for spread in group.values():
                    for e in spread['elements']:
                        if e.get('text')=='СОГЛАСОВАНО':e['text']='НЕ СОГЛАСОВАНО'
            con.execute('UPDATE order_layouts SET document=? WHERE order_id=?',(json.dumps(changed),self.order))
        manifest=self.authorize('student:'+people[0])
        pdf=self.client.get(f"/api/orders/{self.order}/export/files/{manifest['files'][0]['name']}")
        self.assertNotIn('НЕ СОГЛАСОВАНО',''.join(p.extract_text() for p in PdfReader(BytesIO(pdf.content)).pages))
        self.assertEqual(manifest['revision'],document['revision'])

    def test_invalid_gift_and_missing_recipient_never_authorize(self):
        _, document, people, _=self.control_order()
        for payload in ({}, {'gift_owner':'missing'}):
            self.assertEqual(self.client.post(f'/api/orders/{self.order}/production',json=payload).status_code,409)
        with s.db() as con:
            self.assertIsNone(con.execute('SELECT 1 FROM authorizations WHERE order_id=?',(self.order,)).fetchone())
            self.assertIsNone(con.execute('SELECT 1 FROM production_snapshots WHERE order_id=?',(self.order,)).fetchone())
            source=json.loads(con.execute('SELECT source FROM publication_sources WHERE order_id=?',(self.order,)).fetchone()[0])
            source['document']['variants']=[v for v in source['document']['variants'] if v['owner']!='student:'+people[1]]
            con.execute('UPDATE publication_sources SET source=? WHERE order_id=?',(json.dumps(source),self.order))
        self.assertEqual(self.client.post(f'/api/orders/{self.order}/production',json={'gift_owner':'student:'+people[0]}).status_code,409)

    def test_corrupt_or_missing_cached_files_are_rebuilt_and_cleanup_removes_sources(self):
        _, _, people, _=self.control_order()
        manifest=self.authorize('student:'+people[0])
        folder=s.DATA/'exports'/self.order/manifest['layout_hash']
        file=folder/manifest['files'][0]['name'];file.write_bytes(b'old-stub')
        (folder/'print-bundle.zip').unlink()
        refreshed=self.client.get(f'/api/orders/{self.order}/export')
        self.assertEqual(refreshed.status_code,200,refreshed.text)
        self.assertEqual(hashlib.sha256(file.read_bytes()).hexdigest(),refreshed.json()['checksums'][file.name])
        self.assertEqual(self.client.delete(f'/api/orders/{self.order}').status_code,200)
        self.assertFalse((s.DATA/'production'/self.order).exists())
        self.assertFalse((s.DATA/'exports'/self.order).exists())
