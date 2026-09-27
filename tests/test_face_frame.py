"""Face box normalisation without loading the recognition models."""
import unittest

import numpy as np

from album_factory.faces import FaceEngine


class _Detector:
    def __init__(self, faces):
        self.faces = faces
        self.size = None

    def setInputSize(self, size):
        self.size = size

    def detect(self, image):
        if self.faces is None:
            return 0, None
        height, width = image.shape[:2]
        rows = []
        for x, y, w, h in self.faces:
            rows.append([x * width, y * height, w * width, h * height])
        return 1, np.array(rows, dtype=np.float32)


class FaceFrameTests(unittest.TestCase):
    def engine(self, faces):
        engine = FaceEngine.__new__(FaceEngine)
        engine.detector = _Detector(faces)
        return engine

    def test_single_face_is_normalised(self):
        engine = self.engine([(0.1, 0.2, 0.3, 0.4)])
        image = np.zeros((100, 200, 3), dtype=np.uint8)
        box = engine.frame(image)
        self.assertEqual(engine.detector.size, (200, 100))
        self.assertAlmostEqual(box[0], 0.1)
        self.assertAlmostEqual(box[1], 0.2)
        self.assertAlmostEqual(box[2], 0.3)
        self.assertAlmostEqual(box[3], 0.4)

    def test_none_when_missing_or_multiple(self):
        image = np.zeros((40, 40, 3), dtype=np.uint8)
        self.assertIsNone(self.engine(None).frame(image))
        self.assertIsNone(self.engine([(0.1, 0.1, 0.2, 0.2), (0.5, 0.5, 0.2, 0.2)]).frame(image))


if __name__ == "__main__":
    unittest.main()
