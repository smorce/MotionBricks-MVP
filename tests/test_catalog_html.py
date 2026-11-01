import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from catalog_html import parse_collection_html
from d3_router import choose_pose, load_catalog, measure_selection

HTML = """
<div class="row" id="F001"><div><h3>自然に立つ</h3><small>F001 · 立つ・待つ</small></div>
<div class="links"><a class="download" href="assets/general/F001/pose.bvh">BVH</a></div></div>
<div class="row" id="F043"><div><h3>座ってくつろぐ</h3><small>F043 · 椅子に座る</small></div>
<div class="links"><a class="download" href="assets/general/F043/pose.bvh">BVH</a></div></div>
<div class="row" id="MARTIAL_001"><div><h3>ストレートと掌ガード</h3><small>MARTIAL_001 · 打撃・組手</small></div>
<div class="links"><a class="download" href="assets/martial/MARTIAL_001/person_1.bvh">BVH 人物1</a>
<a class="download" href="assets/martial/MARTIAL_001/person_2.bvh">BVH 人物2</a></div></div>
"""


class CatalogHtmlTests(unittest.TestCase):
    def test_parse_rows(self):
        rows = parse_collection_html(HTML, "日常・動作", "https://pose-loom.pages.dev/collection-general")
        self.assertEqual([row["id"] for row in rows], ["F001", "F043", "MARTIAL_001_p1", "MARTIAL_001_p2"])
        self.assertIn("立つ", rows[0]["category"])
        self.assertTrue(rows[0]["bvh_url"].endswith("/assets/general/F001/pose.bvh"))
        self.assertIn("自然に立つ", rows[0]["features"])

    def test_selection_measurement_records_time(self):
        catalog = load_catalog()
        with patch.dict(os.environ, {"D3_API_URL": ""}):
            report = measure_selection(catalog)
        self.assertEqual(report["count"], 3)
        self.assertEqual(report["accuracy"], 1.0)
        self.assertGreaterEqual(report["mean_elapsed_ms"], 0.0)
        self.assertTrue(all(row["correct"] for row in report["cases"]))


class ChoiceInputTests(unittest.TestCase):
    def test_click_and_pose_are_accepted(self):
        catalog = load_catalog()
        with patch.dict(os.environ, {"D3_API_URL": ""}):
            decision = choose_pose(
            "floor",
            "stand",
            1.2,
            catalog,
            click_x=0.4,
            click_y=-1.0,
            pose_summary="root=(0.00,0.00) facing=0deg height=0.95",
        )
        self.assertTrue(decision.pose_id)
        self.assertGreaterEqual(decision.elapsed_ms, 0.0)


if __name__ == "__main__":
    unittest.main()
