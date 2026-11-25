"""Hook text shows only in its own time range. Run: python tests/test_banner_time.py"""
import os, sys, tempfile

os.environ["CLIPFORGE_DATA"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clipforge.captions import to_ass  # noqa: E402
from clipforge_web.engine import banner_times  # noqa: E402

clip = {"start": 100.0, "end": 130.0}
assert banner_times(dict(clip, banner_start=None, banner_end=None)) == (None, None)        # old clips: whole clip
assert banner_times(dict(clip, banner_start=105.0, banner_end=112.5)) == (5.0, 12.5)
assert banner_times(dict(clip, banner_start=90.0, banner_end=140.0)) == (0.0, 30.0)       # clamped to the clip
assert banner_times(dict(clip, banner_start=129.9, banner_end=140.0)) == (None, None)     # too short: whole clip

line = lambda ass: next(x for x in ass.splitlines() if ",Banner," in x and x.startswith("Dialogue"))
assert line(to_ass([], banner_text="WAIT", banner_t0=5.0, banner_t1=12.5)).startswith("Dialogue: 1,0:00:05.00,0:00:12.50,")
assert line(to_ass([], banner_text="WAIT")).startswith("Dialogue: 1,0:00:00.00,9:59:59.00,")
print("ok")
