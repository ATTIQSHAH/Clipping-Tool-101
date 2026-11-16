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


def _load_wav(path):
    # If already a valid WAV file, read directly
    try:
        with wave.open(path, "rb") as w:
            data = w.readframes(w.getnframes())
            if len(data):
                return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    except Exception:
        pass

    # Extract 16 kHz mono audio using ffmpeg for mp4, mkv, webm, etc.
    from .util import which
    ffmpeg = which("ffmpeg")
    cmd = [ffmpeg, "-nostdin", "-v", "error", "-i", path, "-ar", "16000", "-ac", "1", "-f", "s16le", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


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
    audio = _load_wav(wav)
    total = max(len(audio) / 16000.0, 0.1)
    words = []
    with _lock:
        segs, _ = _model.transcribe(audio, word_timestamps=True, vad_filter=True,
                                    language=language, condition_on_previous_text=False)
        for s in segs:
            if should_stop:
                should_stop()
            if on_progress:
                on_progress(min(1.0, s.end / total))
            import time; time.sleep(0.002)
            if should_stop:
                should_stop()
            if on_progress:
                on_progress(min(1.0, s.end / total))
            for w in (s.words or []):
                t = w.word.strip()
                if t:
                    words.append({"w": t, "start": round(w.start, 3), "end": round(w.end, 3)})
    return {"words": words}


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["words"]
