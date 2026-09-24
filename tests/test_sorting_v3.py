"""V3 must preserve V2-series decisions and prepared pixels with bounded lookahead."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from album_factory.sorting_v2 import run as run_v2, compare, decode
from album_factory.sorting_v3 import PreparedImages, run as run_v3


class PrefetchTests(unittest.TestCase):
    def test_same_results_with_skipped_frames_and_returning_person(self):
        identities = [0,0,0,1,1,1,0,0,0,0,0,0]
        items = [dict(id=str(i),filename=f'DSC{i:03}.jpg',path=str(i)) for i in range(len(identities))]
        class Engine:
            def extract(self, pixels):
                who = identities[int(pixels[0,0,0])]
                return 'ready', [1.,0.] if who == 0 else [0.,1.]
        decoder = lambda path,*a: np.full((8,8,3),int(path),dtype=np.uint8)
        with patch('album_factory.sorting_v2.decode',side_effect=decoder), patch('album_factory.sorting_v3.decode',side_effect=decoder), patch('album_factory.sorting_v2.preview',return_value=(1.,np.zeros((32,32,3)))):
            old = run_v2(items,Engine(),'v2_series')
            new = run_v3(items,Engine())
        self.assertEqual(old['photos'],new['photos'])
        self.assertGreater(new['inferred'],0)
        self.assertEqual(compare(old,new)['changed_photos'],0)
        self.assertEqual(new['persons'],2)

    def test_bounded_prefetch_and_unrequested_failure(self):
        items = [dict(path=str(i)) for i in range(15)]
        def decoder(path,*args):
            if path=='1': raise OSError('broken skipped frame')
            return np.zeros((8,8,3),np.uint8)
        with patch('album_factory.sorting_v3.decode',side_effect=decoder):
            prepared = PreparedImages(items)
            try:
                for i in range(0,15,2):
                    self.assertLessEqual(len(prepared.futures),3)
                    prepared(str(i),True)
                self.assertLessEqual(len(prepared.futures),3)
            finally:
                prepared.close()
        self.assertEqual(len(prepared.futures),0)

    def test_requested_failure_and_full_decode_fallback(self):
        items=[dict(path='bad'),dict(path='good')]
        def decoder(path,fast):
            if path=='bad': raise OSError('broken')
            return np.full((8,8,3),fast,np.uint8)
        with patch('album_factory.sorting_v3.decode',side_effect=decoder):
            prepared=PreparedImages(items)
            try:
                with self.assertRaises(OSError): prepared('bad',True)
                self.assertTrue(np.all(prepared('good',True)==1))
                self.assertTrue(np.all(prepared('good',False)==0))
            finally: prepared.close()

    def test_resize_is_pixel_identical_to_v2_engine_input(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'photo.jpg'
            pixels=np.random.default_rng(0).integers(0,256,(3300,2200,3),dtype=np.uint8)
            Image.fromarray(pixels).save(path)
            expected=decode(path,True)
            h,w=expected.shape[:2]
            scale=1600/max(h,w)
            expected=cv2.resize(expected,(round(w*scale),round(h*scale)))
            actual,*_=PreparedImages.prepare(path)
            np.testing.assert_array_equal(expected,actual)

    def test_empty_input(self):
        result=run_v3([],None)
        self.assertEqual(result['photos'],[])
        self.assertEqual(result['pipeline']['prepared'],0)


if __name__=='__main__': unittest.main()
