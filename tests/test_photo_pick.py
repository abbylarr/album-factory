"""Slot categories, hero fallbacks, crops and album-wide assignment of general photos."""
import unittest

from album_factory import photo_pick as pp
from album_factory.master_layout import generate
from album_factory.master_templates import preview_photos, validate, _FlatMeasurer
from album_factory.test_shoot import synthetic

STUDENTS = [{'id': f's{i}', 'first_name': 'Ученик', 'last_name': str(i)} for i in range(12)]


def slot(ident, pick=None, mm=(100, 70), owner='s0', personal=False, target=None, spread='sp', order=0, section='sec'):
    return {'key': ident, 'ident': ident, 'personal': personal, 'owner': owner, 'target': target, 'pick': pick,
            'mm': list(mm), 'aspect_key': round(mm[0] / mm[1], 3), 'section': section, 'spread': spread, 'order': order}


def layer(id, source='class', pick=None, x=10, w=90, h=120):
    value = {'id': id, 'type': 'photo', 'source': source, 'box': {'x': x, 'y': 20, 'w': w, 'h': h}, 'opacity': 100}
    if pick:
        value['pick'] = pick
    return value


def master(pages, kind='fixed', rules=None):
    doc = {'schemaVersion': 1, 'name': 'Тест', 'personalMode': 'owner', 'pageSize': [210, 280],
           'sections': [{'id': 'shared', 'name': 'Общие', 'kind': kind, 'spreads': [
               {'id': 'sp', 'pages': [{'id': 'l', 'background': '#ffffff', 'layers': pages[0]},
                                      {'id': 'r', 'background': '#ffffff', 'layers': pages[1]}]}]}]}
    if rules:
        doc['photoRules'] = rules
    return doc


def snapshot(entries, photos, students=STUDENTS):
    return {'order': {'class_name': '11 А', 'year': '2026'}, 'students': students, 'teachers': [], 'photos': photos,
            'selections': [], 'general': entries, 'general_photos': [e['id'] for e in entries]}


class FitTests(unittest.TestCase):
    def test_crop_keeps_heads_and_refuses_impossible_aspect(self):
        entry = {'safe_box': [.1, .2, .8, .2], 'subject_box': [.1, .2, .8, .7]}
        crop = pp.fit(entry, 1.5, 6000, 4000)
        self.assertEqual(crop[2:], [6000, 4000])
        self.assertIsNone(pp.fit(entry, .5, 6000, 4000))
        cut = pp.fit(entry, .5, 6000, 4000, cut=True)
        self.assertAlmostEqual(cut[0] + cut[2] / 2, 3000, delta=1)
        tall = pp.fit({'safe_box': [.4, .1, .2, .2], 'subject_box': [.4, .1, .2, .8]}, 2, 4000, 6000)
        self.assertLessEqual(tall[1], .1 * 6000)
        self.assertGreaterEqual(tall[1] + tall[3], .3 * 6000)

    def test_categories_resolve_with_master_edits_and_legacy_roles(self):
        c = pp.resolve({'category': 'few', 'who': 'hero'})
        self.assertEqual((c['people'], c['include'], c['fallback']), (['few'], 'item', ['candid', 'dup']))
        self.assertEqual(pp.resolve({'category': 'missing'})['category'], 'any')
        categories = pp.categories_of({'photoCategories': [{'id': 'wide', 'name': 'Очень общий', 'scale': ['wide'], 'people': ['class']},
                                                           {'id': 'mine', 'name': 'Моё', 'style': 'candid'}]})
        self.assertEqual(categories['wide']['name'], 'Очень общий')
        self.assertEqual(pp.resolve({'category': 'wide'}, categories)['people'], ['class'])
        self.assertEqual(pp.resolve({'category': 'mine'}, categories)['style'], 'candid')
        legacy = pp.resolve({'role': 'friends', 'scale': None, 'buckets': ['pair', 'group']})
        self.assertEqual((legacy['include'], legacy['scale'], legacy['people']), ('owner', None, ['few', 'subgroup']))
        self.assertEqual(pp.resolve({'role': 'unknown'})['category'], 'any')


    def test_built_in_categories_can_be_removed_except_any(self):
        doc = master([[layer('a', pick={'category': 'few'})], []])
        doc['removedCategories'] = ['wide', 'empty']
        validate(doc)
        self.assertNotIn('wide', pp.categories_of(doc))
        self.assertEqual(pp.resolve({'category': 'wide'}, pp.categories_of(doc))['category'], 'any')
        for removed, pick in ((['any'], 'few'), (['nope'], 'few'), (['few', 'few'], 'any'), (['few'], 'few')):
            broken = master([[layer('a', pick={'category': pick})], []])
            broken['removedCategories'] = removed
            with self.assertRaises(Exception, msg=removed):
                validate(broken)


