import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from album_factory import server as s


class ProductionV3Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p=patch.object(s,'DATA',Path(self.tmp.name));p.start();self.addCleanup(p.stop)
        s.init_db()
        with s.db() as con:
            con.execute('INSERT INTO orders VALUES (?,?,?,?,?,?,?,?)',('o','School','A',1,0,'','upload',s.now()))

    def photo(self,number,status='pending',person=None,vector=None,color=100):
        id=str(number)
        with s.db() as con:
            con.execute('INSERT INTO photos (id,order_id,filename,sha,status,person_id,embedding,created_at) VALUES (?,?,?,?,?,?,?,?)',
                (id,'o',f'DSC{number:04}.jpg',id,status,person,json.dumps(vector) if vector else None,s.now()))
        for ext in ['.jpg','.thumb.jpg']:
            Image.new('RGB',(80,80),(color,)*3).save(s.DATA/'photos'/(id+ext))
        return id

    def process(self,callback=None):
        class Engine:
            def extract(self,pixels):
                if callback: callback()
                return 'ready',[1.,0.] if pixels[0,0,0]<150 else [0.,1.]
        with patch.object(s,'engine',Engine()): s.process_pending()

    def rows(self):
        with s.db() as con:
            return {r['id']:dict(r) for r in con.execute('SELECT * FROM photos')}

    def test_v3_series_is_durable_uncertain_and_not_a_sample(self):
        for i in [1,2,3]: self.photo(i)
        self.process()
        rows=self.rows()
        self.assertEqual({p['status'] for p in rows.values()},{'ready'})
        self.assertEqual(len({p['person_id'] for p in rows.values()}),1)
        self.assertEqual(rows['2']['uncertain'],1)
        self.assertIsNone(rows['2']['embedding'])
        with s.db() as con:
            a=con.execute("SELECT * FROM photo_analysis WHERE photo_id='2'").fetchone()
            self.assertEqual((a['algorithm'],a['source']),('v3','sequence'))
            self.assertEqual(json.loads(a['anchors']),['1','3'])
        self.assertEqual(s.get_order('o')['processing']['algorithm'],'v3')

    def test_previous_manual_group_preserved_and_reused_on_later_upload(self):
        with s.db() as con: con.execute('INSERT INTO persons VALUES (?,?,?,?)',('manual','o','Chosen name',s.now()))
        self.photo(1,'ready','manual',[1.,0.])
        before=self.rows()['1']
        self.photo(2)
        self.process()
        self.assertEqual(self.rows()['1'],before)
        self.assertEqual(self.rows()['2']['person_id'],'manual')
        self.photo(9)
        self.process()
        self.assertEqual(self.rows()['9']['person_id'],'manual')

    def test_existing_intermediate_photo_blocks_bridge(self):
        with s.db() as con: con.execute('INSERT INTO persons VALUES (?,?,?,?)',('other','o','Other',s.now()))
        self.photo(1)
        self.photo(2,'ready','other',[0.,1.],200)
        self.photo(3)
        self.photo(5)
        self.process()
        self.assertIsNotNone(self.rows()['3']['embedding'])
        self.assertEqual(self.rows()['2']['person_id'],'other')

    def test_failure_retry_and_restart_recovery(self):
        self.photo(1)
        (s.DATA/'photos'/'1.jpg').unlink()
        self.process()
        self.assertEqual(self.rows()['1']['status'],'error')
        Image.new('RGB',(80,80),(100,)*3).save(s.DATA/'photos'/'1.jpg')
        with patch.object(s.executor,'submit'): s.retry('o')
        self.process()
        self.assertEqual(self.rows()['1']['status'],'ready')
        self.photo(2,'processing')
        s.init_db()
        self.process()
        self.assertEqual(self.rows()['2']['status'],'ready')

    def test_photo_deleted_during_inference_not_recreated(self):
        self.photo(1)
        self.process(lambda:s.delete_photos('o',s.PhotoIds(photo_ids=['1'])))
        self.assertEqual(self.rows(),{})
        with s.db() as con: self.assertEqual(con.execute('SELECT COUNT(*) FROM persons').fetchone()[0],0)

    def test_new_upload_during_batch_processed_next(self):
        self.photo(1)
        added=False
        def add():
            nonlocal added
            if not added:
                added=True;self.photo(2)
        self.process(add)
        self.assertEqual({p['status'] for p in self.rows().values()},{'ready'})
        self.assertEqual(len(self.rows()),2)

    def test_returning_person_keeps_identity(self):
        for i,c in [(1,100),(2,100),(3,100),(4,200),(5,200),(6,200),(7,100)]: self.photo(i,color=c)
        self.process()
        r=self.rows()
        self.assertEqual(r['1']['person_id'],r['7']['person_id'])
        self.assertNotEqual(r['1']['person_id'],r['5']['person_id'])

if __name__=='__main__':unittest.main()
