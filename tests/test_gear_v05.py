"""Offline guard and independent gear arithmetic tests; live runs are separate."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from gear_v05 import gear


class GearInputTests(unittest.TestCase):
    def test_reducer_48_wheel(self):
        row = gear("Wheel", 48, 2.5, 20, -20, 20, 32.05, 10)
        self.assertAlmostEqual(row["pitch"], 63.85066634855473)
        self.assertAlmostEqual(row["tip"] - row["root"], 5.625)
        self.assertAlmostEqual(math.degrees(row["twist"]), -6.532103572)
        self.assertEqual([section["z"] for section in row["sections"]], [0, 10, 20])

    def test_spur_has_identical_end_sections(self):
        row = gear("Spur", 24, 2.5, 20, 0, 12, 20)
        self.assertEqual(row["sections"][0]["points"], row["sections"][-1]["points"])

    def test_reject_invalid_inputs(self):
        for values in [
            ("../source", 48, 2.5, 20, 20, 20, 32),
            ("Wheel", 48, 2.5, 20, 31, 20, 32),
            ("Wheel", 48, float("nan"), 20, 20, 20, 32),
            ("Wheel", 48, 2.5, 20, 20, 20, 128),
        ]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                gear(*values)


if __name__ == "__main__":
    unittest.main()

