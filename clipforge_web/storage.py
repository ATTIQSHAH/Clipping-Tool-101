"""Storage breakdown inspection and automatic temporary cache cleanup.

Preserves all user-approved and rendered videos in data/exports permanently,
while automatically deleting temporary audio extractions, motion scores,
whisper caches, and intermediate slice cuts after a retention window (default 48h / 2 days).
"""
import os
import shutil
import time

from . import db


def get_dir_size(path):
    """Calculate the total size in bytes of all files in path recursively."""
    total = 0
    if not os.path.isdir(path):
        return 0
    try:
        for root, _, files in os.walk(path):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    total += os.path.getsize(fp)
                except (OSError, FileNotFoundError):
                    pass
    except Exception:
        pass
    return total


def format_bytes(n):
    """Format bytes into readable string."""
    n = max(0, n or 0)
    if n >= 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024 * 1024):.2f} GB"
    elif n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    elif n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


def get_storage_stats():
    """Return storage sizes and paths for UI and monitoring."""
    data_dir = db.DATA
    exports_dir = os.path.join(data_dir, "exports")
    work_dir = os.path.join(data_dir, "work")
    originals_dir = os.path.join(data_dir, "originals")
    live_dir = os.path.join(data_dir, "live")
    jobs_dir = os.path.join(data_dir, "jobs")

    exports_size = get_dir_size(exports_dir)
    work_size = get_dir_size(work_dir)
    originals_size = get_dir_size(originals_dir)
    live_size = get_dir_size(live_dir)
    jobs_size = get_dir_size(jobs_dir)

    cleanup_hours = int(db.setting("cleanup_hours", "48") or 48)
    last_cleanup = float(db.setting("last_cleanup", "0") or 0)

    total_temp = work_size + live_size + jobs_size

    return {
        "data_dir": data_dir,
        "exports_dir": exports_dir,
        "work_dir": work_dir,
        "originals_dir": originals_dir,
        "live_dir": live_dir,
        "jobs_dir": jobs_dir,
        "exports_size": exports_size,
        "exports_str": format_bytes(exports_size),
        "work_size": work_size,
        "work_str": format_bytes(work_size),
        "originals_size": originals_size,
        "originals_str": format_bytes(originals_size),
        "live_size": live_size,
        "live_str": format_bytes(live_size),
        "jobs_size": jobs_size,
        "jobs_str": format_bytes(jobs_size),
        "total_temp_size": total_temp,
        "total_temp_str": format_bytes(total_temp),
        "total_size": exports_size + work_size + originals_size + live_size + jobs_size,
        "total_str": format_bytes(exports_size + work_size + originals_size + live_size + jobs_size),
        "cleanup_hours": cleanup_hours,
        "last_cleanup": last_cleanup,
    }


