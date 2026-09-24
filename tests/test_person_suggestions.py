import json
import unittest
from album_factory.person_suggestions import suggestions


def photo(n,person='a',vector=(1.,0.),uncertain=0,status='ready'):
    return dict(id=str(n),filename=f'DSC{n:04}.jpg',person_id=person,
                embedding=json.dumps(vector) if vector is not None else None,uncertain=uncertain,status=status)


class SuggestionTests(unittest.TestCase):
    def test_selected_embedding_is_not_its_own_reference(self):
        result=suggestions([photo(1)],['1'])
        self.assertEqual(result[0]['candidates'],[])

    def test_weak_face_and_neighbors_combine_without_assigning(self):
        rows=[photo(1),photo(2,'new',(.4,.916515),1),photo(3)]
        original=json.dumps(rows)
        hint=suggestions(rows,['2'])[0]
        self.assertEqual(hint['candidates'][0]['reason'],'face_and_neighbors')
        self.assertAlmostEqual(hint['candidates'][0]['similarity'],.4)
        self.assertEqual(json.dumps(rows),original)

    def test_missing_face_has_no_invented_similarity(self):
        hint=suggestions([photo(1),photo(2,None,None,status='no_face'),photo(3)],['2'])[0]
        self.assertFalse(hint['has_embedding'])
        self.assertIsNone(hint['candidates'][0]['similarity'])
        self.assertEqual(hint['candidates'][0]['reason'],'neighbors')

    def test_different_or_uncertain_neighbors_do_not_corroborate(self):
        for right in [photo(3,'b',(0.,1.)),photo(3,uncertain=1),photo(30)]:
            hint=suggestions([photo(1),photo(2,'new',(.4,.916515),1),right],['2'])[0]
            self.assertEqual(hint['neighbors'],[])
            self.assertFalse(any(c['reason']=='face_and_neighbors' for c in hint['candidates']))

    def test_contradicting_face_is_not_called_combined(self):
        rows=[photo(1),photo(2,'new',(0.,1.),1),photo(3),photo(9,'b',(0.,1.))]
        hint=suggestions(rows,['2'])[0]
        self.assertEqual(hint['candidates'][0]['person_id'],'b')
        self.assertFalse(any(c['reason']=='face_and_neighbors' for c in hint['candidates']))

    def test_neighbors_do_not_cross_shoot_boundaries(self):
        rows=[photo(1),photo(2,None,None,status='no_face'),photo(3)]
        for row,shoot in zip(rows,['a','b','a']): row['shoot_id']=shoot
        hint=suggestions(rows,['2'])[0]
        self.assertEqual(hint['neighbors'],[])
        self.assertEqual(hint['candidates'],[])

    def test_batch_does_not_use_selected_neighbors(self):
        hints=suggestions([photo(1),photo(2),photo(3)],['1','2'])
        self.assertTrue(all(not h['neighbors'] for h in hints))

if __name__=='__main__':unittest.main()
