"""Live-stream clipping. Records a Twitch/Kick stream in short pieces, watches the sound and the chat in real
time, and cuts a clip whenever something big happens. Twitch, YouTube and Kick chat are read live (read only, no
account); platforms have no "likes" on a live stream, so chat bursts and crowd noise stand in."""
import collections, csv, json, os, queue, random, re, socket, ssl, subprocess, tempfile, threading, time, traceback
import numpy as np

from clipforge import analyze
from clipforge.segments import snap, text_score, title_of
from clipforge.transcribe import load_json, transcribe_file
from clipforge.source import live_chat_line
from clipforge.util import probe, which
from . import db, engine

SESSIONS = {}
CHAT_FACTORY = None          # tests replace this
SEG_SECONDS = 5
NOT_CHANNELS = {"videos", "video", "directory", "downloads", "clips", "settings", "p", "about", "login"}
TEST_FILES = os.environ.get("CLIPFORGE_TEST_SOURCES") == "1"   # lets tests play a local file as a "stream"
STALL = 45                   # seconds with no new piece of video = the stream froze (Kick does this): reconnect
GIVE_UP = 300                # seconds of failed reconnects before we decide the stream is over
DEFAULT_CFG = dict(warmup=60.0, hi=0.55, lo=0.30, cooldown=40.0, lead=22.0, tail=10.0, buffer=1200.0, model="base")


YOUTUBE = re.compile(r"^https?://(?:www\.|m\.)?(?:youtube\.com/(?:@[\w.-]+(?:/live)?|watch\?v=[\w-]+|live/[\w-]+|channel/[\w-]+/live)|youtu\.be/[\w-]+)")


def parse_url(url):
    y = YOUTUBE.match((url or "").strip())
    if y:
        name = re.search(r"@([\w.-]+)|v=([\w-]+)|live/([\w-]+)|channel/([\w-]+)|youtu\.be/([\w-]+)", url)
        return "youtube", next(g for g in name.groups() if g)
    m = re.match(r"^https?://(?:www\.|m\.)?(twitch\.tv|kick\.com)/([A-Za-z0-9_]+)/?(?:\?.*)?$", (url or "").strip())
    if not m or m.group(2).lower() in NOT_CHANNELS:
        raise ValueError("Paste a Twitch, Kick or YouTube Live link, like https://www.twitch.tv/ishowspeed "
                         "(a recording or clip link belongs in 'Add video').")
    return ("twitch" if "twitch" in m.group(1) else "kick"), m.group(2)


# ---------------- chat ----------------
def parse_irc_line(line):
    """':nick!nick@nick.tmi.twitch.tv PRIVMSG #chan :hello' -> 'hello' (None for anything else)."""
    m = re.match(r"^(?:@\S+ )?:[^ ]+ PRIVMSG #\S+ :(.*)$", line)
    return m.group(1) if m else None


class TwitchChat(threading.Thread):
    """Reads a channel's public chat anonymously (no account needed)."""

    def __init__(self, channel):
        super().__init__(daemon=True)
        self.channel, self.events, self.error, self.connected = channel.lower(), collections.deque(), "", False
        self.stopped = False

    def run(self):
        while not self.stopped:
            try:
                raw = socket.create_connection(("irc.chat.twitch.tv", 6697), timeout=15)
                s = ssl.create_default_context().wrap_socket(raw, server_hostname="irc.chat.twitch.tv")
                s.settimeout(30)
                s.sendall(f"PASS SCHMOOPIIE\r\nNICK justinfan{random.randint(10000, 99999)}\r\nJOIN #{self.channel}\r\n".encode())
                buf, last = b"", time.time()
                self.connected, self.error = True, ""
                while not self.stopped:
                    try:
                        chunk = s.recv(4096)
                    except socket.timeout:
                        if time.time() - last > 400:           # Twitch pings every ~5 min; silence = dead socket (PC slept)
                            break
                        continue
                    last = time.time()
                    if not chunk:
                        break
                    buf += chunk
                    while b"\r\n" in buf:
                        line, buf = buf.split(b"\r\n", 1)
                        line = line.decode("utf-8", "replace")
                        if line.startswith("PING"):
                            s.sendall(b"PONG :tmi.twitch.tv\r\n")
                            continue
                        msg = parse_irc_line(line)
                        if msg is not None:
                            self.events.append((time.time(), msg))
            except Exception as e:
                self.error = f"Chat connection lost ({str(e)[:60]}). Retrying."
            self.connected = False
            time.sleep(3)

    def drain(self):
        out = []
        while self.events:
            out.append(self.events.popleft())
        return out

    def close(self):
        self.stopped = True


