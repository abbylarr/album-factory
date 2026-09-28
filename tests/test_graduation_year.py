import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from album_factory import server as s


class GraduationYearTests(unittest.TestCase):
    def test_school_year_boundaries(self):
        for date, expected in [('2026-01-01',2026),('2026-06-30',2026),('2026-07-01',2026),('2026-08-31',2026),('2026-09-01',2027),('2026-12-31',2027)]:
            self.assertEqual(s.graduation_year_for(datetime.fromisoformat(date)),expected)

    def test_create_edit_and_migrate(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(s,'DATA',Path(tmp)), patch.object(s.executor,'submit'), TestClient(s.app) as client:
            client.get('/v2');client.headers['origin']='http://testserver'
            with patch.object(s,'now',return_value='2026-09-28T10:00:00+00:00'):
                response=client.post('/api/orders',json={'school':'Школа 1','class_name':'9 Б','copies':20})
            self.assertEqual(response.status_code,201,response.text)
            id=response.json()['id']
            self.assertEqual(client.get('/api/orders/'+id).json()['graduation_year'],2027)
            response=client.patch('/api/orders/'+id,json={'school':'Школа 1','class_name':'9 Б','graduation_year':2028})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(client.get('/api/orders/'+id).json()['graduation_year'],2028)
            self.assertEqual(client.get('/api/orders').json()[0]['graduation_year'],2028)
            self.assertEqual(client.patch('/api/orders/'+id,json={'school':' ','class_name':'9 Б','graduation_year':2028}).status_code,422)
            self.assertEqual(client.post('/api/orders',json={'school':'Тест','class_name':'9','copies':1,'graduation_year':1900}).status_code,422)
            with s.db() as con:
                con.execute('UPDATE orders SET graduation_year=NULL WHERE id=?',(id,))
            s.init_db()
            self.assertEqual(client.get('/api/orders/'+id).json()['graduation_year'],2027)
            s.init_db()
            self.assertEqual(client.get('/api/orders/'+id).json()['graduation_year'],2027)
