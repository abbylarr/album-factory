"""Model-free rules for general photos: people, shot scale, defects, identity, series."""
import unittest

import numpy as np

from album_factory import general_meta as gm
from album_factory.test_shoot import _person


def raw_with(people, size=(6000, 4000), **extra):
    faces, bodies = [], []
    for cx, hy, face in people:
        f, b = _person(cx, hy, face, size[0] / size[1])
        f['px'] = face * size[1]
        faces.append(f); bodies.append(b)
    return {'size': list(size), 'faces': faces, 'bodies': bodies, **extra}


class ScaleAndPeopleTests(unittest.TestCase):
    def test_scale_follows_visible_body_parts(self):
        cases = {'close': (.5, .34, .26), 'medium': (.5, .24, .12), 'full': (.5, .14, .085), 'wide': (.5, .5, .035)}
        for expected, person in cases.items():
            meta = gm.derive(raw_with([person]), {}, 20)
            self.assertEqual(meta['scale'], expected)
            self.assertEqual(meta['people']['bucket'], 'solo')
        self.assertEqual(gm.derive({'size': [100, 100], 'faces': [], 'bodies': []}, {}, 20)['scale'], 'detail')

    def test_crop_changes_effective_scale(self):
        persons, _ = gm.people(raw_with([(.5, .14, .085)]))
        self.assertEqual(gm.person_scale(persons[0]), 'full')
        self.assertEqual(gm.person_scale(persons[0], (0, 0, 1, .5)), 'medium')

    def test_buckets_and_class(self):
        self.assertEqual(gm.bucket(2, 2, 25), 'pair')
        self.assertEqual(gm.bucket(5, 1, 25), 'small_group')
        self.assertEqual(gm.bucket(9, 3, 25), 'group')
        self.assertEqual(gm.bucket(19, 5, 25), 'class')
        self.assertEqual(gm.bucket(8, 7, 9), 'class')

    def test_repeated_body_of_a_counted_face_is_dropped(self):
        raw = raw_with([(.3, .3, .1), (.6, .3, .1)])
        twin = dict(raw['bodies'][0]); twin['score'] = .5
        raw['bodies'].append(twin)
        self.assertEqual(gm.derive(raw, {}, 20)['people']['count'], 2)

    def test_blurred_background_face_is_confirmed_by_its_body(self):
        raw = raw_with([(.5, .3, .1)])
        raw['faces'][0]['presence'] = -3
        persons, faces = gm.people(raw)
        self.assertFalse(faces[0]['doubtful'])
        raw['bodies'] = []
        persons, faces = gm.people(raw)
        self.assertTrue(faces[0]['doubtful'])
        self.assertEqual(persons, [])

    def test_safe_box_holds_heads_with_room(self):
        meta = gm.derive(raw_with([(.3, .3, .1), (.7, .3, .1)]), {}, 20)
        x, y, w, h = meta['safe_box']
        faces = [p["face"] for p in meta["persons"]]
        self.assertLess(x, faces[0][0]); self.assertGreater(x + w, faces[1][0] + faces[1][2])
        self.assertLess(y, .25)


class DefectTests(unittest.TestCase):
    def test_blur_rejects_only_when_the_sharpest_main_face_is_soft(self):
        raw = raw_with([(.3, .3, .1), (.7, .3, .1)])
        raw['faces'][0]['sharp'] = 40
        self.assertIsNone(gm.derive(raw, {}, 20)['defect'])
        raw['faces'][1]['sharp'] = 50
        self.assertEqual(gm.derive(raw, {}, 20)['defect'], 'reject')

    def test_closed_eyes_reject_posed_frames_but_not_a_downward_look(self):
        raw = raw_with([(.5, .3, .12)], clip={'posed': .8, 'aesthetic': .5})
        raw['faces'][0]['blink'] = [.8, .9]
        self.assertEqual(gm.derive(raw, {}, 20)['defect'], 'reject')
        raw['faces'][0]['pitch'] = -.5
        self.assertIsNone(gm.derive(raw, {}, 20)['defect'])
        raw['faces'][0]['pitch'] = 0
        raw['clip']['posed'] = .2
        meta = gm.derive(raw, {}, 20)
        self.assertIsNone(meta['defect'])
        self.assertEqual([d['level'] for d in meta['defects']], ['minor'])


class IdentityTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(3)
        self.people = {k: v / np.linalg.norm(v) for k, v in zip('abc', rng.normal(size=(3, 128)))}

    def noisy(self, key, amount=.3, seed=0):
        v = self.people[key] + np.random.default_rng(seed).normal(scale=amount / 11, size=128)
        return v / np.linalg.norm(v)

    def test_one_to_one_links_with_levels(self):
        gallery = {k: np.array([v]) for k, v in self.people.items()}
        result = gm.match_faces([self.noisy('a', seed=1), self.noisy('a', seed=2), None, self.noisy('b', 1.5, 3)], gallery)
        self.assertEqual(result[0][0], 'a'); self.assertEqual(result[0][2], 'auto')
        self.assertIsNone(result[1][0])  # the same person cannot appear twice
        self.assertEqual(result[2], (None, None, None))
        self.assertEqual(result[3][0], 'b')

    def test_clusters_never_join_faces_of_one_photo(self):
        items = [('x1', self.noisy('c', seed=1), 'p1'), ('x2', self.noisy('c', seed=2), 'p1'), ('x3', self.noisy('c', seed=3), 'p2')]
        labels = gm.cluster(items)
        self.assertNotEqual(labels['x1'], labels['x2'])
        self.assertEqual(len(set(labels.values())), 2)


class ShootTests(unittest.TestCase):
    def test_series_and_events_with_mixed_offsets(self):
        vec = np.ones(4) / 2
        photos = [{'id': 'a', 'order': 0, 'taken_at': '2026-05-01T10:00:00+03:00', 'clip': vec},
                  {'id': 'b', 'order': 1, 'taken_at': '2026-05-01T10:00:04', 'clip': vec},
                  {'id': 'c', 'order': 2, 'taken_at': '2026-05-01T11:30:00', 'clip': -vec},
                  {'id': 'd', 'order': 3, 'taken_at': None, 'clip': None}]
        self.assertEqual(gm.series(photos), {'a': 'a', 'b': 'a'})
        self.assertEqual(gm.events(photos), {'a': 1, 'b': 1, 'c': 2})


if __name__ == '__main__':
    unittest.main()
