import os, shutil, subprocess, sys, threading, webbrowser
import uvicorn

# Suppress black console windows for all child processes (ffmpeg, yt-dlp, ffprobe) on Windows
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
                kwargs["creationflags"] = (kwargs.get("creationflags") or 0) | subprocess.CREATE_NO_WINDOW
                si = kwargs.get("startupinfo")
                if si is None:
                    si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = 0
                kwargs["startupinfo"] = si
                if "stdin" not in kwargs or kwargs.get("stdin") is None:
                    kwargs["stdin"] = subprocess.DEVNULL
            super().__init__(*args, **kwargs)

    subprocess.Popen = _SilentPopen
    subprocess._clipforge_silent_applied = True

def open_window(url):
    """Open ClipForge in its own app-style window (no browser tabs) using Edge or Chrome; else the normal browser."""
    pf = [os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
          os.environ.get("LOCALAPPDATA", "")]
    cands = [shutil.which("msedge"), shutil.which("chrome")]
    for base in pf:
        cands += [os.path.join(base, r"Microsoft\Edge\Application\msedge.exe"),
                  os.path.join(base, r"Google\Chrome\Application\chrome.exe")]
    for c in cands:
        if c and os.path.exists(c):
            try:
                subprocess.Popen([c, f"--app={url}", "--window-size=1480,920"])
                return
            except Exception:
                pass
    webbrowser.open(url)


def main():
    host = os.environ.get("CLIPFORGE_HOST", "127.0.0.1")
    port = int(os.environ.get("CLIPFORGE_PORT", "8000"))
    if host not in ("127.0.0.1", "localhost") and not os.environ.get("CLIPFORGE_PASSWORD"):
        sys.exit("Refusing to open ClipForge to the network without a password. "
                 "Set CLIPFORGE_PASSWORD first (or keep CLIPFORGE_HOST unset to stay on this computer only).")
    if host in ("127.0.0.1", "localhost"):
        threading.Timer(1.5, lambda: open_window(f"http://127.0.0.1:{port}")).start()
    from clipforge_web.server import app
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
