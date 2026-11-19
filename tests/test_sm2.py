"""SM-2 scheduler against hand-computed values.

Rules: Wozniak (1990), "SuperMemo 2: Algorithm", https://super-memory.com/english/ol/sm2.htm.
EF' = EF + (0.1 - (5-q) * (0.08 + (5-q) * 0.02)): q=5 adds 0.1, q=4 adds 0, q=3 subtracts 0.14.
"""
import unittest

import helpers  # noqa: F401  (sets import paths)
import dansk_db
from dansk_db import mastery, sm2


class SM2(unittest.TestCase):
    def test_three_perfect_reviews(self):
        ef, i, n = 2.5, 0, 0
        ef, i, n = sm2(5, ef, i, n)
        self.assertEqual((ef, i, n), (2.6, 1, 1))          # I(1) = 1
        ef, i, n = sm2(5, ef, i, n)
        self.assertEqual((ef, i, n), (2.7, 6, 2))          # I(2) = 6
        ef, i, n = sm2(5, ef, i, n)
        self.assertEqual((ef, i, n), (2.8, 17, 3))         # ceil(6 * 2.8) = ceil(16.8) = 17

    def test_lapse_resets_without_changing_ef(self):
        ef, i, n = 2.8, 17, 3
        ef, i, n = sm2(2, ef, i, n)
        self.assertEqual((ef, i, n), (2.8, 1, 0))
        ef, i, n = sm2(5, ef, i, n)                        # starts again from I(1)
        self.assertEqual((ef, i, n), (2.9, 1, 1))

    def test_quality_zero_and_one_also_reset(self):
        for q in (0, 1):
            self.assertEqual(sm2(q, 2.18, 6, 2), (2.18, 1, 0))

    def test_quality_four_keeps_ef(self):
        self.assertEqual(sm2(4, 2.5, 0, 0), (2.5, 1, 1))
        self.assertEqual(sm2(4, 2.5, 1, 1), (2.5, 6, 2))
        self.assertEqual(sm2(4, 2.5, 6, 2), (2.5, 15, 3))  # 6 * 2.5 = 15 exactly, not 16

    def test_ef_floor(self):
        # q=3 subtracts 0.14: 2.36, 2.22, 2.08, 1.94, 1.80, 1.66, 1.52, 1.38, then floor 1.3.
        expected = [2.36, 2.22, 2.08, 1.94, 1.8, 1.66, 1.52, 1.38, 1.3, 1.3, 1.3]
        ef, i, n = 2.5, 0, 0
        for want in expected:
            ef, i, n = sm2(3, ef, i, n)
            self.assertAlmostEqual(ef, want, places=6)
        self.assertEqual(ef, dansk_db.EF_FLOOR)

    def test_interval_uses_updated_ef(self):
        # third review at q=3 from EF 2.5: EF 2.5 -> 2.36 -> 2.22 -> 2.08; I(3) = ceil(6 * 2.08) = 13
        ef, i, n = 2.5, 0, 0
        for _ in range(3):
            ef, i, n = sm2(3, ef, i, n)
        self.assertEqual(i, 13)

    def test_bad_quality(self):
        for q in (-1, 6, 2.5, "4"):
            with self.assertRaises(ValueError):
                sm2(q, 2.5, 0, 0)

    def test_mastery_rule(self):
        self.assertEqual([mastery(r) for r in (0, 1, 4, 5, 9)], [0, 1, 4, 5, 5])

    def test_add_days(self):
        self.assertEqual(dansk_db.add_days("2026-11-28", 17), "2026-12-15")


if __name__ == "__main__":
    unittest.main()
