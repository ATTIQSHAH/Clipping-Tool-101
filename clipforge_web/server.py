"""ClipForge web app: API + the page. Local use: binds to 127.0.0.1 only unless a password is set."""
import asyncio, hashlib, hmac, json, os, re, shutil, subprocess, threading, zipfile
from typing import Optional

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response

from clipforge import ai, audiolib, captions, source, voice
from clipforge.captions import TEMPLATES
from clipforge.render import RES
from clipforge.util import which, silent_flags
from . import db, engine, live, storage, worker

app = FastAPI(title="ClipForge")
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
EXTS = {".mp4", ".mov", ".mkv", ".webm"}
CLIP_FIELDS = {
    "title", "template", "layout", "res", "crop_x", "crop_y", "music", "sfx_intro", "sfx_peak",
    "captions", "status", "words", "hook_zoom", "emojis", "censor", "sfx",
    "cam_zoom", "cam_shape", "cam_pos", "cam_pos_x", "cam_pos_y", "banner_text", "banner_style",
    "banner_x", "banner_y", "banner_size", "banner_font", "split_ratio", "cam_corner", "cam_crop_x", "cam_crop_y", "game_zoom", "aspect_ratio",
    "views", "lang", "vo", "caption_size", "caption_font"
}


@app.on_event("startup")
def _start():
    db.conn()
    db.ex("update videos set status='ready', stage='' where status='live'")
    audiolib.make_starter_sfx(which("ffmpeg"))
    worker.start()
    live.start_watcher()


# ---------------- auth ----------------
def _pw():
    return os.environ.get("CLIPFORGE_PASSWORD") or db.setting("password")


def _token(pw):
    return hmac.new(pw.encode(), b"clipforge-auth-v1", hashlib.sha256).hexdigest()


@app.middleware("http")
async def auth_gate(req: Request, call_next):
    pw = _pw()
    if not pw:
        return await call_next(req)
    p = req.url.path
    if p in ("/api/auth/status", "/api/auth/login") or p.startswith("/static/"):
        return await call_next(req)
    tok = req.cookies.get("cf_auth")
    if tok and hmac.compare_digest(tok, _token(pw)):
        return await call_next(req)
    if p.startswith("/api/"):
        return Response(status_code=401, content=json.dumps({"detail": "Sign in required."}),
                        media_type="application/json")
    return await call_next(req)


@app.get("/api/auth/status")
def auth_status(req: Request):
    pw = _pw()
    if not pw:
        return {"required": False, "ok": True}
    tok = req.cookies.get("cf_auth")
    return {"required": True, "ok": bool(tok and hmac.compare_digest(tok, _token(pw)))}


@app.post("/api/auth/login")
def auth_login(body: dict = Body(...)):
    pw = _pw()
    if not pw:
        return {"ok": True}
    if not hmac.compare_digest(body.get("password", ""), pw):
        raise HTTPException(401, "Wrong password.")
    res = Response(content=json.dumps({"ok": True}), media_type="application/json")
    res.set_cookie("cf_auth", _token(pw), httponly=True, samesite="lax", max_age=86400 * 30)
    return res


@app.post("/api/auth/logout")
def auth_logout():
    res = Response(content=json.dumps({"ok": True}), media_type="application/json")
    res.delete_cookie("cf_auth")
    return res


# ---------------- helpers ----------------
def _video(vid: int):
    v = db.q("select * from videos where id=?", (vid,), one=True)
    if not v:
        raise HTTPException(404, "Video not found.")
    who, plat = engine.credit(v)
    if who:
        key = f"{plat}:{who}".lower()
        rule = db.q("select status, note from rules where key=?", (key,), one=True) or {"status": "unknown", "note": ""}
        v["streamer"] = {"name": who, "platform": plat, "key": key, **rule}
    return v


def _clip(cid: int):
    c = db.q("select * from clips where id=?", (cid,), one=True)
    if not c:
        raise HTTPException(404, "Clip not found.")
    return c


