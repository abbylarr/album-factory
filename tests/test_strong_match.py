import unittest
from album_factory.faces import choose_person


class StrongMatchTests(unittest.TestCase):
    def test_high_individual_match_overrides_low_group_average(self):
        groups={'girl': [[.96,.28],[0.,1.],[0.,1.]]}
        self.assertIsNone(choose_person([1.,0.],groups)[0])
        self.assertEqual(choose_person([1.,0.],groups,strong_match_threshold=.93),('girl',False))

    def test_threshold_is_inclusive_and_does_not_accept_below_it(self):
        for score,expected in [(.93,'girl'),(.929,None)]:
            groups={'girl':[[score,0.],[0.,1.],[0.,1.]]}
            self.assertEqual(choose_person([1.,0.],groups,strong_match_threshold=.93)[0],expected)

    def test_high_match_can_override_old_margin_but_not_an_exact_tie(self):
        groups={'girl':[[.96,0.]],'other':[[.95,0.]]}
        self.assertEqual(choose_person([1.,0.],groups,strong_match_threshold=.93),('girl',False))
        groups['other']=[[.96,0.]]
        self.assertIsNone(choose_person([1.,0.],groups,strong_match_threshold=.93)[0])

if __name__=='__main__':unittest.main()
