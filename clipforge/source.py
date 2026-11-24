"""Download a video link with yt-dlp (cached per video id and quality)."""
import json, os, re, subprocess

from .util import which

_PCT = re.compile(r"\[download\]\s+([\d.]+)%")


def _fmt(h):
    return f"bv*[vcodec^=avc1][height<={h}]+ba[ext=m4a]/bv*[height<={h}]+ba/b[height<={h}]/b"


def download(job, url, outdir, max_height=1080, cookies_browser=None, on_progress=None):
    """Returns (path_to_mp4, info_dict_or_None). on_progress(0..1) is called while downloading."""
    ytdlp = which("yt-dlp")
    extra = ["--cookies-from-browser", cookies_browser] if cookies_browser else []
    r = subprocess.run([ytdlp, "--get-id", "--no-playlist"] + extra + [url], capture_output=True, text=True)
    vid = (r.stdout.strip().splitlines() or ["video"])[0]
    base = os.path.join(outdir, f"source_{vid}_{max_height}")
    if not os.path.exists(base + ".mp4"):
        fmt = _fmt(max_height)
        job.log(f"Downloading up to {max_height}p...")
        state = {"parts": 0}

        def line(s):
            if "Destination:" in s:
                state["parts"] += 1
            m = _PCT.search(s)
            if m and on_progress:
                p = float(m.group(1)) / 100
                on_progress(p * 0.9 if state["parts"] <= 1 else 0.9 + p * 0.1)
        job.run_lines([ytdlp, "-f", fmt, "--merge-output-format", "mp4", "--write-info-json", "--no-playlist",
                       "--newline", "-o", base + ".%(ext)s"] + extra + [url], line)
    info = None
    if os.path.exists(base + ".info.json"):
        with open(base + ".info.json", encoding="utf-8") as f:
            info = json.load(f)
    return base + ".mp4", info


def download_section(job, url, out, start, end, max_height=1080, cookies_browser=None):
    """Only start..end seconds of a link at full quality. The cut is exact, so the file starts at `start`."""
    if not os.path.exists(out):
        extra = ["--cookies-from-browser", cookies_browser] if cookies_browser else []
        job.run([which("yt-dlp"), "-f", _fmt(max_height), "--merge-output-format", "mp4", "--no-playlist",
                 "--download-sections", f"*{start:.2f}-{end:.2f}", "--force-keyframes-at-cuts",
                 "-o", out] + extra + [url])
    return out


def youtube_chat(url, base, cookies_browser=None):
    """Download a YouTube stream's chat replay (if it has one) and return [(seconds, message)]. Never raises."""
    path = base + ".live_chat.json"
    if not os.path.exists(path):
        extra = ["--cookies-from-browser", cookies_browser] if cookies_browser else []
        try:
            subprocess.run([which("yt-dlp"), "--skip-download", "--write-subs", "--sub-langs", "live_chat",
                            "--no-playlist", "-o", base + ".%(ext)s"] + extra + [url], capture_output=True, timeout=3600)
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