def _clip_out(c):
    o = {k: v for k, v in c.items() if k not in ("words", "render_path", "track", "src", "cam")}
    o["scores"] = json.loads(c["scores"] or "{}")
    o["reasons"] = json.loads(c["reasons"] or "[]")
    o["sfx"] = json.loads(c["sfx"] or "[]")
    o["qc"] = json.loads(c["qc"]) if c.get("qc") else None
    o["hook_zoom"] = int(c["hook_zoom"]) if ("hook_zoom" in c and c["hook_zoom"] is not None) else 1
    o["emojis"] = int(c["emojis"]) if ("emojis" in c and c["emojis"] is not None) else 1
    o["censor"] = int(c["censor"]) if ("censor" in c and c["censor"] is not None) else 0
    o["sfx_peak"] = c.get("sfx_peak") or ""
    o["rendered"] = bool(c["render_path"] and os.path.exists(c["render_path"]))
    o["split_ratio"] = float(c.get("split_ratio") or 0.5)
    o["cam_corner"] = c.get("cam_corner") or "tr"
    o["cam_zoom"] = float(c.get("cam_zoom") or 1.0)
    o["game_zoom"] = float(c.get("game_zoom") or 1.0)
    o["crop_x"] = float(c.get("crop_x") if c.get("crop_x") is not None else 0.5)
    o["crop_y"] = float(c.get("crop_y") if c.get("crop_y") is not None else 0.5)
    o["banner_x"] = float(c.get("banner_x") if c.get("banner_x") is not None else 0.5)
    o["banner_y"] = float(c.get("banner_y") if c.get("banner_y") is not None else 0.12)
    if c["render_status"] == "failed":
        j = db.q("select error from jobs where type='render' and ref_id=? and status='failed' order by id desc limit 1",
                 (c["id"],), one=True)
        o["render_error"] = (j or {}).get("error")
    return o


def _then(body):
    c = body.get("clips")
    return {"clips": c, "length": body.get("length", 30),
            "whisper_model": body.get("whisper_model", "base")} if c else None


# ---------------- videos ----------------
@app.get("/api/videos")
def videos(client_id: Optional[int] = None):
    sql = "select * from videos"
    args = ()
    if client_id is not None:
        sql += " where client_id=?"
        args = (client_id,)
    sql += " order by id desc"
    rows = db.q(sql, args)
    for r in rows:
        r["curve"] = json.loads(r["curve"] or "[]")
        who, plat = engine.credit(r)
        if who:
            key = f"{plat}:{who}".lower()
            rule = db.q("select status, note from rules where key=?", (key,), one=True) or {"status": "unknown", "note": ""}
            r["streamer"] = {"name": who, "platform": plat, "key": key, **rule}
    return rows


@app.get("/api/past")
def past(url: str):
    """A channel's last 5 past streams, to make clips from a live you missed."""
    try:
        return source.past_streams(url)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, str(e)[:300])


@app.get("/api/videos/{vid}")
def video(vid: int):
    r = _video(vid)
    r["curve"] = json.loads(r["curve"] or "[]")
    return r


@app.delete("/api/videos/{vid}")
def delete_video(vid: int):
    v = _video(vid)
    for row in db.q("select id from clips where video_id=?", (vid,)):
        _delete_clip_files(row["id"])
    db.ex("delete from clips where video_id=?", (vid,))
    db.ex("delete from jobs where (type in ('ingest','analyze') and ref_id=?)", (vid,))
    db.ex("delete from videos where id=?", (vid,))
    shutil.rmtree(engine.vdir(vid), ignore_errors=True)
    shutil.rmtree(engine.wdir(vid), ignore_errors=True)
    return {"ok": True}


@app.post("/api/videos/upload")
async def upload_video(file: UploadFile = File(...), client_id: Optional[int] = None,
                       clips: Optional[int] = None, length: Optional[float] = None,
                       whisper_model: Optional[str] = "base"):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in EXTS:
        raise HTTPException(400, f"Unsupported format {ext}. Use: " + ", ".join(sorted(EXTS)))
    title = os.path.splitext(file.filename or "video")[0]
    vid = db.ex("insert into videos(title,source,status,created,client_id,kind,stage) values(?,?,'importing',?,?,?,'Saving upload')",
                (title, file.filename, db.now(), client_id, "upload"))
    d = engine.vdir(vid)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"source{ext}")
    with open(p, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)
    db.ex("update videos set path=? where id=?", (p, vid))
    then = {"clips": clips, "length": length or 30, "whisper_model": whisper_model} if clips else None
    worker.enqueue("ingest", vid, {"then_analyze": then})
    return {"id": vid}


@app.post("/api/videos/link")
def add_link(body: dict = Body(...)):
    urls = body.get("urls") or ([body["url"]] if body.get("url") else [])
    if not urls:
        raise HTTPException(400, "Provide at least one video link.")
    ids = []
    for u in urls:
        u = u.strip()
        if not u:
            continue
        if not u.startswith(("http://", "https://")):
            raise HTTPException(400, f"That isn't a web link: {u[:60]}")
        vid = db.ex("insert into videos(title,source,status,created,client_id,kind,stage) values(?,?,?,?,?,?,?)",
                    (u, u, "importing", db.now(), body.get("client_id"), "link", "Getting your video"))
        cookies_browser = body.get("cookies_browser") or db.setting("cookies_browser") or None
        worker.enqueue("ingest", vid, {"max_height": body.get("max_height", 1080), "quick": bool(body.get("quick", True)),
                                       "cookies_browser": cookies_browser,
                                       "then_analyze": _then(body)})
        ids.append(vid)
    return {"ids": ids}


