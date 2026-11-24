"""Quality check and post text. Run from the project folder: python tests/test_qc.py"""
import os, sys, tempfile
os.environ["CLIPFORGE_DATA"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clipforge_web.engine import post_text, qc_from_log  # noqa: E402

W = [{"w": "hi", "start": i, "end": i + 0.5} for i in range(20)]
assert qc_from_log("mean_volume: -20.1 dB", 25, W) == []
lv = [q["level"] for q in qc_from_log("mean_volume: -60.0 dB\nblack_duration:9.5", 4, [])]
assert lv == ["fail", "fail", "warn", "warn"], lv
assert "little speech" in qc_from_log("mean_volume: -20 dB", 30, W[:3])[0]["msg"]

c = {"title": "He crashed the plane"}
t = post_text(c, {"source": "https://www.twitch.tv/summit1g", "info_path": None})
assert t == "He crashed the plane\n\nCredit: summit1g on Twitch\n\n#GTA6 #GTA #Shorts #summit1g #Twitch", t
t = post_text(c, {"source": "https://www.twitch.tv/videos/123", "info_path": None})
assert "Credit" not in t and t.endswith("#Twitch"), t
assert post_text(c, {"source": "", "info_path": None}) == "He crashed the plane\n\n#GTA6 #GTA #Shorts"
print("ok")
