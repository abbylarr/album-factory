"""The editor preview (web/collage-core.js) and the PDF layout (collage_frames) must place collage frames identically."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

from album_factory.master_layout import collage_frames

ROOT = Path(__file__).resolve().parents[1]


def leaf(i):
    return {'id': f'c{i}', 'source': 'class'}


LAYERS = [
    {'box': {'x': 0, 'y': 0, 'w': 140, 'h': 100}, 'gapX': 4, 'gapY': 4, 'rows': [[leaf(1), leaf(2)], [leaf(3), leaf(4)]]},
    {'box': {'x': 3, 'y': 5, 'w': 120, 'h': 90}, 'gapX': 7.5, 'gapY': 2, 'rows': [
        [leaf(1), {'id': 's1', 'split': 'v', 'cells': [leaf(2), {'id': 's2', 'split': 'h', 'cells': [leaf(3), leaf(4), leaf(5)]}]}],
        [leaf(6)],
        [leaf(7), leaf(8), leaf(9)]]},
    {'box': {'x': 0, 'y': 0, 'w': 20, 'h': 12}, 'gapX': 40, 'gapY': 0, 'rows': [[{'id': 's', 'split': 'h', 'cells': [leaf(1), leaf(2)]}]]},
]


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class CollageParityTest(unittest.TestCase):
    def test_frames_match(self):
        script = (
            "const fs=require('fs'),vm=require('vm');const c=vm.createContext({window:{}});"
            "vm.runInContext(fs.readFileSync('web/collage-core.js','utf8'),c);"
            "const layers=JSON.parse(fs.readFileSync(0,'utf8'));"
            "process.stdout.write(JSON.stringify(layers.map(l=>c.window.CollageCore.frames(l).map(f=>[f.cell.id,f.x,f.y,f.w,f.h]))));"
        )
        out = subprocess.run(['node', '-e', script], input=json.dumps(LAYERS), capture_output=True, text=True, cwd=ROOT, check=True).stdout
        for layer, js in zip(LAYERS, json.loads(out)):
            py = [[f['cell']['id'], f['x'], f['y'], f['w'], f['h']] for f in collage_frames(layer)]
            self.assertEqual(len(py), len(js))
            for a, b in zip(py, js):
                self.assertEqual(a[0], b[0])
                for x, y in zip(a[1:], b[1:]):
                    self.assertAlmostEqual(x, y, places=9)


if __name__ == '__main__':
    unittest.main()
