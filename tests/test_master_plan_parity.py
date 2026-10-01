"""The editor (web/master-plan-core.js, web/collage-core.js) and generation (master_plan.py, flex_frames) must agree."""
import json
import math
import shutil
import subprocess
import unittest
from pathlib import Path

from album_factory.master_layout import caption_floor, card_slots, fill_capacity, fill_pages, flex_frames, geometry, row_counts
from album_factory.master_plan import list_plan, people, personal_take

ROOT = Path(__file__).resolve().parents[1]


def page(key, grid=False):
    return {'id': key, 'layers': [{'id': key + 'g', 'type': 'grid'}] if grid else []}


def spread(key, role, left=False, right=False):
    return {'id': key, 'role': role, 'pages': [page(key + 'l', left), page(key + 'r', right)]}


SECTIONS = [
    # Classic: two vignette pages per spread, a last spread with one vignette and a photo.
    {'id': 'a', 'target': 2, 'list': {'min': 4, 'max': 12}, 'spreads': [spread('r', 'repeat', True, True), spread('z', 'last', True)]},
    # Teachers: lead portrait next to the first vignette, then full vignette spreads.
    {'id': 'b', 'target': 1, 'list': {'min': 3, 'max': 9}, 'spreads': [spread('i', 'intro', False, True), spread('r', 'repeat', True, True)]},
    # One vignette per spread, decorated page opposite, closing spread.
    {'id': 'c', 'target': 3, 'list': {'min': 2, 'max': 8}, 'spreads': [spread('r', 'repeat', True), spread('o', 'outro')]},
    # Two alternating designs and no last spread: a half-filled spread is reported.
    {'id': 'd', 'target': 2, 'list': {'min': 4, 'max': 12}, 'spreads': [spread('r1', 'repeat', True, True), spread('r2', 'repeat', False, True), spread('r3', 'repeat', True, True)]},
    # Only intro vignettes: overflow has nowhere to go.
    {'id': 'e', 'target': 1, 'list': {'min': 4, 'max': 12}, 'spreads': [spread('i', 'intro', True, True)]},
    # No vignette at all.
    {'id': 'f', 'target': 1, 'list': {'min': 4, 'max': 12}, 'spreads': [spread('x', 'repeat')]},
    # Only a last spread holds the vignette.
    {'id': 'g', 'target': 1, 'list': {'min': 1, 'max': 12}, 'spreads': [spread('i', 'intro'), spread('z', 'last', True, True)]},
    # The first part of a split list: stops after two spreads, the rest goes to its continuation.
    {'id': 'h', 'target': 1, 'limit': 2, 'list': {'min': 4, 'max': 12}, 'spreads': [spread('i', 'intro', False, True), spread('r', 'repeat', True, True), spread('z', 'last', True)]},
    # A limit shorter than the opening spreads keeps them and one vignette page.
    {'id': 'k', 'target': 3, 'limit': 1, 'list': {'min': 2, 'max': 8}, 'spreads': [spread('i', 'intro'), spread('r', 'repeat', True), spread('o', 'outro')]},
    # One vignette spread repeating, no last spread: the list ends on a whole spread when it can.
    {'id': 'm', 'target': 2, 'list': {'min': 2, 'max': 12}, 'spreads': [spread('r', 'repeat', True, True)]},
]
CASES = [(section, n, cap) for section in SECTIONS for n in (0, 1, 5, 12, 22, 37, 80) for cap in (0, 6, 12)]
ASPECTS = [[1.5], [0.75], [1.5, 1.5], [1.5, 0.66], [0.66, 0.66, 1.5], [1.5, 1.5, 1.5, 1.5], [0.75, 1.33, 1.5, 0.8], [1.5] * 5, [1.2] * 6]
BOXES = [(178, 120, 4, 4), (90, 230, 3, 6), (182, 230, 0, 0)]
CARD_BASE = {'gap': 5, 'minPhotoWidth': 20, 'photoWidth': 85, 'fontSize': 12, 'photoNameGap': 3, 'nameDetailGap': 2, 'detailFontSize': 9}
CARDS = [{}, {'showDetail': True}, {'showDetail': True, 'detailAt': 'above'}, {'nameAt': 'right', 'captionWidth': 50},
         {'showDetail': True, 'nameAt': 'left', 'detailAt': 'left', 'photoRatio': 1}, {'nameAt': 'over', 'showDetail': True, 'detailAt': 'over', 'photoRatio': 0.8},
         {'nameAt': 'over', 'overInset': 8, 'photoNameGap': 1, 'showDetail': True, 'detailAt': 'below'},
         {'showDetail': True, 'nameAt': 'above', 'detailAt': 'right', 'photoRatio': 2 / 3, 'lineHeight': 1.5},
         {'anchor': 'top-left'}, {'anchor': 'bottom', 'nameAt': 'right'}, {'anchor': 'right', 'photoRatio': 1},
         {'minFontSize': 6, 'minPhotoWidth': 5}, {'minFontSize': 14, 'nameAt': 'below'},
         {'source': 'teachers', 'textCase': 'upper', 'minFontSize': 9}, {'source': 'teachers', 'nameAt': 'right', 'captionWidth': 60},
         {'showDetail': True, 'nameAt': 'left', 'detailAt': 'left', 'sideAlign': 0}, {'nameAt': 'right', 'sideAlign': 1}]


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class PlanParityTest(unittest.TestCase):
    def run_js(self, script, payload):
        prelude = ("const fs=require('fs'),vm=require('vm');const c=vm.createContext({window:{}});"
                   "vm.runInContext(fs.readFileSync('web/master-plan-core.js','utf8'),c);"
                   "vm.runInContext(fs.readFileSync('web/collage-core.js','utf8'),c);"
                   "const input=JSON.parse(fs.readFileSync(0,'utf8'));")
        out = subprocess.run(['node', '-e', prelude + script], input=json.dumps(payload), capture_output=True, text=True, cwd=ROOT, check=True)
        return json.loads(out.stdout)

    def test_editor_upgrades_old_masters(self):
        subprocess.run(['node', 'tests/test_master_plan_core.js'], cwd=ROOT, check=True, capture_output=True)

    def test_list_blocks_unfold_the_same(self):
        js = self.run_js("process.stdout.write(JSON.stringify(input.map(([s,n,cap])=>c.window.MasterPlan.listPlan(s,n,cap))));", CASES)
        for (section, n, cap), plan in zip(CASES, js):
            with self.subTest(section=section['id'], n=n, cap=cap):
                self.assertEqual(list_plan(section, n, cap), plan)

    def test_everyone_is_placed_when_the_block_can_grow(self):
        for section in SECTIONS[:4]:
            for n in (1, 22, 80):
                plan = list_plan(section, n, 12)
                parts = [p['part'] for s in plan['spreads'] for p in s['pages'] if p['part'] is not None]
                self.assertEqual(sum(plan['counts'][i] for i in parts), n, section['id'])
                self.assertNotIn('overflow', plan['issues'])

    def test_split_list_takes_the_first_pages_of_an_even_split(self):
        part = SECTIONS[7]
        plan = list_plan(part, 54, 12)  # the whole list: five pages of 11/11/11/11/10; this part has three
        self.assertEqual(plan['counts'], [11, 11, 11])
        self.assertEqual(plan['taken'], 33)
        self.assertEqual(len(plan['spreads']), 2)
        self.assertEqual(list_plan(part, 30, 12)['taken'], 30, 'a list that fits is not cut')
        rest = list_plan({key: value for key, value in part.items() if key != 'limit'}, 54 - 33, 12)
        self.assertEqual(sum(rest['counts']), 21)

    def test_split_personal_parts_take_whole_people(self):
        cases = [[{'spreads': [{}] * per, **({'limit': limit} if limit else {})}, n] for per in (1, 2, 3) for limit in (0, 1, 4, 10) for n in (0, 1, 7, 30)]
        js = self.run_js("process.stdout.write(JSON.stringify(input.map(([s,n])=>c.window.MasterPlan.personalTake(s,n))));", cases)
        self.assertEqual([personal_take(s, n) for s, n in cases], js)

    def test_last_spread_replaces_a_half_filled_one(self):
        plan = list_plan({**SECTIONS[0], 'target': 1}, 30, 12)  # three pages of ten: one full spread, then the last spread
        self.assertEqual([s['role'] for s in plan['spreads']], ['repeat', 'last'])
        self.assertEqual(plan['counts'], [10, 10, 10])
        self.assertNotIn('half', plan['issues'])
        # A short list keeps the half spread only when neither more pages (below the minimum) nor fewer (cards do not fit) work.
        self.assertIn('half', list_plan({**SECTIONS[3], 'target': 1}, 5, 12)['issues'])
        self.assertIn('no-repeat', list_plan(SECTIONS[4], 80, 12)['issues'])

    def test_list_ends_on_a_whole_spread(self):
        two = {'id': 'w', 'target': 1, 'list': {'min': 4, 'max': 12}, 'spreads': [spread('r', 'repeat', True, True)]}
        # 25 people, 12 a page: three pages would leave the fourth empty, four pages keep the minimum.
        self.assertEqual(list_plan(two, 25, 12)['counts'], [7, 6, 6, 6])
        self.assertEqual(list_plan(two, 25, 12)['issues'], [])
        # Five people: two pages would go below the minimum, so the second page stays empty and is reported.
        self.assertEqual(list_plan(two, 5, 12)['issues'], ['half'])
        # Stretched to three pages with a minimum of 2 and 7 people: back to two pages rather than up to four.
        self.assertEqual(list_plan({**two, 'target': 2, 'list': {'min': 2, 'max': 12}}, 7, 12)['counts'], [4, 3])

    def test_rows_take_one_more_and_never_leave_one_alone(self):
        self.assertEqual(row_counts(13, 4, 4), [4, 4, 3, 2])
        self.assertEqual(row_counts(13, 4, 3), [5, 4, 4])
        self.assertEqual(row_counts(14, 4, 3), [5, 5, 4])
        self.assertEqual(row_counts(11, 5, 3), [4, 4, 3])
        self.assertEqual(row_counts(7, 6, 2), [4, 3])
        self.assertEqual(row_counts(3, 4, 1), [3])
        # Thirteen cards fit as five, five and three: no row is squeezed while the cards fit without it.
        layer = {**CARD_BASE, 'minPhotoWidth': 30, 'minFontSize': 8, 'box': {'w': 178, 'h': 224}}
        self.assertIsNone(geometry(13, layer)['tight'])
        # With twelve a page, the thirteenth squeezes into the first row instead.
        geo = geometry(13, {**layer, 'max': 12})
        self.assertEqual((geo['cols'], geo['rows']), (4, 3))
        self.assertLess(geo['tight']['photo_w'], geo['photo_w'])

    def test_teachers_share_one_spread_the_same(self):
        teachers = {**CARD_BASE, 'gap': 4, 'source': 'teachers', 'minFontSize': 8, 'minPhotoWidth': 30, 'showDetail': True, 'max': 12}
        layouts = [[{**teachers, 'box': {'w': 178, 'h': 224}}, {**teachers, 'box': {'w': 178, 'h': 224}}],
                   [{**teachers, 'box': {'w': 178, 'h': 224}, 'photoRatio': 1, 'leadRatio': 2 / 3, 'anchor': 'top'}, {**teachers, 'box': {'w': 178, 'h': 224}, 'photoRatio': 1}],
                   [{**teachers, 'box': {'w': 202, 'h': 264}}, {**teachers, 'box': {'w': 178, 'h': 224}, 'gap': 0, 'anchor': 'bottom'}],
                   [{**teachers, 'box': {'w': 178, 'h': 224}, 'nameAt': 'right', 'captionWidth': 40}]]
        payload = [[grids, n, big] for grids in layouts for n in (1, 2, 5, 9, 12, 13, 14, 18, 19, 24, 30) for big in (True, False)]
        js = self.run_js("vm.runInContext(fs.readFileSync('web/master-planner.js','utf8'),Object.assign(c,{MasterPlan:c.window.MasterPlan,document:{createElement:()=>({getContext:()=>({})})}}));"
                         "const p=c.window.MasterPlanner({sections:[]},{});process.stdout.write(JSON.stringify(input.map(([g,n,b])=>[p.fillPages(g,n,b,4),p.fillCapacity(g,b,4)])));", payload)
        for (grids, n, big), (plan, most) in zip(payload, js):
            with self.subTest(grids=len(grids), n=n, big=big):
                ours = fill_pages(grids, n, big, 4)
                self.assertEqual((ours['fits'], ours['lead_card']), (plan['fits'], plan['leadCard']))
                for a, b in zip(ours['pages'], plan['pages']):
                    self.assertEqual((a['count'], a['top']), (b['count'], b['top']))
                    self.assertAlmostEqual(a['cap'], b['cap'], places=9)
                    self.assertAlmostEqual(a['push'], b['push'], places=9)
                    self.assertEqual(a['lead'] is None, b['lead'] is None)
                    if a['lead']:
                        for k, j in (('x', 'x'), ('y', 'y'), ('photo_w', 'photoW')):
                            self.assertAlmostEqual(a['lead'][k], b['lead'][j], places=9)
                self.assertEqual(fill_capacity(grids, big, 4), most)
        # Twelve teachers and the class teacher: the class teacher takes a page of his own, the teachers the other.
        two = layouts[0]
        plan = fill_pages(two, 13, True, 4)
        self.assertEqual(sorted(p['count'] for p in plan['pages']), [0, 12])
        self.assertTrue(any(p['lead'] for p in plan['pages']))
        # Eighteen: the class teacher shares a page with a short row, the other page squeezes a row rather than leave one alone.
        plan = fill_pages(two, 18, True, 4)
        self.assertFalse(plan['lead_card'])
        self.assertTrue(all(p['count'] >= 4 for p in plan['pages']))
        # Too many for a larger portrait: the class teacher is a card like the others.
        self.assertTrue(fill_pages(two, 25, True, 4)['lead_card'])

    def test_personal_blocks(self):
        students = ['s0', 's1', 's2']
        payload = [[{'people': mode}, students, 's1'] for mode in ('all', 'others', 'owner', 'off', None)]
        js = self.run_js("process.stdout.write(JSON.stringify(input.map(([s,l,o])=>c.window.MasterPlan.people(s,l,o))));", payload)
        self.assertEqual(js, [people(s, l, o) for s, l, o in payload])
        self.assertEqual(js[:4], [students, ['s0', 's2'], ['s1'], []])

    def test_flexible_collage_frames(self):
        payload = [[box, aspects] for box in BOXES for aspects in ASPECTS]
        js = self.run_js("process.stdout.write(JSON.stringify(input.map(([b,a])=>c.window.CollageCore.flexFrames(b[0],b[1],a,b[2],b[3]))));", payload)
        for (box, aspects), frames in zip(payload, js):
            py = flex_frames(box[0], box[1], aspects, box[2], box[3])
            self.assertEqual(len(py), len(aspects))
            for a, b in zip(py, frames):
                for k in 'xywh':
                    self.assertAlmostEqual(a[k], b[k], places=9)
        # Two landscape photos stack in a tall area; one portrait takes the whole frame.
        tall = flex_frames(90, 230, [1.5, 1.5], 3, 6)
        self.assertEqual(tall[0]['x'], tall[1]['x'])
        self.assertEqual(flex_frames(90, 120, [0.75])[0], {'x': 0, 'y': 0, 'w': 90, 'h': 120})

    def test_vignette_cards_measure_the_same(self):
        payload = [[{**CARD_BASE, **card, 'box': {'w': w, 'h': h}}, n] for card in CARDS + [{'centerLastRow': True}, {'max': 8}] for w, h in ((178, 224), (90, 230), (202, 120)) for n in (1, 4, 9, 13, 17)]
        js = self.run_js("vm.runInContext(fs.readFileSync('web/master-planner.js','utf8'),Object.assign(c,{document:{createElement:()=>({getContext:()=>({})})}}));"
                         "const p=c.window.MasterPlanner({sections:[]},{});process.stdout.write(JSON.stringify(input.map(([l,n])=>{const g=p.gridGeometry(n,l);return g&&{...g,slots:[n,n-1,Math.ceil(n/2)].map(k=>p.cardSlots(k,g,l))};})));", payload)
        for (layer, n), geo in zip(payload, js):
            with self.subTest(layer=layer, n=n):
                py = geometry(n, layer)
                self.assertEqual(py is None, geo is None)
                if py is None:
                    continue
                self.assertEqual((py['cols'], py['rows']), (geo['cols'], geo['rows']))
                for a, b in (('cell_w', 'cellW'), ('cell_h', 'cellH'), ('photo_w', 'photoW'), ('photo_h', 'photoH'), ('offset_x', 'offsetX'), ('offset_y', 'offsetY'), ('block_w', 'blockW'), ('full_w', 'fullW')):
                    self.assertAlmostEqual(py[a], geo[b], places=9)
                self.assertEqual(py['tight'] is None, geo['tight'] is None)
                if py['tight']:
                    self.assertAlmostEqual(py['tight']['photo_w'], geo['tight']['photoW'], places=9)
                    self.assertAlmostEqual(py['tight']['cell_w'], geo['tight']['cellW'], places=9)
                for k, slots in zip((n, n-1, math.ceil(n/2)), geo['slots']):
                    ours = card_slots(k, py, layer)
                    self.assertEqual(len(ours), len(slots))
                    for (x, y, squeezed), slot in zip(ours, slots):
                        self.assertAlmostEqual(x, slot['x'], places=9)
                        self.assertAlmostEqual(y, slot['y'], places=9)
                        self.assertEqual(squeezed, slot['tight'])
                self.assertEqual(set(py['parts']), set(geo['parts']))
                for key, box in py['parts'].items():
                    for value, k in zip(box, 'xywh'):
                        self.assertAlmostEqual(value, geo['parts'][key][k], places=9)
        # Defaults keep the old card: photo on top, captions under it, card as wide as the photo.
        old = geometry(12, {**CARD_BASE, 'box': {'w': 178, 'h': 224}})
        self.assertEqual(old['cell_w'], old['photo_w'])
        self.assertEqual(old['parts']['name'][1], old['photo_h'] + 3)
        top = geometry(4, {**CARD_BASE, 'anchor': 'top-left', 'box': {'w': 178, 'h': 224}})
        self.assertEqual((top['offset_x'], top['offset_y']), (0, 0))
        low = geometry(4, {**CARD_BASE, 'anchor': 'bottom-right', 'box': {'w': 178, 'h': 224}})
        self.assertAlmostEqual(low['offset_y'] + 2*low['cell_h'] + 5, 224)
        # Tiny photos do not count as fitting when the names under them could not be read.
        tiny = {**CARD_BASE, 'minPhotoWidth': 5, 'minFontSize': 10, 'box': {'w': 178, 'h': 224}}
        self.assertIsNone(geometry(80, tiny))
        self.assertGreaterEqual(geometry(20, tiny)['parts']['name'][2], 15*.52*10*.3528)
        # A teacher's name needs a wider caption than a student's, capitals wider still.
        caps = lambda **extra: max(n for n in range(1, 60) if geometry(n, {**tiny, **extra}))
        self.assertGreater(caps(), caps(source='teachers'))
        self.assertGreaterEqual(caps(source='teachers'), caps(source='teachers', textCase='upper'))
        self.assertGreater(caption_floor({**tiny, 'source': 'teachers', 'textCase': 'upper'}), caption_floor({**tiny, 'source': 'teachers'}))
        # Beside the photo a teacher's name may wrap, so only its longest word has to fit the caption.
        self.assertLess(caption_floor({**tiny, 'source': 'teachers', 'nameAt': 'left'}), caption_floor({**tiny, 'source': 'teachers'}))
        side = geometry(4, {**CARD_BASE, 'nameAt': 'right', 'captionWidth': 50, 'box': {'w': 178, 'h': 224}})
        self.assertAlmostEqual(side['cell_w'], side['photo_w'] + 53)
        # A caption beside the photo stands at the set height: level with the photo top, centred, or down at its foot.
        at = lambda align: geometry(4, {**CARD_BASE, 'nameAt': 'right', 'sideAlign': align, 'box': {'w': 178, 'h': 224}})['parts']
        top, middle, foot = at(0), at(.5), at(1)
        self.assertAlmostEqual(top['name'][1], top['photo'][1])
        self.assertAlmostEqual(middle['name'][1] + middle['name'][3] / 2, middle['photo'][1] + middle['photo'][3] / 2)
        self.assertAlmostEqual(foot['name'][1] + foot['name'][3], foot['photo'][1] + foot['photo'][3])


if __name__ == '__main__':
    unittest.main()
