import unittest
import clipforge_web.engine as engine
import clipforge_web.db as db

class TestCandidateImport(unittest.TestCase):
    def test_auto_sfx_and_words_without_video_id(self):
        # Candidate dict before DB insertion
        cand = {
            "start": 12.5,
            "end": 28.0,
            "peak": 19.2,
            "words": []
        }
        # Must not raise KeyError: 'video_id' or any other exception
        sfx = engine.auto_sfx(cand)
        self.assertIsInstance(sfx, list)
        self.assertGreater(len(sfx), 0)

        # ensure_clip_words must gracefully return empty list or existing words
        words = engine.ensure_clip_words(cand)
        self.assertEqual(words, [])

        # clip_words must return empty list or fallback without crashing
        cw = engine.clip_words(cand)
        self.assertEqual(cw, [])

        # clip_cues must return kinetic fallback cues
        cues = engine.clip_cues(cand)
        self.assertIsInstance(cues, list)
        self.assertGreater(len(cues), 0)

    def test_auto_sfx_with_video_id(self):
        cand = {
            "start": 5.0,
            "end": 15.0,
            "peak": 10.0,
            "words": [{"w": "insane", "start": 9.5, "end": 10.2}],
            "video_id": 99999
        }
        sfx = engine.auto_sfx(cand)
        self.assertIsInstance(sfx, list)
        self.assertTrue(any(item["f"] == "boom.wav" for item in sfx))

    def test_clip_source_safe(self):
        self.assertEqual(engine.clip_source(None, None), "")
        self.assertEqual(engine.clip_source({}, {}), "")
        self.assertEqual(engine.clip_source({"src": ""}, {"id": 999}), "")

    def test_framing_safe(self):
        cand = {"start": 0.0, "end": 10.0, "layout": "stack"}
        video = {"w": 1920, "h": 1080}
        fr = engine.framing(cand, video)
        self.assertIn("box", fr)
        self.assertIn("cam", fr)

if __name__ == "__main__":
    unittest.main()
