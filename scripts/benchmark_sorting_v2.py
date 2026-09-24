"""Run isolated V1/V2 trials against existing uploaded images; SQLite is read-only."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from album_factory.sorting_lab import experiment, snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=Path(__file__).resolve().parents[1] / 'data')
    parser.add_argument('--order', required=True)
    parser.add_argument('--limit', type=int, default=120)
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--mode', choices=['compare', 'compare_v3', 'compare_v4_v5', 'v1', 'v2', 'v2_series', 'v3', 'v4', 'v5'], default='compare')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.limit <= 3000 or args.offset < 0:
        parser.error('limit must be 1..3000; offset must be nonnegative')
    with sqlite3.connect(args.data.resolve().joinpath('album.sqlite').as_uri() + '?mode=ro', uri=True) as con:
        con.row_factory = sqlite3.Row
        items = snapshot(con, args.data, args.order, args.limit, args.offset)
        if not items:
            parser.error('No photographs in selected range')
        def assignment_hash():
            rows = [tuple(r) for r in con.execute('SELECT id,status,person_id,embedding,uncertain FROM photos ORDER BY id')]
            return hashlib.sha256(json.dumps(rows).encode()).hexdigest()
        before = assignment_hash()
        def progress(mode, done, total):
            if done % 30 == 0 or done == total:
                print(f'{mode}: {done}/{total}', flush=True)
        result = experiment(items, args.mode, progress)
        result['production_assignments_unchanged'] = before == assignment_hash()
    report = dict(order_id=args.order, total=len(items), offset=args.offset, result=result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({m: {k: v for k, v in r.items() if k != 'photos'} for m, r in result['variants'].items()}, indent=2))
    print('comparisons', json.dumps(result['comparisons']))
    print('versus_v2_series', json.dumps(result.get('versus_v2_series')))
    print('production_assignments_unchanged', result['production_assignments_unchanged'])


if __name__ == '__main__':
    main()
