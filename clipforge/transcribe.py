"""Word-level transcription with faster-whisper. Output schema (relative to the wav start):
{"words": [{"w": "hello", "start": 0.12, "end": 0.40}, ...]}"""
import json
import os
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
            segs, _ = _model.transcribe(audio, word_timestamps=True, vad_filter=True,
                                        language=language, condition_on_previous_text=False)
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


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["words"]
