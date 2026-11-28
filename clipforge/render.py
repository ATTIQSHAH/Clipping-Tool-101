"""Frame-accurate cut + 9:16 (1080p / 1440p / 4K) + burned-in captions + music/SFX mix."""
import os

ENC = {
    "libx264": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19"],
    "h264_qsv": ["-c:v", "h264_qsv", "-global_quality", "22"],   # Intel Quick Sync - test on your PC
    "h264_nvenc": ["-c:v", "h264_nvenc", "-cq", "22"],           # NVIDIA - only if your GPU supports it
}
RES = {1080: (1080, 1920), 1440: (1440, 2560), 2160: (2160, 3840)}


def _audio_graph(music, music_vol, duck, sfx, first_input, vo=None):
    """vo: (wav, at, length) voice-over; the clip's own sound dips to 30% while it talks."""
    voice = "[0:a]loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000"
    if vo:
        voice += f",volume=0.3:enable='between(t,{vo[1]:.2f},{vo[1] + vo[2] + 0.15:.2f})'"
    if not music and not sfx and not vo:
        return voice + "[aout]", []
    inputs, parts, mix, n = [], [], ["[voice]"], first_input
    parts.append(voice + (",asplit=2[voice][sc]" if (music and duck) else "[voice]"))
    if music:
        inputs += ["-stream_loop", "-1", "-i", music]
        parts.append(f"[{n}:a]aresample=48000,volume={music_vol}[mus]")
        if duck:
            parts.append("[mus][sc]sidechaincompress=threshold=0.03:ratio=10:attack=15:release=350[md]")
            mix.append("[md]")
        else:
            mix.append("[mus]")
        n += 1
    for k, (path, at, vol) in enumerate(sfx):
        ms = int(max(at, 0) * 1000)
        inputs += ["-i", path]
        parts.append(f"[{n}:a]aresample=48000,adelay={ms}|{ms},volume={vol}[s{k}]")
        mix.append(f"[s{k}]")
        n += 1
    if vo:
        ms = int(max(vo[1], 0) * 1000)
        inputs += ["-i", vo[0]]
        parts.append(f"[{n}:a]loudnorm=I=-14:TP=-1.5,aresample=48000,adelay={ms}|{ms}[vo]")
        mix.append("[vo]")
        n += 1
    parts.append("".join(mix) + f"amix=inputs={len(mix)}:duration=first:dropout_transition=0:normalize=0,"
                 "alimiter=limit=0.95[aout]")
    return ";".join(parts), inputs


def _game_crop(w, h, ratio, game_zoom, crop_x, crop_y):
    """Crop (cw, ch, x, y) of the source that fills a frame of this width/height ratio, zoomed and panned."""
    gz = max(0.4, min(float(game_zoom or 1.0), 3.0))
    if w / h > ratio:
        ch = max(32, min(h, int(h / gz))) // 2 * 2
        cw = max(32, min(w, int(ch * ratio))) // 2 * 2
    else:
        cw = max(32, min(w, int(w / gz))) // 2 * 2
        ch = max(32, min(h, int(cw / ratio))) // 2 * 2
    px = max(0.0, min(1.0, float(crop_x if crop_x is not None else 0.5)))
    py = max(0.0, min(1.0, float(crop_y if crop_y is not None else 0.5)))
    return cw, ch, int(min(max((w - cw) * px, 0), w - cw)) // 2 * 2, int(min(max((h - ch) * py, 0), h - ch)) // 2 * 2


CORNER_BOX = {"tl": (0, 0, .35, .50), "tr": (.65, 0, .35, .50), "bl": (0, .45, .35, .55), "br": (.65, .45, .35, .55),
              "tc": (.325, 0, .35, .50), "bc": (.325, .45, .35, .55)}


