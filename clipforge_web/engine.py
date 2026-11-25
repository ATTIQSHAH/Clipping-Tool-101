"""The work behind the buttons: import a video, find clips, frame them on the face, render."""
import functools, json, os, re, subprocess
import numpy as np

from clipforge import ai, analyze, audiolib, captions, faces, game, voice
from clipforge.render import RES, render_clip
from clipforge.segments import HOOK_WORDS, snap, text_score, title_of
from clipforge.source import download, download_section, youtube_chat
from clipforge.transcribe import load_json, transcribe_file
from clipforge.util import Cancelled, probe, which
from . import db


def vdir(vid):
    return os.path.join(db.DATA, "originals", str(vid))


def wdir(vid):
    p = os.path.join(db.DATA, "work", str(vid))
    os.makedirs(p, exist_ok=True)
    return p


def prog(video_id, pct, stage=None):
    """What the progress bar on the video shows (0-100) and the sentence under it."""
    pct = max(0.0, min(100.0, pct))
    if stage is None:
        db.ex("update videos set progress=? where id=?", (round(pct, 1), video_id))
    else:
        db.ex("update videos set progress=?, stage=? where id=?", (round(pct, 1), stage, video_id))


def ai_key():
    return os.environ.get("ANTHROPIC_API_KEY") or db.setting("anthropic_key")


def clip_source(clip, video=None):
    """Live moments are cut into their own small file; prefer HD clip cut if available, else video file."""
    if not clip and not video:
        return ""
    src = clip.get("src") if isinstance(clip, dict) else None
    if src and os.path.exists(src):
        return src
    vid = (clip.get("video_id") if isinstance(clip, dict) else None) or (video.get("id") if isinstance(video, dict) else None)
    vd = vdir(vid) if vid else None
    cid = clip.get("id") if isinstance(clip, dict) else None
    if cid and vd and os.path.isdir(vd):
        for f in os.listdir(vd):
            if f.startswith(f"hd_{cid}_") and f.endswith(".mp4"):
                hd_path = os.path.join(vd, f)
                if os.path.exists(hd_path) and os.path.getsize(hd_path) > 1000:
                    return hd_path
    vpath = video.get("path") if isinstance(video, dict) else None
    if vpath and os.path.exists(vpath):
        return vpath
    if src and vd:
        base = os.path.basename(src)
        cand = os.path.join(vd, base)
        if os.path.exists(cand):
            return cand
    if vd and os.path.isdir(vd):
        for f in os.listdir(vd):
            if f.endswith((".mp4", ".mkv", ".webm")) and not f.endswith(".info.json"):
                return os.path.join(vd, f)
    return vpath or src or ""


