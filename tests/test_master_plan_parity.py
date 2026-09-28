"""The editor (web/master-plan-core.js, web/collage-core.js) and generation (master_plan.py, flex_frames) must agree."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

from album_factory.master_layout import flex_frames
from album_factory.master_plan import list_plan, people

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
]
CASES = [(section, n, cap) for section in SECTIONS for n in (0, 1, 5, 12, 22, 37, 80) for cap in (0, 6, 12)]
ASPECTS = [[1.5], [0.75], [1.5, 1.5], [1.5, 0.66], [0.66, 0.66, 1.5], [1.5, 1.5, 1.5, 1.5], [0.75, 1.33, 1.5, 0.8], [1.5] * 5, [1.2] * 6]
BOXES = [(178, 120, 4, 4), (90, 230, 3, 6), (182, 230, 0, 0)]


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

    def test_last_spread_replaces_a_half_filled_one(self):
        plan = list_plan({**SECTIONS[0], 'target': 1}, 30, 12)  # three pages of ten: one full spread, then the last spread
        self.assertEqual([s['role'] for s in plan['spreads']], ['repeat', 'last'])
        self.assertEqual(plan['counts'], [10, 10, 10])
        self.assertNotIn('half', plan['issues'])
        self.assertIn('half', list_plan({**SECTIONS[3], 'target': 1}, 40, 12)['issues'])
        self.assertIn('no-repeat', list_plan(SECTIONS[4], 80, 12)['issues'])

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


if __name__ == '__main__':
    unittest.main()