def render_clip(job, ffmpeg, src, info, start, end, ass_path, out_path, layout="follow", crop_x=0.5,
                encoder="libx264", fps=30, res=1080, music=None, music_vol=0.18, duck=True, sfx=(),
                track=None, hook_zoom=True, on_progress=None,
                cam_zoom=1.0, cam_size=1.0, cam_shape="rect", cam_pos="top", cam_pos_x=0.5, cam_pos_y=0.65, split_ratio=0.5,
                cam_crop_x=0.5, cam_crop_y=0.5, cam_corner="tr", aspect_ratio="9:16",
                game_zoom=1.0, crop_y=0.5, vo=None):
    base = int(res or 1080)
    aspect = str(aspect_ratio or "9:16").strip()
    if aspect == "1:1":
        W, H = base, base
    elif aspect == "16:9":
        H = base
        W = int(base * 16 / 9) // 2 * 2
    else:  # "9:16" default
        W = base
        H = int(base * 16 / 9) // 2 * 2

    w, h = info["w"], info["h"]
    s = max(0.0, float(start))
    dur = max(0.5, float(end) - s)
    if dur <= 0:
        raise RuntimeError(f"Clip duration is non-positive ({float(end):.2f} - {s:.2f} = {dur:.2f}s). Check start/end times.")
    tmp = os.path.dirname(os.path.abspath(ass_path))
    ass = os.path.basename(ass_path)  # relative name avoids Windows 'C:' escaping problems
    
    # normalize layout aliases
    if layout in ("dual", "stack"):
        layout = "stack"
    
    # Hook zoom effect: subtle kinetic punch zoom over the first 3.2 seconds
    zoom = f",scale=eval=frame:w='if(lte(t,3.2),{W}*(1.07-0.07*t/3.2),{W})':h='if(lte(t,3.2),{H}*(1.07-0.07*t/3.2),{H})',crop={W}:{H}" if hook_zoom else ""

    cam = (track or {}).get("cam") if layout in ("stack", "pip") else None
    if layout == "pip" and not cam:   # no facecam found: float the streamer's corner of the screen (same as the preview)
        fx, fy, fw, fh = CORNER_BOX.get(cam_corner) or CORNER_BOX["tr"]
        cam = [int(w * fx) // 2 * 2, int(h * fy) // 2 * 2, int(w * fw) // 2 * 2, int(h * fh) // 2 * 2]
    if cam:
        cx, cy, cw_, ch_ = cam
        cz = max(0.4, min(float(cam_zoom or 1.0), 3.0))
        zw = max(16, min(w, int(cw_ / cz))) // 2 * 2
        zh = max(16, min(h, int(ch_ / cz))) // 2 * 2
        mid_x = cx + cw_ // 2
        mid_y = cy + ch_ // 2
        px_c = max(0.0, min(1.0, float(cam_crop_x if cam_crop_x is not None else 0.5)))
        py_c = max(0.0, min(1.0, float(cam_crop_y if cam_crop_y is not None else 0.5)))
        shift_x = max(cw_, zw) * 0.8
        shift_y = max(ch_, zh) * 0.8
        scx = int(min(max(mid_x - zw // 2 + (px_c - 0.5) * 2 * shift_x, 0), w - zw)) // 2 * 2
        scy = int(min(max(mid_y - zh // 2 + (py_c - 0.5) * 2 * shift_y, 0), h - zh)) // 2 * 2
        cam = [scx, scy, zw, zh]

    target_ratio = W / H
    is_pip = layout == "pip"
    if is_pip and cam and w / h > target_ratio + 0.01:
        from .faces import PIP_SIZE, PIP_TOP
        from .faces import PIP_SIZE, PIP_TOP
        cx, cy, cw_, ch_ = cam
        cs = max(0.4, min(float(cam_size if cam_size is not None else 1.0), 2.5))
        base_w = int(min(W, H) * (0.44 if cam_shape == "circle" else (PIP_SIZE if aspect == "9:16" else 0.38)))
        pw = int(base_w * cs) // 2 * 2
        ph = pw if cam_shape == "circle" else int(pw * ch_ / cw_) // 2 * 2
        
        # Position calculation matching preview coordinates
        val_x = max(0.0, min(float(cam_pos_x if cam_pos_x is not None else 0.5), 1.0))
        val_y = max(0.0, min(float(cam_pos_y if cam_pos_y is not None else 0.65), 1.0))
        if cam_pos == "pip_top":
            ox, oy = "(W-w)/2", str(int(H * PIP_TOP))
        elif cam_pos == "pip_bottom":
            ox, oy = "(W-w)/2", str(int(H * 0.58))
        elif cam_pos == "pip_center":
            ox, oy = "(W-w)/2", "(H-h)/2"
        else:
            ox = f"(W-w)*{val_x:.3f}"
            oy = f"(H-h)*{val_y:.3f}"

        # Shape mask (circle / rectangle)
        if cam_shape == "circle":
            dim = min(pw, ph) // 2 * 2
            shape_filter = f",scale={dim}:{dim}:flags=lanczos,format=yuva420p,geq=lum='p(X,Y)':a='if(lte(hypot(X-W/2,Y-H/2),min(W,H)/2-2),255,0)'"
        else:
            shape_filter = f",scale={pw}:{ph}:flags=lanczos"

        # gameplay fills the whole vertical frame (zoom + pan like the other layouts), the cam floats on top
        gw, gh, gx, gy = _game_crop(w, h, target_ratio, game_zoom, crop_x, crop_y)
        fc = (f"[0:v]split[v_game][v_pip];"
              f"[v_game]crop={gw}:{gh}:{gx}:{gy},scale={W}:{H}:flags=lanczos[base];"
              f"[v_pip]crop={cw_}:{ch_}:{cx}:{cy}{shape_filter}[pip];"
              f"[base][pip]overlay={ox}:{oy},setsar=1{zoom},ass={ass}[v]")
    elif layout == "stack" and w / h > target_ratio + 0.01:
        top_share = max(0.25, min(float(split_ratio or 0.5), 0.75))
        th = int(H * top_share) // 2 * 2
        bh = H - th

        # Gameplay crop with game_zoom and crop_x, crop_y
        gz = max(0.4, min(float(game_zoom or 1.0), 3.0))
        bot_aspect = W / bh
        if w / h > bot_aspect:
            gh = max(32, min(h, int(h / gz))) // 2 * 2
            gw = max(32, min(w, int(gh * bot_aspect))) // 2 * 2
        else:
            gw = max(32, min(w, int(w / gz))) // 2 * 2
            gh = max(32, min(h, int(gw / bot_aspect))) // 2 * 2
        px_g = max(0.0, min(1.0, float(crop_x if crop_x is not None else 0.5)))
        py_g = max(0.0, min(1.0, float(crop_y if crop_y is not None else 0.5)))
        gx = int(min(max((w - gw) * px_g, 0), w - gw)) // 2 * 2
        gy = int(min(max((h - gh) * py_g, 0), h - gh)) // 2 * 2

        # Streamer reaction crop with cam_zoom and cam_crop_x, cam_crop_y
        if not cam:
            corner = cam_corner or cam_pos or "bl"
            if corner == "tl":
                cx, cy, cw_, ch_ = 0, 0, int(w * 0.35), int(h * 0.50)
            elif corner == "tr":
                cx, cy, cw_, ch_ = int(w * 0.65), 0, int(w * 0.35), int(h * 0.50)
            elif corner == "br":
                cx, cy, cw_, ch_ = int(w * 0.65), int(h * 0.45), int(w * 0.35), int(h * 0.55)
            elif corner == "tc":
                cx, cy, cw_, ch_ = int(w * 0.325), 0, int(w * 0.35), int(h * 0.50)
            elif corner == "bc":
                cx, cy, cw_, ch_ = int(w * 0.325), int(h * 0.45), int(w * 0.35), int(h * 0.55)
            else:  # "bl" default
                cx, cy, cw_, ch_ = 0, int(h * 0.45), int(w * 0.35), int(h * 0.55)
        else:
            cx, cy, cw_, ch_ = cam

        cz = max(0.4, min(float(cam_zoom or 1.0), 3.0))
        top_aspect = W / th
        if cw_ / ch_ > top_aspect:
            sch = max(32, min(h, int(ch_ / cz))) // 2 * 2
            scw = max(32, min(w, int(sch * top_aspect))) // 2 * 2
        else:
            scw = max(32, min(w, int(cw_ / cz))) // 2 * 2
            sch = max(32, min(h, int(scw / top_aspect))) // 2 * 2

        mid_x = cx + cw_ // 2
        mid_y = cy + ch_ // 2
        px_c = max(0.0, min(1.0, float(cam_crop_x if cam_crop_x is not None else 0.5)))
        py_c = max(0.0, min(1.0, float(cam_crop_y if cam_crop_y is not None else 0.5)))
        shift_x = max(cw_, scw) * 0.8
        shift_y = max(ch_, sch) * 0.8
        scx = int(min(max(mid_x - scw // 2 + (px_c - 0.5) * 2 * shift_x, 0), w - scw)) // 2 * 2
        scy = int(min(max(mid_y - sch // 2 + (py_c - 0.5) * 2 * shift_y, 0), h - sch)) // 2 * 2

        # Enhance upscaled webcam/streamer crop with unsharp filter for crisp facial detail
        cam_filter = f"scale={W}:{th}:flags=lanczos,unsharp=5:5:0.7:5:5:0.0"

        if cam_pos in ("bottom", "bl", "br", "bc"):
            # Streamer on bottom, gameplay on top
            fc = (f"[0:v]split[a][b];[b]crop={gw}:{gh}:{gx}:{gy},scale={W}:{bh}:flags=lanczos[top];"
                  f"[a]crop={scw}:{sch}:{scx}:{scy},{cam_filter}[bot];"
                  f"[top][bot]vstack,setsar=1{zoom},ass={ass}[v]")
        else:
            # Streamer on top (default), gameplay on bottom
            fc = (f"[0:v]split[a][b];[a]crop={scw}:{sch}:{scx}:{scy},{cam_filter}[top];"
                  f"[b]crop={gw}:{gh}:{gx}:{gy},scale={W}:{bh}:flags=lanczos[bot];"
                  f"[top][bot]vstack,setsar=1{zoom},ass={ass}[v]")
    elif layout in ("blur", "stack", "pip") or w / h <= target_ratio + 0.01:
        fc = (f"[0:v]split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
              f"boxblur=25:6[bg];[b]scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos[fg];"
              f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1{zoom},ass={ass}[v]")
    elif layout == "follow" and track and track.get("pts"):
        from .faces import crop_width, write_sendcmd
        cw = min(w, int(h * target_ratio)) // 2 * 2
        cmd_name = os.path.splitext(ass)[0] + ".cmd"
        x0 = write_sendcmd(track["pts"], os.path.join(tmp, cmd_name))
        fc = (f"[0:v]sendcmd=f={cmd_name},crop={cw}:{h}:{x0}:0,scale={W}:{H}:flags=lanczos,setsar=1{zoom},ass={ass}[v]")
    else:
        cw, ch, x, y = _game_crop(w, h, target_ratio, game_zoom, crop_x, crop_y)
        fc = f"[0:v]crop={cw}:{ch}:{x}:{y},scale={W}:{H}:flags=lanczos,setsar=1{zoom},ass={ass}[v]"
    af, extra_in = _audio_graph(music, music_vol, duck, sfx, 1, vo)
    cmd = ([ffmpeg, "-nostdin", "-y", "-ss", f"{s:.3f}", "-t", f"{dur:.3f}", "-i", os.path.abspath(src)] + extra_in +
           ["-filter_complex", fc + ";" + af, "-map", "[v]", "-map", "[aout]"] + ENC[encoder] +
           ["-r", str(fps), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-t", f"{dur:.3f}", "-movflags", "+faststart", os.path.abspath(out_path)])
    if on_progress:
        def line(s):
            if s.startswith("out_time_us=") or s.startswith("out_time_ms="):
                try:
                    on_progress(min(0.99, int(s.split("=")[1]) / 1e6 / dur))
                except ValueError:
                    pass
        job.run_lines(cmd[:1] + ["-progress", "pipe:1", "-nostats"] + cmd[1:], line, cwd=tmp)
    else:
        job.run(cmd, cwd=tmp)