class YouTubeChat(threading.Thread):
    """Follows a YouTube live chat through yt-dlp, which keeps writing it to a file while the stream runs."""

    def __init__(self, url):
        super().__init__(daemon=True)
        self.url, self.events, self.error, self.connected, self.stopped = url, collections.deque(), "", False, False
        self.proc = None

    def run(self):
        with tempfile.TemporaryDirectory(prefix="cf_ytchat_") as d:
            path = os.path.join(d, "c.live_chat.json.part")
            while not self.stopped:
                for f in os.listdir(d):                       # a restart starts a fresh file
                    os.remove(os.path.join(d, f))
                self.proc = subprocess.Popen([which("yt-dlp"), "--no-warnings", "--skip-download", "--write-subs",
                                              "--sub-langs", "live_chat", "--no-playlist", "-o", os.path.join(d, "c"), self.url],
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                pos = 0
                while not self.stopped and self.proc.poll() is None:
                    time.sleep(2)
                    if os.path.exists(path):
                        with open(path, "rb") as f:
                            f.seek(pos)
                            lines = f.readlines()
                        if lines and not lines[-1].endswith(b"\n"):  # half-written line: read it next time
                            lines.pop()
                        pos += sum(map(len, lines))
                        for ln in lines:
                            self.events.extend(live_chat_line(ln.decode("utf-8", "ignore")))
                        self.connected, self.error = True, ""
                if not self.stopped:
                    self.connected, self.error = False, "Chat connection lost. Retrying."
                    time.sleep(5)

    def drain(self):
        out = []
        while self.events:
            out.append(self.events.popleft())
        return out

    def close(self):
        self.stopped = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


def kick_msg(frame):
    """Pusher frame (dict) -> message text for a Kick ChatMessageEvent, else None."""
    if "ChatMessageEvent" not in frame.get("event", ""):
        return None
    d = json.loads(frame["data"]) if isinstance(frame.get("data"), str) else frame.get("data") or {}
    return d.get("content")


def _kick_get(url, body=None):
    import requests
    h = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    r = requests.post(url, json=body, headers=h, timeout=15) if body else requests.get(url, headers=h, timeout=15)
    r.raise_for_status()
    return r.json()


class KickChat(threading.Thread):
    """Reads a Kick channel's public chat (read only, no account). Kick hands out the chat server key per request."""

    def __init__(self, channel):
        super().__init__(daemon=True)
        self.channel, self.events, self.error, self.connected, self.stopped = channel.lower(), collections.deque(), "", False, False
        self.ws = None

    def run(self):
        import websocket
        while not self.stopped:
            try:
                ch = _kick_get(f"https://kick.com/api/v2/channels/{self.channel}")
                c = _kick_get(f"https://web.kick.com/api/v1/realtime/channels/{ch['id']}/chat/connection",
                              {"client": {"id": "clipforge", "type": "web"},
                               "capabilities": {"accepted_providers": [{"provider": "pusher"}]}})
                c = c["data"]["connections"][0]["credentials"]
                self.ws = websocket.create_connection(
                    f"wss://ws-{c['cluster']}.pusher.com/app/{c['app_key']}?protocol=7&client=js&version=8.4.0&flash=false",
                    timeout=30, origin="https://kick.com")
                self.ws.send(json.dumps({"event": "pusher:subscribe",
                                         "data": {"auth": "", "channel": f"chatrooms.{ch['chatroom']['id']}.v2"}}))
                self.connected, self.error = True, ""
                while not self.stopped:
                    try:
                        f = json.loads(self.ws.recv())
                    except websocket.WebSocketTimeoutException:
                        self.ws.send(json.dumps({"event": "pusher:ping", "data": {}}))
                        continue
                    if f.get("event") == "pusher:ping":
                        self.ws.send(json.dumps({"event": "pusher:pong", "data": {}}))
                    elif (m := kick_msg(f)) is not None:
                        self.events.append((time.time(), m))
            except Exception as e:
                self.error = f"Chat connection lost ({str(e)[:60]}). Retrying."
            self.connected = False
            if not self.stopped:
                time.sleep(5)

    def drain(self):
        out = []
        while self.events:
            out.append(self.events.popleft())
        return out

    def close(self):
        self.stopped = True
        try:
            self.ws and self.ws.close()
        except Exception:
            pass


class NoChat:
    connected = False

    def __init__(self, platform="kick"):
        self.error = f"{platform.title()} live chat isn't read yet, so only the sound and picture are used."

    def drain(self):
        return []

    def start(self):
        pass

    def close(self):
        pass


# ---------------- the live session ----------------
def source_cmd(url):
    if TEST_FILES and os.path.exists(url):                    # test source: a local file played like a stream
        return [which("ffmpeg"), "-v", "error", "-readrate", os.environ.get("CLIPFORGE_TEST_READRATE", "1"),
                "-i", url, "-c", "copy", "-f", "mpegts", "pipe:1"]
    return [which("streamlink"), "--stdout", "--quiet", "--twitch-disable-ads", "--retry-streams", "3", "--retry-max", "3",
            url, "best"]


class Live:
    def __init__(self, video_id, url, platform, channel, cfg=None):
        self.id, self.url, self.platform, self.channel = video_id, url, platform, channel
        self.cfg = dict(DEFAULT_CFG, **(cfg or {}))
        self.dir = os.path.join(db.DATA, "live", str(video_id))
        os.makedirs(os.path.join(self.dir, "moments"), exist_ok=True)
        self.state, self.error, self.stopped = "starting", "", False
        self.segs, self.seen = [], 0                       # [(name, start, end)] in stream time
        self.samples = np.zeros(0, dtype=np.int16)
        self.db = []                                       # loudness per 0.5 s frame
        self.rate_x = []                                   # chat activity per second
        self.hist = []                                     # per second: (audio, chat, combined)
        self.chat_total, self.t0 = 0, None
        self.pending, self.moments, self.last_peak = queue.Queue(), 0, -999.0
        self.active = None
        self.procs, self.attempt, self.last_new = [], 0, time.time()
        self.chat = (CHAT_FACTORY or self._make_chat)(platform, channel)
        self.lock = threading.Lock()
        self.needed_from = 0.0
        self.busy = False

    def _make_chat(self, platform, channel):
        if platform == "twitch":
            return TwitchChat(channel)
        if platform == "kick":
            return KickChat(channel)
        return YouTubeChat(self.url) if platform == "youtube" else NoChat(platform)

    # ----- lifecycle -----
    def _record(self):
        """(Re)start the recorder. Each attempt writes its own pieces and list; stream time just carries on."""
        self.attempt += 1
        self.seen, self.t0_fix, self.attempt_t = 0, True, time.time()
        self.src = subprocess.Popen(source_cmd(self.url), stdout=subprocess.PIPE,
                                    stderr=open(os.path.join(self.dir, "source.log"), "ab"))
        seg_cmd = [which("ffmpeg"), "-y", "-v", "error", "-i", "pipe:0", "-c", "copy", "-f", "segment",
                   "-segment_time", str(SEG_SECONDS), "-segment_format", "mpegts", "-segment_list", self._list(),
                   "-segment_list_type", "csv", "-reset_timestamps", "1", f"seg_{self.attempt}_%06d.ts"]
        self.seg = subprocess.Popen(seg_cmd, stdin=self.src.stdout, cwd=self.dir,
                                    stderr=open(os.path.join(self.dir, "segmenter.log"), "ab"))
        self.src.stdout.close()
        self.procs = [self.src, self.seg]

    def _list(self):
        return f"list_{self.attempt}.csv"

    def _kill(self):
        for p in self.procs:
            try:
                p.kill()
                p.wait(5)
            except Exception:
                pass

    def start(self):
        try:
            self._record()
        except Exception as e:
            self._fail(str(e))
            return
        if hasattr(self.chat, "start"):
            self.chat.start()
        threading.Thread(target=self._analyze_loop, daemon=True).start()
        threading.Thread(target=self._maker_loop, daemon=True).start()

    def stop(self):
        self.stopped = True
        for p in self.procs:
            try:
                p.terminate()
            except Exception:
                pass
        self.chat.close()

    def _fail(self, msg):
        self.state, self.error = "error", msg
        db.ex("update videos set status='error', error=?, stage='' where id=?", (msg[:400], self.id))

    def media_time(self):
        return self.segs[-1][2] if self.segs else 0.0

    # ----- reading the recording -----
    def _read_segments(self):
        path = os.path.join(self.dir, self._list())
        if not os.path.exists(path):
            return []
        with open(path, newline="") as f:
            rows = [r for r in csv.reader(f) if len(r) >= 3]
        new = []
        for r in rows[self.seen:]:
            d = max(0.0, float(r[2]) - float(r[1]))
            start = self.segs[-1][2] if self.segs else 0.0
            self.segs.append((r[0], start, start + d))
            new.append(self.segs[-1])
        self.seen = len(rows)
        if new:
            self.last_new = time.time()
        return new

    def _add_audio(self, name):
        raw = subprocess.run([which("ffmpeg"), "-v", "error", "-i", os.path.join(self.dir, name), "-vn", "-ac", "1",
                              "-ar", "16000", "-f", "s16le", "-"], capture_output=True).stdout
        self.samples = np.concatenate([self.samples, np.frombuffer(raw[: len(raw) // 2 * 2], dtype=np.int16)])
        n = int(analyze.SR * analyze.FRAME)
        while len(self.samples) >= n:
            a = self.samples[:n].astype(np.float32) / 32768.0
            self.db.append(float(20 * np.log10(np.sqrt((a ** 2).mean()) + 1e-6)))
            self.samples = self.samples[n:]

    def _audio_at(self, i):
        w = np.array(self.db[max(0, i - 600):i + 1])
        med = np.median(w)
        spread = max(float(np.median(np.abs(w - med)) * 1.4826), 2.0)
        return max(0.0, float((self.db[i] - med) / spread))

    def _analyze_loop(self):
        exc, chat_hype, t_sec = [], collections.deque(), 0
        probed = False
        while not self.stopped:
            time.sleep(1.0)
            ended = self.src.poll() is not None and self.seg.poll() is not None
            new = self._read_segments()                        # read before judging, a short stream may be done
            # a new connection gets extra time: Twitch shows ads first and we skip them
            stalled = not ended and time.time() - max(self.last_new, self.attempt_t + STALL) > STALL
            if (ended or stalled) and self.segs and not TEST_FILES and not self.stopped and time.time() - self.last_new < GIVE_UP:
                # the stream dropped or froze: reconnect and keep going (pieces already read stay)
                with open(os.path.join(self.dir, "source.log"), "a") as f:
                    f.write(f"\n{time.strftime('%H:%M:%S')} {'froze' if stalled else 'ended'}: reconnecting\n")
                self._kill()
                db.ex("update videos set stage='Reconnecting' where id=? and status='live'", (self.id,))
                time.sleep(3)
                try:
                    self._record()
                except Exception:
                    pass
                continue
            if stalled and not self.segs and time.time() - self.attempt_t > GIVE_UP:
                self._kill()                                   # nothing ever arrived: give up below
                ended = True
            if ended and not self.segs:
                try:
                    tail = open(os.path.join(self.dir, "source.log"), errors="replace").read()[-300:].strip()
                except Exception:
                    tail = ""
                self._fail("Couldn't open the stream. Is the channel live? " + tail)
                return
            for name, s, e in new:
                if self.t0 is None or self.t0_fix:             # line chat time up with video time (again after a reconnect)
                    self.t0 = time.time() - e
                    self.t0_fix = False
                    self.state = "recording"
                    db.ex("update videos set status='live', stage='Recording' where id=?", (self.id,))
                self._add_audio(name)
                if not probed:
                    probed = True
                    try:
                        p = probe(which("ffprobe"), os.path.join(self.dir, name))
                        db.ex("update videos set w=?, h=?, fps=?, has_audio=1 where id=?", (p["w"], p["h"], p["fps"], self.id))
                    except Exception:
                        pass
            if self.t0 is None:
                continue
            # chat: bucket the new messages by stream second
            for wall, txt in self.chat.drain():
                sec = int(wall - self.t0)
                if sec < 0 or txt.startswith("!") or "http" in txt:   # bot commands and link ads are not a reaction
                    continue
                while len(self.rate_x) <= sec:
                    self.rate_x.append(0.0)
                self.rate_x[sec] += 1.0 + (1.5 if any(k in txt.lower() for k in analyze.CHAT_HYPE) else 0.0)
                self.chat_total += 1
            # one score per second for every second of recording that has audio
            while t_sec < len(self.db) // 2:
                i = min(len(self.db) - 1, (t_sec + 1) * 2 - 1)
                e = [self._audio_at(j) for j in range(max(0, i - 7), i + 1)]
                audio = min(1.0, (sum(e) / len(e)) / 4.0)
                chat = 0.0
                if self.chat_total:
                    while len(self.rate_x) <= t_sec:
                        self.rate_x.append(0.0)
                    x = np.mean(self.rate_x[max(0, t_sec - 5):t_sec + 1])
                    hist = np.array([np.mean(self.rate_x[max(0, k - 5):k + 1]) for k in range(max(0, t_sec - 300), t_sec + 1)])
                    med = np.median(hist)
                    spread = max(float(np.median(np.abs(hist - med)) * 1.4826), 0.5)
                    chat = float(min(1.0, max(0.0, (x - med) / spread) / 6.0))
                comb = 0.6 * audio + 0.4 * chat if self.chat_total else audio
                self.hist.append((audio, chat, comb))
                self._detect(t_sec, comb, audio, chat)
                t_sec += 1
            self._housekeeping()
            if ended and self.segs:                            # the streamer went offline: finish up by itself
                self.stopped = True
                self.chat.close()
                db.ex("update videos set status='ready', stage='', progress=100 where id=? and status='live'", (self.id,))
        if self.state != "error":
            self.state = "stopped"

    def _detect(self, t, c, audio, chat):
        cfg = self.cfg
        if t < cfg["warmup"]:
            return
        a = self.active
        if a is None:
            if c >= cfg["hi"]:
                a = self.active = {"start": t, "peak_t": t, "peak": c, "audio": audio, "chat": chat, "low": 0, "hi_run": 1}
            return
        if c > a["peak"]:
            a.update(peak=c, peak_t=t, audio=audio, chat=chat)
        a["low"] = a["low"] + 1 if c < cfg["lo"] else 0
        if a["low"] >= 4 or t - a["start"] > 40:
            self.active = None
            if a["peak_t"] - self.last_peak >= cfg["cooldown"]:
                self.last_peak = a["peak_t"]
                self._queue_moment(a["peak_t"], a["peak"], a["audio"], a["chat"], "auto")

    def clip_now(self):
        t = max(0.0, self.media_time() - 4)
        self.last_peak = t
        self._queue_moment(t, 1.0, 0.0, 0.0, "manual")

    def _queue_moment(self, peak_t, peak, audio, chat, how):
        self.needed_from = min(self.needed_from or 1e9, peak_t - 60)
        self.moments += 1
        self.pending.put((peak_t, peak, audio, chat, how))

    def _housekeeping(self):
        t = self.media_time()
        if len(self.hist) % 5 == 0 and self.hist:
            step = max(1, len(self.hist) // 400)
            curve = [round(max(h[2] for h in self.hist[i:i + step]), 3) for i in range(0, len(self.hist), step)]
            db.ex("update videos set duration=?, curve=? where id=?", (t, db.dumps({"step": float(step), "v": curve}), self.id))
        keep_from = min(t - self.cfg["buffer"], self.needed_from if self.pending.qsize() else 1e9)
        for name, s, e in list(self.segs):
            f = os.path.join(self.dir, name)
            if e < keep_from and os.path.exists(f):
                os.remove(f)

    # ----- cutting a moment into a clip -----
    def _maker_loop(self):
        while not (self.stopped and self.pending.empty() and not self.busy):
            try:
                task = self.pending.get(timeout=1)
            except queue.Empty:
                continue
            peak_t = task[0]
            self.busy = True
            while not self.stopped and self.media_time() < peak_t + self.cfg["tail"] + 1:
                time.sleep(1)
            try:
                self._make_clip(*task)
            except Exception as e:
                traceback.print_exc()
                db.ex("update videos set error=? where id=?", (f"A clip could not be cut: {str(e)[:200]}", self.id))
            self.busy = False
            if self.pending.empty():
                self.needed_from = 0.0

    def _make_clip(self, peak_t, peak, audio, chat, how):
        cfg, ff = self.cfg, which("ffmpeg")
        t0, t1 = max(0.0, peak_t - cfg["lead"] - 25), min(self.media_time(), peak_t + cfg["tail"] + 6)
        use = [s for s in self.segs if s[2] > t0 and s[1] < t1 and os.path.exists(os.path.join(self.dir, s[0]))]
        if not use:
            return
        k = self.moments_made = getattr(self, "moments_made", 0) + 1
        lst = os.path.join(self.dir, f"m{k}.txt")
        with open(lst, "w") as f:
            for name, _, _ in use:
                f.write("file '" + os.path.join(self.dir, name).replace("\\", "/").replace("'", "'\\''") + "'\n")
        out = os.path.join(self.dir, "moments", f"m{k}.mp4")
        r = subprocess.run([ff, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy",
                            "-bsf:a", "aac_adtstoasc", out], capture_output=True)
        if r.returncode != 0:                                  # unusual audio: re-encode the short excerpt instead
            subprocess.run([ff, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c:v", "libx264",
                            "-preset", "veryfast", "-c:a", "aac", out], check=True, capture_output=True)
        offset = use[0][1]
        info = probe(which("ffprobe"), out)
        wav = os.path.join(self.dir, f"m{k}.wav")
        subprocess.run([ff, "-y", "-v", "error", "-i", out, "-vn", "-ac", "1", "-ar", "16000", wav], check=True)
        words = transcribe_file(wav, db.setting("model", cfg["model"]), "cpu", "int8")["words"]
        rel_peak = peak_t - offset
        s, e = snap(words, rel_peak - cfg["lead"], rel_peak + cfg["tail"], 12.0, 50.0, info["duration"], info["fps"])
        cw = [w for w in words if w["start"] >= s - 0.01 and w["end"] <= e + 0.01]
        speech = text_score(cw, e - s)
        final = max(0.7, peak) if how == "manual" else 0.7 * peak + 0.3 * speech
        v = db.q("select * from videos where id=?", (self.id,), one=True)
        client = db.q("select * from clients where id=?", (v["client_id"],), one=True) if v.get("client_id") else None
        title = title_of(cw) or f"Moment at {int(peak_t // 60)}:{int(peak_t % 60):02d}"
        comp = {"audio": audio, "heat": None, "chat": chat if self.chat_total else None, "speech": speech, "ai": None}
        reasons = ["You pressed Clip it." if how == "manual" else
                   f"Live moment at {int(peak_t // 60)}:{int(peak_t % 60):02d}: the sound and chat jumped well above this stream's normal level."]
        if self.chat_total:
            reasons.append(f"Chat reaction: {chat:.0%} of a big burst.")
        db.ex("insert into clips(video_id,start,end,peak,ws,we,score,scores,reasons,words,title,template,layout,res,"
              "crop_x,music,sfx_intro,sfx_peak,captions,status,render_status,created,src,stream_offset) "
              "values(?,?,?,?,?,?,?,?,?,?,?,?,'pip',1080,0.5,?,'','',1,'candidate','none',?,?,?)",
              (self.id, s, e, rel_peak, 0.0, info["duration"], round(final, 4), db.dumps(comp), db.dumps(reasons),
               db.dumps(words), title, (client or {}).get("template") or "yellow_pop", (client or {}).get("music") or "",
               db.now(), out, offset))

    # ----- numbers for the screen -----
    def stats(self):
        recent = self.hist[-120:]
        return {"state": self.state, "error": self.error, "elapsed": round(self.media_time(), 1),
                "audio": [round(h[0], 3) for h in recent], "chat": [round(h[1], 3) for h in recent],
                "score": [round(h[2], 3) for h in recent], "moments": self.moments,
                "chat_status": ("Reading chat" if getattr(self.chat, "connected", False) else (self.chat.error or "Connecting to chat"))
                if self.platform in ("twitch", "youtube", "kick") else self.chat.error,
                "chat_messages": self.chat_total, "platform": self.platform, "channel": self.channel,
                "warmup": max(0.0, self.cfg["warmup"] - self.media_time())}


# ---------------- manager ----------------
def start(url, client_id=None, cfg=None):
    test = TEST_FILES and os.path.exists(url)
    platform, channel = ("twitch", "test") if test else parse_url(url)
    if not test:
        which("streamlink")                                    # fail early with a clear message if missing
    vid = db.ex("insert into videos(title,source,status,created,client_id,kind,stage) values(?,?,?,?,?,?,?)",
                (f"Live: {channel} ({platform})", url, "live", db.now(), client_id, "live", "Connecting"))
    s = Live(vid, url, platform, channel, cfg)
    SESSIONS[vid] = s
    s.start()
    return vid


def get(vid):
    return SESSIONS.get(vid)


def stop(vid):
    s = SESSIONS.get(vid)
    if s:
        if s.url in watch_list():                              # don't let the watch list restart what you stopped
            _paused.add(s.url)
        s.stop()
        for _ in range(60):                                    # let pending clips finish
            if s.state in ("stopped", "error") and s.pending.empty() and not s.busy:
                break
            time.sleep(0.5)
    v = db.q("select * from videos where id=?", (vid,), one=True)
    if v and v["status"] == "live":
        db.ex("update videos set status='ready', stage='', progress=100 where id=?", (vid,))


# ---------------- watch list: record channels automatically when they go live ----------------
WATCH_EVERY = 60                                               # seconds between checks
MAX_LIVE = int(os.environ.get("CLIPFORGE_MAX_LIVE", "6"))      # each recording costs CPU; raise it on a strong PC
WATCH = {}                                                     # url -> status text for the page
_paused = set()


def watch_list():
    return [u.strip() for u in db.setting("watch", "").splitlines() if u.strip()]


def set_watch_list(text):
    urls = []
    for u in str(text).splitlines():
        u = u.strip()
        if u and u not in urls:
            parse_url(u)                                       # ValueError with a clear message if it isn't a channel
            urls.append(u)
    db.set_setting("watch", "\n".join(urls))
    for u in list(WATCH):
        if u not in urls:
            WATCH.pop(u, None)
            _paused.discard(u)
    return urls


def is_live(url):
    r = subprocess.run([which("streamlink"), "--json", url], capture_output=True, text=True, timeout=120)
    try:
        return bool(json.loads(r.stdout).get("streams"))
    except ValueError:
        return False


def _active(url):
    return any(s.url == url and not s.stopped for s in SESSIONS.values())


def check_watch_list(live_check=is_live, starter=None):
    starter = starter or start
    for url in watch_list():
        if _active(url):
            WATCH[url] = "Recording"
            continue
        try:
            on = live_check(url)
        except Exception as e:
            WATCH[url] = f"Couldn't check ({str(e)[:60]})"
            continue
        if not on:
            _paused.discard(url)
            WATCH[url] = "Offline"
        elif url in _paused:
            WATCH[url] = "Live, but you stopped it"
        elif sum(1 for s in SESSIONS.values() if not s.stopped) >= MAX_LIVE:
            WATCH[url] = f"Live, waiting: {MAX_LIVE} recordings already running"
        else:
            try:
                starter(url)
                WATCH[url] = "Recording"
            except Exception as e:
                WATCH[url] = f"Couldn't start ({str(e)[:80]})"


def _watch_loop():
    while True:
        try:
            check_watch_list()
        except Exception:
            traceback.print_exc()
        time.sleep(WATCH_EVERY)


def start_watcher():
    threading.Thread(target=_watch_loop, daemon=True).start()
