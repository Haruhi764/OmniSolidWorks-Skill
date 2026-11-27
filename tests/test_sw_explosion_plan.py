import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from sw_explosion_plan import camera_from, evaluate_path, step_vector, sweeps, visual_metrics


class ExplosionPlanningTests(unittest.TestCase):
    def test_transient_collision_with_clear_endpoints(self):
        boxes = {"a": (0, 0, 0, 1, 1, 1), "b": (3, 0, 0, 4, 1, 1)}
        _, report = evaluate_path(boxes, [{"id": "move", "component": "a",
                                           "direction": "+x", "distance_mm": 7}])
        self.assertEqual(report["final_overlaps"], 0)
        self.assertEqual(report["potential_counts"]["potential_new_overlap"], 1)
        self.assertIsNone(sweeps(boxes["a"], boxes["b"], (-7, 0, 0)))

    def test_initial_contact_and_group_motion(self):
        boxes = {"a": (0, 0, 0, 2, 2, 2), "b": (1, 0, 0, 3, 2, 2)}
        step = {"id": "move", "component": "a", "direction": "-x", "distance_mm": 7}
        _, report = evaluate_path(boxes, [step], mates=[("a", "b")])
        self.assertEqual(report["potential_counts"], {"initial_mate_envelope": 1})
        _, report = evaluate_path(boxes, [{**step, "components": ["a", "b"]}])
        self.assertEqual(report["potential_counts"], {})

    def test_unconfirmed_axis_and_visibility(self):
        with self.assertRaises(ValueError):
            step_vector({"distance_mm": 4, "installation_directions": ["+z", "-z"]})
        self.assertEqual(step_vector({"distance_mm": 4, "installation_directions": ["-z"]}), (0, 0, -4))
        identity = [1, 0, 0, 0, 1, 0, 0, 0, 1]
        boxes = {"a": (0, 0, 0, 2, 2, 2), "b": (0, 0, 4, 2, 2, 6)}
        self.assertEqual(visual_metrics(boxes, identity)["near_hidden"], 1)
        self.assertEqual(visual_metrics(boxes, camera_from(identity, 90, 0))["near_hidden"], 0)


if __name__ == "__main__":
    unittest.main()

