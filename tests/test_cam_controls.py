"""Test camera controls: cam_size and wide pan X/Y in render_clip and API. Run: python tests/test_cam_controls.py"""
import os, subprocess, sys, tempfile

os.environ["CLIPFORGE_DATA"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clipforge.render import render_clip
from clipforge_web import db, server

# 1. Test database schema & migration
conn = db.conn()
cols = [r[1] for r in conn.execute("pragma table_info(clips)").fetchall()]
assert "cam_size" in cols, f"cam_size missing in clips cols: {cols}"

# 2. Test CLIP_FIELDS in server
assert "cam_size" in server.CLIP_FIELDS, "cam_size missing in server.CLIP_FIELDS"

# 3. Test render_clip with cam_size and pan X/Y
tmp = tempfile.mkdtemp()
src, ass, out = os.path.join(tmp, "src.mp4"), os.path.join(tmp, "c.ass"), os.path.join(tmp, "out.mp4")
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=green:s=1280x720:d=1", "-f", "lavfi", "-i",
                "sine=d=1", "-shortest", src], check=True)
open(ass, "w").write("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n[Events]\nFormat: Layer,Start,End,Name,Style,MarginL,MarginR,MarginV,Effect,Text\n")

class Job:
    def run(self, cmd, cwd=None):
        subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)

# Test rendering with cam_size=1.5 and custom pan X/Y in pip layout
render_clip(Job(), "ffmpeg", src, {"w": 1280, "h": 720}, 0, 1, ass, out, layout="pip",
            cam_zoom=1.8, cam_size=1.5, cam_crop_x=0.8, cam_crop_y=0.2, hook_zoom=False)
assert os.path.isfile(out) and os.path.getsize(out) > 0, "out.mp4 not generated"

# Test rendering in stack layout with cam_zoom=2.0 and custom pan X/Y
render_clip(Job(), "ffmpeg", src, {"w": 1280, "h": 720}, 0, 1, ass, out, layout="stack",
            cam_zoom=2.0, cam_crop_x=0.3, cam_crop_y=0.9, hook_zoom=False)
assert os.path.isfile(out) and os.path.getsize(out) > 0, "out.mp4 not generated"

print("ok - cam controls verified successfully!")
