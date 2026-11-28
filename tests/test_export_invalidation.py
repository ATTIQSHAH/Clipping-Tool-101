import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from clipforge import captions
from clipforge.captions import TEMPLATES
from clipforge_web import db, server

class TestExportInvalidationAndCaptions(unittest.TestCase):
    def test_caption_positions_lowered(self):
        for name, tpl in TEMPLATES.items():
            self.assertLessEqual(tpl["mv"], 220, f"Template {name} mv is too high: {tpl['mv']}")
            self.assertGreaterEqual(tpl["mv"], 100, f"Template {name} mv is too low: {tpl['mv']}")

    def test_caption_toggle_empty_ass(self):
        # When captions are disabled (empty cues), valid ASS without caption dialogue is produced
        ass = captions.to_ass([], "yellow_pop", width=1080, height=1920)
        self.assertIn("[Script Info]", ass)
        self.assertIn("[V4+ Styles]", ass)
        self.assertIn("[Events]", ass)
        self.assertNotIn("Main,,", ass)

    def test_render_stale_invalidation(self):
        # Create a test video and clip in DB
        db.conn()
        vid = db.ex("insert into videos(source, title, status, duration, w, h, fps) values(?, ?, ?, ?, ?, ?, ?)",
                    ("test://video", "Test Video", "ready", 120.0, 1920, 1080, 30.0))
        cid = db.ex("insert into clips(video_id, title, start, end, layout, aspect_ratio, captions, status, render_status, render_path) values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (vid, "Test Clip", 10.0, 30.0, "pip", "9:16", 1, "approved", "done", "C:/dummy/path/clip.mp4"))
        
        # Verify initial state
        c_before = server._clip_out(server._clip(cid))
        # Note: c_before["rendered"] is False because dummy file doesn't exist on disk, which is expected
        
        # Patch layout to stack (Dual-Cam)
        res = server.patch_clip(cid, {"layout": "stack"})
        c_after = server._clip(cid)
        self.assertEqual(c_after["render_status"], "stale", "render_status must become stale after layout change")

        # Patch cam_pos_x and cam_pos_y to 0.0 (top-left)
        res2 = server.patch_clip(cid, {"cam_pos_x": 0.0, "cam_pos_y": 0.0, "cam_pos": "pip_custom"})
        c_after2 = server._clip(cid)
        self.assertEqual(c_after2["cam_pos_x"], 0.0)
        self.assertEqual(c_after2["cam_pos_y"], 0.0)
        self.assertEqual(c_after2["render_status"], "stale")

        # Patch captions to 0 (disabled)
        res3 = server.patch_clip(cid, {"captions": 0})
        c_after3 = server._clip(cid)
        self.assertEqual(c_after3["captions"], 0)
        self.assertEqual(c_after3["render_status"], "stale")

        # Test approve on stale clip triggers re-render
        app_res = server.approve_clip(cid)
        self.assertTrue(app_res["needs_render"], "approve_clip must trigger render when clip is stale")
        c_approved = server._clip(cid)
        self.assertEqual(c_approved["render_status"], "queued")

if __name__ == "__main__":
    unittest.main()
