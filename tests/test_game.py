"""Game banner finding. Run from the project folder: python tests/test_game.py
Needs FFmpeg. The OCR part runs only when rapidocr-onnxruntime is installed (requirements-extras.txt)."""
import glob, os, subprocess, sys, tempfile
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clipforge import game  # noqa: E402

assert game.match("WASTED") == "WASTED" and game.match("BUSTEO") == "BUSTED" and game.match("mission passed!") == "MISSION PASSED"
assert game.match("Respect +") is None and game.match("") is None
s = game.banner_score([(10.0, "WASTED")], 100, 0.5)
assert s[13] == 0 and s[14] == 1 and s[31] == 1 and s[32] == 0, s

from clipforge.analyze import action_kind  # noqa: E402
m, a = np.zeros(100), np.zeros(100)
assert action_kind(None, a, 0, 100) is None and action_kind(m, a, 0, 100) is None
m2 = m.copy(); m2[10:70] = 0.6
assert action_kind(m2, a, 0, 100) == "chase"
m3 = m.copy(); m3[50] = 0.9; a3 = a.copy(); a3[52] = 0.8
assert action_kind(m3, a3, 0, 100) == "crash" and action_kind(m3, a, 0, 100) is None

if not game.available():
    print("ok (OCR not installed: banner reading skipped)")
    raise SystemExit
font = (glob.glob("/usr/share/fonts/**/DejaVuSans-Bold.ttf", recursive=True) + ["C\\:/Windows/Fonts/arialbd.ttf"])[0]
src = os.path.join(tempfile.mkdtemp(), "wasted.mp4")
# 40 s of colourful picture; from 20 s to 25 s the colour drains and a big red WASTED appears, like GTA
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1280x720:d=40:r=30", "-vf",
                "hue=s=0:enable='between(t,20,25)',"
                f"drawtext=fontfile='{font}':text=WASTED:fontsize=150:fontcolor=0xD01818:x=(w-tw)/2:y=(h-th)/2:"
                "enable='between(t,20,25)'", "-c:v", "libx264", "-g", "60", src], check=True)
ev = game.banners("ffmpeg", src)
assert len(ev) == 1 and ev[0][1] == "WASTED" and 19 <= ev[0][0] <= 22, ev
print("ok", ev)