@app.post("/api/videos/{vid}/analyze")
def trigger_analyze(vid: int, body: dict = Body(default={})):
    v = _video(vid)
    if v["status"] in ("importing", "analyzing"):
        raise HTTPException(400, f"Video is already busy ({v['status']}).")
    worker.enqueue("analyze", vid, body)
    return {"ok": True}


@app.post("/api/videos/{vid}/retry")
def retry_video(vid: int, body: dict = Body(default={})):
    v = _video(vid)
    worker.cancel_for("video", vid)
    db.ex("update videos set error=null, progress=0, stage='Retrying' where id=?", (vid,))
    if v["path"] and os.path.exists(v["path"]):
        db.ex("update videos set status='analyzing', stage='Getting ready' where id=?", (vid,))
        worker.enqueue("analyze", vid, _then(body) or {"clips": body.get("clips", 20), "length": body.get("length", 30)})
    else:
        db.ex("update videos set status='importing', stage='Getting your video' where id=?", (vid,))
        cookies_browser = body.get("cookies_browser") or db.setting("cookies_browser") or None
        worker.enqueue("ingest", vid, {
            "max_height": body.get("max_height", 1080),
            "quick": bool(body.get("quick", True)),
            "cookies_browser": cookies_browser,
            "then_analyze": _then(body) or {"clips": body.get("clips", 20), "length": body.get("length", 30)}
        })
    return {"ok": True}


@app.patch("/api/videos/{vid}")
def patch_video(vid: int, body: dict = Body(...)):
    _video(vid)
    if "cam_box" in body:
        val = body["cam_box"]
        if val is not None:
            if not (isinstance(val, list) and len(val) == 4 and all(isinstance(n, (int, float)) for n in val)):
                raise HTTPException(400, "Facecam box must be [x, y, w, h].")
            val = db.dumps([int(n) for n in val])
        db.ex("update videos set cam_box=? where id=?", (val, vid))
        db.ex("update clips set cam=null where video_id=?", (vid,))
    return _video(vid)


@app.post("/api/videos/{vid}/cancel")
def cancel_video(vid: int):
    _video(vid)
    worker.cancel_for("video", vid)
    db.ex("update videos set status='ready', stage='' where id=?", (vid,))
    return {"ok": True}


@app.post("/api/videos/{vid}/approve_all")
def approve_all_clips(vid: int):
    _video(vid)
    clips = db.q("select id, render_path, render_status from clips where video_id=?", (vid,))
    count = 0
    for c in clips:
        try:
            cid = c["id"]
            db.ex("update clips set status='approved' where id=?", (cid,))
            is_rendered = bool(c["render_path"] and os.path.exists(c["render_path"]))
            needs_render = not is_rendered
            if needs_render and c["render_status"] != "running":
                worker.enqueue("render", cid)
            count += 1
        except Exception:
            pass
    return {"ok": True, "approved_count": count}


@app.post("/api/clips/approve_batch")
def approve_batch_clips(body: dict = Body(...)):
    ids = body.get("ids") or []
    count = 0
    for cid in ids:
        try:
            cid = int(cid)
            c = db.q("select id, render_path, render_status from clips where id=?", (cid,), one=True)
            if not c:
                continue
            db.ex("update clips set status='approved' where id=?", (cid,))
            is_rendered = bool(c["render_path"] and os.path.exists(c["render_path"]))
            if not is_rendered and c["render_status"] != "running":
                worker.enqueue("render", cid)
            count += 1
        except Exception:
            pass
    return {"ok": True, "approved_count": count}


