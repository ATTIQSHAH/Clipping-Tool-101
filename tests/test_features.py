import unittest
import sqlite3
import tempfile
import os
from clipforge.captions import to_ass, to_srt
from clipforge_web import engine
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

        # Test transparent clean text banner without background box
        ass_clean = to_ass(
            cues,
            banner_text="NO BACKGROUND TITLE",
            banner_style="clean_text",
            banner_size=1.4,
            banner_font="Impact"
        )
        self.assertIn("Style: Banner,Impact,", ass_clean)
        self.assertIn("NO BACKGROUND TITLE", ass_clean)
        self.assertIn(",1,7,4,", ass_clean)  # BorderStyle=1 (no box, outline only)

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

    def test_to_srt(self):
        cues = [
            {'start': 1.25, 'end': 3.75, 'text': 'Hello world', 'words': [{'w': 'Hello', 'start': 1.25, 'end': 2.0}, {'w': 'world', 'start': 2.0, 'end': 3.75}]}
        ]
        srt = to_srt(cues)
        self.assertIn("00:00:01,250 --> 00:00:03,750", srt)
        self.assertIn("Hello world", srt)

    def test_clip_words_zero_relative_and_timeline(self):
        # Timeline coordinates
        c_timeline = {
            'start': 100.0, 'end': 120.0,
            'words': [{'w': 'First', 'start': 101.0, 'end': 102.0}, {'w': 'Second', 'start': 103.0, 'end': 104.0}]
        }
        res1 = engine.clip_words(c_timeline)
        self.assertEqual(len(res1), 2)
        self.assertEqual(res1[0]['w'], 'First')
        self.assertEqual(res1[0]['start'], 1.0)

        # 0-relative coordinates (e.g. from cut clip)
        c_zero = {
            'start': 100.0, 'end': 120.0,
            'words': [{'w': 'RelFirst', 'start': 1.0, 'end': 2.0}, {'w': 'RelSecond', 'start': 3.0, 'end': 4.0}]
        }
        res2 = engine.clip_words(c_zero)
        self.assertEqual(len(res2), 2)
        self.assertEqual(res2[0]['w'], 'RelFirst')
        self.assertEqual(res2[0]['start'], 1.0)

    def test_db_columns(self):
        c = db.conn()
        cols = [r[1] for r in c.execute("PRAGMA table_info(clips)").fetchall()]
        for expected in ["cam_zoom", "cam_shape", "cam_pos", "cam_pos_x", "cam_pos_y", "banner_text", "banner_style", "game_zoom", "crop_y", "banner_x", "banner_y", "banner_size", "banner_font", "caption_size", "caption_font", "views", "lang", "vo"]:
            self.assertIn(expected, cols, f"Column {expected} missing from clips table")

    def test_caption_size_and_respread(self):
        from clipforge.captions import respread
        cues = [{'start': 1.0, 'end': 3.0, 'words': [{'w': 'old', 'start': 1.0, 'end': 3.0}]}]
        ass_large = to_ass(cues, caption_size=1.5, caption_font="Impact")
        self.assertIn("Style: Main,Impact,", ass_large)

        spread = respread({'start': 1.0, 'end': 3.0}, "Hola mundo")
        self.assertEqual(len(spread["words"]), 2)
        self.assertEqual(spread["words"][0]["w"], "Hola")
        self.assertEqual(spread["words"][1]["w"], "mundo")

    def test_action_kind(self):
        from clipforge.analyze import action_kind
        import numpy as np
        # Single spike with audio boom = crash
        motion_crash = np.array([0.1]*4 + [0.9] + [0.1]*5)
        audio_crash = np.array([0.1]*4 + [0.8] + [0.1]*5)
        self.assertEqual(action_kind(motion_crash, audio_crash, 0, 10), "crash")

        # Sustained movement = chase
        motion_chase = np.array([0.5, 0.6, 0.7, 0.5, 0.6])
        audio_chase = np.array([0.2, 0.2, 0.2, 0.2, 0.2])
        self.assertEqual(action_kind(motion_chase, audio_chase, 0, 5), "chase")

if __name__ == '__main__':
    unittest.main()