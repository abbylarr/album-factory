"""Block rules (rulesVersion 2): list blocks with spread roles, personal blocks per block, book layout, flexible collages."""
from copy import deepcopy
import unittest

from album_factory.layout_workspace import measurer
from album_factory.master_layout import generate
from album_factory.master_templates import _FlatMeasurer, preview_photos
import test_server_v2


def page(key, layers=None):
    return {'id': key, 'background': '#ffffff', 'layers': layers or []}


def grid(key):
    return {'id': key, 'type': 'grid', 'box': {'x': 16, 'y': 33, 'w': 178, 'h': 224}, 'source': 'students', 'gap': 5,
            'minPhotoWidth': 32, 'photoWidth': 85, 'font': 'Arial', 'fontSize': 12, 'minFontSize': 10, 'color': '#34332f'}


def photo(key, source, pick=None):
    layer = {'id': key, 'type': 'photo', 'box': {'x': 10, 'y': 10, 'w': 190, 'h': 250}, 'source': source}
    if pick:
        layer['pick'] = pick
    return layer


def flex(key, low=1, high=4, pick=None):
    return {'id': key, 'type': 'collage', 'box': {'x': 10, 'y': 10, 'w': 190, 'h': 250}, 'gapX': 4, 'gapY': 4, 'fill': '#e6e1ea',
            'rows': [[{'id': key + 'c', 'source': 'class'}]], 'flex': {'min': low, 'max': high}, 'pick': pick or {'category': 'any', 'who': 'hero'}}


def master():
    teachers = grid('tg')
    teachers['source'] = 'teachers'
    return {'schemaVersion': 1, 'rulesVersion': 2, 'layout': 'spreads', 'name': 'Правила блоков', 'sections': [
        {'id': 'intro', 'name': 'Начало', 'kind': 'fixed', 'spreads': [{'id': 'i', 'pages': [page('il'), page('ir', [photo('ip', 'owner')])]}]},
        {'id': 'teachers', 'name': 'Учителя', 'kind': 'flow', 'target': 1,
         'list': {'source': 'teachers', 'min': 3, 'max': 12, 'strictMin': False, 'excludeLead': True},
         'spreads': [{'id': 't1', 'role': 'intro', 'pages': [page('t1l', [photo('lead', 'lead')]), page('t1r', [teachers])]},
                     {'id': 't2', 'role': 'repeat', 'pages': [page('t2l', [dict(teachers, id='tg2')]), page('t2r', [dict(teachers, id='tg3')])]}]},
        {'id': 'students', 'name': 'Класс', 'kind': 'flow', 'target': 1,
         'list': {'source': 'students', 'min': 4, 'max': 12, 'strictMin': False, 'excludeLead': False},
         'spreads': [{'id': 's1', 'role': 'repeat', 'pages': [page('s1l', [grid('g1')]), page('s1r', [grid('g2')])]},
                     {'id': 's2', 'role': 'last', 'pages': [page('s2l', [grid('g3')]), page('s2r', [photo('group', 'class')])]}]},
        {'id': 'mine', 'name': 'Мой разворот', 'kind': 'repeat', 'people': 'owner',
         'spreads': [{'id': 'm', 'pages': [page('ml', [photo('mp', 'item')]), page('mr')]}]},
        {'id': 'others', 'name': 'Одноклассники', 'kind': 'repeat', 'people': 'others',
         'spreads': [{'id': 'o', 'pages': [page('ol', [photo('op', 'item')]), page('or', [{'id': 'who', 'type': 'text', 'box': {'x': 10, 'y': 10, 'w': 150, 'h': 20},
                                                                                          'text': '{{item.name}}', 'font': 'Arial', 'fontSize': 12, 'color': '#333333', 'align': 'left'}])]}]},
    ]}


def snapshot(students=12, teachers=5):
    return {'students': [{'id': f's{i}', 'first_name': 'Ученик', 'last_name': str(i)} for i in range(students)],
            'teachers': [{'id': f't{i}', 'first_name': 'Учитель', 'last_name': str(i), 'is_class_teacher': i == 0} for i in range(teachers)],
            'photos': {}, 'selections': [], 'order': {'class_name': '11А', 'year': '2026'}}


