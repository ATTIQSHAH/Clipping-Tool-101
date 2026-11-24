"""Big on-screen game banners: WASTED, BUSTED, MISSION PASSED... read with OCR from the middle of the screen every few
seconds. Optional: needs rapidocr-onnxruntime
(pip install -r requirements-vision.txt); without it this finds nothing and analysis goes on as before."""
import difflib, re, subprocess
import numpy as np

# label -> phrases. Fuzzy matched, so OCR slips ("BUSTEO") still count.
WORDS = {"WASTED": ["WASTED"], "BUSTED": ["BUSTED"], "MISSION PASSED": ["MISSION PASSED", "MISSION COMPLETE"],
         "MISSION FAILED": ["MISSION FAILED"], "HEIST PASSED": ["HEIST PASSED", "HEIST COMPLETE"],
         "HEIST FAILED": ["HEIST FAILED"], "GAME OVER": ["GAME OVER"], "YOU DIED": ["YOU DIED"]}
W, H = 480, 270
_ocr = None


def available():
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


def match(txt):
    t = re.sub(r"[^A-Z ]", "", (txt or "").upper()).strip()
    if len(t) < 4:
        return None
    tk = t.split()
    for lab, phrases in WORDS.items():
        for p in phrases:
            n = len(p.split())
            cands = [t] + [" ".join(tk[i:i + n]) for i in range(max(1, len(tk) - n + 1))]
            if any(difflib.SequenceMatcher(None, c, p).ratio() >= 0.8 for c in cands):
                return lab
    return None


def read(rgb):
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR(det_limit_type="max")  # default upscales the small crop to 736 px: 50x slower
    crop = np.ascontiguousarray(rgb[int(H * .2):int(H * .8), int(W * .08):int(W * .92), ::-1])  # BGR for OCR
    res, _ = _ocr(crop, use_cls=False)
    return [match(txt) for _, txt, sc in (res or []) if float(sc) > 0.6]


def banners(ffmpeg, src, every=3, check=lambda: None):
    """[(seconds, label)] for every banner found. Reads the screen every `every` seconds (GTA banners stay up 4-5 s),
    keyframes only at 480x270, streamed (flat memory)."""
    if not available():
        return []
    p = subprocess.Popen([ffmpeg, "-v", "error", "-skip_frame", "nokey", "-i", src, "-an", "-vf",
                          f"fps=1/{every},scale={W}:{H}", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    out, t = [], 0.0
    try:
        while True:
            buf = p.stdout.read(W * H * 3)
            if len(buf) < W * H * 3:
                break
            check()
            for lab in read(np.frombuffer(buf, np.uint8).reshape(H, W, 3)):
                if lab and not any(lab == l and t - s < 10 for s, l in out):
                    out.append((t, lab))
            t += every
    finally:
        p.kill()
        p.wait()
    return out


def banner_score(events, n_frames, frame):
    """0-1 per analysis frame: high from 3 s before a banner to 6 s after it (the reaction comes after)."""
    if not events:
        return None
    s = np.zeros(n_frames)
    for t, _ in events:
        s[max(0, int((t - 3) / frame)):max(0, int((t + 6) / frame))] = 1.0
    return s
