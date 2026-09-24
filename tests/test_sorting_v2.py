"""Behavioral checks for isolated trials, sequence risk, and returning people."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
from fastapi.testclient import TestClient

from album_factory import server
from album_factory.sorting_v2 import bridge_allowed, compare, ordered, run


class SequenceTests(unittest.TestCase):
    def items(self, count):
        return [dict(id=str(i), filename=f'DSC{i:04}.jpg', path=str(i)) for i in range(count)]

    def execute(self, identities, mode='v2_series', names=None):
        items = self.items(len(identities))
        if names:
            for p, name in zip(items, names):
                p['filename'] = name
        class Engine:
            def extract(self, image):
                identity = identities[image]
                if identity is None:
                    return 'multiple_faces', None
                return 'ready', [1., 0.] if identity == 'A' else [0., 1.]
        with patch('album_factory.sorting_v2.decode', side_effect=lambda p, *a: int(p)), patch(
                'album_factory.sorting_v2.preview', return_value=(1., np.zeros((32,32,3)))):
            return run(items, Engine(), mode)

    def test_returning_person_does_not_swallow_middle_person(self):
        result = self.execute(['A','A','A','B','B','B','A','A','A'])
        photos = result['photos']
        self.assertEqual(result['persons'], 2)
        self.assertEqual(photos[0]['person_id'], photos[8]['person_id'])
        self.assertNotEqual(photos[0]['person_id'], photos[4]['person_id'])
        self.assertEqual(photos[3]['source'], 'face')
        self.assertEqual(photos[5]['source'], 'face')
        self.assertEqual([p['source'] for p in photos], ['face','sequence','face','face','face','face','face','sequence','face'])

    def test_hidden_single_person_is_flagged_not_claimed_verified(self):
        # A-B-A cannot be ruled out using filenames/preview similarity alone.
        result = self.execute(['A','B','A'])
        middle = result['photos'][1]
        self.assertTrue(middle['uncertain'])
        self.assertEqual(middle['source'], 'sequence')
        self.assertEqual(middle['anchors'], ['0', '2'])
        diff = compare(self.execute(['A','B','A'], 'v1'), result)
        self.assertEqual(diff['merged_pairs'], 2)
        self.assertEqual(diff['changed_photos'], 3)

    def test_multiple_faces_endpoint_prevents_inference(self):
        result = self.execute(['A','A',None])
        self.assertEqual(result['inferred'], 0)
        self.assertEqual(result['photos'][2]['status'], 'multiple_faces')

    def test_gaps_prefixes_and_duplicates_block_inference(self):
        for names in [['DSC1.jpg','DSC10.jpg','DSC11.jpg'], ['A1.jpg','B2.jpg','B3.jpg'],
                      ['DSC1.jpg','DSC1.jpg','DSC2.jpg'], ['one.jpg','two.jpg','three.jpg']]:
            with self.subTest(names=names):
                self.assertEqual(self.execute(['A']*3, names=names)['inferred'], 0)
        self.assertEqual(self.execute(['A']*3, names=['DSC11.jpg','DSC13.jpg','DSC15.jpg'])['inferred'], 1)

    def test_last_frame_and_non_numeric_names_are_processed(self):
        result = self.execute(['A']*4)
        self.assertEqual(len(result['photos']), 4)
        self.assertEqual(result['photos'][-1]['source'], 'face')

    def test_preview_change_blocks_bridge(self):
        items = self.items(3)
        previews = {str(i): (1., np.full((32,32,3), i % 2)) for i in range(3)}
        self.assertFalse(bridge_allowed(*items, previews))

    def test_comparison_ignores_arbitrary_group_numbers(self):
        baseline = self.execute(['A','A','B','B'], 'v1')
        candidate = json.loads(json.dumps(baseline))
        for photo in candidate['photos']:
            photo['person_id'] = 'renamed-' + photo['person_id']
        self.assertEqual(compare(baseline,candidate)['changed_photos'], 0)

    def test_decode_error_does_not_drop_photograph(self):
        with patch('album_factory.sorting_v2.decode', side_effect=OSError):
            result = run(self.items(1), None, 'v2')
        self.assertEqual(result['errors'], 1)
        self.assertEqual(len(result['photos']), 1)


class TrialAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patches = [patch.object(server, 'DATA', Path(self.tmp.name)), patch.object(server.executor, 'submit')]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.client = TestClient(server.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.assertEqual(self.client.get('/sorting-lab').status_code, 200)
        self.client.headers['origin'] = 'http://testserver'
        self.order = self.client.post('/api/orders', json=dict(school='Test',class_name='A',copies=1)).json()['id']
        with server.db() as con:
            con.execute('INSERT INTO persons VALUES (?,?,?,?)', ('person',self.order,'Manual name',server.now()))
            con.execute("INSERT INTO photos (id,order_id,filename,sha,status,person_id,embedding,created_at) VALUES (?,?,?,?,?,?,?,?)", ('photo',self.order,'DSC001.jpg','sha','ready','person','[1,0]',server.now()))
        for suffix in ['.jpg','.thumb.jpg']:
            Image.new('RGB',(100,100)).save(server.DATA/'photos'/('photo'+suffix))

    def test_trial_leaves_production_rows_untouched(self):
        before = self.client.get('/api/orders/'+self.order).json()
        class Engine:
            def extract(self, pixels): return 'no_face', None
        with patch('album_factory.sorting_lab.FaceEngine', Engine):
            response = self.client.post(f'/api/orders/{self.order}/sorting-trials', json=dict(limit=1))
            self.assertEqual(response.status_code, 202)
            trial_id=response.json()['id']
            for _ in range(200):
                report = self.client.get('/api/sorting-trials/'+trial_id).json()
                if report['status'] in {'complete','error'}: break
                time.sleep(.01)
            self.assertEqual(report['status'], 'complete')
        self.assertEqual(before, self.client.get('/api/orders/'+self.order).json())
        self.assertEqual(set(report['result']['variants']), {'v1','v2','v2_series','v3'})
        self.assertTrue((server.DATA/'sorting_trials'/(trial_id+'.json')).exists())

    def test_invalid_limit_and_busy_worker(self):
        self.assertEqual(self.client.post(f'/api/orders/{self.order}/sorting-trials',json={'limit':0}).status_code,422)
        with server.db() as con:
            con.execute("UPDATE photos SET status='pending'")
        self.assertEqual(self.client.post(f'/api/orders/{self.order}/sorting-trials',json={}).status_code,409)

    def test_same_origin_required_and_no_path_traversal(self):
        self.client.headers['origin']='http://elsewhere'
        self.assertEqual(self.client.post(f'/api/orders/{self.order}/sorting-trials',json={}).status_code,403)
        self.assertEqual(self.client.get('/api/sorting-trials/not-a-valid-id').status_code,404)


if __name__ == '__main__':
    unittest.main()
