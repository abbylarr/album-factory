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
    title={'id':'title','type':'text','box':{'x':15,'y':10,'w':170,'h':25},'text':'Наш класс','font':'Arial','fontSize':22,'color':'#333333','align':'left'}
    return {'schemaVersion':1,'name':'Тестовый дизайн','personalMode':'all','sections':[
        {'id':'students','name':'Ученики','kind':'flow','target':2,'spreads':[{'id':'s1','pages':[page('p1',[grid]),page('p2',[title])]}]},
        {'id':'shared','name':'Общие','kind':'fixed','spreads':[{'id':f'g{i}','pages':[page(f'g{i}l'),page(f'g{i}r')]} for i in range(4)]},
        {'id':'personal','name':'Личные','kind':'repeat','spreads':[{'id':'ps','pages':[page('pl'),page('pr')]}]}]}


class MasterTests(unittest.TestCase):
    setUp = test_server_v2.V2Tests.setUp

    def test_order_can_choose_saved_master_now_or_at_generation(self):
        import json
        draft = self.client.post('/api/master-templates', json={'document':master()})
        self.assertEqual(draft.status_code,201,draft.text)
        key = draft.json()['id']
        created = self.client.post('/api/orders', json={'school_city':'Казань', 'school':'Тест','class_name':'9 Б','copies':10,'master_template_id':key})
        self.assertEqual(created.status_code,201,created.text)
        order_id = created.json()['id']
        self.assertEqual(self.client.get('/api/orders/'+order_id).json()['master_template_id'],key)
        with s.db() as con:
            saved = json.loads(con.execute('SELECT edition_json FROM order_terms WHERE order_id=?',(order_id,)).fetchone()[0])
            self.assertEqual(saved['master']['name'],'Тестовый дизайн')
            self.assertEqual(con.execute('SELECT COUNT(*) FROM offers').fetchone()[0],0)
        self.assertEqual(self.client.post('/api/orders',json={'school_city':'Казань', 'school':'Тест','class_name':'9','copies':10,'master_template_id':'missing'}).status_code,404)
        generated = self.client.post(f'/api/orders/{self.order}/layout',json={'master_template_id':key})
        self.assertEqual(generated.status_code,200,generated.text)
        self.assertEqual(self.client.get('/api/orders/'+self.order).json()['master_template_id'],key)
        self.assertEqual(self.client.post(f'/api/orders/{self.order}/layout',json={'master_template_id':'missing'}).status_code,404)
        self.assertEqual(self.client.get('/api/orders/'+self.order).json()['master_template_id'],key)

    def test_order_price_comes_from_package_and_school_from_catalog(self):
        design = self.client.post('/api/designs', json={'name':'Сентябрь','package_name':'Стандарт','price':2500,'document':master()}).json()
        package = design['packages'][0]
        self.assertEqual(package['summary']['spreads'],6)
        school = self.client.post('/api/schools', json={'city':'Казань', 'name':'Лицей № 1'}).json()
        self.assertEqual(self.client.post('/api/schools', json={'city':'Казань', 'name':' лицей  № 1 '}).json()['id'],school['id'])
        created = self.client.post('/api/orders', json={'school_id':school['id'],'class_name':'9 Б','copies':10,'price':99,'master_template_id':package['template_id']})
        self.assertEqual(created.status_code,201,created.text)
        order = self.client.get('/api/orders/'+created.json()['id']).json()
        self.assertEqual((order['school'],order['price']),('Лицей № 1',2500))
        self.assertEqual(self.client.post('/api/orders', json={'school_id':'missing','class_name':'9','copies':1}).status_code,404)
        cheaper = self.client.post(f'/api/designs/{design["id"]}/packages', json={'name':'Эконом','price':1500,'source_id':package['template_id']}).json()
        self.assertEqual(self.client.post(f'/api/orders/{self.order}/layout',json={'master_template_id':cheaper['template_id']}).status_code,200)
        self.assertEqual(self.client.get('/api/orders/'+self.order).json()['price'],1500)

    def test_photo_crop_zoom_is_saved_in_compiled_layout(self):
        doc = master()
        photo = {'id':'portrait','type':'photo','box':{'x':20,'y':40,'w':100,'h':50},
                 'source':'owner','cropX':50,'cropY':50,'cropZoom':2}
        doc['sections'][0]['spreads'][0]['pages'][1]['layers'].append(photo)
        snapshot = {'students':[{'id':'1','first_name':'Ученик','last_name':'Один'}],
                    'teachers':[], 'photos':{'photo-1':{'width':400,'height':400,'path':'unused'}},
                    'selections':[{'owner':'student:1','role':'main_portrait','photo':'photo-1'}],
                    'order':{'class_name':'11А','year':'2026'}}
        compiled = generate({'id':'test','version':1,'master':doc},snapshot,measurer())
        rendered = next(e for spread in compiled['variant_spreads']['student:1'].values()
                        for e in spread['elements'] if e.get('key','').endswith('/portrait'))
        self.assertEqual(rendered['crop'],[100,150,200,100])
        photo['cropZoom'] = 4.1
        self.assertEqual(self.client.post('/api/master-templates',json={'document':doc}).status_code,422)

    def test_photo_roles_and_album_rules_are_validated_and_previewed(self):
        doc = master()
        slot = {'id':'moment','type':'photo','box':{'x':20,'y':40,'w':100,'h':70},'source':'class','pick':{'role':'hero','scale':['full','wide']}}
        doc['sections'][1]['spreads'][0]['pages'][0]['layers'].append(slot)
        doc['photoRules'] = {'reuse':'section','rhythm':True,'chronology':False}
        self.assertEqual(self.client.post('/api/master-templates',json={'document':doc}).status_code,201)
        preview = self.client.post('/api/master-templates/photo-preview',json={'document':doc,'students':6,'teachers':0,'owner':'s2'})
        self.assertEqual(preview.status_code,200,preview.text)
        self.assertIn('shared:0/moment',preview.json()['slots'])
        for bad in ({'role':'unknown'},{'role':'any','scale':['huge']},{'role':'any','include':'item'},{'role':'any','extra':1},{'role':'any','buckets':['pair','pair']}):
            broken = deepcopy(doc); broken['sections'][1]['spreads'][0]['pages'][0]['layers'][0]['pick'] = bad
            self.assertEqual(self.client.post('/api/master-templates',json={'document':broken}).status_code,422,bad)
        personal = deepcopy(doc); personal['sections'][2]['spreads'][0]['pages'][0]['layers'].append({**slot,'id':'with','pick':{'role':'with_item'}})
        self.assertEqual(self.client.post('/api/master-templates',json={'document':personal}).status_code,201)
        for rules in ({'reuse':'never'},{'rhythm':'yes'},{'other':1}):
            broken = deepcopy(doc); broken['photoRules'] = rules
            self.assertEqual(self.client.post('/api/master-templates',json={'document':broken}).status_code,422,rules)

    def test_photo_categories_are_editable_and_validated(self):
        doc = master()
        slot = {'id':'far','type':'photo','box':{'x':20,'y':40,'w':100,'h':70},'source':'class','pick':{'category':'far'}}
        doc['sections'][1]['spreads'][0]['pages'][0]['layers'].append(slot)
        doc['sections'][2]['spreads'][0]['pages'][0]['layers'].append({**slot,'id':'me','pick':{'category':'few','who':'hero'}})
        doc['photoCategories'] = [{'id':'far','name':'Очень общий план','scale':['wide'],'people':['class','subgroup']},
                                  {'id':'few','name':'Пары','people':['few'],'quality':'good'}]
        doc['photoRules'] = {'mixShoots':False,'posedFirst':True}
        self.assertEqual(self.client.post('/api/master-templates',json={'document':doc}).status_code,201)
        preview = self.client.post('/api/master-templates/photo-preview',json={'document':doc,'students':6,'teachers':0,'owner':'s2'})
        self.assertEqual(preview.status_code,200,preview.text)
        self.assertEqual(preview.json()['slots']['shared:0/far']['scale'],'wide')
        shared = doc['sections'][1]['spreads'][0]['pages'][0]['layers']
        for bad in ({'category':'nope'},{'category':'few','who':'hero'},{'category':'few','who':'someone'},{'category':'few','role':'any'}):
            broken = deepcopy(doc); broken['sections'][1]['spreads'][0]['pages'][0]['layers'][len(shared)-1]['pick'] = bad
            self.assertEqual(self.client.post('/api/master-templates',json={'document':broken}).status_code,422,bad)
        for categories in ([{'id':'x','name':''}],[{'id':'x','name':'a'},{'id':'x','name':'b'}],[{'id':'x','name':'a','people':['crowd']}],
                           [{'id':'x','name':'a','style':'loud'}],[{'id':'x y','name':'a'}],[{'id':'x','name':'a','extra':1}]):
            broken = deepcopy(doc); broken['photoCategories'] = categories + [doc['photoCategories'][0]]
            self.assertEqual(self.client.post('/api/master-templates',json={'document':broken}).status_code,422,categories)

    def create(self):
        response=self.client.post('/api/master-templates',json={'document':master()})
        self.assertEqual(response.status_code,201,response.text)
        return response.json()

    def test_shared_text_style_controls_compiled_text(self):
        doc=master()
        doc['textStyles']=[{'id':'text-title','name':'Заголовок','font':'Georgia','fontSize':34,
                            'color':'#112233','align':'center','bold':True,'italic':False,
                            'underline':False,'strike':False,'lineHeight':1.2,'letterSpacing':0}]
        title=doc['sections'][0]['spreads'][0]['pages'][1]['layers'][0]
        title['styleId']='text-title'
        saved=self.client.post('/api/master-templates',json={'document':doc})
        self.assertEqual(saved.status_code,201,saved.text)
        snapshot={'students':[{'id':'1','first_name':'Ученик','last_name':'Один'}],
                  'teachers':[],'photos':{},'selections':[],
                  'order':{'class_name':'11А','year':'2026'}}
        compiled=generate({'id':'test','version':1,'master':doc},snapshot,measurer())
        text=next(e for spread in compiled['variant_spreads']['student:1'].values()
                  for e in spread['elements'] if e['type']=='text' and e['text']=='Наш класс')
        self.assertEqual((text['size'],text['color'],text['align']),(34,'#112233','center'))
        title['styleId']='missing-style'
        self.assertEqual(self.client.post('/api/master-templates',json={'document':doc}).status_code,422)

    def test_custom_page_size_is_validated_and_compiled(self):
        doc=master()
        doc['pageSize']=[300,400]
        response=self.client.post('/api/master-templates',json={'document':doc})
        self.assertEqual(response.status_code,201,response.text)
        snapshot={'students':[{'id':'1','first_name':'Ученик','last_name':'Один'}],
                  'teachers':[],'photos':{},'selections':[],
                  'order':{'class_name':'11А','year':'2026'}}
        compiled=generate({'id':'test','version':1,'master':doc},snapshot,measurer())
        self.assertEqual(compiled['spread_size_mm'],[600,400])
        self.assertIsNone(compiled['cover_size_mm'])
        first=next(iter(compiled['variant_spreads']['student:1'].values()))
        backgrounds=[e['box'] for e in first['elements'] if e['key'].endswith('/background')]
        self.assertEqual(backgrounds,[[0,0,300,400],[300,0,300,400]])
        doc['pageSize']=[40,400]
        self.assertEqual(self.client.post('/api/master-templates',json={'document':doc}).status_code,422)
        doc=master()
        doc['sections'][0]['pageSize']=[180,240]
        self.assertEqual(self.client.post('/api/master-templates',json={'document':doc}).status_code,422)

    def test_cover_has_independent_size_and_is_first_pdf_page(self):
        from io import BytesIO
        from pypdf import PdfReader
        doc=master()
        doc['sections']=doc['sections'][1:2]
        doc['sections'][0]['spreads']=doc['sections'][0]['spreads'][:1]
        doc['pageSize']=[210,280]
        doc['safety']={'safe':5,'bleed':3}
        cover={'id':'cover','name':'Обложка','cover':True,'kind':'fixed',
               'pageSize':[225,290], 'safety':{'safe':8,'bleed':4,'spine':10,'gap':2},
               'spreads':[{'id':'cover-spread','pages':[
                   {'id':'cover-back','background':'#ffffff','layers':[]},
                   {'id':'cover-front','background':'#ffffff','layers':[
                       {'id':'cover-title','type':'text','box':{'x':20,'y':20,'w':180,'h':30},
                        'text':'Моя обложка','font':'Arial','fontSize':24,
                        'color':'#333333','align':'left'}]}]}]}
        doc['sections'].insert(0,cover)
        draft=self.client.post('/api/master-templates',json={'document':doc})
        self.assertEqual(draft.status_code,201,draft.text)
        pub=self.client.post(f'/api/master-templates/{draft.json()["id"]}/publish',json={'revision':1}).json()
        order=self.client.post('/api/orders',json={'school_city':'Казань', 'school':'Тест','class_name':'9Б','copies':1,'offer_id':pub['offer_id']}).json()['id']
        response=self.client.post(f'/api/orders/{order}/layout')
        self.assertEqual(response.status_code,200,response.text)
        generated=response.json()['document']
        self.assertEqual(generated['cover_size_mm'],[460,290])  # two sides and the 10 mm spine
        self.assertEqual(generated['spread_size_mm'],[420,280])
        self.assertEqual(generated['variants'][0]['sequence'][0],'cover[student:class]')
        self.assertEqual(generated['covers']['student:class']['section'],'cover')
        pdf_response=self.client.get(f'/api/orders/{order}/layout/pdf/student:class')
        self.assertEqual(pdf_response.status_code,200,pdf_response.text[:100] if pdf_response.status_code!=200 else '')
        pdf=PdfReader(BytesIO(pdf_response.content))
        self.assertEqual(len(pdf.pages),2)
        self.assertAlmostEqual(float(pdf.pages[0].mediabox.width),460*72/25.4,delta=1)
        self.assertAlmostEqual(float(pdf.pages[1].mediabox.width),420*72/25.4,delta=1)
        self.assertIn('Моя обложка',pdf.pages[0].extract_text())

        bad=deepcopy(doc)
        bad['sections'][0]['safety']['safe']=-1
        self.assertEqual(self.client.post('/api/master-templates',json={'document':bad}).status_code,422)
        bad=deepcopy(doc)
        bad['safety']['book']={'safe':3,'bleed':7.5,'outer':3,'spine':250}
        self.assertEqual(self.client.post('/api/master-templates',json={'document':bad}).status_code,422)
        book=deepcopy(doc)
        book['safety']['book']={'safe':3,'bleed':7.5,'outer':3,'spine':10}
        self.assertEqual(self.client.post('/api/master-templates',json={'document':book}).status_code,201)

    def test_grid_effects_go_to_each_portrait(self):
        doc=master()
        grid=doc['sections'][0]['spreads'][0]['pages'][0]['layers'][0]
        grid.update(strokeOn=True, strokeWidth=1.2, stroke='#663399', strokeAlign='outside',
                    shadow={'color':'#000000','offsetX':2,'offsetY':3,'blur':4,'opacity':40})
        snapshot={'students':[{'id':'1','first_name':'Ученик','last_name':'Один'}],
                  'teachers':[],'photos':{},'selections':[],
                  'order':{'class_name':'11А','year':'2026'}}
        compiled=generate({'id':'test','version':1,'master':doc},snapshot,measurer())
        first=next(iter(compiled['variant_spreads']['student:1'].values()))['elements']
        grid_items=[e for e in first if '/grid/' in e['key']]
        photos=[e for e in grid_items if e['key'].endswith('/photo')]
        self.assertTrue(photos)
        for photo in photos:
            self.assertEqual((photo['strokeWidth'],photo['stroke'],photo['strokeAlign']),(1.2,'#663399','outside'))
            self.assertIn('shadow',photo)
        self.assertTrue(all(e.get('strokeWidth',0)==0 and not e.get('shadow') for e in grid_items if e not in photos))
        self.assertFalse(any(e['key'].endswith(('/outline','/backing')) for e in grid_items))
        grid['strokeOn']=False
        grid.pop('shadow')
        compiled=generate({'id':'test','version':1,'master':doc},snapshot,measurer())
        first=next(iter(compiled['variant_spreads']['student:1'].values()))['elements']
        self.assertTrue(all(e.get('strokeWidth',0)==0 and not e.get('shadow') for e in first if '/grid/' in e['key']))

    def test_versions_and_conflict_and_isolation(self):
        draft=self.create();key=draft['id']
        published=self.client.post(f'/api/master-templates/{key}/publish',json={'revision':1,'price':1700}).json()
        order=self.client.post('/api/orders',json={'school_city':'Казань', 'school':'Лицей','class_name':'11А','copies':22,'student_count':22,'offer_id':published['offer_id']}).json()['id']
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
        order=self.client.post('/api/orders',json={'school_city':'Казань', 'school':'Тест','class_name':'9Б','copies':1,'offer_id':pub['offer_id']}).json()['id']
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

    def test_class_preview_uses_draft_and_lists_ready_classes(self):
        draft=self.create()
        order=self.client.post('/api/orders',json={'school_city':'Казань', 'school':'Тест','class_name':'9Б','copies':1}).json()['id']
        classes={c['id']:c for c in self.client.get('/api/preview-classes').json()}
        self.assertFalse(classes[order]['ready']);self.assertIn('нет учеников',classes[order]['missing'])
        with s.db() as con: con.execute('INSERT INTO persons VALUES (?,?,?,?)',('missing',order,'Без портрета',s.now()))
        classes={c['id']:c for c in self.client.get('/api/preview-classes').json()}
        self.assertEqual(classes[order]['missing'],['нет портретов у 1 из 1 учеников','анкеты заполнили 0 из 1','нет общих фотографий'])
        document=master();document['sections'][0]['name']='Черновик'
        result=self.client.post(f'/api/master-templates/{draft["id"]}/class-preview',json={'document':document,'order_id':order})
        self.assertEqual(result.status_code,200,result.text)
        doc=result.json()['document'];self.assertTrue(doc['master_template']);self.assertEqual(len(doc['variants']),1)
        # The preview never creates or changes the order's own layout.
        self.assertEqual(self.client.get(f'/api/orders/{order}/layout').status_code,404)
        self.assertEqual(self.client.post(f'/api/master-templates/{draft["id"]}/class-preview',json={'document':document,'order_id':'nope'}).status_code,404)

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
            {'id':'caption','type':'text','box':{'x':10,'y':140,'w':180,'h':30},'text':'Проверка PDF','font':'Times New Roman','fontSize':24,'align':'center','color':'#333333'}]
        draft=self.client.post('/api/master-templates',json={'document':doc}).json()
        pub=self.client.post(f'/api/master-templates/{draft["id"]}/publish',json={'revision':1}).json()
        order=self.client.post('/api/orders',json={'school_city':'Казань', 'school':'Тест','class_name':'9Б','copies':1,'offer_id':pub['offer_id']}).json()['id']
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

    def test_vignette_detail_uses_quote_or_school_subject(self):
        doc=master()
        student_grid=doc['sections'][0]['spreads'][0]['pages'][0]['layers'][0]
        student_grid.update(showDetail=True,detailFont='Georgia',detailFontSize=9,detailColor='#554433',detailAlign='center')
        teacher_section=deepcopy(doc['sections'][0]);teacher_section['id']='teachers';teacher_section['name']='Учителя'
        teacher_section['spreads'][0]['id']='teachers-spread'
        teacher_section['spreads'][0]['pages'][0]['id']='teachers-page'
        teacher_section['spreads'][0]['pages'][1]['id']='teachers-title-page'
        teacher_section['spreads'][0]['pages'][1]['layers'][0]['id']='teachers-title'
        teacher_grid=teacher_section['spreads'][0]['pages'][0]['layers'][0]
        teacher_grid.update(id='teacher-grid',source='teachers',showDetail=True)
        doc['sections'].insert(1,teacher_section)
        self.assertEqual(self.client.post('/api/master-templates',json={'document':doc}).status_code,201)
        snapshot={'students':[{'id':'s','first_name':'Анна','last_name':'Иванова','quote':'Мечтай смело'}],
                  'teachers':[{'id':'t','first_name':'Мария','last_name':'Петрова','school_subject':'Математика'}],
                  'photos':{},'selections':[],'order':{'class_name':'11А','year':'2026'}}
        compiled=generate({'id':'test','version':1,'master':doc},snapshot,measurer())
        details=[e for spread in compiled['variant_spreads']['student:s'].values()
                 for e in spread['elements'] if e['key'].endswith('/detail')]
        self.assertEqual({e['text'] for e in details},{'Мечтай смело','Математика'})
        quote=next(e for e in details if e['text']=='Мечтай смело')
        self.assertEqual((quote['font'],quote['size'],quote['color']),('display',9,'#554433'))

    def test_vignette_spacing_controls_actual_elements(self):
        doc=master();grid=doc['sections'][0]['spreads'][0]['pages'][0]['layers'][0]
        grid['box']['h']=90
        grid.update(gap=0,photoWidth=30,minPhotoWidth=20,photoNameGap=7,
                    nameDetailGap=5,showDetail=True,detailFontSize=8)
        people=[{'id':str(i),'first_name':'Анна','last_name':'Иванова','quote':'Привет'} for i in range(2)]
        snapshot={'students':people,'teachers':[],'photos':{},'selections':[],
                  'order':{'class_name':'11А','year':'2026'}}
        compiled=generate({'id':'test','version':1,'master':doc},snapshot,measurer())
        elements=[e for spread in compiled['variant_spreads']['student:0'].values()
                  for e in spread['elements'] if '/card[student:' in e['key']]
        photos=sorted((e for e in elements if e['key'].endswith('/photo')),key=lambda e:e['box'][0])
        self.assertEqual(len(photos),2)
        self.assertAlmostEqual(photos[1]['box'][0]-(photos[0]['box'][0]+photos[0]['box'][2]),0)
        name=next(e for e in elements if e['key'].endswith('student:0]/name'))
        detail=next(e for e in elements if e['key'].endswith('student:0]/detail'))
        self.assertAlmostEqual(name['box'][1]-(photos[0]['box'][1]+photos[0]['box'][3]),7)
        actual_name_height=measurer().height(name['text'],name['font'],name['size'],name['leading'],name['box'][2],name.get('letterSpacing') or 0)
        self.assertAlmostEqual(detail['box'][1]-(name['box'][1]+actual_name_height),5)

    def test_vignette_radius_and_shadow_go_to_card_photos(self):
        doc=master();grid=doc['sections'][0]['spreads'][0]['pages'][0]['layers'][0]
        grid.update(radius=4,shadow={'color':'#000000','offsetX':0,'offsetY':1,'blur':2,'opacity':30})
        people=[{'id':str(i),'first_name':'Анна','last_name':'Иванова'} for i in range(3)]
        snapshot={'students':people,'teachers':[],'photos':{},'selections':[],
                  'order':{'class_name':'11А','year':'2026'}}
        compiled=generate({'id':'test','version':1,'master':doc},snapshot,measurer())
        elements=[e for spread in compiled['variant_spreads']['student:0'].values() for e in spread['elements']]
        photos=[e for e in elements if '/card[student:' in e['key'] and e['key'].endswith('/photo')]
        self.assertEqual([e['radius'] for e in photos],[4,4,4])
        # One shadow layer under all cards: a card's shadow must not fall on its neighbour.
        self.assertEqual(len({e['shadowGroup'] for e in photos}),1)
        self.assertFalse(any(e['key'].endswith(('/outline','/backing')) for e in elements))

    def test_photo_shadow_is_cast_by_the_stroke_edge(self):
        from album_factory.layout_render import _stroke_reach
        photo={'photo':'1','strokeWidth':3}
        self.assertEqual(_stroke_reach({**photo,'strokeAlign':'outside'}),3)
        self.assertEqual(_stroke_reach(photo),1.5)
        self.assertEqual(_stroke_reach({**photo,'strokeAlign':'inside'}),0)
        self.assertEqual(_stroke_reach({**photo,'photo':None}),0)

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

    def test_design_duplicate_and_delete_keep_orders(self):
        design=self.client.post('/api/designs',json={'name':'Осень','package_name':'Стандарт','price':2500,'document':master()}).json()
        source=design['packages'][0]['template_id']
        self.client.post(f'/api/designs/{design["id"]}/packages',json={'name':'Эконом','price':1500,'source_id':source})
        self.client.post(f'/api/designs/{design["id"]}/blocks',json={'name':'Ученики','section':master()['sections'][0]})
        order=self.client.post('/api/orders',json={'school_city':'Казань', 'school':'Тест','class_name':'9 Б','copies':10,'master_template_id':source}).json()['id']
        copy=self.client.post(f'/api/designs/{design["id"]}/duplicate')
        self.assertEqual(copy.status_code,201,copy.text)
        copy=copy.json()
        self.assertEqual(copy['name'],'Осень (копия)')
        self.assertEqual([(p['name'],p['price'],p['revision']) for p in copy['packages']],[('Стандарт',2500,1),('Эконом',1500,1)])
        self.assertNotIn(source,[p['template_id'] for p in copy['packages']])
        self.assertEqual(len(copy['blocks']),1)
        self.assertEqual(self.client.delete(f'/api/designs/{design["id"]}').status_code,200)
        self.assertEqual(self.client.get(f'/api/designs/{design["id"]}').status_code,404)
        self.assertEqual(self.client.get(f'/api/master-templates/{source}').status_code,404)
        self.assertEqual([d['id'] for d in self.client.get('/api/designs').json()],[copy['id']])
        self.assertEqual(self.client.get(f'/api/orders/{order}').status_code,200)
        self.assertEqual(self.client.post(f'/api/orders/{order}/layout',json={}).status_code,200)
        other=TestClient(s.app);other.headers['origin']='http://testserver'
        other.post('/api/register',json={'email':'dup@other.test','password':'secret-pass','studio_name':'Другая'})
        self.assertEqual(other.post(f'/api/designs/{copy["id"]}/duplicate').status_code,404)
        self.assertEqual(other.delete(f'/api/designs/{copy["id"]}').status_code,404)

    def test_design_access_and_foreign_copy(self):
        first=self.client.post('/api/designs',json={'name':'Первый','document':master()}).json()
        second=self.client.post('/api/designs',json={'name':'Второй','document':master()}).json()
        self.assertEqual(self.client.post(f'/api/designs/{second["id"]}/packages',json={'name':'Копия','source_id':first['packages'][0]['template_id']}).status_code,404)
        other=TestClient(s.app);other.headers['origin']='http://testserver'
        other.post('/api/register',json={'email':'design@other.test','password':'secret-pass','studio_name':'Другая'})
        self.assertEqual(other.get(f'/api/designs/{first["id"]}').status_code,404)
        self.assertEqual(other.post(f'/api/designs/{first["id"]}/blocks',json={'name':'Шаблон','section':master()['sections'][0]}).status_code,404)

    def test_collage_splits_rows_independently(self):
        from fastapi import HTTPException
        from album_factory.master_templates import validate
        from album_factory.master_layout import collage_frames
        doc=master()
        collage={'id':'col','type':'collage','box':{'x':10,'y':10,'w':100,'h':80},'gapX':4,'gapY':6,'fill':'#e6e1ea','opacity':100,'rows':[
            [{'id':'a','source':'class'},{'id':'split','split':'v','cells':[{'id':'b','source':'class'},{'id':'c','source':'class'}]}],
            [{'id':'d','source':'class'}]]}
        doc['sections'][1]['spreads'][0]['pages'][0]['layers']=[collage]
        validate(doc)
        frames=collage_frames(collage)
        self.assertEqual([f['cell']['id'] for f in frames], ['a','b','c','d'])
        self.assertEqual([round(f['w'],1) for f in frames], [48,48,48,100])
        self.assertEqual([round(f['h'],1) for f in frames], [37,15.5,15.5,37])
        broken=master();broken['sections'][0]['spreads'][0]['pages'][0]['layers'].append({'id':'bad','type':'collage','box':{'x':1,'y':1,'w':20,'h':20},'rows':[]})
        with self.assertRaises(HTTPException):
            validate(broken)

    def test_layer_may_cross_the_fold_above_both_backgrounds(self):
        doc=master()
        pages=doc['sections'][1]['spreads'][0]['pages']
        pages[1]['background']='#eeeeee'
        pages[0]['layers']=[{'id':'wide','type':'rect','box':{'x':20,'y':20,'w':300,'h':100},'fill':'#223344'}]
        response=self.client.post('/api/master-templates',json={'document':doc})
        self.assertEqual(response.status_code,201,response.text)
        snapshot={'students':[{'id':'1','first_name':'Ученик','last_name':'Один'}],
                  'teachers':[],'photos':{},'selections':[],
                  'order':{'class_name':'11А','year':'2026'}}
        compiled=generate({'id':'test','version':1,'master':doc},snapshot,measurer())
        spread=next(sp for sp in compiled['variant_spreads']['student:1'].values() if any(e['key'].endswith('/wide') for e in sp['elements']))
        keys=[e['key'] for e in spread['elements']]
        wide=next(i for i,k in enumerate(keys) if k.endswith('/wide'))
        self.assertTrue(all(i<wide for i,k in enumerate(keys) if k.endswith('/background')))
        self.assertEqual(spread['elements'][wide]['box'],[20,20,300,100])
        # A layer may hang past the spread edges (print cuts it) but not leave the spread entirely.
        for box in ({'x':20,'y':20,'w':420,'h':100},{'x':-5,'y':-30,'w':100,'h':100},{'x':380,'y':250,'w':100,'h':100}):
            partial=deepcopy(doc);partial['sections'][1]['spreads'][0]['pages'][0]['layers'][0]['box']=box
            self.assertEqual(self.client.post('/api/master-templates',json={'document':partial}).status_code,201,box)
        for box in ({'x':420,'y':20,'w':100,'h':100},{'x':-120,'y':20,'w':100,'h':100},{'x':20,'y':-100,'w':100,'h':100},{'x':20,'y':280,'w':100,'h':100}):
            bad=deepcopy(doc);bad['sections'][1]['spreads'][0]['pages'][0]['layers'][0]['box']=box
            self.assertEqual(self.client.post('/api/master-templates',json={'document':bad}).status_code,422,box)
        right=deepcopy(doc);right['sections'][1]['spreads'][0]['pages'][0]['layers']=[]
        right['sections'][1]['spreads'][0]['pages'][1]['layers']=[{'id':'wide','type':'rect','box':{'x':-150,'y':20,'w':300,'h':100},'fill':'#223344'}]
        self.assertEqual(self.client.post('/api/master-templates',json={'document':right}).status_code,201)
        grid=deepcopy(doc);grid['sections'][0]['spreads'][0]['pages'][0]['layers'][0]['box']['w']=250
        self.assertEqual(self.client.post('/api/master-templates',json={'document':grid}).status_code,422)

    def cover_book(self, sheet, layers=()):
        doc=master();doc['rulesVersion']=2;doc['layout']='spreads'
        doc['sections']=[{'id':'cover','name':'Обложка','cover':True,'kind':'fixed','pageSize':[220,300],'safety':{'safe':5,'bleed':3,'spine':6,'gap':2},
                          'spreads':[{'id':'cs','pages':[{'id':'cb','background':'#112233','layers':list(layers)},{'id':'cf','background':'#445566','layers':[]}]}]},
                         {'id':'shared','name':'Общие','kind':'fixed','spreads':[{'id':f'g{i}','pages':[{'id':f'g{i}l','background':'#ffffff','layers':[]},{'id':f'g{i}r','background':'#ffffff','layers':[]}]} for i in range(4)]}]
        if sheet is not None:
            doc['sheetThickness']=sheet
        return doc

    def compile_cover(self, doc):
        snapshot={'students':[{'id':'1','first_name':'Ученик','last_name':'Один'}],'teachers':[],'photos':{},'selections':[],'order':{'class_name':'11А','year':'2026'}}
        self.assertEqual(self.client.post('/api/master-templates',json={'document':doc}).status_code,201)
        return generate({'id':'test','version':1,'master':doc},snapshot,measurer())

    def test_spine_follows_the_sheet_thickness(self):
        # 4 spreads × 1.2 mm + 3.5 mm of boards = 8.3 → 10 mm, rounded up to even millimetres
        compiled=self.compile_cover(self.cover_book(1.2))
        cover=compiled['covers']['student:1']
        self.assertEqual((cover['spine_mm'],cover['size_mm'],compiled['cover_size_mm']),(10,[450,300],[450,300]))
        backgrounds=[e['box'] for e in cover['elements'] if e['key'].endswith('/background')]
        self.assertEqual(backgrounds,[[0,0,225,300],[225,0,225,300]])
        self.assertEqual(compiled['print'],{'files':'spreads','dpi':300})
        self.assertFalse(compiled['issues'])
        self.assertEqual(self.compile_cover(self.cover_book(0.14))['covers']['student:1']['spine_mm'],8)  # never thinner than 8 mm
        book=self.cover_book(2);book['layout']='book'  # a book of 4 spreads has 6 pages on 3 sheets: 3.5 + 6 → 10
        self.assertEqual(self.compile_cover(book)['covers']['student:1']['spine_mm'],10)
        compiled=self.compile_cover(self.cover_book(None))
        self.assertEqual(compiled['covers']['student:1']['size_mm'],[446,300])  # fixed spine of the cover
        for value in (0,6,'1',True):
            self.assertEqual(self.client.post('/api/master-templates',json={'document':self.cover_book(value)}).status_code,422)

    def test_cover_layers_keep_to_the_spine(self):
        rect=lambda i,x,w,pin=None:{'id':i,'type':'rect','box':{'x':x,'y':10,'w':w,'h':20},'fill':'#ffffff',**({'pin':pin} if pin else {})}
        doc=self.cover_book(2,[rect('back',10,50),rect('title',-4,8,'spine'),rect('wrap',0,440,'wrap')])
        doc['sections'][0]['spreads'][0]['pages'][1]['layers']=[rect('front',10,50)]
        boxes={e['key'].rsplit('/',1)[1]:e['box'][:3] for e in self.compile_cover(doc)['covers']['student:1']['elements']}
        self.assertEqual(boxes['back'],[10,10,50]);self.assertEqual(boxes['front'],[242,10,50])
        self.assertEqual(boxes['title'],[222,10,8]);self.assertEqual(boxes['wrap'],[0,10,452])
        bad=deepcopy(doc);bad['sections'][1]['spreads'][0]['pages'][0]['layers']=[rect('x',0,10,'spine')]
        self.assertEqual(self.client.post('/api/master-templates',json={'document':bad}).status_code,422)
        # A spine layer sits on the side holding its centre, stacking above that side; a wrap stays on the back.
        front=deepcopy(doc);front['sections'][0]['spreads'][0]['pages'][1]['layers'].append(rect('late',-2,40,'spine'))
        self.assertEqual(self.client.post('/api/master-templates',json={'document':front}).status_code,201)
        keys=[e['key'].rsplit('/',1)[1] for e in self.compile_cover(front)['covers']['student:1']['elements']]
        self.assertGreater(keys.index('late'),keys.index('front'))
        bad=deepcopy(doc);bad['sections'][0]['spreads'][0]['pages'][1]['layers'].append(rect('w2',0,440,'wrap'))
        self.assertEqual(self.client.post('/api/master-templates',json={'document':bad}).status_code,422)
        bad=deepcopy(doc);bad['sections'][0]['spreads'][0]['pages'][0]['layers'][1]={'id':'t','type':'text','box':{'x':0,'y':0,'w':100,'h':20},'text':'x','font':'Arial','fontSize':12,'color':'#333333','align':'left','pin':'wrap'}
        self.assertEqual(self.client.post('/api/master-templates',json={'document':bad}).status_code,422)

    def test_printer_files_are_jpeg_spreads_or_pages(self):
        import zipfile
        from io import BytesIO
        from PIL import Image
        doc=self.cover_book(2)
        def files(document, class_name):
            draft=self.client.post('/api/master-templates',json={'document':document})
            self.assertEqual(draft.status_code,201,draft.text)
            pub=self.client.post(f'/api/master-templates/{draft.json()["id"]}/publish',json={'revision':1}).json()
            order=self.client.post('/api/orders',json={'school_city':'Казань','school':'Тест','class_name':class_name,'copies':1,'offer_id':pub['offer_id']}).json()['id']
            self.assertEqual(self.client.post(f'/api/orders/{order}/layout').status_code,200)
            response=self.client.get(f'/api/orders/{order}/layout/print/student:class')
            self.assertEqual(response.status_code,200,response.text[:200])
            return zipfile.ZipFile(BytesIO(response.content))
        archive=files(doc,'9А')
        self.assertEqual(archive.namelist(),['cover.jpg']+[f'spread-{i:02d}.jpg' for i in range(1,5)])
        cover=Image.open(BytesIO(archive.read('cover.jpg')))
        self.assertEqual((cover.format,cover.mode,cover.size,round(cover.info['dpi'][0])),('JPEG','RGB',(round(452/25.4*300),round(300/25.4*300)),300))
        self.assertIn('icc_profile',cover.info)
        self.assertTrue(all(abs(a-b)<=2 for a,b in zip(cover.getpixel((10,10)),(0x11,0x22,0x33))))
        book=deepcopy(doc);book['layout']='book'
        archive=files(book,'9Б')
        self.assertEqual(archive.namelist(),['cover.jpg']+[f'page-{i:03d}.jpg' for i in range(1,7)])
        page=Image.open(BytesIO(archive.read('page-001.jpg')))
        self.assertEqual(page.size,(round(210/25.4*300)+1,round(280/25.4*300)))  # a page takes the odd pixel of the 4961 px spread

    def test_svg_shape_is_saved_and_drawn(self):
        from pypdf import PdfReader
        from io import BytesIO
        svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="40" fill="#e23b3b"/><path d="M10 80 H90 V90 H10 Z" fill="#112233"/></svg>'
        doc=master();doc['sections']=doc['sections'][1:2];doc['sections'][0]['spreads']=doc['sections'][0]['spreads'][:1]
        doc['sections'][0]['spreads'][0]['pages'][0]['layers']=[{
            'id':'mark','type':'svg','name':'Метка','box':{'x':20,'y':20,'w':40,'h':40},'opacity':100,'fill':'#29282d','fillMode':'color','stroke':'#111111','strokeMode':'color','strokeWidth':0.6,'strokeAlign':'center','strokeCap':'round','strokeJoin':'round','strokeDash':'solid','svg':svg}]
        draft=self.client.post('/api/master-templates',json={'document':doc})
        self.assertEqual(draft.status_code,201,draft.text)
        pub=self.client.post(f'/api/master-templates/{draft.json()["id"]}/publish',json={'revision':1})
        self.assertLess(pub.status_code,300,pub.text)
        order=self.client.post('/api/orders',json={'school_city':'Казань', 'school':'Тест','class_name':'9Б','copies':1,'offer_id':pub.json()['offer_id']}).json()['id']
        generated=self.client.post(f'/api/orders/{order}/layout')
        self.assertEqual(generated.status_code,200,generated.text)
        element=next(e for spread in generated.json()['document']['variant_spreads']['student:class'].values() for e in spread['elements'] if e['type']=='svg')
        self.assertIn('#29282d', element['svg'].lower())
        pdf=self.client.get(f'/api/orders/{order}/layout/pdf/student:class')
        self.assertEqual(pdf.status_code,200,pdf.text[:120] if pdf.status_code!=200 else '')
        self.assertEqual(len(PdfReader(BytesIO(pdf.content)).pages),1)
        hostile=master();hostile['sections'][1]['spreads'][0]['pages'][0]['layers']=[{'id':'x','type':'svg','box':{'x':1,'y':1,'w':20,'h':20},'fill':'#111111','svg':'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'}]
        self.assertEqual(self.client.post('/api/master-templates',json={'document':hostile}).status_code,422)

    def test_text_styles_custom_font_stroke_and_shadow(self):
        import base64
        from io import BytesIO
        from pathlib import Path
        from pypdf import PdfReader
        raw=Path('/System/Library/Fonts/Supplemental/Georgia.ttf').read_bytes()
        data='data:font/ttf;base64,'+base64.b64encode(raw).decode()
        doc=master();doc['fonts']=[{'id':'font-demo','name':'Мой шрифт','dataUrl':data}]
        doc['sections']=doc['sections'][1:2];doc['sections'][0]['spreads']=doc['sections'][0]['spreads'][:1]
        doc['sections'][0]['spreads'][0]['pages'][0]['layers']=[{
            'id':'caption','type':'text','box':{'x':10,'y':20,'w':180,'h':40},'text':'Свой шрифт',
            'font':'font-demo','fontSize':28,'align':'center','color':'#222222','bold':True,'italic':True,'underline':True,
            'lineHeight':1.3,'letterSpacing':2,'stroke':'#7712b3','strokeWidth':0.4,'strokeOn':True,'strokeAlign':'outside','strokeDash':'solid',
            'shadow':{'color':'#000000','opacity':40,'blur':1.2,'offsetX':0.4,'offsetY':0.8}}]
        saved=self.client.post('/api/master-templates',json={'document':doc})
        self.assertEqual(saved.status_code,201,saved.text)
        unknown=master();unknown['sections'][1]['spreads'][0]['pages'][0]['layers']=[{'id':'t','type':'text','box':{'x':10,'y':10,'w':40,'h':12},'text':'А','font':'Comic Sans','fontSize':12,'align':'left','color':'#333333'}]
        self.assertEqual(self.client.post('/api/master-templates',json={'document':unknown}).status_code,422)
        broken=master();broken['fonts']=[{'id':'font-bad','name':'Битый','dataUrl':'data:font/ttf;base64,AAAA'}]
        self.assertEqual(self.client.post('/api/master-templates',json={'document':broken}).status_code,422)
        pub=self.client.post(f'/api/master-templates/{saved.json()["id"]}/publish',json={'revision':1})
        self.assertLess(pub.status_code,300,pub.text)
        order=self.client.post('/api/orders',json={'school_city':'Казань', 'school':'Тест','class_name':'9Б','copies':1,'offer_id':pub.json()['offer_id']}).json()['id']
        generated=self.client.post(f'/api/orders/{order}/layout')
        self.assertEqual(generated.status_code,200,generated.text)
        text=next(e for spread in generated.json()['document']['variant_spreads']['student:class'].values() for e in spread['elements'] if e['type']=='text' and e.get('text')=='Свой шрифт')
        self.assertTrue(text['font'].startswith('custom-font-demo'))
        self.assertIn('shadow', text)
        pdf=self.client.get(f'/api/orders/{order}/layout/pdf/student:class')
        self.assertEqual(pdf.status_code,200,pdf.text[:160] if pdf.status_code!=200 else '')
        self.assertIn('Свой шрифт', PdfReader(BytesIO(pdf.content)).pages[0].extract_text())
