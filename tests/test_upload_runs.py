"""Order head rows: the server remembers a browser upload so an interrupted one shows, and counts fixed corrections."""
import io
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from album_factory import server as s


def jpeg(colour):
    buf = io.BytesIO()
    Image.new('RGB', (40, 40), colour).save(buf, 'JPEG')
    return buf.getvalue()


class OrderCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for target in (patch.object(s, 'DATA', Path(self.tmp.name)), patch.object(s.executor, 'submit')):
            target.start()
            self.addCleanup(target.stop)
        self.client = TestClient(s.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.client.get('/v2')
        self.client.headers['origin'] = 'http://testserver'
        self.order = self.client.post('/api/orders', json={'school_city': 'Казань', 'school': 'Школа', 'class_name': '9 А', 'copies': 3}).json()['id']
        self.shoot = self.client.post(f'/api/orders/{self.order}/shoots', json={'kind': 'portrait', 'title': 'Портреты'}).json()['id']

    def listed(self):
        return next(o for o in self.client.get('/api/orders').json() if o['id'] == self.order)

    def detail(self):
        return self.client.get(f'/api/orders/{self.order}').json()


class UploadRunTests(OrderCase):
    def send(self, body):
        return self.client.post(f'/api/orders/{self.order}/photos?shoot_id={self.shoot}&filename=a.jpg', content=body,
                                headers={'Content-Type': 'application/octet-stream'})

    def start(self, files):
        return self.client.post(f'/api/orders/{self.order}/uploads', json={'shoot_id': self.shoot, 'files': files})

    def quiet(self):
        stamp = (datetime.now(timezone.utc) - timedelta(seconds=s.upload_runs.STALL_SECONDS + 5)).isoformat()
        with s.db() as con:
            con.execute('UPDATE upload_runs SET updated_at=?', (stamp,))

    def test_arrived_files_count_and_a_quiet_run_is_interrupted(self):
        self.start(3)
        self.assertEqual(self.send(jpeg('#123456')).status_code, 201)
        self.send(jpeg('#123456'))  # a skipped duplicate still reached the server
        run = self.detail()['upload']
        self.assertEqual((run['total'], run['done'], run['stalled'], run['shoot_id']), (3, 2, False, self.shoot))
        self.quiet()
        self.assertTrue(self.detail()['upload']['stalled'])
        self.assertTrue(self.listed()['upload']['stalled'])

    def test_more_files_join_a_running_upload_but_restart_after_interruption(self):
        self.start(3)
        self.send(jpeg('#654321'))
        self.start(2)
        run = self.detail()['upload']
        self.assertEqual((run['total'], run['done']), (5, 1))
        self.quiet()
        self.start(4)
        run = self.detail()['upload']
        self.assertEqual((run['total'], run['done'], run['stalled']), (4, 0, False))

    def test_finished_or_dismissed_run_disappears(self):
        self.start(1)
        self.assertEqual(self.client.delete(f'/api/orders/{self.order}/uploads').status_code, 200)
        self.assertIsNone(self.detail()['upload'])

    def test_deleting_the_order_forgets_the_run(self):
        self.start(1)
        self.client.delete(f'/api/orders/{self.order}')
        with s.db() as con:
            self.assertIsNone(con.execute('SELECT 1 FROM upload_runs WHERE order_id=?', (self.order,)).fetchone())

    def test_teacher_files_from_the_order_count_like_any_shoot(self):
        school = self.client.post('/api/schools', json={'name': 'Лицей', 'city': 'Казань'}).json()['id']
        order = self.client.post('/api/orders', json={'school_id': school, 'class_name': '11 А', 'copies': 10}).json()['id']
        self.client.post(f'/api/orders/{order}/uploads', json={'shoot_id': 'teachers', 'files': 2})
        send = lambda colour: self.client.post(f'/api/schools/{school}/teacher-photos?filename=t.jpg&order_id={order}', content=jpeg(colour),
                                               headers={'Content-Type': 'application/octet-stream'})
        self.assertEqual(send('#aa0000').status_code, 201)
        send('#aa0000')  # the same file again is skipped but still arrived
        body = self.client.get(f'/api/orders/{order}').json()
        self.assertEqual((body['upload']['done'], body['upload']['shoot_id']), (2, 'teachers'))
        self.assertEqual((body['teacher_total'], body['teacher_pending']), (1, 1))
        listed = next(o for o in self.client.get('/api/orders').json() if o['id'] == order)
        self.assertEqual((listed['teacher_total'], listed['teacher_pending']), (1, 1))

    def test_photo_errors_are_counted_for_cards(self):
        with s.db() as con:
            con.execute('''INSERT INTO photos (id,order_id,filename,sha,status,created_at,shoot_id)
                VALUES ('bad',?,'bad.jpg','bad','error',?,?)''', (self.order, s.now(), self.shoot))
        self.assertEqual(self.listed()['error_count'], 1)


class CorrectionCountTests(OrderCase):
    def correction(self, fix_id, status='open', revision='r1'):
        with s.db() as con:
            con.execute('''INSERT INTO layout_corrections (id,order_id,revision,kind,spread_label,comment,status,created_at)
                VALUES (?,?,?,'spread','Разворот 3','Заменить фото',?,?)''', (fix_id, self.order, revision, status, s.now()))

    def test_fixed_corrections_count_towards_the_total_and_can_be_reopened(self):
        with s.db() as con:
            con.execute('INSERT INTO publications (order_id,revision,document,published_at) VALUES (?,?,?,?)',
                        (self.order, 'r1', '{}', s.now()))
        self.correction('a')
        self.correction('b', 'resolved')
        self.correction('old', revision='r0')  # an earlier publication does not count
        body = self.detail()
        self.assertEqual((body['corrections_open'], body['corrections_total']), (1, 2))
        self.assertEqual((self.listed()['corrections_open'], self.listed()['corrections_total']), (1, 2))
        every = self.client.get(f'/api/orders/{self.order}/corrections?all=true').json()
        self.assertEqual({c['id']: c['status'] for c in every}, {'a': 'open', 'b': 'resolved'})
        self.assertEqual([c['id'] for c in self.client.get(f'/api/orders/{self.order}/corrections').json()], ['a'])
        self.assertEqual(self.client.post(f'/api/orders/{self.order}/corrections/b/reopen').status_code, 200)
        self.assertEqual(self.detail()['corrections_open'], 2)
        self.assertEqual(self.client.post(f'/api/orders/{self.order}/corrections/nope/reopen').status_code, 404)


if __name__ == '__main__':
    unittest.main()
