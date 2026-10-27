"""PC-side checks for geometry and the browser data contract (no maix needed)."""
import importlib.util
import math
import pathlib
import tempfile
import unittest


class PoseRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = pathlib.Path(__file__).with_name("main.py")
        if path.exists():
            spec = importlib.util.spec_from_file_location("pose_example", path)
            cls.pose = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.pose)
        else:
            cls.pose = None

    def setUp(self):
        self.assertIsNotNone(self.pose, "main.py pose example has not been implemented")
        self.points = [None] * 17
        for i, xy in {5: (80, 80), 6: (120, 80), 9: (80, 150),
                      10: (120, 150), 11: (80, 160), 12: (120, 160),
                      13: (80, 210), 14: (120, 210),
                      15: (80, 260), 16: (120, 260)}.items():
            self.points[i] = list(xy)

    def test_straight_visible_legs_are_standing(self):
        self.assertIn("standing", self.pose.classify_pose(self.points))

    def test_both_wrists_above_shoulders_are_both_hands_up(self):
        self.points[9][1] = self.points[10][1] = 40
        self.assertIn("both_hands_up", self.pose.classify_pose(self.points))
        self.assertNotIn("left_hand_up", self.pose.classify_pose(self.points))

    def test_missing_opposite_wrist_does_not_claim_single_hand_up(self):
        self.points[9][1] = 40
        self.points[10] = None
        self.assertIn("left_hand_up_right_unknown", self.pose.classify_pose(self.points))
        self.assertNotIn("left_hand_up", self.pose.classify_pose(self.points))

    def test_missing_joints_remain_unknown(self):
        self.assertEqual(["unknown"], self.pose.classify_pose([None] * 17))

    def test_two_bent_knees_are_crouch_or_sit(self):
        self.points[15] = [125, 210]
        self.points[16] = [165, 210]
        self.assertIn("crouch_or_sit", self.pose.classify_pose(self.points))
        self.assertNotIn("standing", self.pose.classify_pose(self.points))

    def test_degenerate_joint_does_not_have_an_angle(self):
        self.assertIsNone(self.pose.joint_angle([1, 1], [1, 1], [2, 1]))

    def test_hidden_and_out_of_frame_points_are_not_exported(self):
        flat = [10, 20] * 17
        flat[0:2] = [-1, 20]
        flat[2:4] = [320, 40]
        flat[4:6] = [math.nan, 30]
        points = self.pose.normalize_points(flat, 320, 224)
        self.assertEqual(points[:3], [None, None, None])
        self.assertEqual(points[3], [10, 20])

    def test_flat_xy_layout_must_have_34_values(self):
        with self.assertRaises(ValueError):
            self.pose.normalize_points([1, 2, 3], 320, 224)

    def test_missing_html_uses_embedded_page_for_single_file_run(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = pathlib.Path(folder) / "index.html"
            actual = self.pose.load_html(missing)
        self.assertEqual(actual, pathlib.Path(__file__).with_name("index.html").read_bytes())

    def test_supplied_html_overrides_embedded_page(self):
        with tempfile.TemporaryDirectory() as folder:
            page = pathlib.Path(folder) / "index.html"
            page.write_bytes(b"<!doctype html><title>custom skeleton page</title>")
            self.assertEqual(self.pose.load_html(page), page.read_bytes())


if __name__ == "__main__":
    unittest.main()
