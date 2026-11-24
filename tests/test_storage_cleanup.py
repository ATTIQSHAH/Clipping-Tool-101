import os
import tempfile
import time
import unittest

# Set temporary data directory before importing db
TMP = tempfile.mkdtemp()
os.environ["CLIPFORGE_DATA"] = TMP

from clipforge_web import db, storage
db.DATA = TMP


class StorageCleanupTests(unittest.TestCase):
    def setUp(self):
        db.conn()

    def test_saved_videos_in_exports_never_deleted(self):
        exports_dir = os.path.join(TMP, "exports")
        os.makedirs(exports_dir, exist_ok=True)
        saved_video = os.path.join(exports_dir, "clip_999.mp4")
        with open(saved_video, "wb") as f:
            f.write(b"saved approved video content" * 100)

        # Set modification time to 5 days ago (120 hours ago)
        old_time = time.time() - (120 * 3600)
        os.utime(saved_video, (old_time, old_time))

        # Run cleanup with 48h (2 days) retention, and even clean_all_temp=True
        storage.clean_storage(older_than_hours=48)
        self.assertTrue(os.path.exists(saved_video), "Saved video in exports must NOT be deleted!")

        storage.clean_storage(clean_all_temp=True)
        self.assertTrue(os.path.exists(saved_video), "Saved video in exports must NEVER be deleted even on full temp clean!")

    def test_temp_work_files_older_than_48h_deleted(self):
        work_dir = os.path.join(TMP, "work", "123")
        os.makedirs(work_dir, exist_ok=True)

        # Add a dummy video in DB so it's not treated as orphaned
        db.ex("insert or replace into videos(id, title, status) values(123, 'Test Vid', 'ready')")

        old_wav = os.path.join(work_dir, "full.wav")
        new_wav = os.path.join(work_dir, "recent.wav")

        with open(old_wav, "wb") as f:
            f.write(b"old wav content" * 100)
        with open(new_wav, "wb") as f:
            f.write(b"new wav content" * 100)

        # old_wav: 3 days ago (72 hours); new_wav: 5 hours ago
        t_old = time.time() - (72 * 3600)
        t_new = time.time() - (5 * 3600)
        os.utime(old_wav, (t_old, t_old))
        os.utime(new_wav, (t_new, t_new))

        # Run cleanup with 48h retention
        res = storage.clean_storage(older_than_hours=48)
        self.assertTrue(res["ok"])
        self.assertFalse(os.path.exists(old_wav), "Files older than 48h must be deleted.")
        self.assertTrue(os.path.exists(new_wav), "Files newer than 48h must be kept.")

    def test_active_video_work_skipped(self):
        work_dir = os.path.join(TMP, "work", "456")
        os.makedirs(work_dir, exist_ok=True)
        db.ex("insert or replace into videos(id, title, status) values(456, 'Busy Vid', 'analyzing')")

        old_file = os.path.join(work_dir, "motion_score.npy")
        with open(old_file, "wb") as f:
            f.write(b"data" * 50)
        t_old = time.time() - (100 * 3600)
        os.utime(old_file, (t_old, t_old))

        storage.clean_storage(older_than_hours=48)
        self.assertTrue(os.path.exists(old_file), "Active analyzing video files must be skipped.")

    def test_storage_stats(self):
        stats = storage.get_storage_stats()
        self.assertIn("exports_size", stats)
        self.assertIn("work_size", stats)
        self.assertIn("total_size", stats)
        self.assertIn("cleanup_hours", stats)


if __name__ == "__main__":
    unittest.main()
