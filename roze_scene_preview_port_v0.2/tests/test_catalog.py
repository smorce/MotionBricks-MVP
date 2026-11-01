import sys, unittest, os
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'backend'))
from jev_router import load_catalog, shortlist, choose_pose

class CatalogTests(unittest.TestCase):
    def test_fallback(self):
        poses=load_catalog()
        with patch.dict(os.environ, {'TYPESAFE_API_KEY':''}):
            d=choose_pose('floor','walk',3,poses)
        self.assertTrue(d.pose_id)
    def test_shortlist(self):
        poses=load_catalog()
        self.assertLessEqual(len(shortlist(poses,'chair')),24)
        self.assertTrue(any('座' in x['name'] for x in shortlist(poses,'chair')))

if __name__=='__main__':unittest.main()
