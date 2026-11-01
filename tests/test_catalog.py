import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from d3_router import load_catalog, shortlist, choose_pose


class CatalogTests(unittest.TestCase):
    def test_fallback_when_api_disabled(self):
        poses = load_catalog()
        with patch.dict(os.environ, {'D3_API_URL': ''}, clear=False):
            d = choose_pose('floor', 'walk', 3, poses)
        self.assertTrue(d.pose_id)
        self.assertEqual(d.backend, 'fallback-no-api')

    def test_shortlist(self):
        poses = load_catalog()
        self.assertLessEqual(len(shortlist(poses, 'chair')), 24)
        self.assertTrue(any('座' in x['name'] for x in shortlist(poses, 'chair')))

    def test_d3_choice_success(self):
        poses = load_catalog()
        options = shortlist(poses, 'floor')
        chosen = options[0]
        payload = {
            'answers': {
                'arrival_pose': {
                    'type': 'choice',
                    'choice': chosen['id'],
                    'confidence': 0.91,
                    'probabilities': {chosen['id']: 0.91},
                }
            }
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode('utf-8')
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False
        with patch.dict(os.environ, {'D3_API_URL': 'http://127.0.0.1:8080'}, clear=False):
            with patch('urllib.request.urlopen', return_value=mock_resp) as urlopen:
                d = choose_pose('floor', 'walk', 3.0, poses)
        self.assertEqual(d.pose_id, chosen['id'])
        self.assertEqual(d.backend, 'd3-mini')
        self.assertGreaterEqual(d.confidence, 0.35)
        req = urlopen.call_args[0][0]
        self.assertTrue(str(req.full_url).endswith('/v1/two-stage'))


if __name__ == '__main__':
    unittest.main()
