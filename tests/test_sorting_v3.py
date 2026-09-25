"""Production V3 image preparation and sequence rules."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from album_factory.sorting_v3 import PreparedImages, bridge_allowed, decode, ordered


class PrefetchTests(unittest.TestCase):
    def test_numeric_order_and_bridge_guards(self):
        items = [dict(id=str(i), filename=f'DSC{n}.jpg') for i, n in enumerate((4, 1, 2))]
        left, middle, right = ordered(items)
        self.assertEqual([p['filename'] for p in (left, middle, right)], ['DSC1.jpg', 'DSC2.jpg', 'DSC4.jpg'])
        previews = {p['id']: (1., np.zeros((32, 32, 3))) for p in items}
        self.assertTrue(bridge_allowed(left, middle, right, previews))
        previews[middle['id']] = (1., np.ones((32, 32, 3)))
        self.assertFalse(bridge_allowed(left, middle, right, previews))

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

    def test_resize_matches_v3_decode(self):
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

if __name__=='__main__': unittest.main()