def clean_storage(older_than_hours=None, clean_all_temp=False):
    """Safely cleans temporary caches, intermediate wav/npy files, and old chunks.

    IMPORTANT: data/exports/ is NEVER touched or deleted. All saved videos remain safe.
    """
    if older_than_hours is None:
        val = db.setting("cleanup_hours", "48")
        try:
            older_than_hours = int(val) if val is not None else 48
        except (ValueError, TypeError):
            older_than_hours = 48

    # 0 means auto-cleanup is disabled unless explicitly requested via clean_all_temp
    if older_than_hours == 0 and not clean_all_temp:
        return {"ok": True, "freed_bytes": 0, "freed_mb": "0 MB", "files_removed": 0, "skipped": True}

    now = time.time()
    cutoff_time = 0 if clean_all_temp else (now - (older_than_hours * 3600))

    freed_bytes = 0
    files_removed = 0

    # Collect active videos & clips so we never delete active working files
    try:
        active_vids = {r["id"] for r in db.q("select id from videos where status in ('importing', 'analyzing')")}
        existing_vids = {r["id"] for r in db.q("select id from videos")}
    except Exception:
        active_vids = set()
        existing_vids = set()

    data_dir = db.DATA
    work_dir = os.path.join(data_dir, "work")
    live_dir = os.path.join(data_dir, "live")
    jobs_dir = os.path.join(data_dir, "jobs")
    originals_dir = os.path.join(data_dir, "originals")

    # 1. Clean work directory (audio extractions, motion/audio scores, temp subtitle files)
    if os.path.isdir(work_dir):
        for entry in os.listdir(work_dir):
            sub_path = os.path.join(work_dir, entry)
            if not os.path.isdir(sub_path):
                continue
            try:
                vid = int(entry)
            except ValueError:
                vid = None

            # Skip videos currently being imported or analyzed
            if vid is not None and vid in active_vids:
                continue

            # If video is completely deleted from DB, purge the whole orphaned folder
            if vid is not None and existing_vids and vid not in existing_vids:
                try:
                    folder_size = get_dir_size(sub_path)
                    shutil.rmtree(sub_path, ignore_errors=True)
                    freed_bytes += folder_size
                    files_removed += 1
                    continue
                except Exception:
                    pass

            # Otherwise, purge temporary files older than cutoff
            for root, _, files in os.walk(sub_path):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        st = os.stat(fp)
                        if clean_all_temp or st.st_mtime < cutoff_time:
                            size = st.st_size
                            os.remove(fp)
                            freed_bytes += size
                            files_removed += 1
                    except (OSError, FileNotFoundError):
                        pass

            # Remove empty subdirectories
            try:
                if not os.listdir(sub_path):
                    os.rmdir(sub_path)
            except OSError:
                pass

    # 2. Clean live recordings directory (stale stream chunks .ts and logs)
    if os.path.isdir(live_dir):
        for root, _, files in os.walk(live_dir):
            for f in files:
                if f.endswith((".ts", ".log")):
                    fp = os.path.join(root, f)
                    try:
                        st = os.stat(fp)
                        if clean_all_temp or st.st_mtime < cutoff_time:
                            size = st.st_size
                            os.remove(fp)
                            freed_bytes += size
                            files_removed += 1
                    except (OSError, FileNotFoundError):
                        pass

    # 3. Clean jobs directory (.stop tokens and old logs)
    if os.path.isdir(jobs_dir):
        for f in os.listdir(jobs_dir):
            fp = os.path.join(jobs_dir, f)
            try:
                st = os.stat(fp)
                if clean_all_temp or st.st_mtime < cutoff_time:
                    size = st.st_size
                    if os.path.isfile(fp):
                        os.remove(fp)
                        freed_bytes += size
                        files_removed += 1
            except (OSError, FileNotFoundError):
                pass

    # 4. Clean intermediate HD slice cuts in originals (hd_{cid}_*.mp4)
    # These are temporary cuts fetched for render. The rendered video is already in exports/.
    if os.path.isdir(originals_dir):
        for entry in os.listdir(originals_dir):
            sub_path = os.path.join(originals_dir, entry)
            if not os.path.isdir(sub_path):
                continue
            try:
                vid = int(entry)
            except ValueError:
                vid = None

            if vid is not None and vid in active_vids:
                continue

            # If video was deleted from DB, purge its orphaned original files
            if vid is not None and existing_vids and vid not in existing_vids:
                try:
                    folder_size = get_dir_size(sub_path)
                    shutil.rmtree(sub_path, ignore_errors=True)
                    freed_bytes += folder_size
                    files_removed += 1
                    continue
                except Exception:
                    pass

            for f in os.listdir(sub_path):
                if f.startswith("hd_") and f.endswith(".mp4"):
                    fp = os.path.join(sub_path, f)
                    try:
                        st = os.stat(fp)
                        if clean_all_temp or st.st_mtime < cutoff_time:
                            size = st.st_size
                            os.remove(fp)
                            freed_bytes += size
                            files_removed += 1
                    except (OSError, FileNotFoundError):
                        pass

    # Update last cleanup time
    try:
        db.set_setting("last_cleanup", str(time.time()))
    except Exception:
        pass

    return {
        "ok": True,
        "freed_bytes": freed_bytes,
        "freed_mb": format_bytes(freed_bytes),
        "files_removed": files_removed,
        "cutoff_hours": older_than_hours,
    }