class PickerTests(unittest.TestCase):
    def setUp(self):
        self.entries, self.photos = synthetic(STUDENTS)

    def picker(self, rules=None, entries=None):
        return pp.Picker(entries or self.entries, self.photos, {**pp.DEFAULT_RULES, **(rules or {})}, STUDENTS)

    def test_categories_choose_matching_photos_without_repeats(self):
        names = ['class', 'subgroup', 'few', 'solo', 'candid', 'wide', 'empty']
        slots = [slot(n, {'category': n}, (180, 110) if n in ('class', 'wide') else (90, 70), order=i) for i, n in enumerate(names)]
        self.picker().assign(slots)
        by = {e['id']: e for e in self.entries}
        got = {s['ident']: by[s['result']['photo']] for s in slots}
        for name in ('class', 'subgroup', 'few', 'solo'):
            self.assertEqual(pp.people_of(got[name]), name)
        self.assertEqual(pp.people_of(got['empty']), 'none')
        self.assertEqual(got['candid']['style'], 'candid')
        self.assertEqual(slots[names.index('wide')]['result']['scale'], 'wide')
        self.assertFalse(any(e['alt'] for e in got.values()), 'series doubles stay out of ordinary slots')
        self.assertEqual(len({s['result']['photo'] for s in slots}), len(names))
        self.assertTrue(all(not s['result']['relaxed'] for s in slots))

    def test_hero_slots_show_the_hero_prominently_and_fall_back_like_a_designer(self):
        hero = 's5'
        mine = [e for e in self.entries if hero in e['subjects']]
        spread = [slot(f'h{i}', {'category': c, 'who': 'hero'}, (90, 90), target=hero, spread='me', order=i)
                  for i, c in enumerate(('solo', 'few', 'candid'))]
        self.picker().assign(spread)
        for s in spread:
            self.assertIn(hero, next(e for e in self.entries if e['id'] == s['result']['photo'])['subjects'])
        # Without pairs or candids of the hero, a double of a posed group with the hero is taken.
        doubles = [e for e in mine if e['alt']]
        self.assertTrue(doubles)
        only = [e for e in mine if pp.people_of(e) == 'subgroup' and e['style'] == 'posed']
        lone = [slot('pair', {'category': 'few', 'who': 'hero'}, (90, 90), target=hero)]
        self.picker(entries=only).assign(lone)
        self.assertEqual(lone[0]['result']['relaxed'], ['dup'])
        self.assertTrue(next(e for e in only if e['id'] == lone[0]['result']['photo'])['alt'])

    def shoots(self, slots):
        return {next(e for e in self.entries if e['id'] == s['result']['photo'])['shoot'] for s in slots}

    def test_student_spreads_mix_shoots_and_shared_ones_keep_to_one(self):
        # Both rules on, as by default: the student's spread takes several shoots, the shared one stays in one.
        mine = [slot(f'me{i}', {'category': 'any', 'who': 'hero'}, (90, 90), target='s5', spread='me', order=i) for i in range(4)]
        self.picker().assign(mine)
        self.assertEqual(len(self.shoots(mine)), 2)
        # One spread of a forty-frame album: its slots sit close together in the album's order.
        shared = [dict(slot(f'sh{i}', {'category': 'any'}, (90, 90), spread='shared', order=18 + i), total=40) for i in range(4)]
        self.picker().assign(shared)
        self.assertEqual(len(self.shoots(shared)), 1)

    def test_shared_spreads_prefer_students_shown_less_so_far(self):
        for category, behind in (('solo', 's3'), ('few', 's7')):
            picker = self.picker()
            picker.coverage = {s: 0 if s == behind else 4 for s in picker.coverage}
            slots = [slot('x', {'category': category}, (90, 90))]
            picker.assign(slots)
            self.assertIn(behind, next(e for e in self.entries if e['id'] == slots[0]['result']['photo'])['subjects'])

    def test_posed_photos_come_first(self):
        early, late = slot('first', None, (90, 70), order=0, spread='a'), slot('last', None, (90, 70), order=9, spread='b')
        self.picker({'chronology': False}).assign([early, late])
        style = {e['id']: e['style'] for e in self.entries}
        self.assertEqual((style[early['result']['photo']], style[late['result']['photo']]), ('posed', 'candid'))

    def test_personal_slots_show_their_owner_and_may_differ_per_variant(self):
        slots = [slot(f'friends-{o}', {'category': 'few', 'who': 'owner'}, (90, 90), owner=o, personal=True, target=o) for o in ('s1', 's2')]
        self.picker().assign(slots)
        for s in slots:
            entry = next(e for e in self.entries if e['id'] == s['result']['photo'])
            self.assertIn(s['owner'], entry['subjects'])

    def test_relaxation_is_reported_and_reuse_is_last(self):
        few = [e for e in self.entries if e['bucket'] == 'pair'][:1]
        slots = [slot('a', {'category': 'class'}, order=0), slot('b', None, order=1)]
        report = self.picker(entries=few).assign(slots)
        self.assertEqual(slots[0]['result']['photo'], few[0]['id'])
        self.assertIn('people', slots[0]['result']['relaxed'])
        self.assertIn('reuse', slots[1]['result']['relaxed'])
        self.assertEqual(report['slots']['a']['candidates'], 0)

    def test_must_use_wins_and_rejects_stay_out(self):
        must = dict(self.entries[20], flags={'must_use': True})
        bad = dict(self.entries[21], defect='reject', quality=.99)
        entries = [must, bad] + self.entries[22:30]
        slots = [slot('x', None, order=0)]
        report = self.picker(entries=entries).assign(slots)
        self.assertEqual(slots[0]['result']['photo'], must['id'])
        self.assertEqual(report['unplaced'], [])

    def test_legacy_entries_fill_plain_slots(self):
        entries = [{'id': 'old', 'legacy': True}]
        photos = {'old': {'width': 3000, 'height': 2000}}
        slots = [slot('x', None, (90, 60))]
        pp.Picker(entries, photos, pp.DEFAULT_RULES, STUDENTS).assign(slots)
        self.assertEqual(slots[0]['result']['photo'], 'old')
        self.assertEqual(slots[0]['result']['relaxed'], [])


