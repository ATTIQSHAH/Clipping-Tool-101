"""Process control (cancel / stop file), ffprobe helper."""
import json, os, shutil, subprocess, sys, tempfile, threading, time


def silent_flags():
    """Return creationflags and startupinfo for running child processes completely hidden on Windows."""
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        return {"creationflags": subprocess.CREATE_NO_WINDOW, "startupinfo": si}
    return {}


# Universal hook on Windows to guarantee NO black console windows ever appear for any subprocess
if os.name == "nt" and not getattr(subprocess, "_clipforge_silent_applied", False):
    _RealPopen = subprocess.Popen

    class _SilentPopen(_RealPopen):
        def __init__(self, *args, **kwargs):
            cmd = args[0] if args else kwargs.get("args")
            is_browser = False
            if cmd and isinstance(cmd, (list, tuple)) and len(cmd) > 0:
                c0 = str(cmd[0]).lower()
                if "msedge" in c0 or "chrome" in c0:
                    is_browser = True
            if not is_browser:
                if "creationflags" not in kwargs:
                    kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
                else:
                    kwargs["creationflags"] |= subprocess.CREATE_NO_WINDOW
                if "startupinfo" not in kwargs:
                    si = subprocess.STARTUPINFO()
                    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    si.wShowWindow = 0
                    kwargs["startupinfo"] = si
            super().__init__(*args, **kwargs)

    subprocess.Popen = _SilentPopen
    subprocess._clipforge_silent_applied = True


class Cancelled(Exception):
    pass


def which(name, bin_dir=None):
    exe = name + (".exe" if os.name == "nt" else "")
    dirs = [bin_dir] if bin_dir else []
    p = shutil.which(name)
    if p:
        return p
    # pip puts tools in Python's Scripts folder, which is not always on PATH; winget uses its Links folder
    dirs += [os.path.join(sys.prefix, "Scripts"), os.path.join(os.path.dirname(sys.executable), "Scripts"),
             os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Links")]
    for d in dirs:
        c = os.path.join(d, exe)
        if d and os.path.exists(c):
            return c
    raise RuntimeError(f"'{name}' not found. Run Install-Windows.bat, or install it and restart ClipForge.")


def kill_tree(p):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **silent_flags())
        else:
            p.kill()
    except Exception:
        pass


class Job:
    """Runs child processes and lets you stop everything: Ctrl+C, job.cancel(),
    or by creating the stop file (e.g. a STOP file in the output folder)."""

    def __init__(self, stop_file=None, log=print):
        self.stop_file = stop_file
        self.log = log
        self.cancelled = threading.Event()
        self.procs = set()
        self.show_output = True
        self.lock = threading.Lock()

    def cancel(self):
        self.cancelled.set()
        with self.lock:
            for p in list(self.procs):
                kill_tree(p)

    def check(self):
        if self.stop_file and os.path.exists(self.stop_file):
            self.cancelled.set()
        if self.cancelled.is_set():
            self.cancel()
            raise Cancelled()

    check_cancelled = check

    def _wait(self, p, cmd, err, reader=None):
        """Wait for a child process while honouring cancel; raise with the tail of stderr if it fails."""
        with self.lock:
            self.procs.add(p)
        try:
            while p.poll() is None:
                time.sleep(0.2)
                self.check()
        finally:
            with self.lock:
                self.procs.discard(p)
        if reader:
            reader.join(timeout=3)
        err.seek(0)
        text = err.read().decode(errors="replace")
        err.close()
        if p.returncode != 0:
            self.log(f"Command failed ({p.returncode}): {' '.join(map(str, cmd[:2]))}\n{text[-1500:]}")
            lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("WARNING")]
            errs = [ln for ln in lines if ln.startswith("ERROR:")]       # yt-dlp: keep only its reason
            msg = errs[-1].split(": ", 2)[-1] if errs else "\n".join(lines[-4:])
            raise RuntimeError(f"{os.path.basename(str(cmd[0]))} failed: {msg[-600:] or 'no details'}")
        return text

    def run(self, cmd, cwd=None, show=False):
        self.check()
        err = tempfile.TemporaryFile()
        kwargs = silent_flags() if os.name == "nt" else {}
        p = subprocess.Popen(cmd, cwd=cwd, stdout=None if (show and self.show_output) else subprocess.DEVNULL, stderr=err, **kwargs)
        return self._wait(p, cmd, err)

    def run_lines(self, cmd, on_line, cwd=None):
        """Like run(), but hands every output line to on_line() while the program runs (for progress bars)."""
        self.check()
        err = tempfile.TemporaryFile()
        kwargs = silent_flags() if os.name == "nt" else {}
        p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=err, text=True, bufsize=1, errors="replace", **kwargs)

        def reader():
            for line in p.stdout:
                try:
                    on_line(line.strip())
                except Exception:
                    pass
        th = threading.Thread(target=reader, daemon=True)
        th.start()
        return self._wait(p, cmd, err, th)


def probe(ffprobe, path):
    kwargs = silent_flags() if os.name == "nt" else {}
    r = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height,r_frame_rate",
                        "-show_entries", "format=duration", "-of", "json", path],
                       capture_output=True, text=True, **kwargs)
    try:
        d = json.loads(r.stdout)
        s = d["streams"][0]
        n, _, den = s["r_frame_rate"].partition("/")
        fps = float(n) / float(den or 1)
        return {"w": int(s["width"]), "h": int(s["height"]), "fps": fps or 30.0,
                "duration": float(d["format"]["duration"])}
    except (ValueError, KeyError, IndexError, ZeroDivisionError):
        raise RuntimeError("Couldn't read this video file. It may be damaged or not a video.")
