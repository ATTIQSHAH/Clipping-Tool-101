"""SQLite storage (single file, no server needed)."""
import json, os, shutil, sqlite3, sys, threading, time

if getattr(sys, "frozen", False):
    ROOT = os.path.dirname(sys.executable)
else:
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get("CLIPFORGE_DATA") or os.path.join(ROOT, "data")
_lock = threading.RLock()
_conn = None

SCHEMA = """
create table if not exists clients(
  id integer primary key, name text, template text default 'yellow_pop', music text default '', created real);
create table if not exists videos(
  id integer primary key, title text, source text, path text, status text, error text,
  duration real, w integer, h integer, fps real, size integer, has_audio integer,
  info_path text, curve text, created real, client_id integer, kind text, progress real default 0, stage text default '',
  hd integer default 0, cookies text, cam_box text);
create table if not exists clips(
  id integer primary key, video_id integer, start real, end real, peak real, ws real, we real,
  score real, scores text, reasons text, words text, title text,
  template text, layout text, res integer, crop_x real, music text, sfx_intro text, sfx_peak text,
  captions integer, status text, render_status text, render_path text, created real,
  render_progress real default 0, src text, track text, downloaded integer default 0, stream_offset real default 0, cam text,
  sfx text, hook_zoom integer default 1, emojis integer default 1, censor integer default 0,
  cam_zoom real default 1.0, cam_size real default 1.0, cam_shape text default 'rect', cam_pos text default 'top',
  cam_pos_x real default 0.5, cam_pos_y real default 0.65, banner_text text default '', banner_style text default 'white_box',
  banner_x real default 0.5, banner_y real default 0.12,
  banner_size real default 1.0, banner_font text default 'Arial',
  caption_size real default 1.0, caption_font text default 'Arial', caption_y real default 0.88,
  views integer, lang text default '', vo text default '',
  split_ratio real default 0.5, cam_corner text default 'tr',
  cam_crop_x real default 0.5, cam_crop_y real default 0.5,
  game_zoom real default 1.0, crop_y real default 0.5,
  aspect_ratio text default '9:16', qc text);
create table if not exists jobs(
  id integer primary key, type text, ref_id integer, params text, status text,
  log text default '', error text, created real, started real, finished real);
create table if not exists settings(key text primary key, value text);
create table if not exists rules(key text primary key, status text, note text);
"""

MIGRATE = {
    "videos": [
        ("hd", "integer default 0"),
        ("cookies", "text"),
        ("client_id", "integer"),
        ("kind", "text"),
        ("progress", "real default 0"),
        ("stage", "text default ''"),
        ("cam_box", "text"),
    ],
    "clips": [
        ("render_progress", "real default 0"),
        ("src", "text"),
        ("track", "text"),
        ("downloaded", "integer default 0"),
        ("stream_offset", "real default 0"),
        ("cam", "text"),
        ("sfx", "text"),
        ("hook_zoom", "integer default 1"),
        ("emojis", "integer default 1"),
        ("censor", "integer default 0"),
        ("sfx_peak", "text default ''"),
        ("cam_zoom", "real default 1.0"),
        ("cam_size", "real default 1.0"),
        ("cam_shape", "text default 'rect'"),
        ("cam_pos", "text default 'top'"),
        ("cam_pos_x", "real default 0.5"),
        ("cam_pos_y", "real default 0.65"),
        ("banner_text", "text default ''"),
        ("banner_style", "text default 'white_box'"),
        ("split_ratio", "real default 0.5"),
        ("cam_corner", "text default 'tr'"),
        ("cam_crop_x", "real default 0.5"),
        ("cam_crop_y", "real default 0.5"),
        ("aspect_ratio", "text default '9:16'"),
        ("qc", "text"),
        ("game_zoom", "real default 1.0"),
        ("crop_y", "real default 0.5"),
        ("banner_x", "real default 0.5"),
        ("banner_y", "real default 0.12"),
        ("banner_size", "real default 1.0"),
        ("banner_font", "text default 'Arial'"),
        ("caption_size", "real default 1.0"),
        ("caption_font", "text default 'Arial'"),
        ("caption_y", "real default 0.88"),
        ("views", "integer"),
        ("lang", "text default ''"),
        ("vo", "text default ''"),
        ("banner_start", "real"),
        ("banner_end", "real"),
    ],
}


def conn():
    global _conn
    if _conn is not None:
        try:
            _conn.total_changes
        except (sqlite3.ProgrammingError, sqlite3.OperationalError):
            _conn = None
    if _conn is None:
        os.makedirs(DATA, exist_ok=True)
        db_file = os.path.join(DATA, "clipforge.db")
        # Migrate existing db if present in _internal/data
        if not os.path.exists(db_file) and getattr(sys, "frozen", False):
            old_db = os.path.join(ROOT, "_internal", "data", "clipforge.db")
            if os.path.exists(old_db):
                try:
                    shutil.copy2(old_db, db_file)
                except Exception:
                    pass
        _conn = sqlite3.connect(db_file, check_same_thread=False, timeout=60.0)
        _conn.row_factory = sqlite3.Row
        try:
            _conn.execute("PRAGMA journal_mode=WAL;")
            _conn.execute("PRAGMA synchronous=NORMAL;")
            _conn.execute("PRAGMA busy_timeout=60000;")
        except Exception:
            pass
        _conn.executescript(SCHEMA)
        for table, cols in MIGRATE.items():                     # upgrade databases from older versions
            have = [r[1] for r in _conn.execute(f"pragma table_info({table})").fetchall()]
            for name, decl in cols:
                if name not in have:
                    _conn.execute(f"alter table {table} add column {name} {decl}")
        _conn.commit()
    return _conn


def q(sql, args=(), one=False):
    for attempt in range(5):
        try:
            with _lock:
                rows = [dict(r) for r in conn().execute(sql, args).fetchall()]
            return (rows[0] if rows else None) if one else rows
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < 4:
                time.sleep(0.1 * (attempt + 1))
                continue
            raise


def ex(sql, args=()):
    for attempt in range(5):
        try:
            with _lock:
                cur = conn().execute(sql, args)
                conn().commit()
                return cur.lastrowid
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < 4:
                time.sleep(0.1 * (attempt + 1))
                continue
            raise


def now():
    return time.time()


def dumps(x):
    return json.dumps(x, ensure_ascii=False)


def setting(key, default=""):
    r = q("select value from settings where key=?", (key,), one=True)
    return r["value"] if r else default


def set_setting(key, value):
    ex("insert into settings(key,value) values(?,?) on conflict(key) do update set value=excluded.value", (key, value))