@app.get("/api/videos/{vid}/download_zip")
def download_video_zip(vid: int):
    v = _video(vid)
    clips = db.q("select id, title, render_path from clips where video_id=? and render_status='done'", (vid,))
    rendered_clips = [c for c in clips if c["render_path"] and os.path.exists(c["render_path"])]
    if not rendered_clips:
        raise HTTPException(400, "No rendered clips ready yet. Please wait for rendering to finish.")
    zip_dir = os.path.join(db.DATA, "exports")
    os.makedirs(zip_dir, exist_ok=True)
    clean_title = re.sub(r"[^\w\-.]+", "_", v["title"] or f"video_{vid}").strip("_")
    zip_path = os.path.join(zip_dir, f"{clean_title}_all_clips.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for idx, c in enumerate(rendered_clips, 1):
            c_name = re.sub(r"[^\w\-.]+", "_", c["title"] or f"clip_{c['id']}").strip("_")
            arcname = f"{idx:02d}_{c_name}.mp4"
            zf.write(c["render_path"], arcname)
    return FileResponse(zip_path, filename=f"{clean_title}_all_clips.zip", media_type="application/zip")


# ---------------- clips ----------------
@app.get("/api/videos/{vid}/clips")
def list_clips(vid: int):
    rows = db.q("select * from clips where video_id=? order by score desc, id", (vid,))
    return [_clip_out(r) for r in rows]


def _delete_clip_files(cid):
    c = db.q("select render_path, src from clips where id=?", (cid,), one=True)
    if c:
        if c["render_path"] and os.path.exists(c["render_path"]):
            try:
                os.remove(c["render_path"])
            except Exception:
                pass
        if c["src"] and os.path.exists(c["src"]):
            try:
                os.remove(c["src"])
            except Exception:
                pass


@app.delete("/api/clips/{cid}")
def delete_clip(cid: int):
    _clip(cid)
    _delete_clip_files(cid)
    db.ex("delete from jobs where type='render' and ref_id=?", (cid,))
    db.ex("delete from clips where id=?", (cid,))
    return {"ok": True}


@app.get("/api/clips/{cid}")
def clip(cid: int):
    return _clip_out(_clip(cid))


def _clean_sfx(val):
    if not isinstance(val, list) or len(val) > 30:
        raise HTTPException(400, "Up to 30 sound effects per clip.")
    out = []
    for e in val:
        try:
            f, t, v = str(e["f"]), float(e["t"]), float(e.get("v", 0.6))
        except (KeyError, TypeError, ValueError):
            raise HTTPException(400, "Each sound effect needs a file and a time.")
        if not audiolib.resolve("sfx", f):
            raise HTTPException(400, f"'{f}' isn't in the audio library.")
        out.append({"f": f, "t": round(max(t, 0), 3), "v": round(min(max(v, 0), 1.5), 2)})
    return sorted(out, key=lambda e: e["t"])


@app.post("/api/clips/{cid}/sfx/auto")
def auto_sfx(cid: int):
    c = _clip(cid)
    db.ex("update clips set sfx=?, render_status=case when render_status='done' then 'stale' else render_status end "
          "where id=?", (db.dumps(engine.auto_sfx(c)), cid))
    return _clip_out(_clip(cid))


@app.post("/api/clips/{cid}/ask")
def ask_edit(cid: int, body: dict = Body(...)):
    """Change a clip in plain words ('end 2 s earlier', 'split layout'). Uses the AI editor when a key is set,
    simple built-in rules otherwise. Returns the clip and what changed."""
    c = _clip(cid)
    ask = str(body.get("text") or "").strip()
    if not ask:
        raise HTTPException(400, "Say what to change, like 'end 2 s earlier'.")
    state = {k: c[k] for k in ai.EDIT_KEYS if k in c}
    patch, key = ai.rule_edit(ask, state), engine.ai_key()
    if key and not patch:
        words = [w for w in json.loads(c["words"] or "[]") if c["start"] - 15 <= w["start"] <= c["end"] + 15]
        try:
            patch = ai.plan_edit(key, ask, state, words, list(TEMPLATES))
        except Exception as e:
            raise HTTPException(502, f"The AI editor didn't answer ({str(e)[:120]}).")
    if not patch:
        raise HTTPException(400, "I didn't understand that. Try 'end 2 s earlier', 'start 3 s later', 'title: ...', "
                                 "'split layout', 'no captions' or '4k'." + ("" if key else " Add an AI key in Settings "
                                                                              "for any other request."))
    return {"changed": patch, "clip": patch_clip(cid, patch)}


@app.patch("/api/clips/{cid}")
def patch_clip(cid: int, body: dict = Body(...)):
    c = _clip(cid)
    v = _video(c["video_id"])
    sets, vals = [], []
    for k, val in body.items():
        if k in ("start", "end"):
            continue
        if k not in CLIP_FIELDS:
            raise HTTPException(400, f"Can't change '{k}'.")
        if k == "template" and val not in TEMPLATES:
            raise HTTPException(400, "Unknown caption style.")
        if k == "aspect_ratio" and val not in ("9:16", "1:1", "16:9"):
            raise HTTPException(400, "Aspect ratio must be 9:16, 1:1, or 16:9.")
        if k == "layout":
            if val == "dual":
                val = "stack"
            if val not in ("pip", "stack", "follow", "crop", "blur"):
                raise HTTPException(400, "Framing must be pip, stack (dual), follow, crop or blur.")
        if k == "res" and int(val) not in RES:
            raise HTTPException(400, "Resolution must be 1080, 1440 (2K) or 2160 (4K).")
        if k == "status" and val not in ("candidate", "approved", "rejected"):
            raise HTTPException(400, "Unknown status.")
        if k in ("music", "sfx_intro", "sfx_peak") and val not in ("", "random") and not audiolib.resolve(
                "music" if k == "music" else "sfx", val):
            raise HTTPException(400, f"'{val}' isn't in the audio library.")
        if k == "sfx":
            val = db.dumps(_clean_sfx(val))
        if k == "views":
            try:
                val = None if val in (None, "") else max(0, int(val))
            except (TypeError, ValueError):
                raise HTTPException(400, "Views must be a number.")
        if k == "lang" and val and val not in ai.LANGS:
            raise HTTPException(400, "Unknown language.")
        if k == "vo":
            val = str(val or "").strip()[:300]
        if k == "caption_size":
            try:
                val = max(0.4, min(3.0, float(val)))
            except (TypeError, ValueError):
                val = 1.0
        if k == "caption_font":
            val = str(val or "Arial").strip()[:50]
        sets.append(f"{k}=?")
        if k in ("res", "captions", "hook_zoom", "emojis", "censor"):
            vals.append(int(val))
        elif k == "views":
            vals.append(val)
        elif k in ("crop_x", "cam_zoom", "cam_pos_x", "cam_pos_y", "split_ratio", "cam_crop_x", "cam_crop_y", "banner_size", "banner_x", "banner_y", "game_zoom", "crop_y", "caption_size"):
            vals.append(float(val))
        else:
            vals.append(str(val) if val is not None else "")
    if "cam_corner" in body or "layout" in body:
        sets.append("cam=null")
    if "start" in body or "end" in body:
        v_dur = float(v.get("duration") or 86400.0)
        s, e = float(body.get("start", c["start"])), float(body.get("end", c["end"]))
        if e - s < 1.0 or s < 0 or e > v_dur + 5.0:
            raise HTTPException(400, f"Clip must be between 1s and {v_dur:.1f}s.")
        sets += ["start=?", "end=?"]
        vals += [round(s, 3), round(e, 3)]
    if sets:
        if any(not x.startswith(("status", "title", "views")) for x in sets) and c["render_status"] == "done":
            sets.append("render_status='stale'")
        db.ex(f"update clips set {','.join(sets)} where id=?", vals + [cid])
    return _clip_out(_clip(cid))


@app.get("/api/clips/{cid}/source")
def clip_source_video(cid: int):
    c = _clip(cid)
    p = c["src"] if (c.get("src") and os.path.exists(c["src"])) else None
    if not p:
        p = engine.clip_source(c, _video(c["video_id"]))
    if not p or not os.path.exists(p):
        raise HTTPException(404, "No video file.")
    return FileResponse(p, media_type="video/mp4" if p.endswith(".mp4") else "video/webm")


@app.get("/api/clips/{cid}/video")
def clip_video(cid: int):
    c = _clip(cid)
    p = c["render_path"] if (c["render_status"] == "done" and c["render_path"] and os.path.exists(c["render_path"])) else None
    if not p and c["render_path"]:
        cand = os.path.join(db.DATA, "exports", os.path.basename(c["render_path"]))
        if os.path.exists(cand):
            p = cand
    if not p:
        p = c["src"] if (c.get("src") and os.path.exists(c["src"])) else None
    if not p:
        p = engine.clip_source(c, _video(c["video_id"]))
    if not p or not os.path.exists(p):
        raise HTTPException(404, "No video file.")
    return FileResponse(p, media_type="video/mp4" if p.endswith(".mp4") else "video/webm")


def _format_cues(cues):
    out = []
    for q in cues:
        ws = q.get("words") or []
        first = ws[0].get("i", 0) if ws else 0
        last = ws[-1].get("i", 0) if ws else 0
        text = q.get("text") or " ".join(w.get("w", "") for w in ws)
        out.append({
            "first": first,
            "last": last,
            "start": round(float(q.get("start", 0.0)), 3),
            "end": round(float(q.get("end", 0.0)), 3),
            "text": text,
            "words": [{"w": w.get("w", ""), "start": round(float(w.get("start", 0.0)), 3), "end": round(float(w.get("end", 0.0)), 3)} for w in ws]
        })
    return out


@app.get("/api/clips/{cid}/cues")
def get_cues(cid: int):
    c = _clip(cid)
    return _format_cues(engine.clip_cues(c))


@app.patch("/api/clips/{cid}/cue")
def update_cue(cid: int, body: dict = Body(...)):
    c = _clip(cid)
    new_words = engine.edit_cue(c, int(body["first"]), int(body["last"]), str(body["text"]))
    db.ex("update clips set words=?, render_status=case when render_status='done' then 'stale' else render_status end where id=?",
          (db.dumps(new_words), cid))
    return _format_cues(engine.clip_cues(_clip(cid)))


@app.get("/api/clips/{cid}/subtitles")
def clip_subtitles(cid: int, format: str = "srt"):
    c = _clip(cid)
    cues = engine.clip_cues(c)
    if not cues:
        raise HTTPException(404, "No subtitles available for this clip.")
    srt_data = captions.to_srt(cues)
    filename = re.sub(r"[^\w\-.]+", "_", c["title"] or f"clip_{cid}").strip("_") + ".srt"
    return Response(content=srt_data, media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _thumb(src, t, out):
    """One small JPEG frame at t seconds, made once and kept."""
    if not os.path.exists(out):
        if not src or not os.path.exists(src):
            raise HTTPException(404, "No picture yet.")
        subprocess.run([which("ffmpeg"), "-nostdin", "-v", "error", "-y", "-ss", f"{max(t, 0):.2f}", "-i", src, "-frames:v", "1",
                        "-vf", "scale=320:-2", "-q:v", "5", out], capture_output=True, timeout=60, **silent_flags())
        if not os.path.exists(out):
            raise HTTPException(404, "No picture yet.")
    return FileResponse(out, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


@app.get("/api/videos/{vid}/thumb")
def video_thumb(vid: int):
    v = _video(vid)
    return _thumb(v["path"], (v["duration"] or 0) * 0.2, os.path.join(engine.wdir(vid), "thumb.jpg"))


@app.get("/api/clips/{cid}/thumb")
def clip_thumb(cid: int):
    c = _clip(cid)
    t = (c["start"] + c["end"]) / 2
    return _thumb(engine.clip_source(c, _video(c["video_id"])), t,
                  os.path.join(engine.wdir(c["video_id"]), f"thumb_{cid}_{t:.1f}.jpg"))


@app.get("/api/clips/{cid}/framing")
def clip_framing(cid: int):
    c = _clip(cid)
    v = _video(c["video_id"])
    return engine.framing(c, v)


@app.get("/api/clips/{cid}/words")
def clip_words_endpoint(cid: int):
    return engine.clip_words(_clip(cid))


@app.put("/api/clips/{cid}/words")
def save_words_endpoint(cid: int, body: list = Body(...)):
    engine.save_words(cid, body)
    return {"ok": True}


RULES = ("allowed", "tips", "no", "unknown")


@app.put("/api/rules")
def set_rule(body: dict = Body(...)):
    """What a streamer says about clipping their streams: allowed, tips (allowed with conditions), no, unknown."""
    key, status, note = str(body.get("key") or "").strip().lower(), body.get("status"), str(body.get("note") or "")[:1000]
    if not key or status not in RULES:
        raise HTTPException(400, "Pick one of: allowed, tips, no, unknown.")
    db.ex("insert into rules(key,status,note) values(?,?,?) on conflict(key) do update set status=excluded.status, "
          "note=excluded.note", (key, status, note))
    return {"key": key, "status": status, "note": note}


@app.post("/api/clips/{cid}/approve")
def approve_clip(cid: int, body: Optional[dict] = Body(None)):
    c = _clip(cid)
    s = _video(c["video_id"]).get("streamer")
    if s and s["status"] == "no" and not (body or {}).get("permission"):
        raise HTTPException(409, f"{s['name']} doesn't allow clipping. Only go on if you have their permission.")
    db.ex("update clips set status='approved' where id=?", (cid,))
    is_rendered = bool(c["render_path"] and os.path.exists(c["render_path"]))
    needs_render = not is_rendered
    if needs_render and c["render_status"] != "running":
        worker.enqueue("render", cid)
    c_updated = _clip_out(_clip(cid))
    return {"ok": True, "needs_render": needs_render, "clip": c_updated}


@app.post("/api/clips/{cid}/render")
def trigger_render(cid: int):
    _clip(cid)
    db.ex("update clips set render_status='queued', render_progress=0 where id=?", (cid,))
    worker.enqueue("render", cid)
    return {"ok": True}


@app.get("/api/clips/{cid}/download")
def download_clip(cid: int):
    c = _clip(cid)
    p = c["render_path"]
    if not p or not os.path.exists(p):
        raise HTTPException(404, "Clip hasn't been rendered yet.")
    db.ex("update clips set downloaded=1 where id=?", (cid,))
    name = re.sub(r"[^\w\-.]+", "_", c["title"] or f"clip_{cid}").strip("_") + ".mp4"
    return FileResponse(p, filename=name, media_type="video/mp4")


@app.get("/api/clips/{cid}/post")
def post_text(cid: int):
    c = _clip(cid)
    return {"text": engine.post_text(c, _video(c["video_id"]))}


@app.get("/api/clips/{cid}/cover")
def cover(cid: int):
    """A full-size picture of the finished clip at its big moment, for the video's cover."""
    c = _clip(cid)
    if not (c["render_path"] and os.path.exists(c["render_path"])):
        raise HTTPException(404, "Make the clip first, then the cover comes from it.")
    t = min(max(c["peak"] - c["start"], 0.5), c["end"] - c["start"] - 0.2) if c["peak"] else 1.0
    out = os.path.splitext(c["render_path"])[0] + f"_cover_{t:.1f}.jpg"
    if not os.path.exists(out) or os.path.getmtime(out) < os.path.getmtime(c["render_path"]):
        subprocess.run([which("ffmpeg"), "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", c["render_path"], "-frames:v", "1",
                        "-q:v", "2", out], capture_output=True, timeout=60)
    if not os.path.exists(out):
        raise HTTPException(500, "Couldn't make the cover picture.")
    _slug = lambda s: re.sub(r"[^\w\-.]+", "_", s or "").strip("_")
    return FileResponse(out, media_type="image/jpeg", filename=f"ClipForge_{_slug(c['title'])}_cover.jpg")


# ---------------- live ----------------
@app.get("/api/live/channels")
def live_channels():
    return live.list_channels()


@app.post("/api/live/channels")
def add_live_channel(body: dict = Body(...)):
    url = body.get("url")
    if not url:
        raise HTTPException(400, "Provide a channel or stream URL.")
    return live.add_channel(url)


@app.delete("/api/live/channels/{cid}")
def delete_live_channel(cid: int):
    live.delete_channel(cid)
    return {"ok": True}


@app.post("/api/live/channels/{cid}/toggle")
def toggle_live_channel(cid: int):
    return live.toggle_channel(cid)


@app.post("/api/live/start")
def live_start(body: dict = Body(...)):
    url = body.get("url")
    if not url:
        raise HTTPException(400, "Provide a live stream URL.")
    try:
        vid = live.start_session(url, client_id=body.get("client_id"), auto_clip=bool(body.get("auto_clip", True)),
                                 whisper_model=body.get("whisper_model", "base"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": vid}


@app.get("/api/live/{vid}/status")
def live_status(vid: int):
    s = live.session(vid)
    if not s:
        raise HTTPException(404, "Live session isn't running.")
    return s.stats()


@app.post("/api/live/{vid}/clip")
def live_manual_clip(vid: int):
    s = live.session(vid)
    if not s:
        raise HTTPException(404, "Live session isn't running.")
    s.clip_now()
    return {"ok": True}


@app.post("/api/live/{vid}/stop")
def live_stop(vid: int):
    s = live.session(vid)
    if not s:
        raise HTTPException(404, "Live session isn't running.")
    s.stop()
    return {"ok": True}


# ---------------- clients ----------------
@app.get("/api/clients")
def list_clients():
    return db.q("select * from clients order by name")


@app.post("/api/clients")
def create_client(body: dict = Body(...)):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Name is required.")
    cid = db.ex("insert into clients(name,template,music,created) values(?,?,?,?)",
                (name, body.get("template", "yellow_pop"), body.get("music", ""), db.now()))
    return db.q("select * from clients where id=?", (cid,), one=True)


@app.patch("/api/clients/{cid}")
def patch_client(cid: int, body: dict = Body(...)):
    sets, vals = [], []
    for k in ("name", "template", "music"):
        if k in body:
            sets.append(f"{k}=?")
            vals.append(body[k])
    if sets:
        db.ex(f"update clients set {','.join(sets)} where id=?", vals + [cid])
    return db.q("select * from clients where id=?", (cid,), one=True)


@app.delete("/api/clients/{cid}")
def delete_client(cid: int):
    db.ex("delete from clients where id=?", (cid,))
    return {"ok": True}


# ---------------- meta & templates ----------------
@app.get("/api/templates")
def templates():
    return TEMPLATES


@app.get("/api/audio/sfx/{name}")
def sfx_file(name: str):
    p = audiolib.resolve("sfx", name)
    if not p:
        raise HTTPException(404, "No such sound effect.")
    return FileResponse(p)


@app.get("/api/audio")
def audio():
    return {"music": audiolib.list_files("music"), "sfx": audiolib.list_files("sfx")}


@app.get("/api/settings")
def get_settings():
    cf = source.find_cookie_file()
    cleanup_h = int(db.setting("cleanup_hours", "48") or 48)
    env = bool(os.environ.get("ANTHROPIC_API_KEY"))
    return {
        "anthropic_key": env or bool(db.setting("anthropic_key")),
        "has_password": bool(_pw()),
        "anthropic_valid": (ai.valid_key(os.environ["ANTHROPIC_API_KEY"]) if env
                            else (ai.valid_key(db.setting("anthropic_key")) if db.setting("anthropic_key") else False)),
        "cookies_browser": db.setting("cookies_browser", ""),
        "has_cookies": bool(cf),
        "cookies_file": os.path.basename(cf) if cf else "",
        "cookies_path": cf or "",
        "cleanup_hours": cleanup_h,
        "my_channel": db.setting("my_channel", ""),
        "voice": voice.available(),
        "langs": ai.LANGS,
    }


@app.post("/api/settings")
def update_settings(body: dict = Body(...)):
    if "anthropic_key" in body:
        db.set_setting("anthropic_key", (body["anthropic_key"] or "").strip())
    if "password" in body:
        db.set_setting("password", (body["password"] or "").strip())
    if "cookies_browser" in body:
        db.set_setting("cookies_browser", (body["cookies_browser"] or "").strip())
    if "my_channel" in body:
        db.set_setting("my_channel", (body["my_channel"] or "").strip())
    if "cleanup_hours" in body:
        try:
            db.set_setting("cleanup_hours", str(int(body["cleanup_hours"])))
        except (ValueError, TypeError):
            pass
    return get_settings()


@app.get("/api/learn")
def learn_state():
    n = db.q("select count(*) n from clips where views is not null", one=True)["n"]
    w = engine.learned()
    return {"with_views": n, "need": engine.MIN_RESULTS,
            "top": [engine.FEATS[k] for k in sorted(w, key=lambda k: -w[k])]}


@app.post("/api/learn/fetch")
def learn_fetch(body: dict = Body(...)):
    """Read your channel's Shorts views and give them to the clips with the same title."""
    ch = str(body.get("channel") or "").strip()
    try:
        posts = source.my_posts(ch)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, str(e)[:300])
    db.set_setting("my_channel", ch)
    return dict(learn_state(), posts=len(posts), matched=engine.match_views(posts))



@app.get("/api/settings/storage")
def storage_stats():
    return storage.get_storage_stats()


@app.post("/api/settings/cleanup")
def cleanup_temp_storage(body: dict = Body(default={})):
    older = body.get("older_than_hours")
    clean_all = bool(body.get("clean_all_temp"))
    return storage.clean_storage(older_than_hours=older, clean_all_temp=clean_all)


@app.post("/api/settings/cookies/upload")
async def upload_cookies(file: UploadFile = File(...)):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target = os.path.join(root, "cookies.txt")
    with open(target, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)
    for dest in [
        os.path.join(db.DATA, "cookies.txt"),
        os.path.join(os.getcwd(), "cookies.txt"),
        r"c:\attiq\clipping software\clipforge\cookies.txt",
        r"c:\attiq\clipping software\clipforge\dist\ClipForge\cookies.txt",
    ]:
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy(target, dest)
        except Exception:
            pass
    return {"ok": True, "message": "cookies.txt saved successfully!"}


@app.delete("/api/settings/cookies")
def delete_cookies():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for p in [
        os.path.join(root, "cookies.txt"),
        os.path.join(db.DATA, "cookies.txt"),
        "cookies.txt",
        r"c:\attiq\clipping software\clipforge\cookies.txt",
        r"c:\attiq\clipping software\clipforge\dist\ClipForge\cookies.txt",
    ]:
        if os.path.isfile(p):
            try:
                os.remove(p)
            except Exception:
                pass
    return {"ok": True}


# ---------------- frontend ----------------
@app.get("/")
def index():
    p = os.path.join(STATIC, "index.html")
    if not os.path.exists(p):
        return HTMLResponse("<h1>ClipForge</h1><p>Frontend static files missing.</p>")
    with open(p, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/static/{file_path:path}")
def static_file(file_path: str):
    p = os.path.join(STATIC, file_path)
    if not os.path.exists(p):
        raise HTTPException(404, "Static file not found.")
    return FileResponse(p)
