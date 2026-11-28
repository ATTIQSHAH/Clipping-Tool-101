"""Word-level transcription with faster-whisper. Output schema (relative to the wav start):
{"words": [{"w": "hello", "start": 0.12, "end": 0.40}, ...]}"""
import json
import os
import re
import subprocess
import threading
import wave

import numpy as np

DEVICE = os.environ.get("CLIPFORGE_DEVICE", "")   # "cuda" = NVIDIA GPU, much faster when many streams run
_model = None
_loaded = None                # (model, device, compute) of the loaded model
_lock = threading.Lock()      # the web app and live mode may transcribe at the same time


CHUNK, PAD = 600.0, 5.0      # long audio goes in 10-minute pieces so memory stays flat (a 3 h file whole took ~7 GB)


def _load_wav(path, start=0.0, end=None):
    try:
        with wave.open(path, "rb") as w:
            sr, n = w.getframerate(), w.getnframes()
            a, b = int(start * sr), n if end is None else min(n, int(end * sr))
            w.setpos(min(a, n))
            data = w.readframes(max(b - a, 0))
            if len(data):
                return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    except Exception:
        pass

    from .util import which
    ffmpeg = which("ffmpeg")
    ss_args = ["-ss", f"{start:.3f}"] if start > 0 else []
    t_args = ["-t", f"{(end - start):.3f}"] if end is not None else []
    cmd = [ffmpeg, "-nostdin", "-v", "error"] + ss_args + t_args + ["-i", path, "-ar", "16000", "-ac", "1", "-f", "s16le", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def wav_seconds(path):
    try:
        with wave.open(path, "rb") as w:
            return w.getnframes() / w.getframerate()
    except Exception:
        from .util import which, probe
        try:
            return float(probe(which("ffprobe"), path)["duration"])
        except Exception:
            return 0.0


def transcribe_file(wav, model="base", device="cpu", compute="int8", language=None, on_progress=None,
                    model_size=None, compute_type=None, should_stop=None):
    global _model, _loaded
    if model_size:
        model = model_size
    if compute_type:
        compute = compute_type
    if DEVICE:
        device, compute = DEVICE, ("int8" if DEVICE == "cpu" else "float16")
    with _lock:
        if _model is None or _loaded != (model, device, compute):   # reload when Settings change the accuracy
            from faster_whisper import WhisperModel
            # Cap cpu_threads so Whisper never starves the web server / OS event loop
            cpu_threads = max(1, min(4, (os.cpu_count() or 4) // 2))
            _model = WhisperModel(model, device=device, compute_type=compute, cpu_threads=cpu_threads, num_workers=1)
            _loaded = (model, device, compute)
    total = max(wav_seconds(wav), 0.1)
    words, pos = [], 0.0
    while pos < total:
        off = max(pos - PAD, 0.0)
        audio = _load_wav(wav, off, pos + CHUNK + PAD)
        with _lock:
            # Tuned VAD and transcription for fast-speaking streamers:
            # - lower threshold (0.35) catches quiet/fast speech and speech over game music
            # - speech_pad_ms (400ms) preserves initial and ending consonants without clipping
            # - min_silence_duration_ms (180ms) doesn't merge separate fast clauses
            vad_params = dict(
                threshold=0.35,
                min_speech_duration_ms=100,
                max_speech_duration_s=float('inf'),
                min_silence_duration_ms=180,
                speech_pad_ms=400
            )
            segs, _ = _model.transcribe(
                audio,
                word_timestamps=True,
                vad_filter=True,
                vad_parameters=vad_params,
                beam_size=5,
                best_of=5,
                temperature=[0.0, 0.2, 0.4],
                condition_on_previous_text=False,
                no_speech_threshold=0.4,
                language=language
            )
            for s in segs:
                if should_stop:
                    should_stop()
                if on_progress:
                    on_progress(min(1.0, (off + s.end) / total))
                for w in (s.words or []):
                    t, st = w.word.strip(), off + w.start
                    if t and pos <= st < pos + CHUNK:
                        words.append({"w": t, "start": round(st, 3), "end": round(off + w.end, 3)})
        pos += CHUNK
    return {"words": words}


def parse_subtitles_file(path):
    """Parse YouTube/external subtitle files (.json3, .vtt, .srt) into word-level list:
    [{"w": "hello", "start": 1.23, "end": 1.55}, ...]"""
    if not os.path.exists(path):
        return []
    ext = os.path.splitext(path)[1].lower()

    # 1. YouTube JSON3 format (exact millisecond word segments)
    if ext == ".json3" or path.endswith(".json3"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            words = []
            events = data.get("events") or []
            for ev in events:
                t0 = float(ev.get("tStartMs", 0)) / 1000.0
                dur = float(ev.get("dDurationMs", 0)) / 1000.0
                segs = ev.get("segs") or []
                for i, s in enumerate(segs):
                    txt = s.get("utf8", "").strip()
                    if not txt or txt == "\n":
                        continue
                    offset = float(s.get("tOffsetMs", 0)) / 1000.0
                    st = t0 + offset
                    next_offset = float(segs[i + 1].get("tOffsetMs", 0)) / 1000.0 if i + 1 < len(segs) else dur
                    en = max(st + 0.08, t0 + next_offset)
                    words.append({"w": txt, "start": round(st, 3), "end": round(en, 3)})
            if words:
                return words
        except Exception:
            pass

    # 2. WebVTT format (.vtt)
    if ext == ".vtt" or path.endswith(".vtt"):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            words = []
            blocks = re.split(r"\n\s*\n", content)
            def _sec(h, m, s, ms):
                hrs = int(h.rstrip(":")) if h else 0
                return hrs * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

            for b in blocks:
                m = re.search(r"(?:(\d{1,2}:)?(\d{2}):(\d{2})\.(\d{3}))\s*-->\s*(?:(\d{1,2}:)?(\d{2}):(\d{2})\.(\d{3}))", b)
                if not m:
                    continue
                c_st = _sec(m.group(1), m.group(2), m.group(3), m.group(4))
                c_en = _sec(m.group(5), m.group(6), m.group(7), m.group(8))
                lines = [l for l in b.splitlines() if "-->" not in l and not l.strip().isdigit() and not l.startswith("NOTE")]
                text = " ".join(lines).strip()
                if not text:
                    continue
                
                # Check for inline word tags: <00:00:01.200>word
                word_matches = list(re.finditer(r"(?:<(\d{1,2}:)?(\d{2}):(\d{2})\.(\d{3})>)?([^\s<]+)", text))
                has_inline_tags = any(wm.group(2) for wm in word_matches)
                if has_inline_tags:
                    for i, wm in enumerate(word_matches):
                        w_txt = re.sub(r"<[^>]+>", "", wm.group(5)).strip()
                        if not w_txt:
                            continue
                        if wm.group(2):
                            st = _sec(wm.group(1), wm.group(2), wm.group(3), wm.group(4))
                        else:
                            st = c_st
                        if i + 1 < len(word_matches) and word_matches[i + 1].group(2):
                            nxt = _sec(word_matches[i + 1].group(1), word_matches[i + 1].group(2), word_matches[i + 1].group(3), word_matches[i + 1].group(4))
                            en = max(st + 0.08, nxt)
                        else:
                            en = c_en
                        words.append({"w": w_txt, "start": round(st, 3), "end": round(en, 3)})
                else:
                    # Spread words across cue time
                    clean = [w for w in re.sub(r"<[^>]+>", "", text).split() if w]
                    if clean and c_en > c_st:
                        step = (c_en - c_st) / len(clean)
                        for i, w in enumerate(clean):
                            words.append({"w": w, "start": round(c_st + i * step, 3), "end": round(c_st + (i + 1) * step, 3)})
            if words:
                return words
        except Exception:
            pass

    # 3. SubRip format (.srt)
    if ext == ".srt" or path.endswith(".srt"):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            words = []
            blocks = re.split(r"\n\s*\n", content)
            def _sec_srt(h, m, s, ms):
                return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

            for b in blocks:
                m = re.search(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})", b)
                if not m:
                    continue
                c_st = _sec_srt(m.group(1), m.group(2), m.group(3), m.group(4))
                c_en = _sec_srt(m.group(5), m.group(6), m.group(7), m.group(8))
                lines = [l for l in b.splitlines() if "-->" not in l and not l.strip().isdigit()]
                text = " ".join(lines).strip()
                clean = [w for w in re.sub(r"<[^>]+>", "", text).split() if w]
                if clean and c_en > c_st:
                    step = (c_en - c_st) / len(clean)
                    for i, w in enumerate(clean):
                        words.append({"w": w, "start": round(c_st + i * step, 3), "end": round(c_st + (i + 1) * step, 3)})
            if words:
                return words
        except Exception:
            pass

    return []


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["words"]
