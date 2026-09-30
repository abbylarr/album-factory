"""Regressions for service audit B1–B7, isolated DB and synthetic photos."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
import unittest
from fastapi.testclient import TestClient
from album_factory import server as s
import test_server_v2


class AuditFixTests(unittest.TestCase):
    setUp = test_server_v2.V2Tests.setUp
    photo = test_server_v2.V2Tests.photo

    def link(self, manager=False):
        pins = self.client.post(f'/api/orders/{self.order}/client-link').json()
        base = '/client-api/' + pins['url'].rsplit('/', 1)[1]
        self.assertEqual(self.client.post(base+'/enter', json={'pin': pins['entry_pin']}).status_code, 200)
        if manager:
            self.assertEqual(self.client.post(base+'/manage', json={'pin': pins['manage_pin']}).status_code, 200)
        return base, pins

    def publish(self, photo=None, revision='audit-rev'):
        document = {'revision': revision, 'issues': [], 'variants': [{'owner': 'person', 'name': 'Ученик', 'sequence': ['page']}, {'owner': 'teacher_variant', 'name': 'Учителю', 'sequence': ['page']}],
                    'spread_size_mm': [30, 20], 'print': {'dpi': 72, 'files': 'spreads'},
                    'shared_spreads': {'page': {'key': 'page', 'elements': []}}, 'covers': {}, 'variant_spreads': {}}
        if photo:
            document['shared_spreads']['page']['elements'].append({'type': 'photo', 'photo': photo, 'box': [0, 0, 10, 10]})
        with s.db() as con:
            con.execute('INSERT OR REPLACE INTO order_layouts VALUES (?,?,?,?,?)',
                        (self.order, '{}', json.dumps(document), '[]', s.now()))
        return self.client.post(f'/api/orders/{self.order}/layout/publish')

    def prepared(self):
        self.photo()
        self.assertEqual(self.publish().status_code, 200)
        base, pins = self.link(manager=True)
        summary = self.client.get(base+'/summary').json()
        payload = {'allocations': summary['allocations'], 'paid_total': 20, 'delivery': {'mode': 'personal', 'recipient': 'Ирина'}}
        for row in payload['allocations']:
            if row['key'] == 'person':
                row['paid'] = 20
        self.assertEqual(self.client.put(base+'/summary', json=payload).status_code, 200)
        return base, pins, payload

    def test_b1_both_pin_limits_expiry_and_reset(self):
        base, pins = self.link()
        for kind, field in [('enter', 'entry_pin'), ('manage', 'manage_pin')]:
            wrong = '0000' if pins[field] != '0000' else '0001'
            for _ in range(8):
                self.assertEqual(self.client.post(base+'/'+kind, json={'pin': wrong}).status_code, 401)
            self.assertEqual(self.client.post(base+'/'+kind, json={'pin': pins[field]}).status_code, 429)
            db_kind = 'entry' if kind == 'enter' else 'manage'
            with s.db() as con:
                attempt = con.execute('SELECT fails,locked_until FROM pin_attempts WHERE order_id=? AND kind=?', (self.order, db_kind)).fetchone()
                self.assertEqual(attempt['fails'], 8)
                con.execute("UPDATE pin_attempts SET locked_until='2000-01-01T00:00:00+00:00' WHERE order_id=? AND kind=?", (self.order, db_kind))
            self.assertEqual(self.client.post(base+'/'+kind, json={'pin': wrong}).status_code, 401)
            with s.db() as con:
                self.assertEqual(con.execute('SELECT fails FROM pin_attempts WHERE order_id=? AND kind=?', (self.order, db_kind)).fetchone()[0], 1)
            self.assertEqual(self.client.post(base+'/'+kind, json={'pin': pins[field]}).status_code, 200)
        with s.db() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM pin_attempts').fetchone()[0], 0)
        self.client.post(base+'/enter', json={'pin': wrong})
        self.client.post(f'/api/orders/{self.order}/client-codes/reset')
        with s.db() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM pin_attempts').fetchone()[0], 0)

    def test_b1_concurrent_failures_are_counted(self):
        base, pins = self.link()
        wrong = '0000' if pins['entry_pin'] != '0000' else '0001'
        def attempt(_):
            client = TestClient(s.app)
            client.headers['origin'] = 'http://testserver'
            return client.post(base+'/enter', json={'pin': wrong}).status_code
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(list(pool.map(attempt, range(8))), [401]*8)
        self.assertEqual(self.client.post(base+'/enter', json={'pin': wrong}).status_code, 429)

    def test_b2_foreign_studio_cannot_rename(self):
        self.photo()
        other = TestClient(s.app)
        other.headers['origin'] = 'http://testserver'
        self.assertEqual(other.post('/api/register', json={'email': 'audit@studio.test', 'password': 'secret-pass', 'studio_name': 'Чужая'}).status_code, 200)
        self.assertEqual(other.patch(f'/api/orders/{self.order}/persons/person', json={'name': 'Взлом'}).status_code, 404)
        with s.db() as con:
            self.assertEqual(con.execute("SELECT name FROM persons WHERE id='person'").fetchone()[0], 'Имя')
        self.assertEqual(self.client.patch(f'/api/orders/{self.order}/persons/person', json={'name': 'Анна'}).status_code, 200)

    def select(self, base, photo):
        self.assertEqual(self.client.put(base+'/persons/person', json={'photo_id': photo, 'first_name': 'Анна', 'last_name': 'Иванова'}).status_code, 200)
        self.assertEqual(self.client.post(base+'/persons/person/submit').status_code, 200)

    def test_b3_delete_unlocks_and_can_submit_again(self):
        a, b = self.photo(), self.photo()
        base, _ = self.link()
        self.select(base, a)
        self.assertEqual(self.client.post(f'/api/orders/{self.order}/delete-photos', json={'photo_ids': [a]}).status_code, 200)
        person = self.client.get(base).json()['persons'][0]
        self.assertFalse(person['photo_locked'])
        self.assertFalse(person['submitted'])
        self.select(base, b)

    def test_b3_move_unlocks_original_and_destination(self):
        a, b = self.photo(), self.photo()
        base, _ = self.link()
        self.select(base, a)
        moved = self.client.post(f'/api/orders/{self.order}/move', json={'photo_ids': [a]})
        self.assertEqual(moved.status_code, 200)
        with s.db() as con:
            self.assertIsNone(con.execute("SELECT * FROM selection_state WHERE person_id='person'").fetchone())
            self.assertIsNone(con.execute("SELECT * FROM client_selections WHERE person_id='person'").fetchone())
        self.select(base, b)

    def test_b3_general_move_and_restart_repair(self):
        a, b = self.photo(), self.photo()
        base, _ = self.link()
        self.select(base, a)
        shoot = self.client.post(f'/api/orders/{self.order}/shoots', json={'kind': 'general', 'title': 'Общая'}).json()['id']
        self.assertEqual(self.client.post(f'/api/orders/{self.order}/shoots/{shoot}/move-photos', json={'photo_ids': [a]}).status_code, 200)
        self.select(base, b)
        s.init_db()
        self.assertTrue(self.client.get(base).json()['persons'][0]['submitted'])
        with s.db() as con:
            con.execute('DELETE FROM photos WHERE id=?', (b,))
            con.execute("INSERT INTO selection_state VALUES ('orphan','missing',1)")
        s.init_db()
        with s.db() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM selection_state').fetchone()[0], 0)

    def test_b4_publication_blocks_atomic_deletion_and_shoot(self):
        a, b = self.photo(), self.photo()
        shoot = self.client.post(f'/api/orders/{self.order}/shoots', json={'kind': 'portrait', 'title': 'Портреты'}).json()['id']
        with s.db() as con:
            con.execute('UPDATE photos SET shoot_id=? WHERE id=?', (shoot, a))
        self.assertEqual(self.publish(a).status_code, 200)
        base, _ = self.link()
        self.assertEqual(self.client.post(f'/api/orders/{self.order}/delete-photos', json={'photo_ids': [b, a]}).status_code, 409)
        self.assertEqual(self.client.delete(f'/api/orders/{self.order}/shoots/{shoot}').status_code, 409)
        self.assertEqual(self.client.get(base+'/layout').status_code, 200)
        self.assertEqual(self.client.get(base+f'/layout/photos/{a}/thumb').status_code, 200)
        for photo in (a, b):
            self.assertTrue((s.DATA/'photos'/f'{photo}.jpg').is_file())
        self.assertEqual(self.publish(revision='without-photo').status_code, 200)
        self.assertEqual(self.client.delete(f'/api/orders/{self.order}/shoots/{shoot}').status_code, 200)
        self.assertEqual(self.client.delete(f'/api/orders/{self.order}').status_code, 200)

    def test_b4_missing_files_block_publication_view_and_production(self):
        a = self.photo()
        self.assertEqual(self.publish(a).status_code, 200)
        base, _ = self.link()
        (s.DATA/'photos'/f'{a}.jpg').unlink()
        self.assertEqual(self.client.get(base+'/layout').status_code, 409)
        self.assertEqual(self.client.post(f'/api/orders/{self.order}/production', json={'responsibility': True}).status_code, 409)
        self.assertEqual(self.publish(a, revision='missing').status_code, 409)
        with s.db() as con:
            self.assertEqual(con.execute('SELECT revision FROM publications').fetchone()[0], 'audit-rev')

    def test_b5_only_manager_writes_and_production_is_frozen(self):
        base, pins, payload = self.prepared()
        entry = TestClient(s.app)
        entry.headers['origin'] = 'http://testserver'
        entry.post(base+'/enter', json={'pin': pins['entry_pin']})
        self.assertEqual(entry.put(base+'/summary', json=payload).status_code, 401)
        before = self.client.get(base+'/summary').json()
        self.assertEqual(self.client.post(base+'/approve', json={'hash': before['hash']}).status_code, 200)
        self.assertEqual(self.client.post(f'/api/orders/{self.order}/production', json={'responsibility': False}).status_code, 200)
        export = self.client.get(f'/api/orders/{self.order}/export').json()
        self.assertEqual(export['total'], before['total'])
        self.assertEqual(export['production_hash'], before['hash'])
        self.assertIn('offer_price', self.client.get(f'/api/orders/{self.order}/deal').json())
        self.assertNotIn('offer_price', self.client.get(base+'/summary').json())
        for stage in ('print', 'delivery', 'archive'):
            with s.db() as con:
                con.execute('UPDATE orders SET stage=? WHERE id=?', (stage, self.order))
            altered = deepcopy(payload)
            altered['delivery'] = {'mode': 'shipping', 'address': 'Новый адрес'}
            self.assertEqual(self.client.put(base+'/summary', json=altered).status_code, 409)
        # A stale manifest and even subsequently altered live DB rows cannot change the frozen job.
        (s.DATA/'exports'/self.order/'manifest.json').write_text('{"total":999,"files":[]}')
        with s.db() as con:
            con.execute('UPDATE allocations SET paid=999 WHERE order_id=?', (self.order,))
        self.assertEqual(self.client.get(base+'/summary').json(), before)
        self.assertEqual(self.client.get(f'/api/orders/{self.order}/export').json(), export)

    def test_b6_gift_total_is_fixed_but_distribution_can_change(self):
        base, _, payload = self.prepared()
        old = self.client.get(base+'/summary').json()
        for gift in (0, 5):
            bad = deepcopy(payload)
            for row in bad['allocations']:
                row['gift'] = gift if row['key'] == 'gift' else 0
            self.assertEqual(self.client.put(base+'/summary', json=bad).status_code, 422)
            self.assertEqual(self.client.get(base+'/summary').json(), old)
        for row in payload['allocations']:
            row['gift'] = 1 if row['key'] == 'person' else 0
        changed = self.client.put(base+'/summary', json=payload)
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(sum(r['paid']+r['gift'] for r in changed.json()['allocations']), changed.json()['total'])

    def test_b7_invalid_inputs_are_422_and_atomic(self):
        base, _, payload = self.prepared()
        before = self.client.get(base+'/summary').json()
        cases = []
        for value in ('abc', '20', 1.9, True, None, {}, -1, 1001):
            bad = deepcopy(payload); bad['allocations'][0]['paid'] = value; cases.append(bad)
            bad = deepcopy(payload); bad['paid_total'] = value; cases.append(bad)
            bad = deepcopy(payload); bad['allocations'][0]['gift'] = value; cases.append(bad)
        bad = deepcopy(payload); bad['allocations'].append(deepcopy(bad['allocations'][0])); cases.append(bad)
        bad = deepcopy(payload); bad['delivery']['recipient'] = {}; cases.append(bad)
        bad = deepcopy(payload); bad['delivery']['mode'] = 'unknown'; cases.append(bad)
        bad = deepcopy(payload); bad['delivery'] = {'mode': 'shipping', 'address': ' '}; cases.append(bad)
        bad = deepcopy(payload); bad['allocations'][0]['key'] = 'unknown'; cases.append(bad)
        bad = deepcopy(payload); bad['delivery']['address'] = 'x'*1001; cases.append(bad)
        for bad in cases:
            with self.subTest(payload=bad):
                response = self.client.put(base+'/summary', json=bad)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(self.client.get(base+'/summary').json(), before)

    def test_b4_whole_order_deletion_includes_published_resources(self):
        photo = self.photo()
        self.assertEqual(self.publish(photo).status_code, 200)
        base, _ = self.link()
        self.select(base, photo)
        self.assertEqual(self.client.delete(f'/api/orders/{self.order}').status_code, 200)
        with s.db() as con:
            for table in ('selection_state', 'client_selections', 'publications', 'production_snapshots'):
                self.assertEqual(con.execute(f'SELECT count(*) FROM {table}').fetchone()[0], 0)
        self.assertFalse((s.DATA/'photos'/f'{photo}.jpg').exists())

    def test_b4_editor_and_cached_exports_detect_missing_resource(self):
        import test_proof_editor
        order, layout = test_proof_editor.ApiTests.make_order(self)
        owner = layout['document']['variants'][0]['owner']
        revision = layout['document']['revision']
        cached = s.DATA/'layouts'/order/revision
        cached.mkdir(parents=True, exist_ok=True)
        (cached/(owner.replace(':', '-')+'.pdf')).write_bytes(b'cached')
        (cached/(owner.replace(':', '-')+'-print.zip')).write_bytes(b'cached')
        with s.db() as con:
            photo = con.execute('SELECT id FROM photos WHERE order_id=? LIMIT 1', (order,)).fetchone()[0]
        (s.DATA/'photos'/f'{photo}.jpg').unlink()
        response = self.client.get(f'/api/orders/{order}/layout')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(any(i['level'] == 'error' and photo in i['message'] for i in response.json()['document']['issues']))
        for endpoint in ('pdf', 'print'):
            self.assertEqual(self.client.get(f'/api/orders/{order}/layout/{endpoint}/{owner}').status_code, 409)

    def test_b5_legacy_authorization_freezes_on_first_export(self):
        base, _, _ = self.prepared()
        before = self.client.get(base+'/summary').json()
        with s.db() as con:
            con.execute('INSERT INTO authorizations VALUES (?,?,?,?)', (self.order, before['revision'], 1, s.now()))
            con.execute("UPDATE orders SET stage='print' WHERE id=?", (self.order,))
        export = self.client.get(f'/api/orders/{self.order}/export')
        self.assertEqual(export.status_code, 200, export.text)
        self.assertEqual(export.json()['production_hash'], before['hash'])
        with s.db() as con:
            self.assertIsNotNone(con.execute('SELECT document FROM production_snapshots WHERE order_id=?', (self.order,)).fetchone())

    def test_b6_zero_gifts_order_cannot_add_a_gift(self):
        self.client.put('/api/profile', json={'teacher_gift': False, 'delivery_modes': 'both'})
        self.order = self.client.post('/api/orders', json={'school_city': 'Казань', 'school': 'Лицей', 'class_name': '1А', 'copies': 20}).json()['id']
        base, _, payload = self.prepared()
        payload['allocations'][0]['gift'] = 1
        self.assertEqual(self.client.put(base+'/summary', json=payload).status_code, 422)
