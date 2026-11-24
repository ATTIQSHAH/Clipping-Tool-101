"""Learning from views, translated captions, voice-over mixing, meme sounds. Run: python tests/test_extras.py
Needs FFmpeg. The voice part runs only when piper-tts is installed (requirements-extras.txt)."""
import json, os, subprocess, sys, tempfile

os.environ["CLIPFORGE_DATA"] = tmp = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clipforge import ai, audiolib, captions, voice  # noqa: E402
from clipforge.render import _audio_graph  # noqa: E402
from clipforge_web import db, engine  # noqa: E402

# --- learn from views: clips with lots of chat got the views, loudness didn't matter
assert engine.learned() == {}
for i in range(8):
    comp = {"audio": 0.5, "chat": i / 7, "motion": None, "game": "WASTED" if i > 5 else None}
    db.ex("insert into clips(video_id,title,scores,views,render_path) values(1,?,?,?,?)",
          (f"clip number {i}", db.dumps(comp), 100 * i, "x.mp4"))
w = engine.learned()
assert set(w) == {"chat", "game"} and w["chat"] > 0.9, w
f, by = engine.fit({"audio": 0.5, "chat": 1.0, "game": "BUSTED"}, w)
assert f == 1.0 and by in ("chat bursts", "game banners"), (f, by)
assert engine.fit({"audio": 0.5, "chat": 0.0, "game": None}, w)[0] == 0.0

# --- views from your channel go to the clip with the same title
cid = db.ex("insert into clips(video_id,title,scores,render_path) values(1,'He got WASTED by a cop!','{}','y.mp4')")
n = engine.match_views([{"title": "he got wasted by a cop 😂 #GTA6 #Shorts", "views": 5400},
                        {"title": "something else entirely", "views": 9}])
assert n == 1 and db.q("select views from clips where id=?", (cid,), one=True)["views"] == 5400

# --- translation: same number of lines back, words spread over the cue
fake = lambda key, body, **k: {"content": [{"type": "text", "text": '["NO PUEDE SER", "vamos"]'}]}
assert ai.translate("k", ["no way", "let's go"], "es", post=fake) == ["NO PUEDE SER", "vamos"]
try:
    ai.translate("k", ["one"], "es", post=fake)
    raise AssertionError("wrong line count accepted")
except ValueError:
    pass
cue = captions.respread({"start": 1.0, "end": 2.0, "words": []}, "no puede ser")
assert cue["words"][0]["start"] == 1.0 and abs(cue["words"][-1]["end"] - 2.0) < 0.01 and len(cue["words"]) == 3

# --- voice-over mix: the clip's sound dips while the voice talks
g, ins = _audio_graph(None, 0, False, [], 1, ("vo.wav", 0.2, 2.0))
assert "volume=0.3:enable='between(t,0.20,2.35)'" in g and "[vo]" in g and ins == ["-i", "vo.wav"], g
assert _audio_graph(None, 0, False, [], 1) == ("[0:a]loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[aout]", [])

# --- meme sound on a game banner
words = [{"w": "ok", "start": 101.0, "end": 101.3}]
fx = engine.auto_sfx({"start": 100.0, "end": 120.0, "peak": 108.0, "words": json.dumps(words),
                      "scores": json.dumps({"game": "WASTED", "game_t": 112.0})})
assert ("sad_trombone.wav", 112.4) in [(e["f"], e["t"]) for e in fx], fx
for name in ("airhorn.wav", "sad_trombone.wav", "record_scratch.wav", "vine_boom.wav"):
    assert audiolib.resolve("sfx", name), name

# --- real render of the mix with FFmpeg (a tone stands in for the voice)
src, vo = os.path.join(tmp, "src.mp4"), os.path.join(tmp, "vo.wav")
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=6", "-f", "lavfi", "-i",
                "color=s=320x240:d=6", "-shortest", src], check=True)
if voice.available():
    vlen = voice.say("No way he got wasted.", "en", vo, os.path.join(db.ROOT, "data", "voices"))  # the app's own voice folder
    assert 0.5 < vlen < 5, vlen
else:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=880:d=1.5", vo], check=True)
    vlen = 1.5
g, ins = _audio_graph(None, 0, False, [], 1, (vo, 0.2, vlen))
out = os.path.join(tmp, "out.m4a")
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src] + ins + ["-filter_complex", g, "-map", "[aout]", out], check=True)
assert os.path.getsize(out) > 1000
print("ok" + ("" if voice.available() else " (voice not installed: tone used)"))
