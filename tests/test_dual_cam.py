import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
from clipforge_web import engine
from clipforge.render import render_clip

def test_dual_cam_framing():
    video = {"id": 1, "w": 1280, "h": 720, "cam_box": None}
    clip_bl = {"id": 1, "video_id": 1, "layout": "stack", "cam_corner": "bl", "cam": None, "split_ratio": 0.5}
    cam = engine.get_cam(None, clip_bl, video)
    assert cam["box"] == [0, int(720 * 0.45), int(1280 * 0.35), int(720 * 0.55)], f"Expected BL box, got {cam['box']}"
    
    f = engine.framing(clip_bl, video)
    assert f["stack"] is True, "Expected stack to be True"
    assert f["pip"] is False, "Expected pip to be False"
    assert f["box"] == [0, int(720 * 0.45), int(1280 * 0.35), int(720 * 0.55)]
    print("Dual cam BL framing test: OK")

def test_render_dual_cam():
    class DummyJob:
        def __init__(self):
            self.cmd = None
        def run(self, cmd, cwd=None):
            self.cmd = cmd
            
    job = DummyJob()
    info = {"w": 1280, "h": 720, "duration": 10.0}
    render_clip(job, "ffmpeg", "source.mp4", info, 0.0, 5.0, "sub.ass", "out.mp4",
                layout="stack", crop_x=0.5, res=1080, split_ratio=0.5, cam_corner="bl",
                music=None, sfx=())
    
    cmd_str = " ".join(job.cmd)
    assert "-filter_complex" in cmd_str
    # Extract filter complex string
    fc_idx = job.cmd.index("-filter_complex") + 1
    fc = job.cmd[fc_idx]
    assert "vstack" in fc, f"Expected vstack in filter graph, got: {fc}"
    assert "[top][bot]vstack" in fc
    print("Render dual cam graph test: OK")

def test_render_dual_cam_zoom():
    class DummyJob:
        def __init__(self):
            self.cmd = None
        def run(self, cmd, cwd=None):
            self.cmd = cmd

    job = DummyJob()
    info = {"w": 1280, "h": 720, "duration": 10.0}
    render_clip(job, "ffmpeg", "source.mp4", info, 0.0, 5.0, "sub.ass", "out.mp4",
                layout="stack", crop_x=0.6, crop_y=0.4, res=1080, split_ratio=0.5, cam_corner="tr",
                cam_zoom=1.5, game_zoom=1.8, music=None, sfx=())

    cmd_str = " ".join(job.cmd)
    fc_idx = job.cmd.index("-filter_complex") + 1
    fc = job.cmd[fc_idx]
    assert "vstack" in fc
    assert "unsharp" in fc
    print("Dual cam zoom & pan test: OK")

if __name__ == "__main__":
    test_dual_cam_framing()
    test_render_dual_cam()
    test_render_dual_cam_zoom()
    print("ALL DUAL CAM TESTS PASSED!")
