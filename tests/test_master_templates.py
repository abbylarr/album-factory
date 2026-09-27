"""Service acceptance: master versions, ownership, compilation and immutable orders."""
from copy import deepcopy
import unittest
from fastapi.testclient import TestClient
from album_factory import server as s
from album_factory.master_layout import generate
from album_factory.layout_workspace import measurer
import test_server_v2


def master():
    def page(key, layers=None): return {'id':key,'background':'#ffffff','layers':layers or []}
    grid={'id':'grid','type':'grid','box':{'x':16,'y':33,'w':178,'h':224},'source':'students','min':4,'max':12,'gap':5,'minPhotoWidth':32,'font':'Arial','fontSize':12,'minFontSize':10,'color':'#34332f'}
    title={'id':'title','type':'text','box':{'x':15,'y':10,'w':170,'h':25},'text':'Наш класс','binding':'static','font':'Arial','fontSize':22,'color':'#333333','align':'left'}
    return {'schemaVersion':1,'name':'Тестовый дизайн','personalMode':'all','sections':[
        {'id':'students','name':'Ученики','kind':'flow','target':2,'spreads':[{'id':'s1','pages':[page('p1',[grid]),page('p2',[title])]}]},
        {'id':'shared','name':'Общие','kind':'fixed','spreads':[{'id':f'g{i}','pages':[page(f'g{i}l'),page(f'g{i}r')]} for i in range(4)]},
        {'id':'personal','name':'Личные','kind':'repeat','spreads':[{'id':'ps','pages':[page('pl'),page('pr')]}]}]}


