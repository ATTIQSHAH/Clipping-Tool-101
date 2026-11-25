"""Floating cam (pip) makes a vertical clip: gameplay fills the 9:16 frame. Run: python tests/test_pip_vertical.py"""
import os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clipforge.render import render_clip  # noqa: E402

tmp = tempfile.mkdtemp()
src, ass, out = (os.path.join(tmp, n) for n in ("src.mp4", "c.ass", "out.mp4"))
# landscape gameplay: left half red, right half blue
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=red:s=1280x720:d=2", "-f", "lavfi", "-i",
                "sine=d=2", "-vf", "drawbox=x=640:y=0:w=640:h=720:color=blue:t=fill", "-shortest", src], check=True)
open(ass, "w").write("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n[V4+ Styles]\n"
                     "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,"
                     "Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,"
                     "MarginR,MarginV,Encoding\nStyle: Main,Arial,80,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,"
                     "100,100,0,0,1,2,0,2,10,10,10,1\n\n[Events]\nFormat: Layer,Start,End,Name,Style,MarginL,MarginR,"
                     "MarginV,Effect,Text\n")


class Job:
    def run(self, cmd, cwd=None):
        subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


def pixel(x, y):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1", "-i", out, "-frames:v", "1", "-vf", f"crop=2:2:{x}:{y}",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return tuple(raw[:3])


for pan, want in ((0.0, "red"), (1.0, "blue")):
    render_clip(Job(), "ffmpeg", src, {"w": 1280, "h": 720}, 0, 2, ass, out, layout="pip", crop_x=pan,
                hook_zoom=False, cam_corner="tr", cam_pos="pip_top")   # no facecam detected: floats the corner
    wh = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height",
                         "-of", "csv=p=0", out], capture_output=True, text=True).stdout.strip()
    assert wh == "1080,1920", wh
    r, g, b = pixel(540, 1800)                       # bottom of the frame: gameplay, not blur/letterbox
    assert (r > 180 and b < 80) if want == "red" else (b > 180 and r < 80), (pan, r, g, b)
    r, g, b = pixel(540, 200)                        # the floating cam (top-right corner of the source = blue)
    assert b > 180 and r < 80, ("cam", r, g, b)
print("ok")
