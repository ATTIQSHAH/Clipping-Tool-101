import unittest
import sqlite3
import tempfile
import os
from clipforge.captions import to_ass
import clipforge_web.db as db

class TestFeatures(unittest.TestCase):
    def test_banner_ass(self):
        cues = [
            {'start': 0.0, 'end': 2.0, 'words': [{'w': 'Hello', 'start': 0.0, 'end': 1.0}, {'w': 'World', 'start': 1.0, 'end': 2.0}]}
        ]
        # Test white card banner
        ass_content = to_ass(
            cues,
            banner_text="Peak stream 😂💀",
            banner_style="white_box"
        )
        self.assertIn("Style: Banner", ass_content)
        self.assertIn("Peak stream", ass_content)
        self.assertTrue("{\\an5\\pos(" in ass_content or "{\\an8}" in ass_content)

        # Test dark card banner
        ass_dark = to_ass(
            cues,
            banner_text="WAIT TILL THE END",
            banner_style="dark_box"
        )
        self.assertIn("Style: Banner", ass_dark)
        self.assertIn("WAIT TILL THE END", ass_dark)

        # Test hidden banner
        ass_none = to_ass(
            cues,
            banner_text="Something",
            banner_style="none"
        )
        self.assertNotIn("Style: Banner", ass_none)

    def test_db_columns(self):
        c = db.conn()
        cols = [r[1] for r in c.execute("PRAGMA table_info(clips)").fetchall()]
        for expected in ["cam_zoom", "cam_shape", "cam_pos", "cam_pos_x", "cam_pos_y", "banner_text", "banner_style", "game_zoom", "crop_y", "banner_x", "banner_y"]:
            self.assertIn(expected, cols, f"Column {expected} missing from clips table")
        c.close()

if __name__ == '__main__':
    unittest.main()