# ---------------- import ----------------
def ingest(job, video_id, params):
    v = db.q("select * from videos where id=?", (video_id,), one=True)
    os.makedirs(vdir(video_id), exist_ok=True)
    title = v["title"]
    prog(video_id, 0, "Getting your video")
    if v["source"].startswith(("http://", "https://")):
        hd = int(params.get("max_height") or 1080)
        quick = bool(params.get("quick"))     # small copy to find clips; full quality fetched per clip at render
        path, info = download(job, v["source"], vdir(video_id), 360 if quick else hd,
                              params.get("cookies_browser") or None,
                              on_progress=lambda f: prog(video_id, f * 95, "Downloading a quick copy" if quick
                                                         else "Downloading the video"))
        db.ex("update videos set hd=?, cookies=? where id=?",
              (hd if quick else 0, params.get("cookies_browser") or None, video_id))
        title = (info or {}).get("title") or title
        if "youtube.com" in v["source"] or "youtu.be" in v["source"]:
            prog(video_id, 96, "Reading the chat replay")
            try:
                chat_path = youtube_chat(v["source"], os.path.splitext(path)[0], params.get("cookies_browser") or None)
                if chat_path and os.path.exists(chat_path):
                    events = []
                    with open(chat_path, "r", encoding="utf-8") as cf:
                        for line in cf:
                            try:
                                d = json.loads(line)
                                item = d.get("replayChatItemAction", {}).get("actions", [{}])[0]
                                act = item.get("addChatItemAction", {}).get("item", {})
                                msg_renderer = act.get("liveChatTextMessageRenderer", {})
                                t = int(d.get("videoOffsetTimeMsec", 0)) / 1000.0
                                msg = "".join(p.get("text", "") for p in msg_renderer.get("message", {}).get("runs", []))
                                if msg:
                                    events.append((t, msg))
                            except Exception:
                                pass
                    if events and len(events) >= 20:
                        with open(os.path.join(wdir(video_id), "chat.txt"), "w", encoding="utf-8") as cf:
                            cf.write("\n".join(f"{t:.2f} {m.replace(chr(10), ' ')}" for t, m in events))
                        job.log(f"Chat replay: {len(events)} messages.")
            except Exception as e:
                job.log(f"Chat replay note: {e}")
    else:
        path = v["path"]
    ffprobe = which("ffprobe")
    p = probe(ffprobe, path)
    audio = subprocess.run([ffprobe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                            "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip()
    info_path = os.path.splitext(path)[0] + ".info.json"
    db.ex("update videos set path=?,title=?,duration=?,w=?,h=?,fps=?,size=?,has_audio=?,info_path=?,error=null "
          "where id=?", (path, title, p["duration"], p["w"], p["h"], p["fps"], os.path.getsize(path),
                         1 if audio else 0, info_path if os.path.exists(info_path) else None, video_id))
    if not audio:
        raise RuntimeError("This video has no sound, so ClipForge can't find its best moments.")
    prog(video_id, 100, "Ready to analyze")


# ---------------- chat logs ----------------
_TS = re.compile(r"^\[?(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)\]?\s*(.*)$")


def parse_chat_events(text):
    """Chat log lines like '[0:12:34] name: message' or '754.5 message' -> [(seconds, message)]."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        m = _TS.match(line)
        if m:
            h, mi, s, msg = m.groups()
            out.append((int(h or 0) * 3600 + int(mi) * 60 + float(s), msg))
            continue
        parts = line.split(None, 1)
        try:
            out.append((float(parts[0]), parts[1] if len(parts) > 1 else ""))
        except Exception:
            pass
    return out


# ---------------- find clips ----------------
def _mmss(t):
    return f"{int(t // 60)}:{int(t % 60):02d}"


# ---------------- learn from your posted clips' views ----------------
FEATS = {"audio": "loud reactions", "chat": "chat bursts", "motion": "on-screen action", "heat": "most-replayed parts",
         "speech": "talking", "ai": "AI editor score", "game": "game banners"}
MIN_RESULTS = 6


def _feat(comp, k):
    v = comp.get(k)
    return (1.0 if v else 0.0) if k == "game" else v


def learned():
    """{signal: weight} for the signals that go with more views, from clips you entered or fetched views for.
    Empty until MIN_RESULTS clips have views. Weight = rank correlation of the signal with views."""
    rows = db.q("select scores, views from clips where views is not null")
    if len(rows) < MIN_RESULTS:
        return {}
    comps = [json.loads(r["scores"] or "{}") for r in rows]
    ranks = np.argsort(np.argsort([r["views"] for r in rows])).astype(float)
    out = {}
    for k in FEATS:
        pts = [(f, r) for comp, r in zip(comps, ranks) if (f := _feat(comp, k)) is not None]
        if len(pts) >= MIN_RESULTS:
            x, y = np.array(pts, float).T
            if x.std() > 0 and y.std() > 0:
                corr = float(np.corrcoef(x, y)[0, 1])
                if corr > 0.1:
                    out[k] = round(corr, 3)
    return out


def fit(comp, weights):
    """0-1: how much this clip looks like your best performers, and the top signal behind it."""
    have = {k: w for k, w in weights.items() if _feat(comp, k) is not None}
    if not have:
        return 0.0, ""
    top = max(have, key=lambda k: have[k] * _feat(comp, k))
    return round(sum(w * min(_feat(comp, k), 1.0) for k, w in have.items()) / sum(have.values()), 3), FEATS[top]


def _norm(t):
    return " ".join(re.sub(r"#\w+", " ", (t or "").lower()).translate({ord(ch): " " for ch in "!?.,:;'\"()[]-_|/"}).split())


def match_views(posts):
    """Give each made clip the views of your post with the same title. posts: [{title, views}]. Returns clips matched."""
    import difflib
    clips = db.q("select id, title from clips where render_path is not null or downloaded=1")
    got = {}
    for p in posts:
        pt = _norm(p["title"])
        best = max(((difflib.SequenceMatcher(None, _norm(c["title"]), pt).ratio()
                     if not (len(_norm(c["title"])) >= 10 and _norm(c["title"]) in pt) else 1.0, c["id"]) for c in clips),
                   default=(0, None))
        if best[0] >= 0.8:
            got[best[1]] = max(got.get(best[1], 0), p["views"])
    for cid, views in got.items():
        db.ex("update clips set views=? where id=?", (views, cid))
    return len(got)


def _reasons(peak, comp, words, hooks, wps, q_first, ai_info):
    r = []
    if ai_info and ai_info.get("reason"):
        r.append("AI editor: " + ai_info["reason"])
    if comp["audio"] >= 0.15:
        r.append(f"Loudness peak at {_mmss(peak)}: {comp['audio']:.0%} of the loudest moment in this video.")
    if comp.get("action") == "chase":
        r.append("Looks like a chase: the picture keeps moving fast for a long stretch.")
    elif comp.get("action") == "crash":
        r.append("Looks like a crash or explosion: a sudden jolt on screen with a loud bang.")
    elif comp.get("motion") is not None and comp["motion"] >= 0.3:
        r.append(f"Big on-screen action here: {comp['motion']:.0%} of the wildest moment.")
    if comp.get("game"):
        r.append(f"On screen: {comp['game']}. A big game moment.")
    if comp.get("fit") is not None and comp["fit"] >= 0.5 and comp.get("fit_by"):
        r.append(f"Like the clips that got the most views on your channel (strong {comp['fit_by']}).")
    if comp["heat"] is not None:
        r.append(f"YouTube 'most replayed' signal here: {comp['heat']:.0%}.")
    if comp["chat"] is not None:
        r.append(f"Chat reaction here: {comp['chat']:.0%} of the biggest chat burst.")
    if hooks:
        r.append("Hook words in the speech: " + ", ".join(sorted(set(hooks))[:6]) + ".")
    if q_first:
        r.append("Opens with a question.")
    if words:
        r.append(f"Speech density: {wps:.1f} words per second. Cut starts and ends at sentence boundaries.")
    else:
        r.append("No speech detected here. Cut points are time-based, so check them by ear.")
    return r


def _resolve_overlaps(chosen, min_clip=5.0):
    """Clips may not overlap: where two touch, the boundary moves to the middle. Too-short leftovers are dropped."""
    chosen = sorted(chosen, key=lambda c: c["s"])
    out = []
    for c in chosen:
        if out and c["s"] < out[-1]["e"]:
            mid = (c["s"] + out[-1]["e"]) / 2
            out[-1]["e"] = c["s"] = mid
            if out[-1]["e"] - out[-1]["s"] < min_clip:
                out.pop()
            if c["e"] - c["s"] < min_clip:
                continue
        out.append(c)
    return out


def analyze_video(job, video_id, p):
    v = db.q("select * from videos where id=?", (video_id,), one=True)
    ffmpeg = which("ffmpeg")
    work = wdir(video_id)
    src, dur, fps = v["path"], v["duration"], v["fps"] or 30
    n = max(1, min(int(p.get("clips", 20)), 100))
    length = max(8.0, min(float(p.get("length", 30)), 90.0))
    min_len, max_len = max(6.0, length * 0.6), max(length * 1.7, 18.0)
    many = n >= 30
    min_score = 0.0 if many else float(p.get("min_score", 0.1))
    gap = length if many else max(length, float(p.get("min_gap", 45)))
    model, device = p.get("model", "base"), p.get("device", "cpu")
    compute = "int8" if device == "cpu" else "float16"
    pad = 5.0
    db.ex("update videos set status='analyzing', error=null where id=?", (video_id,))

    # 1) the whole video's audio, cheaply
    prog(video_id, 2, "Listening to the whole video")
    acache = os.path.join(work, "audio_score.npy")
    if os.path.exists(acache):
        a = np.load(acache)
    else:
        raw = os.path.join(work, "audio.raw")
        job.run([ffmpeg, "-nostdin", "-y", "-i", src, "-vn", "-ac", "1", "-ar", str(analyze.SR), "-f", "s16le", raw])
        a = analyze.audio_score(analyze.loudness_db(raw))
        os.remove(raw)
        np.save(acache, a)
    prog(video_id, 14, "Checking the crowd signals")
    heat = None
    if v["info_path"] and os.path.exists(v["info_path"]):
        with open(v["info_path"], encoding="utf-8") as f:
            heat = analyze.heat_score(json.load(f).get("heatmap"), len(a))
    chat = None
    chat_file = os.path.join(work, "chat.txt")
    if os.path.exists(chat_file):
        with open(chat_file, encoding="utf-8", errors="ignore") as f:
            chat = analyze.chat_events_score(parse_chat_events(f.read()), len(a))
    prog(video_id, 16, "Watching for big on-screen moments")
    mcache = os.path.join(work, "motion_score.npy")
    if os.path.exists(mcache):
        motion = np.load(mcache)
    else:
        job.check()
        motion = analyze.motion_score(ffmpeg, src, len(a))
        if motion is not None:
            np.save(mcache, motion)
    gcache = os.path.join(work, "game_events.json")
    if os.path.exists(gcache):
        with open(gcache) as f:
            events = [tuple(e) for e in json.load(f)]
    else:
        prog(video_id, 18, "Looking for game banners (WASTED, BUSTED...)")
        events = game.banners(ffmpeg, src, check=job.check)
        if game.available():
            with open(gcache, "w") as f:
                json.dump(events, f)
        job.log(f"Game banners: {len(events)} found." if game.available() else
                "Game banners skipped (install requirements-extras.txt to turn them on).")
    gscore = game.banner_score(events, len(a), analyze.FRAME)
    score = analyze.combine(a, heat, chat, motion, gscore)
    k = max(1, len(score) // 400)
    curve = [round(float(score[i:i + k].max()), 3) for i in range(0, len(score), k)]
    db.ex("update videos set curve=? where id=?", (db.dumps({"step": k * analyze.FRAME, "v": curve}), video_id))

    # 2) candidate moments
    lead, tail = length * 0.65, length * 0.35
    n_cand = min(int(n * (1.6 if many else 3)), max(1, int(dur / gap)))
    cands = analyze.pick_windows(score, n_cand, gap, min_score, lead, tail, dur)
    if not cands:
        raise RuntimeError("No exciting moments stood out in this video. Try a shorter clip length.")
    for c in cands:
        c["start"] = max(0.0, min(dur - 2.0, c["start"]))
        c["end"] = min(dur, max(c["start"] + 2.0, c["end"]))
        c["ws"] = max(0.0, min(dur - 2.0, c["start"] - pad))
        c["we"] = min(dur, max(c["ws"] + 2.0, c["end"] + pad))
    covered = sum(max(0.0, c["we"] - c["ws"]) for c in cands)

    # 3) transcribe: once for the whole video if the clips cover most of it, otherwise only the good moments
    prog(video_id, 20, "Reading what is said")
    if covered >= 0.45 * dur or len(cands) > 40:
        tj = os.path.join(work, f"full_{model}.json")
        if not os.path.exists(tj):
            wav = os.path.join(work, "full.wav")
            if not os.path.exists(wav):
                job.run([ffmpeg, "-nostdin", "-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000", wav])
            res = transcribe_file(wav, model, device, compute, p.get("language") or None,
                                  on_progress=lambda f: (job.check(), prog(video_id, 22 + f * 58, "Reading what is said")))
            with open(tj, "w", encoding="utf-8") as f:
                json.dump(res, f)
        allw = load_json(tj)
        for c in cands:
            c["words"] = [w for w in allw if w["start"] >= c["ws"] - 0.01 and w["end"] <= c["we"] + 0.01]
    else:
        for i, c in enumerate(cands, 1):
            job.check()
            import time; time.sleep(0.01)
            prog(video_id, 22 + 58 * i / len(cands), f"Reading what is said ({i} of {len(cands)})")
            win_dur = max(2.0, c["we"] - c["ws"])
            key = f"win_{int(c['ws'] * 1000)}_{int(c['we'] * 1000)}"
            wav, tj = os.path.join(work, key + ".wav"), os.path.join(work, key + ".json")
            if not os.path.exists(tj):
                if not os.path.exists(wav):
                    job.run([ffmpeg, "-nostdin", "-y", "-ss", f"{c['ws']:.3f}", "-t", f"{win_dur:.3f}", "-i", src,
                             "-vn", "-ac", "1", "-ar", "16000", wav])
                with open(tj, "w", encoding="utf-8") as f:
                    json.dump(transcribe_file(wav, model, device, compute, p.get("language") or None), f)
            c["words"] = [{"w": w["w"], "start": w["start"] + c["ws"], "end": w["end"] + c["ws"]} for w in load_json(tj)]

    # 4) clean cut points and a first score
    prog(video_id, 82, "Choosing where each clip starts and ends")
    for c in cands:
        c["s"], c["e"] = snap(c["words"], c["start"], c["end"], min_len, max_len, dur, fps)
        c["cw"] = [w for w in c["words"] if w["start"] >= c["s"] - 0.01 and w["end"] <= c["e"] + 0.01]
        c["text"] = text_score(c["cw"], c["e"] - c["s"])

    # 5) optional smarter scoring with an AI editor
    key = ai_key()
    ai_res = {}
    if key:
        prog(video_id, 86, "Asking the AI editor")
        ai_res = ai.score_clips(key, [{"id": str(i), "text": " ".join(w["w"] for w in c["cw"])}
                                      for i, c in enumerate(cands) if c["cw"]], log=job.log)
    weights = learned()
    for i, c in enumerate(cands):
        c["ai"] = ai_res.get(str(i))
        sig = c["score"]
        c["final"] = (0.5 * sig + 0.1 * c["text"] + 0.4 * c["ai"]["score"]) if c["ai"] else (0.7 * sig + 0.3 * c["text"])
        idx = min(int(c["peak"] / analyze.FRAME), len(a) - 1)
        banner = next(((t, lab) for t, lab in events if c["s"] - 3 <= t <= c["e"]), (None, None))
        c["comp"] = comp = {
            "audio": float(a[idx]), "heat": None if heat is None else float(heat[idx]),
            "motion": None if motion is None else float(motion[idx]),
            "chat": None if chat is None else float(chat[idx]), "speech": float(c["text"]),
            "action": analyze.action_kind(motion, a, int(c["s"] / analyze.FRAME), int(c["e"] / analyze.FRAME)),
            "game": banner[1], "game_t": banner[0], "ai": c["ai"]["score"] if c["ai"] else None}
        if weights:   # learned from your posted clips' views: 20% of the final score
            comp["fit"], comp["fit_by"] = fit(comp, weights)
            c["final"] = 0.8 * c["final"] + 0.2 * comp["fit"]

    # 6) best N, no overlaps
    prog(video_id, 94, "Ranking the clips")
    chosen = _resolve_overlaps(sorted(cands, key=lambda x: -x["final"])[:n])
    db.ex("delete from clips where video_id=? and status='candidate'", (video_id,))
    client = db.q("select * from clients where id=?", (v["client_id"],), one=True) if v.get("client_id") else None
    tpl_default = (client or {}).get("template") or "yellow_pop"
    music_default = (client or {}).get("music") or ""
    for c in chosen:
        comp = c["comp"]
        txt = " ".join(w["w"] for w in c["cw"]).lower()
        hooks = [h for h in HOOK_WORDS if h in txt]
        first = " ".join(w["w"] for w in c["cw"][:12])
        wps = len(c["cw"]) / max(c["e"] - c["s"], 1)
        title = (c["ai"] or {}).get("title") or title_of(c["words"]) or (c["words"][0]["w"] if c["words"] else "Untitled clip")
        init_sfx = auto_sfx({"start": c["s"], "end": c["e"], "peak": c["peak"], "words": c["words"], "video_id": video_id})
        db.ex("insert into clips(video_id,start,end,peak,ws,we,score,scores,reasons,words,title,template,layout,res,"
              "crop_x,music,sfx_intro,sfx_peak,captions,status,render_status,created,sfx,hook_zoom,emojis,censor) "
              "values(?,?,?,?,?,?,?,?,?,?,?,?,'stack',1080,0.5,?,'whoosh.wav','sub_bass_drop.wav',1,'candidate','none',?,?,1,1,0)",
              (video_id, c["s"], c["e"], c["peak"], c["ws"], c["we"], round(c["final"], 4), db.dumps(comp),
               db.dumps(_reasons(c["peak"], comp, c["cw"], hooks, wps, "?" in first, c["ai"])),
               db.dumps(c["words"]), title, tpl_default, music_default, db.now(), db.dumps(init_sfx)))
    db.ex("update videos set status='ready', progress=100, stage='', error=null where id=?", (video_id,))
    job.log(f"{len(chosen)} clips ranked.")


# ---------------- captions for a clip ----------------
def ensure_clip_words(clip, video=None):
    """Ensure the clip has valid words with good coverage. Checks full video json cache first,
    then falls back to on-the-fly Whisper transcription of the clip audio."""
    if not clip or not isinstance(clip, dict):
        return []
    s = float(clip.get("start", 0.0) or 0.0)
    e = float(clip.get("end", s + 1.0) or (s + 1.0))
    dur = max(0.5, e - s)
    cid = clip.get("id")

    vid_id = clip.get("video_id") or (video.get("id") if isinstance(video, dict) else None)
    if not video and vid_id:
        video = db.q("select * from videos where id=?", (vid_id,), one=True)
    if not video:
        raw = clip.get("words")
        return json.loads(raw) if isinstance(raw, str) else (raw or [])

    work = wdir(vid_id)

    # 1. First, check if full video transcription cache exists in work/
    if os.path.isdir(work):
        for fn in os.listdir(work):
            if fn.startswith("full_") and fn.endswith(".json"):
                try:
                    full_words = load_json(os.path.join(work, fn))
                    filtered = [w for w in full_words if float(w.get("end", 0)) >= s - 0.2 and float(w.get("start", 0)) <= e + 0.2]
                    if filtered:
                        if cid:
                            db.ex("update clips set words=? where id=?", (db.dumps(filtered), cid))
                        clip["words"] = filtered
                        return filtered
                except Exception:
                    pass

    # 2. Extract audio and transcribe with Whisper
    src = clip_source(clip, video)
    if not src or not os.path.exists(src):
        raw = clip.get("words")
        return json.loads(raw) if isinstance(raw, str) else (raw or [])

    try:
        ffmpeg = which("ffmpeg")
        clip_wav = os.path.join(work, f"clip_{cid or 'tmp'}_speech.wav")
        vpath = video.get("path") if isinstance(video, dict) else None
        is_full = bool(vpath and os.path.exists(vpath) and os.path.abspath(src) == os.path.abspath(vpath))
        ss_val = s if is_full else 0.0
        cmd = [ffmpeg, "-y", "-ss", f"{ss_val:.3f}", "-t", f"{dur:.3f}", "-i", src,
               "-vn", "-ac", "1", "-ar", "16000", clip_wav]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        tr = transcribe_file(clip_wav, model="base")
        tr_words = tr.get("words") or []
        if tr_words:
            new_words = []
            for w in tr_words:
                st = round(s + w["start"], 3) if is_full else round(w["start"], 3)
                en = round(s + w["end"], 3) if is_full else round(w["end"], 3)
                new_words.append({"w": w["w"], "start": st, "end": en})
            if cid:
                db.ex("update clips set words=? where id=?", (db.dumps(new_words), cid))
            clip["words"] = new_words
            return new_words
    except Exception:
        pass

    raw = clip.get("words")
    return json.loads(raw) if isinstance(raw, str) else (raw or [])


def clip_words(clip):
    """Words inside the clip on the clip timeline, each remembering its index in the stored word list.
    Handles both absolute video timeline timestamps and 0-relative clip timestamps seamlessly."""
    if not clip or not isinstance(clip, dict):
        return []
    s = float(clip.get("start", 0.0) or 0.0)
    e = float(clip.get("end", s + 1.0) or (s + 1.0))
    dur = max(0.5, e - s)
    raw = clip.get("words")
    words = json.loads(raw) if isinstance(raw, str) else (raw or [])

    # 1. Try matching words on the absolute timeline
    matching = [
        {"w": w["w"], "start": round(max(0.0, float(w.get("start", 0)) - s), 3),
         "end": round(min(dur, float(w.get("end", 0)) - s), 3), "i": i}
        for i, w in enumerate(words)
        if float(w.get("end", 0)) >= s - 0.2 and float(w.get("start", 0)) <= e + 0.2
    ]

    # 2. If no absolute match, check if words are already 0-relative (e.g. from cut clip/live moment)
    if not matching and words:
        matching = [
            {"w": w["w"], "start": round(max(0.0, float(w.get("start", 0))), 3),
             "end": round(min(dur, float(w.get("end", 0))), 3), "i": i}
            for i, w in enumerate(words)
            if float(w.get("end", 0)) >= 0.0 and float(w.get("start", 0)) <= dur + 0.5
        ]

    # 3. If still no words or coverage is too poor (<15%), ensure words via transcription or full json
    if not matching or (matching[-1]["end"] - matching[0]["start"] < dur * 0.15):
        new_words = ensure_clip_words(clip)
        if new_words:
            matching = [
                {"w": w["w"], "start": round(max(0.0, float(w.get("start", 0)) - s), 3),
                 "end": round(min(dur, float(w.get("end", 0)) - s), 3), "i": i}
                for i, w in enumerate(new_words)
                if float(w.get("end", 0)) >= s - 0.2 and float(w.get("start", 0)) <= e + 0.2
            ]
            if not matching:
                matching = [
                    {"w": w["w"], "start": round(max(0.0, float(w.get("start", 0))), 3),
                     "end": round(min(dur, float(w.get("end", 0))), 3), "i": i}
                    for i, w in enumerate(new_words)
                    if float(w.get("end", 0)) >= 0.0 and float(w.get("start", 0)) <= dur + 0.5
                ]
    return matching


def auto_sfx(clip):
    """Effects that make a clip hit harder: whoosh in, riser into the big moment, boom on it, pops on reaction words.
    Times are on the video timeline (like start/end), so trimming never moves them off their moment."""
    s = clip.get("start", 0.0)
    dur = max(0.5, clip.get("end", s + 1.0) - s)
    peak = clip.get("peak", s + dur * 0.4) - s
    if not 0.5 < peak < dur - 0.3:
        peak = dur * 0.4
    out = [{"f": "whoosh.wav", "t": 0.0, "v": 0.5}]
    if peak > 2:
        out.append({"f": "riser.wav", "t": peak - 1.5, "v": 0.35})
    out.append({"f": "boom.wav", "t": peak, "v": 0.8})
    sc = json.loads(clip.get("scores") or "{}")
    if sc.get("game_t") is not None and 0.3 < sc["game_t"] - s + 0.4 < dur - 0.5:   # meme sound on a game banner
        fail = sc["game"] not in ("MISSION PASSED", "HEIST PASSED")
        out.append({"f": audiolib.MEME_FAIL if fail else audiolib.MEME_WIN, "t": sc["game_t"] - s + 0.4, "v": 0.7})
    words = clip_words(clip)
    toks = [re.sub(r"[^a-z0-9 ]", "", w["w"].lower()) for w in words]
    last = -9.0
    for i, w in enumerate(words):
        said = " ".join(toks[i:i + 3])
        if (any(said == h or said.startswith(h + " ") for h in HOOK_WORDS) and abs(w["start"] - peak) > 1.5
                and w["start"] - last >= 2 and 0.3 < w["start"] < dur - 0.3):
            out.append({"f": "pop.wav", "t": w["start"], "v": 0.6})
            last = w["start"]
            if sum(e["f"] == "pop.wav" for e in out) == 3:
                break
    return [dict(e, t=round(s + e["t"], 3)) for e in sorted(out, key=lambda e: e["t"])
            if audiolib.resolve("sfx", e["f"])]


def clip_cues(clip):
    words = clip_words(clip)
    if words:
        cues = captions.build_cues(words)
        if cues:
            return cues

    # Fallback to kinetic phrase cues from title so subtitles never appear blank
    title = (clip.get("title") or "MOMENT OF THE STREAM 🔥").strip()
    s = clip.get("start", 0.0)
    dur = max(1.0, clip.get("end", s + 1.0) - s)
    words_list = title.split()
    if not words_list:
        words_list = ["WATCH", "THIS", "MOMENT", "🔥"]

    chunk_size = 3
    chunks = [words_list[i:i + chunk_size] for i in range(0, len(words_list), chunk_size)]
    chunk_dur = min(2.5, dur / max(len(chunks), 1))
    cues = []
    for idx, ch in enumerate(chunks):
        c_start = idx * chunk_dur
        c_end = min(dur, c_start + chunk_dur)
        w_dur = (c_end - c_start) / max(len(ch), 1)
        c_words = []
        for j, wrd in enumerate(ch):
            ws = c_start + j * w_dur
            we = ws + w_dur
            c_words.append({"w": wrd, "start": ws, "end": we, "i": idx * 10 + j})
        cues.append({"words": c_words, "start": c_start, "end": c_end, "text": " ".join(ch)})
    return cues


def edit_cue(clip, first, last, text):
    words = json.loads(clip["words"])
    if not (0 <= first <= last < len(words)):
        raise ValueError("bad cue range")
    toks = text.split()
    if not toks:
        raise ValueError("Caption text can't be empty.")
    if len(toks) == last - first + 1:                            # same word count: keep each word's timing
        for t, i in zip(toks, range(first, last + 1)):
            words[i]["w"] = t
    else:                                                        # spread new words across the same time span
        t0, t1 = words[first]["start"], words[last]["end"]
        total = sum(len(t) + 1 for t in toks)
        cur, new = t0, []
        for t in toks:
            d = (t1 - t0) * (len(t) + 1) / total
            new.append({"w": t, "start": round(cur, 3), "end": round(cur + d, 3)})
            cur += d
        words[first:last + 1] = new
    return words


# ---------------- translated captions + voice-over ----------------
def _lang_and_voice(job, c, cues, work):
    """Translate the captions (and voice-over line) when the clip has a language, then speak the voice-over.
    Both are optional: any problem is logged and the clip is made without it."""
    lang, text, vo_lang = c.get("lang") or "", (c.get("vo") or "").strip(), "en"
    if lang and (cues or text):
        key = ai_key()
        if not key:
            job.log("Translated captions need an AI key in Settings: using the original words.")
        else:
            try:
                lines = ai.translate(key, [" ".join(w["w"] for w in q["words"]) for q in cues] + ([text] if text else []), lang)
                if text:
                    text = lines.pop()
                cues = [captions.respread(q, t) for q, t in zip(cues, lines)]
                vo_lang = lang
                job.log(f"Translated to {ai.LANGS.get(lang, lang)}.")
            except Exception as e:
                job.log(f"Translation skipped ({str(e)[:120]}): using the original words.")
    if not text:
        return cues, None
    if not voice.available():
        job.log("Voice-over skipped: install requirements-extras.txt to turn it on.")
        return cues, None
    wav = os.path.join(work, f"clip_{c['id']}_vo.wav")
    try:
        job.log("Recording the voice-over (the first time downloads the voice, about 100 MB)...")
        return cues, (wav, 0.2, voice.say(text, vo_lang, wav, os.path.join(db.DATA, "voices")))
    except Exception as e:
        job.log(f"Voice-over skipped ({str(e)[:120]}).")
        return cues, None


# ---------------- face framing + render ----------------
def get_track(job, clip, video):
    """Face-following crop path for a clip (cached until the clip's start or end changes)."""
    s = clip.get("start", 0.0)
    e = clip.get("end", s + 1.0)
    if clip.get("track"):
        try:
            t = json.loads(clip["track"])
            if abs(t.get("start", 0) - s) < 0.01 and abs(t.get("end", 0) - e) < 0.01:
                return t
        except Exception:
            pass
    aspect = str(clip.get("aspect_ratio") or "9:16").strip()
    target_ratio = 1.0 if aspect == "1:1" else (16/9 if aspect == "16:9" else 9/16)
    vw = (video.get("w") if isinstance(video, dict) else None) or 1280
    vh = (video.get("h") if isinstance(video, dict) else None) or 720
    t = faces.track(which("ffmpeg"), clip_source(clip, video), vw, vh, s, e,
                    fps=5, should_stop=job.check if job else None, target_ratio=target_ratio)
    t["start"], t["end"] = s, e
    cid = clip.get("id")
    if cid:
        db.ex("update clips set track=? where id=?", (db.dumps(t), cid))
    return t


def get_cam(job, clip, video):
    """Facecam box for the stacked layout (cached until the clip's start or end changes).
    A clip-specific corner or box chosen wins over general video detection."""
    vw = (video.get("w") if isinstance(video, dict) else None) or 1280
    vh = (video.get("h") if isinstance(video, dict) else None) or 720
    split_r = float(clip.get("split_ratio") or 0.5)

    # 1. Corner preset selected on clip
    corner = clip.get("cam_corner")
    if corner and corner in ("tl", "tr", "bl", "br", "tc", "bc"):
        if corner == "tl":
            box = [0, 0, int(vw * 0.35), int(vh * 0.50)]
        elif corner == "bl":
            box = [0, int(vh * 0.45), int(vw * 0.35), int(vh * 0.55)]
        elif corner == "br":
            box = [int(vw * 0.65), int(vh * 0.45), int(vw * 0.35), int(vh * 0.55)]
        elif corner == "tc":
            box = [int(vw * 0.325), 0, int(vw * 0.35), int(vh * 0.50)]
        elif corner == "bc":
            box = [int(vw * 0.325), int(vh * 0.45), int(vw * 0.35), int(vh * 0.55)]
        else: # tr
            box = [int(vw * 0.65), 0, int(vw * 0.35), int(vh * 0.50)]
        return {"cam": faces.fit_panel(box[0], box[1], box[2], box[3], box[0] + box[2] / 2, box[1] + box[3] / 2, top_share=split_r),
                "box": box, "kind": "facecam", "exact": True, "manual": True}

    # 2. Hand-drawn box on video
    if isinstance(video, dict) and video.get("cam_box"):
        try:
            x, y, bw, bh = json.loads(video["cam_box"])
            return {"cam": faces.fit_panel(x, y, bw, bh, x + bw / 2, y + bh / 2, top_share=split_r), "box": [x, y, bw, bh], "kind": "facecam",
                    "exact": True, "manual": True}
        except Exception:
            pass

    s = clip.get("start", 0.0)
    e = clip.get("end", s + 1.0)
    cid = clip.get("id")
    vid = clip.get("video_id") or (video.get("id") if isinstance(video, dict) else None)

    if clip.get("cam"):
        try:
            c = json.loads(clip["cam"])
            if "box" in c and abs(c.get("start", 0) - s) < 0.01 and abs(c.get("end", 0) - e) < 0.01:
                return c
        except Exception:
            pass
    if vid and cid:
        other = db.q("select cam from clips where video_id=? and cam is not null and cam != '' and id != ? limit 1",
                     (vid, cid), one=True)
        if other and other.get("cam"):
            try:
                c = json.loads(other["cam"])
                if c.get("box") and c.get("kind") == "facecam" and c.get("exact"):
                    c["start"], c["end"] = s, e
                    db.ex("update clips set cam=? where id=?", (db.dumps(c), cid))
                    return c
            except Exception:
                pass
    if job:
        job.check()
    c = faces.find_facecam(which("ffmpeg"), clip_source(clip, video), vw, vh, s, e, top_share=split_r)
    c["start"], c["end"] = s, e
    if cid:
        db.ex("update clips set cam=? where id=?", (db.dumps(c), cid))
    if isinstance(video, dict) and not video.get("cam_box") and c.get("kind") == "facecam" and c.get("box") and c.get("exact") and video.get("id"):
        try:
            db.ex("update videos set cam_box=? where id=? and cam_box is null", (db.dumps(c["box"]), video["id"]))
        except Exception:
            pass
    return c


def framing(clip, video):
    """What the browser preview needs to mimic the face-following crop or the stacked layout."""
    vw = (video.get("w") if isinstance(video, dict) else None) or 1280
    vh = (video.get("h") if isinstance(video, dict) else None) or 720
    layout = clip.get("layout", "stack")
    if layout in ("stack", "pip"):
        c = get_cam(None, clip, video)
        cam_box = c.get("box")
        cam_crop = c.get("cam")
        if not cam_box or not cam_crop:
            corner = clip.get("cam_corner") or "tr"
            if corner == "tl":
                cam_box = [0, 0, int(vw * 0.35), int(vh * 0.50)]
            elif corner == "bl":
                cam_box = [0, int(vh * 0.45), int(vw * 0.35), int(vh * 0.55)]
            elif corner == "br":
                cam_box = [int(vw * 0.65), int(vh * 0.45), int(vw * 0.35), int(vh * 0.55)]
            elif corner == "tc":
                cam_box = [int(vw * 0.325), 0, int(vw * 0.35), int(vh * 0.50)]
            elif corner == "bc":
                cam_box = [int(vw * 0.325), int(vh * 0.45), int(vw * 0.35), int(vh * 0.55)]
            elif corner == "center":
                cam_box = [int(vw * 0.25), int(vh * 0.15), int(vw * 0.5), int(vh * 0.6)]
            else:
                cam_box = [int(vw * 0.65), 0, int(vw * 0.35), int(vh * 0.50)]
            cam_crop = faces.fit_panel(cam_box[0], cam_box[1], cam_box[2], cam_box[3],
                                       cam_box[0] + cam_box[2] / 2, cam_box[1] + cam_box[3] / 2)
        split_ratio = float(clip.get("split_ratio") or 0.5)
        return {"stack": layout == "stack", "pip": layout == "pip",
                "size": faces.PIP_SIZE, "ptop": faces.PIP_TOP,
                "kind": c.get("kind") or "facecam", "cam": cam_crop, "box": cam_box, "w": vw, "h": vh,
                "top": split_ratio, "split_ratio": split_ratio, "found": 1.0, "pts": [], "manual": bool(c.get("manual")),
                "cam_zoom": float(clip.get("cam_zoom") or 1.0),
                "cam_crop_x": float(clip.get("cam_crop_x") if clip.get("cam_crop_x") is not None else 0.5),
                "cam_crop_y": float(clip.get("cam_crop_y") if clip.get("cam_crop_y") is not None else 0.5),
                "cam_shape": clip.get("cam_shape") or "rect",
                "cam_corner": clip.get("cam_corner") or "tr",
                "cam_pos": clip.get("cam_pos") or "top",
                "cam_pos_x": float(clip.get("cam_pos_x") or 0.5),
                "cam_pos_y": float(clip.get("cam_pos_y") or 0.65),
                "banner_text": clip.get("banner_text") or "",
                "banner_style": clip.get("banner_style") or "white_box"}
    t = get_track(None, clip, video)
    room = max(vw - t["cw"], 1)
    return {"found": t["found"], "cw": t["cw"], "w": vw, "h": vh,
            "pts": [[p[0], round(p[1] / room, 4)] for p in t["pts"]]}


def _hd_part(job, c, v, info, track):
    """Quick-copy videos: fetch just this clip in full quality and move the face boxes to its size.
    Returns None (render from the quick copy) if the link no longer works."""
    out = os.path.join(vdir(v["id"]), f"hd_{c['id']}_{c['start']:.2f}_{c['end']:.2f}.mp4")
    job.log(f"Getting this part in {v['hd']}p...")
    try:
        download_section(job, v["source"], out, c["start"], c["end"], v["hd"], v["cookies"])
        p = probe(which("ffprobe"), out)
    except Cancelled:
        raise
    except Exception as e:
        job.log(f"Couldn't get the full-quality part ({str(e)[:200]}). Using the quick copy instead.")
        return None
    k = p["w"] / v["w"]
    if track:
        track = dict(track)
        for key in ("cam", "box"):
            if track.get(key):
                track[key] = [int(n * k) // 2 * 2 for n in track[key]]
        if track.get("pts"):
            track["pts"] = [[t, x * k] for t, x in track["pts"]]
    return out, 0.0, c["end"] - c["start"], {**info, "w": p["w"], "h": p["h"], "fps": p["fps"]}, track


def render(job, clip_id, p):
    c = db.q("select * from clips where id=?", (clip_id,), one=True)
    v = db.q("select * from videos where id=?", (c["video_id"],), one=True)
    ffmpeg = which("ffmpeg")
    info = {"w": v["w"], "h": v["h"], "fps": v["fps"], "duration": v["duration"]}
    cues = clip_cues(c) if c["captions"] else []
    work = wdir(c["video_id"])
    ass = os.path.join(work, f"clip_{clip_id}.ass")
    censor = bool(c["censor"]) if ("censor" in c and c["censor"] is not None) else False
    emojis = bool(c["emojis"]) if ("emojis" in c and c["emojis"] is not None) else True
    hook_zoom = bool(c["hook_zoom"]) if ("hook_zoom" in c and c["hook_zoom"] is not None) else True
    banner_text = c.get("banner_text") or ""
    banner_style = c.get("banner_style") or "white_box"
    banner_x = float(c.get("banner_x") if c.get("banner_x") is not None else 0.5)
    banner_y = float(c.get("banner_y") if c.get("banner_y") is not None else 0.12)
    banner_size = float(c.get("banner_size") if c.get("banner_size") is not None else 1.0)
    banner_font = str(c.get("banner_font") or "Arial")
    caption_size = float(c.get("caption_size") if c.get("caption_size") is not None else 1.0)
    caption_font = str(c.get("caption_font") or "Arial")

    res_base = int(c["res"] or 1080)
    aspect = str(c.get("aspect_ratio") or "9:16").strip()
    if aspect == "1:1":
        W, H = res_base, res_base
    elif aspect == "16:9":
        H = res_base
        W = int(res_base * 16 / 9) // 2 * 2
    else:
        W = res_base
        H = int(res_base * 16 / 9) // 2 * 2

    cues, vo = _lang_and_voice(job, c, cues, work)
    with open(ass, "w", encoding="utf-8") as f:
        f.write(captions.to_ass(cues, c["template"], width=W, height=H, censor=censor, emojis=emojis, hook_boost=True,
                                banner_text=banner_text, banner_style=banner_style, banner_x=banner_x, banner_y=banner_y,
                                banner_size=banner_size, banner_font=banner_font,
                                caption_size=caption_size, caption_font=caption_font))
    out_dir = os.path.join(db.DATA, "exports")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"clip_{clip_id}.mp4")
    last = {"p": -1}

    def setp(frac):
        pct = round(frac * 100)
        if pct != last["p"]:
            last["p"] = pct
            db.ex("update clips set render_progress=? where id=?", (pct, clip_id))
    setp(0.01)
    track, layout = None, c["layout"]
    wide = v["w"] / v["h"] > (W / H) + 0.01
    if layout in ("stack", "pip") and wide:
        cam = get_cam(job, c, v)
        job.log({"facecam": "Facecam found: placed over the gameplay." if layout == "pip" else "Facecam found: stacked above the gameplay.", "camera": "Full camera shot: following the face.",
                 "none": "No facecam: showing the whole gameplay."}[cam["kind"]])
        if cam["kind"] == "camera":
            layout = "follow"
        else:
            track = {"cam": cam["cam"], "box": cam["box"]}
    if layout == "follow" and wide:
        track = get_track(job, c, v)
        job.log(f"Face found in {track['found']:.0%} of the clip.")
    src, start, end = clip_source(c, v), c["start"], c["end"]
    if v["hd"] and not c["src"]:
        src, start, end, info, track = _hd_part(job, c, v, info, track) or (src, start, end, info, track)
    elif src and src != (v.get("path") if isinstance(v, dict) else None):
        # src is already cut to this clip (starts at 0.0)
        start = 0.0
        end = c["end"] - c["start"]
    setp(0.12)
    dur = c["end"] - c["start"]
    sfx = []
    path = audiolib.resolve("sfx", c["sfx_intro"])
    if path:
        sfx.append((path, 0.0, 0.7))
    for e in json.loads(c["sfx"] or "[]"):                 # placed effects, stored on the video timeline
        path = audiolib.resolve("sfx", e["f"])
        if path and c["start"] <= e["t"] < c["end"]:
            sfx.append((path, e["t"] - c["start"], e["v"]))
    music = audiolib.resolve("music", c["music"])
    job.log(f"Rendering {dur:.0f}s clip at {W}x{H} ({aspect})...")
    if c.get("sfx_peak"):
        p_peak = audiolib.resolve("sfx", c["sfx_peak"])
        if p_peak:
            peak_offset = max(0.5, min(dur - 0.5, c["peak"] - c["start"]))
            if not any(abs(at - peak_offset) < 0.8 for _, at, _ in sfx):
                sfx.append((p_peak, peak_offset, 0.85))
    render_clip(job, ffmpeg, src, info, start, end, ass, out, layout, c["crop_x"],
                res=c["res"], music=music, music_vol=0.18, duck=True, sfx=sfx, track=track,
                hook_zoom=hook_zoom, on_progress=lambda f: setp(0.12 + 0.88 * f),
                cam_zoom=float(c.get("cam_zoom") or 1.0),
                cam_shape=c.get("cam_shape") or "rect",
                cam_pos=c.get("cam_pos") or "top",
                cam_pos_x=float(c.get("cam_pos_x") or 0.5),
                cam_pos_y=float(c.get("cam_pos_y") or 0.65),
                split_ratio=float(c.get("split_ratio") or 0.5),
                cam_crop_x=float(c.get("cam_crop_x") if c.get("cam_crop_x") is not None else 0.5),
                cam_crop_y=float(c.get("cam_crop_y") if c.get("cam_crop_y") is not None else 0.5),
                cam_corner=c.get("cam_corner") or "tr",
                aspect_ratio=aspect,
                game_zoom=float(c.get("game_zoom") or 1.0),
                crop_y=float(c.get("crop_y") if c.get("crop_y") is not None else 0.5),
                vo=vo)
    db.ex("update clips set render_status='done', render_progress=100, render_path=?, qc=? where id=?",
          (out, db.dumps(quality_check(ffmpeg, out, clip_words(c))), clip_id))


# ---------------- quality check, post text ----------------
def quality_check(ffmpeg, path, words):
    """Problems a viewer would notice: [{"level": "fail"|"warn", "msg": ...}]. Empty list = looks fine."""
    r = subprocess.run([ffmpeg, "-v", "info", "-i", path, "-vf", "blackdetect=d=1:pix_th=0.08", "-af", "volumedetect",
                        "-f", "null", "-"], capture_output=True, text=True)
    log = r.stderr
    return qc_from_log(log, probe(which("ffprobe"), path)["duration"], words)


def qc_from_log(log, dur, words):
    out = []
    if dur < 6:
        out.append({"level": "fail", "msg": f"Only {dur:.0f} seconds long. Shorts under 6 s rarely get views."})
    m = re.search(r"mean_volume: (-?[\d.]+) dB", log)
    if m and float(m.group(1)) < -45:
        out.append({"level": "fail", "msg": "The sound is almost silent."})
    black = sum(float(x) for x in re.findall(r"black_duration:([\d.]+)", log))
    if black > max(1.5, dur * 0.25):
        out.append({"level": "warn", "msg": f"{black:.0f} s of black screen."})
    if not words:
        out.append({"level": "warn", "msg": "Nobody speaks in this clip, so there are no captions."})
    elif len(words) / max(dur, 1) < 0.5:
        out.append({"level": "warn", "msg": "Very little speech: check it still makes sense without sound."})
    return out


@functools.lru_cache(maxsize=512)
def _uploader(info_path, mtime):
    with open(info_path, encoding="utf-8") as f:
        info = json.load(f)
    return info.get("channel") or info.get("uploader")


def credit(v):
    """(streamer name or None, platform name or '') for a video, from its link and download info."""
    if not v:
        return None, ""
    src = v.get("source") or ""
    plat = next((n for k, n in (("twitch.tv", "Twitch"), ("kick.com", "Kick"), ("youtu", "YouTube")) if k in src), "")
    who = None
    if v.get("info_path") and os.path.exists(v["info_path"]):
        who = _uploader(v["info_path"], os.path.getmtime(v["info_path"]))
    m = re.search(r"(?:twitch\.tv|kick\.com)/([A-Za-z0-9_]+)|youtube\.com/@([\w.-]+)", src)
    if not who and m and (m.group(1) or "").lower() != "videos":
        who = m.group(1) or m.group(2)
    return who, plat


def post_text(c, v):
    """Ready-to-paste post: title, credit to the streamer and hashtags."""
    who, plat = credit(v)
    tag = re.sub(r"[^A-Za-z0-9]", "", who or "")
    tags = ["#GTA6", "#GTA", "#Shorts"] + ([f"#{tag}"] if tag else []) + ([f"#{plat}"] if plat else [])
    return "\n\n".join(x for x in (c["title"], f"Credit: {who}" + (f" on {plat}" if plat else "") if who else "",
                                    " ".join(tags)) if x)