def names(document, owner, section):
    return [e['text'] for key, spread in document['variant_spreads'][owner].items() if spread['section'] == section
            for e in spread['elements'] if e['key'].endswith('/name')]


class BlockRulesTests(unittest.TestCase):
    def build(self, doc=None, **counts):
        return generate({'id': 'v2', 'version': 1, 'master': doc or master()}, snapshot(**counts), measurer())

    def test_list_block_places_everyone_once_and_uses_the_last_spread(self):
        for n in (1, 12, 30, 54, 80):
            result = self.build(students=n)
            placed = names(result, 'student:s0', 'students')
            self.assertEqual(sorted(placed), sorted(f'Ученик {i}' for i in range(n)), n)
        # 30 students with twelve per page: three pages of ten, the third on the last spread with the group photo.
        result = self.build(students=30)
        keys = [key for key, spread in result['variant_spreads']['student:s0'].items() if spread['section'] == 'students']
        self.assertEqual(len(keys), 2)
        second = result['variant_spreads']['student:s0'][keys[1]]
        self.assertTrue(any(e['key'].endswith('/group') for e in second['elements']))

    def test_teacher_intro_keeps_the_lead_once(self):
        result = self.build(teachers=20)
        leads = [e for spread in result['variant_spreads']['student:s0'].values() for e in spread['elements'] if e['key'].endswith('/lead')]
        self.assertEqual(len(leads), 1)
        self.assertEqual(len(names(result, 'student:s0', 'teachers')), 19)

    def test_personal_blocks_choose_people_per_block(self):
        result = self.build(students=4)
        plan = {p['section']: p['spreads'] for p in result['plan']}
        self.assertEqual((plan['mine'], plan['others']), (1, 3))
        spreads = result['variant_spreads']['student:s2']
        mine = [s for s in spreads.values() if s['section'] == 'mine']
        others = [s for s in spreads.values() if s['section'] == 'others']
        self.assertEqual(len(mine), 1)
        self.assertEqual(len(others), 3)
        shown = [e['text'] for s in others for e in s['elements'] if e['key'].endswith('/who')]
        self.assertEqual(shown, ['Ученик 0', 'Ученик 1', 'Ученик 3'])

    def test_book_layout_leaves_the_outer_pages_unprinted(self):
        doc = master()
        doc['layout'] = 'book'
        result = self.build(doc, students=4)
        sequence = result['variants'][0]['sequence']
        spreads = result['variant_spreads']['student:s0']
        first, last = spreads[sequence[0]], spreads[sequence[-1]]
        self.assertEqual(first['blank'], [0])
        self.assertEqual(last['blank'], [1])
        self.assertFalse(any(e['box'][0] < 210 for e in first['elements']))
        self.assertEqual(result['layout'], 'book')
        self.assertEqual(result['page_count'], len(sequence) * 2 - 2)
        plain = self.build(students=4)
        self.assertNotIn('layout', plain)
        self.assertFalse(any('blank' in s for s in plain['variant_spreads']['student:s0'].values()))

    def test_spread_stacking_crosses_the_fold(self):
        def order(doc):
            result = self.build(doc, students=4)
            spread = next(s for s in [*result['shared_spreads'].values(), *result['variant_spreads']['student:s0'].values()] if s['section'] == 'intro')
            return [e['key'].rsplit('/', 1)[-1] for e in spread['elements'] if e['key'].rsplit('/', 1)[-1] in {'ip', 'note'}]
        doc = master()
        note = {'id': 'note', 'type': 'text', 'box': {'x': 150, 'y': 10, 'w': 100, 'h': 20}, 'text': 'Подпись',
                'font': 'Arial', 'fontSize': 12, 'color': '#333333', 'align': 'left'}
        doc['sections'][0]['spreads'][0]['pages'][0]['layers'].append(note)
        self.assertEqual(order(doc), ['note', 'ip'])  # no order yet: the left page stays under the right one
        note['z'], doc['sections'][0]['spreads'][0]['pages'][1]['layers'][0]['z'] = 1, 0
        self.assertEqual(order(doc), ['ip', 'note'])