class GenerateTests(unittest.TestCase):
    def test_shared_slots_match_across_variants_and_personal_ones_follow_owner(self):
        entries, photos = synthetic(STUDENTS)
        doc = master([[layer('hero', pick={'role': 'hero'}), layer('mine', pick={'role': 'friends'}, x=110, w=90, h=90)],
                      [layer('class', pick={'role': 'class_photo'}, w=180, h=110)]])
        result = generate({'id': 'e', 'version': 1, 'master': doc}, snapshot(entries, photos), _FlatMeasurer())
        photo = {}
        for owner, spreads in result['variant_spreads'].items():
            for element in next(iter(spreads.values()))['elements']:
                if element.get('slot'):
                    photo.setdefault(element['key'].split('/')[-1], {})[owner] = element['photo']
        self.assertEqual(len(set(photo['hero'].values())), 1)
        self.assertEqual(len(set(photo['class'].values())), 1)
        by = {e['id']: e for e in entries}
        for owner, chosen in photo['mine'].items():
            self.assertIn(owner.split(':')[1], by[chosen]['subjects'])
        self.assertNotIn(photo['hero']['student:s0'], photo['mine'].values())
        self.assertEqual([i for i in result['issues'] if i['level'] == 'error'], [])
        self.assertIn('coverage', result['photo_report'])

    def test_missing_general_photos_is_an_error_for_every_automatic_frame(self):
        collage = {'id': 'c', 'type': 'collage', 'box': {'x': 10, 'y': 10, 'w': 100, 'h': 100}, 'rows': [[{'id': 'c1'}, {'id': 'c2'}]]}
        doc = master([[layer('p')], [collage]])
        result = generate({'id': 'e', 'version': 1, 'master': doc}, snapshot([], {}), _FlatMeasurer())
        missing = {i['key'].split('/')[-1] for i in result['issues'] if i['level'] == 'error'}
        self.assertEqual(missing, {'p', 'c1', 'c2'})

    def test_snapshots_saved_before_analysis_keep_round_robin_order(self):
        collage = {'id': 'c', 'type': 'collage', 'box': {'x': 10, 'y': 10, 'w': 100, 'h': 100}, 'rows': [[{'id': 'c1'}]]}
        doc = master([[layer('a'), layer('b', x=110)], [collage]])
        photos = {'g1': {'width': 300, 'height': 200}, 'g2': {'width': 300, 'height': 200}}
        old = {'order': {'class_name': '1', 'year': '2026'}, 'students': STUDENTS[:2], 'teachers': [], 'photos': photos,
               'selections': [], 'general_photos': ['g1', 'g2']}
        result = generate({'id': 'e', 'version': 1, 'master': doc}, old, _FlatMeasurer())
        for spreads in result['variant_spreads'].values():
            elements = {e['key'].split('/')[-1]: e for e in next(iter(spreads.values()))['elements']}
            self.assertEqual([elements[k]['photo'] for k in ('a', 'b', 'c1')], ['g1', 'g2', 'g1'])
            self.assertNotIn('slot', elements['a'])
        old['general_photos'] = []
        result = generate({'id': 'e', 'version': 1, 'master': doc}, old, _FlatMeasurer())
        cell = next(e for e in next(iter(result['variant_spreads']['student:s0'].values()))['elements'] if e['key'].endswith('/c1'))
        self.assertEqual(cell['type'], 'rect')

    def test_editor_preview_runs_the_same_picker(self):
        doc = master([[layer('hero', pick={'role': 'hero'})], [layer('air', pick={'role': 'atmosphere'})]], rules={'rhythm': False})
        result = preview_photos(doc, 12, 0, 's3')
        self.assertEqual(set(result['slots']), {'shared:0/hero', 'shared:1/air'})
        self.assertEqual(result['slots']['shared:1/air']['bucket'], 'none')
        self.assertTrue(all(0 <= v <= 1 for v in result['slots']['shared:0/hero']['crop']))


if __name__ == '__main__':
    unittest.main()
