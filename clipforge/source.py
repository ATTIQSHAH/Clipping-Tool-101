"""Download videos, clips and chats from YouTube, Twitch and other web video platforms."""
import json, os, re, shutil, subprocess

from .util import which, silent_flags

_PCT = re.compile(r"\[download\]\s+([\d.]+)%")


def _impersonate_args():
    try:
        import curl_cffi
        return ["--impersonate", "chrome"]
    except ImportError:
        return []


def _fmt(h):
    if h <= 480:
        return f"b[height<={h}][ext=mp4]/b[height<={h}]/bv*[height<={h}]+ba/b"
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
    return _cookie_args(cookies_spec) + _js_args() + _impersonate_args()


def download(job, url, outdir, max_height=1080, cookies_browser=None, on_progress=None):
    os.makedirs(outdir, exist_ok=True)
    ytdlp = which("yt-dlp")
    extra = _auth_args(cookies_browser)
    r = subprocess.run([ytdlp, "--get-id", "--no-playlist"] + extra + [url],
                       capture_output=True, text=True, **silent_flags())
    err = (r.stderr or "").lower()
    if r.returncode != 0:
        if "confirm your age" in err or "age-restricted" in err:
            raise RuntimeError("This video is Age-Restricted (18+) by YouTube. Please upload your fresh cookies.txt in Settings or use a regular video.")
        if "not currently live" in err or "offline" in err or "no playable streams" in err:
            raise RuntimeError("The streamer is currently offline. Please wait until they go live or paste a recorded video / VOD link.")
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
               "--concurrent-fragments", "4", "--no-mtime", "--socket-timeout", "15", "--retries", "3",
               "-o", base + ".%(ext)s"] + extra + [url]
        job.run_lines(cmd, line)
    info = None
    if os.path.exists(base + ".info.json"):
        with open(base + ".info.json", encoding="utf-8") as f:
            info = json.load(f)
    return base + ".mp4", info


def download_section(job, url, out, start, end, max_height=1080, cookies_browser=None):
    """Only start..end seconds of a link at full quality. The cut is exact, so the file starts at `start`."""
    if end <= start:
        raise RuntimeError(f"Cannot download section: end ({end:.2f}) must be after start ({start:.2f}).")
    if not os.path.exists(out):
        extra = _auth_args(cookies_browser)
        job.run([which("yt-dlp"), "-f", _fmt(max_height), "--merge-output-format", "mp4", "--no-playlist",
                 "--download-sections", f"*{start:.2f}-{end:.2f}", "--force-keyframes-at-cuts",
                 "--concurrent-fragments", "4", "--no-mtime", "--socket-timeout", "15", "--retries", "3",
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
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3600, **silent_flags())
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
    """One line of a live_chat.json being written during a stream -> [(unix time, message, author)]."""
    try:
        acts = json.loads(line)["replayChatItemAction"]["actions"]
    except (KeyError, ValueError, TypeError):
        return []
    out = []
    for a in acts:
        r = a.get("addChatItemAction", {}).get("item", {}).get("liveChatTextMessageRenderer")
        if r and r.get("timestampUsec"):
            out.append((int(r["timestampUsec"]) / 1e6, "".join(x.get("text", "") for x in r.get("message", {}).get("runs", [])),
                        r.get("authorName", {}).get("simpleText")))
    return out


def past_list_url(channel):
    """A channel link -> the yt-dlp link of its past live streams, newest first. ValueError if it isn't a channel."""
    c = (channel or "").strip()
    m = re.match(r"^(?:https?://)?(?:www\.|m\.)?twitch\.tv/([A-Za-z0-9_]+)", c)
    if m and m.group(1).lower() not in ("videos", "directory"):
        return f"https://www.twitch.tv/{m.group(1)}/videos?filter=archives&sort=time"
    m = re.match(r"^(?:https?://)?(?:www\.|m\.)?youtube\.com/(@[\w.-]+|channel/[\w-]+)", c)
    if m:
        return f"https://www.youtube.com/{m.group(1)}/streams"
    m = re.match(r"^(?:https?://)?(?:www\.)?kick\.com/([A-Za-z0-9_-]+)", c)
    if m:
        return f"https://kick.com/{m.group(1)}/videos"
    raise ValueError("Paste a channel link, like https://www.twitch.tv/summit1g or https://www.youtube.com/@name")


def _flat(url, n, what):
    r = subprocess.run([which("yt-dlp"), "--flat-playlist", "-J", "--playlist-end", str(n), "--no-warnings", url],
                       capture_output=True, text=True, timeout=180)
    try:
        return json.loads(r.stdout).get("entries") or []
    except ValueError:
        err = [ln for ln in r.stderr.splitlines() if ln.startswith("ERROR:")]
        raise RuntimeError((err[-1].split(": ", 2)[-1] if err else f"Couldn't read that channel's {what}.")[:300])


def past_streams(channel, n=5):
    """The channel's last n past streams: [{url, title, duration}]."""
    return [{"url": e.get("url") or e.get("webpage_url"), "title": e.get("title") or "", "duration": e.get("duration")}
            for e in _flat(past_list_url(channel), n, "past streams")[:n] if e.get("url") or e.get("webpage_url")]


def my_posts(channel, n=200):
    """Your channel's latest Shorts (or TikTok videos) with views: [{title, views}]."""
    c = (channel or "").strip()
    m = re.match(r"^(?:https?://)?(?:www\.|m\.)?youtube\.com/(@[\w.-]+|channel/[\w-]+)", c)
    if m:
        c = f"https://www.youtube.com/{m.group(1)}/shorts"
    elif not re.match(r"^(?:https?://)?(?:www\.)?tiktok\.com/@[\w.-]+", c):
        raise ValueError("Paste your YouTube channel (https://www.youtube.com/@name) or TikTok (https://www.tiktok.com/@name).")
    return [{"title": e.get("title") or e.get("description") or "", "views": int(e["view_count"])}
            for e in _flat(c, n, "videos") if e.get("view_count") is not None]