def split_master(limit=1):
    """Students split into two parts with a general block between them."""
    doc = master()
    first = doc['sections'][2]
    first['limit'] = limit
    rest = deepcopy(first)
    rest.update(id='students2', name='Класс, продолжение', continues='students')
    del rest['limit']
    for spread in rest['spreads']:
        spread['id'] += 'b'
        for p in spread['pages']:
            p['id'] += 'b'
            for layer in p['layers']:
                layer['id'] += 'b'
    general = {'id': 'general', 'name': 'Общие', 'kind': 'fixed', 'spreads': [{'id': 'gen', 'pages': [page('genl'), page('genr')]}]}
    doc['sections'][3:3] = [general, rest]
    return doc


def split_personal(limit=2):
    """Personal spreads of the classmates: the first part, general spreads, then the rest of the class."""
    doc = master()
    others = doc['sections'][4]
    others['limit'] = limit
    rest = deepcopy(others)
    rest.update(id='others2', name='Одноклассники, продолжение', continues='others')
    del rest['limit']
    rest['spreads'] = [{'id': 'o2', 'pages': [page('o2l', [photo('o2p', 'item')]), page('o2r', [dict(others['spreads'][0]['pages'][1]['layers'][0], id='who2')])]}]
    doc['sections'] += [{'id': 'general', 'name': 'Общие', 'kind': 'fixed', 'spreads': [{'id': 'gen', 'pages': [page('genl'), page('genr')]}]}, rest]
    return doc


class SplitListTests(unittest.TestCase):
    def build(self, doc, **counts):
        return generate({'id': 'v2', 'version': 1, 'master': doc}, snapshot(**counts), measurer())

    def test_parts_continue_the_list_without_repeats(self):
        for n in (8, 30, 54, 80):
            result = self.build(split_master(), students=n)
            first, rest = names(result, 'student:s0', 'students'), names(result, 'student:s0', 'students2')
            self.assertEqual(first + rest, [f'Ученик {i}' for i in range(n)], n)
            order = [spread['section'] for spread in (result['variant_spreads']['student:s0'][k] for k in result['variants'][0]['sequence'])]
            self.assertLess(order.index('general'), order.index('students2') if 'students2' in order else len(order))
            # The first part stops after one spread: two vignette pages at most.
            self.assertLessEqual(sum(1 for s in result['variant_spreads']['student:s0'].values() if s['section'] == 'students'), 1)

    def test_pages_stay_even_across_parts(self):
        # 54 students, twelve per page: five pages of about eleven; the first part takes the first two pages.
        result = self.build(split_master(), students=54)
        self.assertEqual(len(names(result, 'student:s0', 'students')), 22)
        self.assertEqual(len(names(result, 'student:s0', 'students2')), 32)

    def test_a_short_list_leaves_the_continuation_out(self):
        result = self.build(split_master(limit=3), students=10)
        self.assertEqual(len(names(result, 'student:s0', 'students')), 10)
        self.assertEqual([p['spreads'] for p in result['plan'] if p['section'] == 'students2'], [0])

    def test_a_continuation_above_its_start_is_reported(self):
        doc = split_master()
        doc['sections'].insert(2, doc['sections'].pop(4))
        result = self.build(doc, students=30)
        self.assertEqual(names(result, 'student:s0', 'students2'), [])
        self.assertEqual(len(names(result, 'student:s0', 'students')), 20)
        self.assertTrue(any(i['key'] == 'students2' and i['level'] == 'error' for i in result['issues']))


    def test_personal_spreads_continue_after_general_ones(self):
        result = self.build(split_personal(), students=6)
        spreads = result['variant_spreads']['student:s2']
        order = [spreads[k]['section'] for k in result['variants'][2]['sequence']]
        shown = lambda key: [e['text'] for k in result['variants'][2]['sequence'] for e in spreads[k]['elements'] if e['key'].split('/')[-1] == key]
        self.assertEqual(shown('who'), ['Ученик 0', 'Ученик 1'])
        self.assertEqual(shown('who2'), ['Ученик 3', 'Ученик 4', 'Ученик 5'])
        self.assertLess(order.index('general'), order.index('others2'))


