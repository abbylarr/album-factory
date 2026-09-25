"""Read-only review hints. Similarity is a cosine score, never a probability."""
import json
import numpy as np
from .sorting_v3 import ordered, sequence_key


def suggestions(rows, selected_ids):
    selected = set(selected_ids)
    sequences = {}
    for p in rows:
        sequences.setdefault(p.get('shoot_id'), []).append(p)
    sequences = {key: ordered(value) for key, value in sequences.items()}
    positions = {p['id']: i for sequence in sequences.values() for i, p in enumerate(sequence)}
    groups = {}
    for p in rows:
        if p['id'] in selected or not p['person_id'] or not p['embedding'] or p['uncertain'] or p['status'] != 'ready':
            continue
        groups.setdefault(p['person_id'], []).append(json.loads(p['embedding']))
    matrices = {pid: np.asarray(values) for pid, values in groups.items()}
    hints = []
    for photo in rows:
        if photo['id'] not in selected:
            continue
        candidates = []
        if photo['embedding']:
            vector = np.asarray(json.loads(photo['embedding']))
            for person, samples in matrices.items():
                values = samples @ vector
                candidates.append(dict(person_id=person, similarity=float(values.max()), mean=float(values.mean())))
            candidates.sort(key=lambda c: c['similarity'], reverse=True)
        sequence = sequences[photo.get('shoot_id')]
        index = positions[photo['id']]
        neighbors = []
        if 0 < index < len(sequence) - 1:
            left, right = sequence[index-1], sequence[index+1]
            keys = [sequence_key(p) for p in (left, photo, right)]
            if (all(k is not None for k in keys) and len({k[0] for k in keys}) == 1
                    and all(0 < b[1]-a[1] <= 3 for a,b in zip(keys,keys[1:]))
                    and all(p['id'] not in selected and p['status']=='ready' and not p['uncertain']
                            and p['person_id'] and p['embedding'] for p in (left,right))
                    and left['person_id']==right['person_id']):
                neighbors = [dict(id=p['id'],filename=p['filename'],person_id=p['person_id']) for p in (left,right)]
        neighbor_person = neighbors[0]['person_id'] if neighbors else None
        # Only corroborating evidence is highlighted; no changes to assignment or
        # recognition thresholds. A competing face candidate blocks a combined hint.
        best = candidates[0] if candidates else None
        runner = candidates[1]['similarity'] if len(candidates)>1 else -1
        combined = bool(best and best['person_id']==neighbor_person and best['similarity']>=.35
                        and best['similarity']-runner>=.03)
        for c in candidates[:3]:
            c['reason'] = 'face_and_neighbors' if combined and c['person_id']==neighbor_person else 'neighbors' if c['person_id']==neighbor_person else 'face'
        candidates = candidates[:3]
        if neighbor_person and not any(c['person_id']==neighbor_person for c in candidates):
            candidates.append(dict(person_id=neighbor_person, similarity=None, mean=None, reason='neighbors'))
        hints.append(dict(photo_id=photo['id'],status=photo['status'],has_embedding=bool(photo['embedding']),
                          candidates=candidates,neighbors=neighbors))
    return hints
