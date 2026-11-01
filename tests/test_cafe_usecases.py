import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from cafe_usecases import load_usecases, resolve_usecase
from d3_router import choose_arrival_pose, load_catalog


def _response(answer_key: str, choice: str, confidence: float = 0.82):
    payload = {"answers": {answer_key: {"type": "choice", "choice": choice, "confidence": confidence}}}
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False
    return mock_resp


class CafeUsecaseTests(unittest.TestCase):
    def test_markers_cover_separate_cafe_spots(self):
        cases = load_usecases()
        markers = [case for case in cases if case["marker"]]
        self.assertGreaterEqual(len(markers), 12)
        self.assertIn("open-floor", {case["id"] for case in cases})
        for left_index, left in enumerate(markers):
            for right in markers[left_index + 1 :]:
                distance = ((left["x"] - right["x"]) ** 2 + (left["z"] - right["z"]) ** 2) ** 0.5
                self.assertGreaterEqual(distance, 2.0, f"{left['id']} and {right['id']} are {distance:.2f}m apart")

    def test_unknown_click_is_open_floor(self):
        case = resolve_usecase("not-a-place")
        self.assertEqual(case["id"], "open-floor")
        self.assertFalse(case["marker"])

    def test_fallback_uses_full_catalog_hint(self):
        catalog = load_catalog()
        self.assertEqual(len(catalog), 1173)
        bistro = resolve_usecase("bistro-sit")
        phone = resolve_usecase("phone-wait")
        with patch.dict(os.environ, {"D3_API_URL": ""}, clear=False):
            sat = choose_arrival_pose(bistro, 2.0, catalog, click_x=1.0, click_y=0.2)
            looked = choose_arrival_pose(phone, 1.4, catalog)
        self.assertEqual(sat.backend, "fallback-no-api")
        self.assertEqual(sat.catalog_size, 1173)
        self.assertIn(sat.pose_name, bistro["hints"])
        self.assertIn("スマホ", looked.pose_name)

    def test_d3_chooses_one_pose_from_all_1173(self):
        catalog = load_catalog()
        bistro = resolve_usecase("bistro-sit")
        chosen = next(pose for pose in catalog if pose["name"] == "座ってくつろぐ")
        categories = {pose["category"] for pose in catalog}
        with patch.dict(os.environ, {"D3_API_URL": "http://127.0.0.1:8080"}, clear=False):
            with patch(
                "urllib.request.urlopen",
                side_effect=[
                    _response("pose_category", chosen["category"]),
                    _response("arrival_pose", chosen["id"]),
                ],
            ) as urlopen:
                decision = choose_arrival_pose(
                    bistro,
                    3.0,
                    catalog,
                    click_x=-5.7,
                    click_y=8.3,
                    pose_summary="root=(0.00,0.00) facing=0deg height=0.95",
                )
        self.assertEqual(decision.pose_id, chosen["id"])
        self.assertEqual(decision.backend, "d3-mini")
        self.assertEqual(decision.catalog_size, 1173)
        self.assertEqual(decision.category, chosen["category"])
        bodies = [json.loads(call.args[0].data.decode("utf-8")) for call in urlopen.call_args_list]
        self.assertEqual(set(bodies[0]["questions"]["pose_category"]["criteria"]), categories)
        self.assertIn("1173", bodies[0]["questions"]["pose_category"]["instructions"])
        self.assertIn("格闘スポーツ · 打撃・組手", bodies[0]["questions"]["pose_category"]["criteria"])
        stage2_ids = set(bodies[1]["questions"]["arrival_pose"]["criteria"])
        expected_ids = {pose["id"] for pose in catalog if pose["category"] == chosen["category"]}
        self.assertEqual(stage2_ids, expected_ids)
        self.assertEqual(bodies[1]["state"]["user_intent"], bistro["intent"])
        self.assertEqual(bodies[1]["state"]["catalog_size"], 1173)


if __name__ == "__main__":
    unittest.main()