class MasterTests(unittest.TestCase):
    setUp = test_server_v2.V2Tests.setUp

    def create(self):
        response=self.client.post('/api/master-templates',json={'document':master()})
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def test_versions_and_conflict_and_isolation(self):
        draft=self.create();key=draft['id']
        published=self.client.post(f'/api/master-templates/{key}/publish',json={'revision':1,'price':1700}).json()
        order=self.client.post('/api/orders',json={'school':'Лицей','class_name':'11А','copies':22,'student_count':22,'offer_id':published['offer_id']}).json()['id']
        changed=master();changed['name']='Новый дизайн'
        self.assertEqual(self.client.put(f'/api/master-templates/{key}',json={'revision':1,'document':changed}).status_code,200)
        self.assertEqual(self.client.put(f'/api/master-templates/{key}',json={'revision':1,'document':changed}).status_code,409)
        self.assertEqual(self.client.post(f'/api/master-templates/{key}/publish',json={'revision':1}).status_code,409)
        with s.db() as con:
            import json
            frozen=json.loads(con.execute('SELECT edition_json FROM order_terms WHERE order_id=?',(order,)).fetchone()[0])
            self.assertEqual(frozen['master']['name'],'Тестовый дизайн')
        other=TestClient(s.app);other.headers['origin']='http://testserver'
        other.post('/api/register',json={'email':'master@other.test','password':'secret-pass','studio_name':'Другая'})
        self.assertEqual(other.get('/api/master-templates').json(),[])
        self.assertEqual(other.get(f'/api/master-templates/{key}').status_code,404)
        self.assertEqual(other.post('/api/offers',json={'title':'Чужой','price':1,'edition_id':published['edition_id']}).status_code,404)

    def test_reject_bad_import(self):
        for mutate in [lambda d:d['sections'][0]['spreads'][0]['pages'][0]['layers'][0]['box'].update(w=-1), lambda d:d['sections'][0]['spreads'][0]['pages'][0]['layers'][0].update(max=0)]:
            doc=master();mutate(doc)
            self.assertEqual(self.client.post('/api/master-templates',json={'document':doc}).status_code,422)

    def test_volume_and_every_student(self):
        for n in [1,22,54,80]:
            snapshot={'students':[{'id':str(i),'first_name':'Ученик','last_name':str(i)} for i in range(n)],'teachers':[],'photos':{},'selections':[],'order':{'class_name':'11А','year':'2026'}}
            doc=generate({'id':'test','version':1,'master':master()},snapshot,measurer())
            self.assertEqual(next(p['spreads'] for p in doc['plan'] if p['section']=='shared'),4)
            self.assertEqual(next(p['spreads'] for p in doc['plan'] if p['section']=='personal'),n)
            first=doc['variant_spreads']['student:0']
            names=[e for spread in first.values() for e in spread['elements'] if e['key'].endswith('/name')]
            self.assertEqual(len(names),n)
            self.assertEqual(len({e['text'] for e in names}),n)
            self.assertTrue(any(i['level']=='error' for i in doc['issues']))

    def test_order_uses_master_and_preserves_manual_edit(self):
        draft=self.create();pub=self.client.post(f'/api/master-templates/{draft["id"]}/publish',json={'revision':1}).json()
        order=self.client.post('/api/orders',json={'school':'Тест','class_name':'9Б','copies':1,'offer_id':pub['offer_id']}).json()['id']
        with s.db() as con: con.execute('INSERT INTO persons VALUES (?,?,?,?)',('missing',order,'Без портрета',s.now()))
        result=self.client.post(f'/api/orders/{order}/layout')
        self.assertEqual(result.status_code,200,result.text)
        doc=result.json()['document'];self.assertTrue(doc['master_template'])
        self.assertEqual(doc['edition']['id'],pub['edition_id'])
        self.assertEqual(len(doc['variants']),1)
        e=next(e for group in doc['variant_spreads'].values() for spread in group.values() for e in spread['elements'] if e['type']=='text' and e['text']=='Наш класс')
        edited=self.client.put(f'/api/orders/{order}/layout/element',json={'revision':doc['revision'],'key':e['key'],'type':'text','value':'Наш выпуск'})
        self.assertEqual(edited.status_code,200,edited.text)
        regenerated=self.client.post(f'/api/orders/{order}/layout').json()['document']
        self.assertIn(e['key'],regenerated['overrides']['applied'])
        self.assertEqual(self.client.get(f'/api/orders/{order}/layout').json()['document']['edition']['id'],pub['edition_id'])

    def test_pdf_shapes_assets_and_text(self):
        import base64
        from io import BytesIO
        from PIL import Image
        from pypdf import PdfReader
        buffer=BytesIO();Image.new('RGB',(600,800),'#bbaaff').save(buffer,'PNG')
        doc=master();doc['sections']=doc['sections'][1:2];doc['sections'][0]['spreads']=doc['sections'][0]['spreads'][:1]
        doc['sections'][0]['spreads'][0]['pages'][0]['layers']=[
            {'id':'asset','type':'photo','box':{'x':10,'y':10,'w':90,'h':120},'source':'custom','angle':12,'radius':8,'stroke':'#333333','strokeWidth':.5,'dataUrl':'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()},
            {'id':'oval','type':'ellipse','box':{'x':110,'y':10,'w':40,'h':40},'fill':'#aabbcc','opacity':50},
            {'id':'caption','type':'text','box':{'x':10,'y':140,'w':180,'h':30},'text':'Проверка PDF','binding':'static','font':'Times New Roman','fontSize':24,'align':'center','color':'#333333'}]
        draft=self.client.post('/api/master-templates',json={'document':doc}).json()
        pub=self.client.post(f'/api/master-templates/{draft["id"]}/publish',json={'revision':1}).json()
        order=self.client.post('/api/orders',json={'school':'Тест','class_name':'9Б','copies':1,'offer_id':pub['offer_id']}).json()['id']
        generated=self.client.post(f'/api/orders/{order}/layout')
        self.assertEqual(generated.status_code,200,generated.text)
        self.assertEqual(generated.json()['document']['issues'],[])
        result=self.client.get(f'/api/orders/{order}/layout/pdf/student:class')
        self.assertEqual(result.status_code,200,result.text[:100] if result.status_code!=200 else '')
        pdf=PdfReader(BytesIO(result.content));self.assertEqual(len(pdf.pages),1)
        self.assertIn('Проверка PDF',pdf.pages[0].extract_text())
        # The published client view must preserve transforms and authorize embedded assets.
        self.assertEqual(self.client.post(f'/api/orders/{order}/layout/publish').status_code,200)
        link=self.client.post(f'/api/orders/{order}/client-link').json()
        token=link['url'].rsplit('/',1)[1]
        self.client.post(f'/client-api/{token}/enter',json={'pin':link['entry_pin']})
        public=self.client.get(f'/client-api/{token}/layout').json()
        asset=next(e for sp in public['variants'][0]['spreads'] for e in sp['elements'] if e['type']=='photo')
        self.assertEqual(asset['angle'],12);self.assertEqual(asset['radius'],8)
        self.assertEqual(self.client.get(f'/client-api/{token}/layout/photos/{asset["photo"]}/full').status_code,200)
        self.assertEqual(self.client.get(f'/client-api/{token}/layout/photos/master-{"0"*64}/full').status_code,404)


    def test_twenty_teachers_lead_is_not_duplicated(self):
        doc=master();doc['sections']=doc['sections'][:1];section=doc['sections'][0];section['id']='teachers'
        grid=section['spreads'][0]['pages'][0]['layers'][0];grid['source']='teachers';grid['excludeLead']=True
        section['spreads'][0]['pages'][1]['layers']=[{'id':'lead','type':'photo','box':{'x':10,'y':10,'w':100,'h':150},'source':'lead'}]
        snapshot={'students':[{'id':'s','first_name':'Ученик'}],'teachers':[{'id':str(i),'first_name':'Учитель','last_name':str(i)} for i in range(20)],'photos':{},'selections':[],'order':{'class_name':'11А','year':'2026'}}
        generated=generate({'id':'test','version':1,'master':doc},snapshot,measurer())
        names=[e['text'] for spread in generated['variant_spreads']['student:s'].values() for e in spread['elements'] if e['key'].endswith('/name')]
        self.assertEqual(len(names),19);self.assertNotIn('Учитель 0',names)

    def test_design_packages_copy_and_shared_library(self):
        response=self.client.post('/api/designs',json={'name':'Осень','package_name':'Стандарт','price':2500,'document':master()})
        self.assertEqual(response.status_code,201,response.text)
        design=response.json();source=design['packages'][0]['template_id']
        copied=self.client.post(f'/api/designs/{design["id"]}/packages',json={'name':'Эконом','price':1500,'source_id':source})
        self.assertEqual(copied.status_code,201,copied.text)
        target=copied.json()['template_id']
        original=self.client.get(f'/api/master-templates/{source}').json()
        copy=self.client.get(f'/api/master-templates/{target}').json()
        self.assertEqual(original['document'],copy['document'])
        changed=deepcopy(copy['document']);changed['sections'].pop()
        self.client.put(f'/api/master-templates/{target}',json={'document':changed,'revision':1})
        self.assertEqual(self.client.get(f'/api/master-templates/{source}').json()['document'],original['document'])
        self.assertEqual(self.client.post(f'/api/designs/{design["id"]}/blocks',json={'name':'Ученики','section':master()['sections'][0]}).status_code,201)
        self.assertEqual(len(self.client.get(f'/api/designs/{design["id"]}').json()['blocks']),1)
        published=self.client.post(f'/api/master-templates/{target}/publish',json={'revision':2})
        self.assertEqual(published.status_code,201,published.text)
        offers=self.client.get('/api/offers').json()
        offer=next(o for o in offers if o['id']==published.json()['offer_id'])
        self.assertEqual(offer['price'],1500);self.assertIn('Осень · Эконом',offer['title'])
        edited=self.client.put(f'/api/master-templates/{target}/package',json={'name':'Лайт','price':1700,'revision':2})
        self.assertEqual(edited.status_code,200)
        self.assertEqual(self.client.put(f'/api/master-templates/{target}/package',json={'name':'Wrong','price':1,'revision':2}).status_code,409)
        self.assertEqual(next(o for o in self.client.get('/api/offers').json() if o['id']==offer['id'])['price'],1500)

    def test_design_access_and_foreign_copy(self):
        first=self.client.post('/api/designs',json={'name':'Первый','document':master()}).json()
        second=self.client.post('/api/designs',json={'name':'Второй','document':master()}).json()
        self.assertEqual(self.client.post(f'/api/designs/{second["id"]}/packages',json={'name':'Копия','source_id':first['packages'][0]['template_id']}).status_code,404)
        other=TestClient(s.app);other.headers['origin']='http://testserver'
        other.post('/api/register',json={'email':'design@other.test','password':'secret-pass','studio_name':'Другая'})
        self.assertEqual(other.get(f'/api/designs/{first["id"]}').status_code,404)
        self.assertEqual(other.post(f'/api/designs/{first["id"]}/blocks',json={'name':'Шаблон','section':master()['sections'][0]}).status_code,404)
