import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from omni_gb import audit, dimension_chain, dimension_lanes, dimension_text, inspect_drawing
from v03_schema import validation_geometry


class OmniGBTests(unittest.TestCase):
    def setUp(self):
        self.anchors = {"datum": 0, "shoulder": 20, "end": 55}
        self.dimensions = [{"start": "datum", "end": "shoulder", "mm": 20},
                           {"start": "shoulder", "end": "end", "mm": 35}]

    def test_reference_closure_and_driving_cycle(self):
        total = {"start": "datum", "end": "end", "mm": 55, "reference": True, "text": "(55)"}
        self.assertEqual(dimension_chain(self.anchors, [*self.dimensions, total]), [])
        self.assertIn("closed_chain", {x["code"] for x in dimension_chain(
            self.anchors, [*self.dimensions, dict(total, reference=False)])})

    def test_duplicate_missing_and_incorrect(self):
        first = dict(self.dimensions[0], mm=20.4)
        reverse = {"start": "shoulder", "end": "datum", "mm": 20}
        codes = {x["code"] for x in dimension_chain(self.anchors, [first, reverse])}
        self.assertEqual(codes, {"dimension_value", "duplicate_span", "closed_chain", "unlocated_anchors"})

    def test_label_shape_and_lane_spacing(self):
        for text in ("⌀12H7/g6", "R4", "15°", "(55)"):
            self.assertTrue(dimension_text(text), text)
        for text in ("待确认", "Φ12H7)", "12 mm", "∞"):
            self.assertFalse(dimension_text(text), text)
        self.assertEqual(dimension_lanes([{"paperSpanMm": [1, 30], "text": "29"},
                                          {"paperSpanMm": [2, 8], "text": "6"},
                                          {"paperSpanMm": [40, 48], "text": "8"}], 2.5), [1, 0, 0])

    def test_native_sheet_and_bom_negatives(self):
        contract = {"paper": "A3", "view_scale": .5, "views": {"Front": [30]},
                    "unique_expected_dimensions": True, "bom": {"Pin": 2}}
        native = {"firstAngle": True, "detailStandard": 7, "scale": .5, "sheetMm": [420, 297],
                  "views": [{"role": "Front", "boundsMm": [15, 50, 105, 120], "dimensions": [{"valueMm": 30}]}],
                  "bom": {"rows": [{"part": "Pin", "item": "1", "quantity": 2, "names": ["Pin-1", "Pin-2"]}],
                          "balloons": [{"item": "1", "leaders": 1}]}}
        self.assertTrue(audit(contract, native)["passed"])
        faulty = copy.deepcopy(native)
        faulty["views"][0]["boundsMm"][2] = 425
        faulty["views"][0]["dimensions"] = [{"valueMm": 30}, {"valueMm": 30}]
        faulty["bom"]["rows"][0]["quantity"] = 3
        faulty["bom"]["balloons"] = []
        self.assertEqual({x["code"] for x in inspect_drawing(contract, faulty)},
                         {"view_outside_sheet", "repeated_native_dimension", "bom_instance_quantity",
                          "bom_quantity", "bom_balloon_link"})
        faulty["views"][0]["dimensions"] = []
        self.assertIn("missing_native_dimension", {item["code"] for item in inspect_drawing(contract, faulty)})

    def test_centroid_contract(self):
        spec = {"volume_mm3": 24, "bounds_mm": [[0, 0, 0], [1, 4, 6]],
                "cylinders": [], "centroid_mm": [.5, 2, 3]}
        self.assertEqual(validation_geometry(spec)["centroid_mm"], [.5, 2, 3])
        with self.assertRaises(ValueError):
            validation_geometry(dict(spec, centroid_mm=[-1, 2, 3]))


if __name__ == "__main__":
    unittest.main()
