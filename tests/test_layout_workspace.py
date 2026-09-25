"""A real order can advance from portraits to a saved editable layout."""
import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from album_factory import server as s


class LayoutWorkspaceTests(unittest.TestCase):
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
        self.order = self.client.post('/api/orders', json={'school':'Школа', 'class_name':'9 А', 'copies':3}).json()['id']

    def photo(self, person_id=None, kind='portrait', size=(2400, 3300)):
        photo_id, shoot_id = s.uid(), s.uid()
        with s.db() as con:
            con.execute('INSERT INTO shoots (id,order_id,title,kind,created_at) VALUES (?,?,?,?,?)',
                        (shoot_id, self.order, kind, kind, s.now()))
            if person_id:
                con.execute('INSERT INTO persons VALUES (?,?,?,?)', (person_id, self.order, person_id, s.now()))
            con.execute('''INSERT INTO photos (id,order_id,filename,sha,status,person_id,created_at,shoot_id)
                VALUES (?,?,?,?,?,?,?,?)''', (photo_id,self.order,photo_id+'.jpg',photo_id,'ready',person_id,s.now(),shoot_id))
        Image.new('RGB', size, '#d6d8d4').save(s.DATA/'photos'/(photo_id+'.jpg'))
        return photo_id

    def test_generate_edit_and_export(self):
        path=f'/api/orders/{self.order}/layout'
        self.assertEqual(self.client.post(path).status_code,409)
        portraits=[self.photo('student-'+str(i)) for i in range(3)]
        created=self.client.post(path)
        self.assertEqual(created.status_code,200,created.text)
        self.assertEqual({p['person_id'] for p in created.json()['photos']}, {'student-0','student-1','student-2'})
        document=created.json()['document']
        self.assertEqual(len(document['variants']),3)
        self.assertEqual(document['edition'],{'id':'editorial','version':2})
        self.assertTrue({'intro','teachers','moments','story'} <= document['shared_spreads'].keys())
        personal=document['variant_spreads']['student:student-0']['personal[student:student-0]']['elements']
        self.assertTrue(any(e['key'].endswith('/second_portrait') and e['photo'] == portraits[0] for e in personal))
        self.assertTrue(any(e['key'].endswith('/name') and e['box'][1] >= 224 for e in personal))
        self.assertTrue(any(i['code']=='empty_slot' for i in document['issues']))
        self.assertEqual(self.client.get(path).json()['document']['revision'],document['revision'])
        self.assertEqual(self.client.get(path+'/pdf/student:student-0').status_code,409)
        general=self.photo(kind='general',size=(6000,4000))
        self.assertIn(general,{p['id'] for p in self.client.get(path).json()['photos']})
        required={i['key'] for i in document['issues'] if i['code']=='empty_slot'}
        self.assertIn('intro/class_photo',required)
        self.assertIn('teachers/photo_left',required)
        self.assertIn('story/hero',required)
        for key in sorted(required):
            edit=self.client.put(path+'/element',json={'key':key,'type':'photo','value':general,'revision':document['revision']})
            self.assertEqual(edit.status_code,200,edit.text)
            document=edit.json()['document']
        teacher_name=self.client.put(path+'/element',json={'key':'teachers/left_name','type':'text','value':'Елена Иванова','revision':document['revision']})
        self.assertEqual(teacher_name.status_code,200,teacher_name.text)
        document=teacher_name.json()['document']
        self.assertEqual([i for i in document['issues'] if i['level']=='error'],[])
        added=self.client.post(path+'/spreads',json={'revision':document['revision'],'after_index':2})
        self.assertEqual(added.status_code,200,added.text)
        custom=added.json()['added_spread']
        document=added.json()['document']
        self.assertEqual(document['spread_count'],created.json()['document']['spread_count']+1)
        self.assertEqual(document['variants'][0]['sequence'][3],custom)
        self.assertTrue(all(v['sequence'][3]==custom for v in document['variants']))
        for side,template in [('left','editorial'),('right','grid')]:
            changed=self.client.put(f'{path}/spreads/{custom}/pages/{side}',json={'revision':document['revision'],'template':template})
            self.assertEqual(changed.status_code,200,changed.text)
            document=changed.json()['document']
        self.assertEqual(document['shared_spreads'][custom]['page_templates'],{'left':'editorial','right':'grid'})
        slot=custom+'/left/photo1'
        edited=self.client.put(path+'/element',json={'key':slot,'type':'photo','value':general,'revision':document['revision']})
        self.assertEqual(edited.status_code,200,edited.text)
        document=edited.json()['document']
        self.assertEqual(document['shared_spreads'][custom]['elements'][0]['photo'],general)
        caption=self.client.put(path+'/element',json={'key':custom+'/left/caption','type':'text','value':'Наш класс','revision':document['revision']})
        self.assertEqual(caption.status_code,200,caption.text)
        document=caption.json()['document']
        for template in ('blank','editorial'):
            changed=self.client.put(f'{path}/spreads/{custom}/pages/left',json={'revision':document['revision'],'template':template})
            self.assertEqual(changed.status_code,200,changed.text)
            document=changed.json()['document']
        restored=document['shared_spreads'][custom]['elements']
        self.assertEqual(next(e for e in restored if e['key']==slot)['photo'],general)
        self.assertEqual(next(e for e in restored if e['key']==custom+'/left/caption')['text'],'Наш класс')
        self.assertEqual(self.client.get(path).json()['document']['revision'],document['revision'])
        refreshed=self.client.post(path)
        self.assertEqual(refreshed.status_code,200,refreshed.text)
        document=refreshed.json()['document']
        self.assertIn(custom,document['shared_spreads'])
        self.assertEqual(document['shared_spreads'][custom]['page_templates'],{'left':'editorial','right':'grid'})
        pdf=self.client.get(path+'/pdf/student:student-0')
        self.assertEqual(pdf.status_code,200,pdf.text[:200] if pdf.status_code!=200 else '')
        self.assertTrue(pdf.content.startswith(b'%PDF'))
        from pypdf import PdfReader
        from io import BytesIO
        self.assertEqual(len(PdfReader(BytesIO(pdf.content)).pages),document['spread_count']+1)
        self.assertEqual(self.client.request('DELETE',f'{path}/spreads/{custom}',json={'revision':'stale'}).status_code,409)
        removed=self.client.request('DELETE',f'{path}/spreads/{custom}',json={'revision':document['revision']})
        self.assertEqual(removed.status_code,200,removed.text)
        self.assertNotIn(custom,removed.json()['document']['shared_spreads'])
        self.assertTrue(all(custom not in v['sequence'] for v in removed.json()['document']['variants']))
        document=removed.json()['document']
        self.assertEqual(self.client.get('/api/orders').json()[0]['stage'],'layout')
        other=self.client.post('/api/orders',json={'school':'Другая','class_name':'1 А','copies':1}).json()['id']
        self.assertEqual(self.client.get(f'/api/orders/{other}/layout').status_code,404)
        self.assertEqual(self.client.put(path+'/element',json={'key':'intro/class_photo','type':'photo','value':'missing','revision':document['revision']}).status_code,422)

    def test_existing_layout_upgrades_to_editorial_on_open(self):
        for index in range(3):
            self.photo('student-'+str(index))
        path=f'/api/orders/{self.order}/layout'
        created=self.client.post(path)
        self.assertEqual(created.status_code,200,created.text)
        with s.db() as con:
            document=created.json()['document']
            document['edition']={'id':'classic','version':1}
            con.execute('UPDATE order_layouts SET document=? WHERE order_id=?',(json.dumps(document),self.order))
        upgraded=self.client.get(path)
        self.assertEqual(upgraded.status_code,200,upgraded.text)
        self.assertEqual(upgraded.json()['document']['edition'],{'id':'editorial','version':2})
        self.assertIn('teachers',upgraded.json()['document']['shared_spreads'])