class FlexibleCollageTests(unittest.TestCase):
    def doc(self, pick=None, low=1, high=4):
        doc = master()
        doc['sections'] = [s for s in doc['sections'] if s['id'] in ('mine',)]
        doc['sections'][0]['spreads'][0]['pages'][1]['layers'] = [flex('fx', low, high, pick)]
        return doc

    def frames(self, result, prefix='mine:'):
        return {k: v for k, v in result['slots'].items() if '/fx/flex' in k}

    def test_takes_only_the_photos_that_fit_and_lays_them_out(self):
        result = preview_photos(self.doc(), 12, 0, 's0')
        found = self.frames(result)
        self.assertTrue(1 <= len(found) <= 4)
        self.assertEqual(len({slot['photo'] for slot in found.values()}), len(found), 'no photo twice in one collage')
        self.assertTrue(all(slot.get('photo') for slot in found.values()))

    def test_nothing_honest_keeps_the_minimum_and_reports_it(self):
        impossible = {'category': 'empty', 'who': 'hero'}  # nobody is on photos without people
        result = preview_photos(self.doc(impossible, 2, 4), 12, 0, 's0')
        self.assertEqual(len(self.frames(result)), 2)

    def test_frames_never_overlap_and_stay_in_the_area(self):
        from album_factory.test_shoot import synthetic
        people = [{'id': f's{i}', 'first_name': 'Ученик', 'last_name': str(i)} for i in range(12)]
        entries, photos = synthetic(people)
        snap = {**snapshot(12, 0), 'students': people, 'photos': photos, 'general': entries, 'general_photos': [e['id'] for e in entries]}
        result = generate({'id': 'fx', 'version': 1, 'master': self.doc()}, snap, _FlatMeasurer(), only_owner='s0')
        cells = [e for s in result['variant_spreads']['student:s0'].values() for e in s['elements'] if '/fx/flex' in e['key']]
        self.assertTrue(cells)
        for e in cells:
            x, y, w, h = e['box']
            self.assertTrue(220 - .01 <= x and x + w <= 410 + .01 and 10 - .01 <= y and y + h <= 260 + .01, e['box'])
        for a in cells:
            for b in cells:
                if a is not b:
                    ax, ay, aw, ah = a['box']; bx, by, bw, bh = b['box']
                    self.assertFalse(ax < bx + bw - .01 and bx < ax + aw - .01 and ay < by + bh - .01 and by < ay + ah - .01)


class ValidationTests(unittest.TestCase):
    setUp = test_server_v2.V2Tests.setUp

    def post(self, doc):
        return self.client.post('/api/master-templates', json={'document': doc})

    def test_v2_documents_are_accepted_and_checked(self):
        self.assertEqual(self.post(master()).status_code, 201)
        self.assertEqual(self.post(split_master()).status_code, 201)
        self.assertEqual(self.post(split_personal()).status_code, 201)
        bad = []
        doc = master(); doc['sections'][2]['spreads'][0]['role'] = 'middle'; bad.append(doc)
        doc = master(); doc['sections'][2]['list']['min'] = 20; bad.append(doc)
        doc = master(); doc['sections'][2]['spreads'][0]['pages'][0]['layers'][0]['source'] = 'teachers'; bad.append(doc)
        doc = master(); doc['sections'][3]['people'] = 'friends'; bad.append(doc)
        doc = master(); doc['layout'] = 'magazine'; bad.append(doc)
        doc = master(); doc['sections'][3]['spreads'][0]['pages'][1]['layers'] = [flex('fx', 3, 2)]; bad.append(doc)
        doc = master(); del doc['sections'][2]['list']; bad.append(doc)
        doc = master(); doc['sections'][2]['limit'] = 2; bad.append(doc)
        doc = split_master(); doc['sections'][4]['continues'] = 'teachers'; bad.append(doc)
        doc = split_master(); doc['sections'][4]['continues'] = 'nowhere'; bad.append(doc)
        doc = split_master(); doc['sections'][2]['limit'] = 0; bad.append(doc)
        doc = split_personal(); doc['sections'][-1]['people'] = 'all'; bad.append(doc)
        doc = split_master(); doc['sections'].append({**deepcopy(doc['sections'][4]), 'id': 'students3'}); bad.append(doc)
        for doc in bad:
            self.assertEqual(self.post(doc).status_code, 422)
        legacy = master(); del legacy['rulesVersion']
        self.assertEqual(self.post(legacy).status_code, 422, 'a v1 document still needs its personal mode')


if __name__ == '__main__':
    unittest.main()
