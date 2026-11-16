"""Download videos, clips and chats from YouTube, Twitch and other web video platforms."""
import json, os, re, shutil, subprocess

from .util import which

_PCT = re.compile(r"\[download\]\s+([\d.]+)%")


def _fmt(h):
    return f"bv*[vcodec^=avc1][height<={h}]+ba[ext=m4a]/bv*[height<={h}]+ba/b[height<={h}]/b"


def find_cookie_file(cookies_spec=None):
    """Find any available valid cookies.txt file across standard locations."""
    import sys
    if cookies_spec and os.path.isfile(cookies_spec) and os.path.getsize(cookies_spec) > 10:
        return os.path.abspath(cookies_spec)
    candidates = []
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(exe_dir, "cookies.txt"))
        candidates.append(os.path.join(exe_dir, "..", "cookies.txt"))
        candidates.append(os.path.join(exe_dir, "..", "..", "cookies.txt"))

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates.append(os.path.join(root, "cookies.txt"))
    candidates.append(os.path.join(root, "..", "cookies.txt"))

    data_dir = os.environ.get("CLIPFORGE_DATA") or os.path.join(root, "data")
    candidates.append(os.path.join(data_dir, "cookies.txt"))
    candidates.append(os.path.join(os.getcwd(), "cookies.txt"))
    candidates.append(os.path.abspath("cookies.txt"))
    candidates.append(r"c:\attiq\clipping software\clipforge\cookies.txt")
    candidates.append(r"c:\attiq\clipping software\clipforge\dist\ClipForge\cookies.txt")

    for c in candidates:
        if c and os.path.isfile(c) and os.path.getsize(c) > 10:
            return os.path.abspath(c)
    return None


def _cookie_args(cookies_spec=None):
    """Resolve cookie file or browser arguments for yt-dlp."""
    cf = find_cookie_file(cookies_spec)
    if cf:
        return ["--cookies", cf]

    if cookies_spec and cookies_spec.lower() in ("chrome", "edge", "firefox", "brave", "opera", "vivaldi", "safari"):
        return ["--cookies-from-browser", cookies_spec.lower()]

    return []


def _js_args():
    """Enable JavaScript challenge runtime if node is installed."""
    if shutil.which("node") or os.path.isfile(r"C:\Program Files\nodejs\node.exe"):
        return ["--js-runtimes", "node", "--remote-components", "ejs:github"]
    return []


def _auth_args(cookies_spec=None):
    return _cookie_args(cookies_spec) + _js_args()


def download(job, url, outdir, max_height=1080, cookies_browser=None, on_progress=None):
    os.makedirs(outdir, exist_ok=True)
    ytdlp = which("yt-dlp")
    extra = _auth_args(cookies_browser)
    r = subprocess.run([ytdlp, "--get-id", "--no-playlist"] + extra + [url], capture_output=True, text=True)
    err = (r.stderr or "").lower()
    if r.returncode != 0 and ("confirm your age" in err or "age-restricted" in err):
        raise RuntimeError("This video is Age-Restricted (18+) by YouTube. Please upload your fresh cookies.txt in Settings or use a regular video.")
    vid = (r.stdout.strip().splitlines() or ["video"])[0]
    base = os.path.join(outdir, f"source_{vid}_{max_height}")
    if not os.path.exists(base + ".mp4"):
        fmt = _fmt(max_height)
        job.log(f"Downloading up to {max_height}p...")
        state = {"parts": 0}

        def line(s):
            m = _PCT.search(s)
            if m and on_progress:
                pct = float(m.group(1))
                on_progress((state["parts"] + pct / 100) / 2)
            if "[download] 100%" in s:
                state["parts"] += 1

        cmd = [ytdlp, "-f", fmt, "--merge-output-format", "mp4", "--write-info-json", "--no-playlist",
               "-o", base + ".%(ext)s"] + extra + [url]
        job.run_lines(cmd, line)
    info = None
    if os.path.exists(base + ".info.json"):
        with open(base + ".info.json", encoding="utf-8") as f:
            info = json.load(f)
    return base + ".mp4", info


def download_section(job, url, out, start, end, max_height=1080, cookies_browser=None):
    """Only start..end seconds of a link at full quality. The cut is exact, so the file starts at `start`."""
    if not os.path.exists(out):
        extra = _auth_args(cookies_browser)
        job.run([which("yt-dlp"), "-f", _fmt(max_height), "--merge-output-format", "mp4", "--no-playlist",
                 "--download-sections", f"*{start:.2f}-{end:.2f}", "--force-keyframes-at-cuts",
                 "-o", out] + extra + [url])
    return out


def youtube_chat(url, base, cookies_browser=None):
    """Download a YouTube stream's chat replay (if it has one) and return [(seconds, message)]. Never raises."""
    path = base + ".live_chat.json"
    if not os.path.exists(path):
        extra = _auth_args(cookies_browser)
        try:
            subprocess.run([which("yt-dlp"), "--skip-download", "--write-subs", "--sub-langs", "live_chat",
                            "--no-playlist", "-o", base + ".%(ext)s"] + extra + [url],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3600)
        except Exception:
            return []
    if not os.path.exists(path):
        return []
    return parse_live_chat(path)


def parse_live_chat(path):
    out = []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            try:
                d = json.loads(line)["replayChatItemAction"]
                t = int(d["videoOffsetTimeMsec"]) / 1000
                for a in d["actions"]:
                    r = a.get("addChatItemAction", {}).get("item", {}).get("liveChatTextMessageRenderer")
                    if r:
                        out.append((t, "".join(x.get("text", "") for x in r.get("message", {}).get("runs", []))))
            except (KeyError, ValueError, TypeError):
                continue
    return out


def live_chat_line(line):
    """One line of a live_chat.json being written during a stream -> [(unix time, message)]."""
    try:
        acts = json.loads(line)["replayChatItemAction"]["actions"]
    except (KeyError, ValueError, TypeError):
        return []
    out = []
    for a in acts:
        r = a.get("addChatItemAction", {}).get("item", {}).get("liveChatTextMessageRenderer")
        if r and r.get("timestampUsec"):
            out.append((int(r["timestampUsec"]) / 1e6, "".join(x.get("text", "") for x in r.get("message", {}).get("runs", []))))
    return out
