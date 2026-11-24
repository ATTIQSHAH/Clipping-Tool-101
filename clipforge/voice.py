"""Voice-over: reads a line aloud with Piper (offline text-to-speech, runs on the computer).
Optional: pip install --no-deps -r requirements-extras.txt. Each language's voice (60-120 MB) downloads once
from Hugging Face (rhasspy/piper-voices) the first time it is used."""
import os, threading, wave

VOICES = {"en": "en_US-ryan-high", "es": "es_MX-ald-medium", "pt": "pt_BR-faber-medium", "fr": "fr_FR-tom-medium",
          "de": "de_DE-thorsten-medium", "it": "it_IT-paola-medium", "hi": "hi_IN-rohan-medium",
          "ar": "ar_JO-kareem-medium", "ru": "ru_RU-dmitri-medium", "tr": "tr_TR-dfki-medium"}
_lock = threading.Lock()
_loaded = {}


def available():
    try:
        import piper  # noqa: F401
        return True
    except ImportError:
        return False


def say(text, lang, out_wav, voice_dir):
    """Speak text into out_wav. Returns its length in seconds."""
    from piper import PiperVoice
    name = VOICES.get(lang or "en", VOICES["en"])
    model = os.path.join(voice_dir, name + ".onnx")
    with _lock:   # one download/load at a time; Piper itself is fast (2 s of speech in about 0.5 s)
        if model not in _loaded:
            if not (os.path.exists(model) and os.path.exists(model + ".json")):
                from pathlib import Path
                from piper.download_voices import download_voice
                os.makedirs(voice_dir, exist_ok=True)
                download_voice(name, Path(voice_dir))
            try:
                _loaded[model] = PiperVoice.load(model)
            except Exception:
                for p in (model, model + ".json"):   # a broken download: fetch it again next time
                    if os.path.exists(p):
                        os.remove(p)
                raise
        with wave.open(out_wav, "wb") as w:
            _loaded[model].synthesize_wav(text, w)
    with wave.open(out_wav) as w:
        return w.getnframes() / w.getframerate()
