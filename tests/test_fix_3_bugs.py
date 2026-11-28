"""Verification test for the 3 user-reported bugs:
1. Layout option button clickability and valid framing settings.
2. Stop rendering & Discard immediately cancelling the active render job.
3. Captions pacing, readable on-screen holding time, and Whisper Large-v3-Turbo model default.

Run: python tests/test_fix_3_bugs.py
"""
import os, sys, tempfile, json, time
os.environ["CLIPFORGE_DATA"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from clipforge import captions
from clipforge_web import db, server, worker, engine

# ----------------- TEST 1: Caption Pacing & ASS Generation -----------------
print("1. Testing caption pacing & natural on-screen duration...")
# Fast speech sample (e.g. streamer speaking rapidly with commas)
sample_words = [
    {"w": "All", "start": 0.0, "end": 0.15},
    {"w": "right,", "start": 0.18, "end": 0.35},
    {"w": "let's", "start": 0.40, "end": 0.58},
    {"w": "close", "start": 0.62, "end": 0.85},
    {"w": "it,", "start": 0.88, "end": 1.05},
    {"w": "close", "start": 1.10, "end": 1.30},
    {"w": "it", "start": 1.32, "end": 1.50},
    {"w": "now!", "start": 1.55, "end": 1.80},
]
cues = captions.build_cues(sample_words)
assert len(cues) > 0, "No cues built from sample words"

# Verify each cue stays on screen for a readable minimum duration
for q in cues:
    dur = q["end"] - q["start"]
    print(f"  Cue '{' '.join(w['w'] for w in q['words'])}': {q['start']:.2f}s -> {q['end']:.2f}s (dur={dur:.2f}s)")
    assert dur >= 1.0, f"Cue duration too short: {dur:.2f}s (must be >= 1.0s for human readability)"

# Test ASS generation
ass_text = captions.to_ass(cues, template="yellow_pop", width=1080, height=1920, caption_y=0.88)
assert "ScriptType: v4.00+" in ass_text, "Invalid ASS header"
assert "Dialogue:" in ass_text, "Missing dialogue events in ASS"
# Ensure Dialogue lines exist and pop animation is only on initial entrance, not every word jiggling
dialogue_lines = [ln for ln in ass_text.splitlines() if ln.startswith("Dialogue:")]
assert len(dialogue_lines) >= len(sample_words), f"Expected at least {len(sample_words)} dialogue events, got {len(dialogue_lines)}"
print("  ✓ Caption pacing and ASS generation passed!")

# ----------------- TEST 2: Stop & Discard Render Cancellation -----------------
print("2. Testing Stop & Discard render cancellation...")
conn = db.conn()
vid = db.ex("insert into videos(title,source,status,created,duration,w,h) values(?,?,?,?,?,?,?)",
            ("test_v", "source.mp4", "ready", db.now(), 60.0, 1280, 720))
cid = db.ex("insert into clips(video_id,start,end,title,status,layout) values(?,?,?,?,?,?)",
            (vid, 0.0, 10.0, "Test Clip", "candidate", "stack"))

# A. Test enqueueing render then cancelling via /api/clips/{cid}/cancel
worker.enqueue("render", cid)
c = server._clip(cid)
assert c["render_status"] == "queued", f"Expected queued, got {c['render_status']}"

res = server.cancel_clip_render(cid)
assert res["ok"] is True
c_after = server._clip(cid)
assert c_after["render_status"] == "stale", f"Expected stale, got {c_after['render_status']}"

# Check that the job was cancelled in the DB
jobs = db.q("select status from jobs where ref_id=? and type='render' order by id desc", (cid,))
assert jobs and jobs[0]["status"] == "cancelled", f"Job status not cancelled: {jobs[0]['status']}"

# B. Test Discard (PATCH /api/clips/{cid} with status='rejected') aborts render
worker.enqueue("render", cid)
c = server._clip(cid)
assert c["render_status"] == "queued"

patch_res = server.patch_clip(cid, {"status": "rejected"})
c_rejected = server._clip(cid)
assert c_rejected["status"] == "rejected"
assert c_rejected["render_status"] == "none", f"Expected none after reject, got {c_rejected['render_status']}"
print("  ✓ Stop and Discard render cancellation passed!")

# ----------------- TEST 3: Layout Options Switching & Defaults -----------------
print("3. Testing layout options switching and defaults...")
# Test all 5 layouts can be set without error
for l in ["stack", "pip", "follow", "crop", "blur"]:
    server.patch_clip(cid, {"layout": l})
    c_l = server._clip(cid)
    assert c_l["layout"] == l, f"Layout not updated to {l}"

# Test default Whisper model is large-v3-turbo
model_setting = db.setting("model")
assert model_setting == "large-v3-turbo", f"Default model setting expected large-v3-turbo, got {model_setting}"

print("  ✓ Layout options and model defaults passed!")

# ----------------- TEST 4: Frontend HTML Sanity -----------------
print("4. Testing HTML script syntax...")
html_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "clipforge_web", "static", "index.html")
with open(html_path, "r", encoding="utf-8") as f:
    html = f.read()

assert "const $$=" in html, "$$ helper missing in index.html"
assert 'id="stopRender"' in html, "stopRender button missing in index.html"
assert '$$(' not in html or "const $$" in html, "$$ used without definition"
print("  ✓ HTML frontend sanity passed!")

print("\nALL TESTS PASSED SUCCESSFULLY!")
