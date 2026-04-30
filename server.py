"""Dance Toolkit — API server + static file serving on port 8091."""

from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
import json
import os
import shutil
import sqlite3
import subprocess
import threading
import urllib.parse

PORT = 8091
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DB_PATH = os.path.join(BASE_DIR, "database.db")
VIDEOS_DIR = os.path.join(BASE_DIR, "videos")

# Track download jobs: { routine_id: { "status": "...", "error": "..." } }
_download_jobs = {}


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS routines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS alternates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            routine_id INTEGER NOT NULL REFERENCES routines(id) ON DELETE CASCADE,
            youtube_url TEXT NOT NULL,
            label TEXT DEFAULT '',
            is_mirrored INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS moves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            routine_id INTEGER NOT NULL REFERENCES routines(id) ON DELETE CASCADE,
            alternate_id INTEGER REFERENCES alternates(id) ON DELETE SET NULL,
            name TEXT NOT NULL,
            start_time REAL NOT NULL,
            end_time REAL NOT NULL,
            max_clean_speed REAL DEFAULT 1.0,
            status TEXT DEFAULT 'learning',
            last_drilled TEXT,
            drill_count INTEGER DEFAULT 0,
            sort_order INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            move_id INTEGER NOT NULL REFERENCES moves(id) ON DELETE CASCADE,
            youtube_url TEXT,
            mime_type TEXT DEFAULT 'video/webm',
            upload_status TEXT DEFAULT 'pending',
            recorded TEXT DEFAULT (datetime('now')),
            notes TEXT DEFAULT ''
        );
    """)
    conn.commit()
    conn.close()


def rows_to_list(rows):
    return [dict(r) for r in rows]


def get_youtube_url_for_routine(routine_id):
    """Get the first alternate's YouTube URL for a routine."""
    conn = get_db()
    row = conn.execute(
        "SELECT youtube_url FROM alternates WHERE routine_id = ? ORDER BY sort_order LIMIT 1",
        (routine_id,)
    ).fetchone()
    conn.close()
    return row["youtube_url"] if row else None


def download_video(routine_id, youtube_url):
    """Download video with yt-dlp. Single file, no ffmpeg — client handles speed via playbackRate."""
    _download_jobs[routine_id] = {"status": "downloading", "error": None}
    video_path = os.path.join(VIDEOS_DIR, f"{routine_id}.mp4")

    try:
        if os.path.isfile(video_path):
            _download_jobs[routine_id] = {"status": "complete", "error": None}
            return

        yt_dlp = shutil.which("yt-dlp") or os.path.expanduser("~/.local/bin/yt-dlp")
        result = subprocess.run(
            [yt_dlp, "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best",
             "--merge-output-format", "mp4", "-o", video_path, youtube_url],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            _download_jobs[routine_id] = {"status": "error", "error": f"yt-dlp failed: {result.stderr[:200]}"}
            return

        if not os.path.isfile(video_path):
            _download_jobs[routine_id] = {"status": "error", "error": "Download produced no file"}
            return

        _download_jobs[routine_id] = {"status": "complete", "error": None}

    except subprocess.TimeoutExpired:
        _download_jobs[routine_id] = {"status": "error", "error": "Download timed out"}
    except Exception as e:
        _download_jobs[routine_id] = {"status": "error", "error": str(e)[:200]}


def get_fresh_youtube_token():
    """Load token.json, refresh if expired, return access_token string."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    token_path = os.path.join(BASE_DIR, "token.json")
    if not os.path.isfile(token_path):
        return None

    creds = Credentials.from_authorized_user_file(token_path)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return creds.token


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/health":
            return self.send_json({"status": "ok", "service": "dance-toolkit"})

        if path == "/api/routines":
            return self.handle_list_routines()

        # /api/routines/123
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "routines" and parts[2].isdigit():
            return self.handle_get_routine(int(parts[2]))

        # /api/youtube/token — serve fresh OAuth access token to client
        if path == "/api/youtube/token":
            return self.handle_youtube_token()

        # /api/attempts — all attempts across all routines
        if path == "/api/attempts":
            return self.handle_all_attempts()

        # /api/routines/123/moves/456/attempts
        if len(parts) == 6 and parts[0] == "api" and parts[1] == "routines" and parts[3] == "moves" and parts[5] == "attempts":
            return self.handle_list_attempts(int(parts[4]))

        # /api/routines/123/video/status
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "routines" and parts[2].isdigit() and parts[3] == "video":
            return self.handle_serve_video(int(parts[2]))

        if len(parts) == 5 and parts[0] == "api" and parts[1] == "routines" and parts[2].isdigit() and parts[3] == "video" and parts[4] == "status":
            return self.handle_video_status(int(parts[2]))

        # Static file serving with SPA fallback
        file_path = os.path.join(STATIC_DIR, path.lstrip("/"))
        if not os.path.isfile(file_path) and not path.startswith("/assets/") and not path.startswith("/api/"):
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        parts = path.strip("/").split("/")

        body = self.read_body()

        if path == "/api/routines":
            return self.handle_create_routine(body)

        # /api/routines/123/alternates
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "routines" and parts[2].isdigit() and parts[3] == "alternates":
            return self.handle_create_alternate(int(parts[2]), body)

        # /api/routines/123/moves
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "routines" and parts[2].isdigit() and parts[3] == "moves":
            return self.handle_create_move(int(parts[2]), body)

        # /api/routines/123/download-video
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "routines" and parts[2].isdigit() and parts[3] == "download-video":
            return self.handle_download_video(int(parts[2]))

        # /api/routines/123/moves/456/attempts — create attempt (metadata only)
        if len(parts) == 6 and parts[0] == "api" and parts[1] == "routines" and parts[3] == "moves" and parts[5] == "attempts":
            return self.handle_create_attempt(int(parts[4]), body)

        # /api/routines/123/moves/456/drill
        if len(parts) == 6 and parts[0] == "api" and parts[1] == "routines" and parts[3] == "moves" and parts[5] == "drill":
            return self.handle_drill_move(int(parts[4]))

        self.send_error_json(404, "Not found")

    def do_PUT(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        parts = path.strip("/").split("/")

        body = self.read_body()

        # /api/routines/123
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "routines" and parts[2].isdigit():
            return self.handle_update_routine(int(parts[2]), body)

        # /api/routines/123/alternates/456
        if len(parts) == 5 and parts[1] == "routines" and parts[3] == "alternates" and parts[4].isdigit():
            return self.handle_update_alternate(int(parts[4]), body)

        # /api/routines/123/moves/456
        if len(parts) == 5 and parts[1] == "routines" and parts[3] == "moves" and parts[4].isdigit():
            return self.handle_update_move(int(parts[4]), body)

        # /api/attempts/123 — update attempt metadata (e.g. youtube_url after client upload)
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "attempts" and parts[2].isdigit():
            return self.handle_update_attempt(int(parts[2]), body)

        self.send_error_json(404, "Not found")

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        parts = path.strip("/").split("/")

        # /api/routines/123
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "routines" and parts[2].isdigit():
            return self.handle_delete_routine(int(parts[2]))

        # /api/routines/123/alternates/456
        if len(parts) == 5 and parts[1] == "routines" and parts[3] == "alternates" and parts[4].isdigit():
            return self.handle_delete_alternate(int(parts[4]))

        # /api/routines/123/moves/456
        if len(parts) == 5 and parts[1] == "routines" and parts[3] == "moves" and parts[4].isdigit():
            return self.handle_delete_move(int(parts[4]))

        # /api/routines/123/moves/456/attempts/789
        if len(parts) == 7 and parts[1] == "routines" and parts[3] == "moves" and parts[5] == "attempts" and parts[6].isdigit():
            return self.handle_delete_attempt(int(parts[6]))

        self.send_error_json(404, "Not found")

    # --- Routine handlers ---

    def handle_list_routines(self):
        conn = get_db()
        routines = rows_to_list(conn.execute("SELECT * FROM routines ORDER BY created DESC").fetchall())
        for r in routines:
            moves = rows_to_list(conn.execute("SELECT * FROM moves WHERE routine_id = ?", (r["id"],)).fetchall())
            r["move_count"] = len(moves)
            r["solid_count"] = sum(1 for m in moves if m["status"] in ("solid", "mastered"))
            if moves:
                r["timing_floor"] = min(m["max_clean_speed"] for m in moves)
            else:
                r["timing_floor"] = None
        conn.close()
        self.send_json(routines)

    def handle_get_routine(self, routine_id):
        conn = get_db()
        routine = conn.execute("SELECT * FROM routines WHERE id = ?", (routine_id,)).fetchone()
        if not routine:
            conn.close()
            return self.send_error_json(404, "Routine not found")
        result = dict(routine)
        result["alternates"] = rows_to_list(
            conn.execute("SELECT * FROM alternates WHERE routine_id = ? ORDER BY sort_order", (routine_id,)).fetchall()
        )
        moves = rows_to_list(
            conn.execute("SELECT * FROM moves WHERE routine_id = ? ORDER BY sort_order, start_time", (routine_id,)).fetchall()
        )
        # Attach attempts to each move
        for m in moves:
            m["attempts"] = rows_to_list(
                conn.execute("SELECT * FROM attempts WHERE move_id = ? ORDER BY recorded DESC", (m["id"],)).fetchall()
            )
        result["moves"] = moves
        result["timing_floor"] = min((m["max_clean_speed"] for m in moves), default=None)
        conn.close()
        self.send_json(result)

    def handle_create_routine(self, body):
        name = body.get("name", "").strip()
        if not name:
            return self.send_error_json(400, "Name required")
        conn = get_db()
        cur = conn.execute("INSERT INTO routines (name) VALUES (?)", (name,))
        routine_id = cur.lastrowid
        # If a URL was provided, add it as the first alternate
        url = body.get("youtube_url", "").strip()
        if url:
            conn.execute(
                "INSERT INTO alternates (routine_id, youtube_url, label) VALUES (?, ?, ?)",
                (routine_id, url, body.get("label", ""))
            )
        conn.commit()
        result = dict(conn.execute("SELECT * FROM routines WHERE id = ?", (routine_id,)).fetchone())
        conn.close()
        self.send_json(result, status=201)

    def handle_update_routine(self, routine_id, body):
        conn = get_db()
        name = body.get("name", "").strip()
        if name:
            conn.execute("UPDATE routines SET name = ? WHERE id = ?", (name, routine_id))
            conn.commit()
        result = conn.execute("SELECT * FROM routines WHERE id = ?", (routine_id,)).fetchone()
        conn.close()
        if not result:
            return self.send_error_json(404, "Routine not found")
        self.send_json(dict(result))

    def handle_delete_routine(self, routine_id):
        conn = get_db()
        conn.execute("DELETE FROM routines WHERE id = ?", (routine_id,))
        conn.commit()
        conn.close()
        self.send_json({"deleted": True})

    # --- Alternate handlers ---

    def handle_create_alternate(self, routine_id, body):
        url = body.get("youtube_url", "").strip()
        if not url:
            return self.send_error_json(400, "youtube_url required")
        conn = get_db()
        cur = conn.execute(
            "INSERT INTO alternates (routine_id, youtube_url, label, is_mirrored, notes) VALUES (?, ?, ?, ?, ?)",
            (routine_id, url, body.get("label", ""), body.get("is_mirrored", 0), body.get("notes", ""))
        )
        conn.commit()
        result = dict(conn.execute("SELECT * FROM alternates WHERE id = ?", (cur.lastrowid,)).fetchone())
        conn.close()
        self.send_json(result, status=201)

    def handle_update_alternate(self, alt_id, body):
        conn = get_db()
        fields = []
        values = []
        for key in ("youtube_url", "label", "notes"):
            if key in body:
                fields.append(f"{key} = ?")
                values.append(body[key])
        if "is_mirrored" in body:
            fields.append("is_mirrored = ?")
            values.append(1 if body["is_mirrored"] else 0)
        if fields:
            values.append(alt_id)
            conn.execute(f"UPDATE alternates SET {', '.join(fields)} WHERE id = ?", values)
            conn.commit()
        result = conn.execute("SELECT * FROM alternates WHERE id = ?", (alt_id,)).fetchone()
        conn.close()
        if not result:
            return self.send_error_json(404, "Alternate not found")
        self.send_json(dict(result))

    def handle_delete_alternate(self, alt_id):
        conn = get_db()
        conn.execute("DELETE FROM alternates WHERE id = ?", (alt_id,))
        conn.commit()
        conn.close()
        self.send_json({"deleted": True})

    # --- Move handlers ---

    def handle_create_move(self, routine_id, body):
        name = body.get("name", "").strip()
        if not name:
            return self.send_error_json(400, "Name required")
        conn = get_db()
        cur = conn.execute(
            "INSERT INTO moves (routine_id, alternate_id, name, start_time, end_time, max_clean_speed, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (routine_id, body.get("alternate_id"), name,
             body.get("start_time", 0), body.get("end_time", 0),
             body.get("max_clean_speed", 1.0), body.get("status", "learning"))
        )
        conn.commit()
        result = dict(conn.execute("SELECT * FROM moves WHERE id = ?", (cur.lastrowid,)).fetchone())
        conn.close()
        self.send_json(result, status=201)

    def handle_update_move(self, move_id, body):
        conn = get_db()
        fields = []
        values = []
        for key in ("name", "start_time", "end_time", "max_clean_speed", "status", "alternate_id"):
            if key in body:
                fields.append(f"{key} = ?")
                values.append(body[key])
        if fields:
            values.append(move_id)
            conn.execute(f"UPDATE moves SET {', '.join(fields)} WHERE id = ?", values)
            conn.commit()
        result = conn.execute("SELECT * FROM moves WHERE id = ?", (move_id,)).fetchone()
        conn.close()
        if not result:
            return self.send_error_json(404, "Move not found")
        self.send_json(dict(result))

    def handle_delete_move(self, move_id):
        conn = get_db()
        conn.execute("DELETE FROM moves WHERE id = ?", (move_id,))
        conn.commit()
        conn.close()
        self.send_json({"deleted": True})

    def handle_drill_move(self, move_id):
        conn = get_db()
        conn.execute(
            "UPDATE moves SET last_drilled = datetime('now'), drill_count = drill_count + 1 WHERE id = ?",
            (move_id,)
        )
        conn.commit()
        result = conn.execute("SELECT * FROM moves WHERE id = ?", (move_id,)).fetchone()
        conn.close()
        if not result:
            return self.send_error_json(404, "Move not found")
        self.send_json(dict(result))

    # --- Attempt handlers ---

    def handle_create_attempt(self, move_id, body):
        """Create attempt record (metadata only). Client holds the video in IndexedDB."""
        mime_type = body.get("mime_type", "video/webm")
        conn = get_db()
        cur = conn.execute(
            "INSERT INTO attempts (move_id, mime_type, upload_status, notes) VALUES (?, ?, 'pending', ?)",
            (move_id, mime_type, body.get("notes", ""))
        )
        conn.commit()
        result = dict(conn.execute("SELECT * FROM attempts WHERE id = ?", (cur.lastrowid,)).fetchone())
        conn.close()
        self.send_json(result, status=201)

    def handle_update_attempt(self, attempt_id, body):
        """Update attempt metadata — client calls this after uploading to YouTube."""
        conn = get_db()
        fields = []
        values = []
        for key in ("youtube_url", "upload_status", "notes"):
            if key in body:
                fields.append(f"{key} = ?")
                values.append(body[key])
        if fields:
            values.append(attempt_id)
            conn.execute(f"UPDATE attempts SET {', '.join(fields)} WHERE id = ?", values)
            conn.commit()
        result = conn.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
        conn.close()
        if not result:
            return self.send_error_json(404, "Attempt not found")
        self.send_json(dict(result))

    def handle_all_attempts(self):
        """List all attempts across all routines, with context."""
        conn = get_db()
        attempts = rows_to_list(conn.execute(
            "SELECT a.*, m.name as move_name, m.start_time, m.routine_id, r.name as routine_name "
            "FROM attempts a "
            "JOIN moves m ON a.move_id = m.id "
            "JOIN routines r ON m.routine_id = r.id "
            "ORDER BY a.recorded DESC"
        ).fetchall())
        conn.close()
        self.send_json(attempts)

    def handle_list_attempts(self, move_id):
        conn = get_db()
        attempts = rows_to_list(conn.execute(
            "SELECT * FROM attempts WHERE move_id = ? ORDER BY recorded DESC", (move_id,)
        ).fetchall())
        conn.close()
        self.send_json(attempts)

    def handle_delete_attempt(self, attempt_id):
        conn = get_db()
        conn.execute("DELETE FROM attempts WHERE id = ?", (attempt_id,))
        conn.commit()
        conn.close()
        self.send_json({"deleted": True})

    # --- YouTube token handler ---

    def handle_youtube_token(self):
        """Serve a fresh OAuth access token so the client can upload directly to YouTube."""
        try:
            token = get_fresh_youtube_token()
        except Exception as e:
            return self.send_error_json(500, f"Token refresh failed: {str(e)[:200]}")
        if not token:
            return self.send_error_json(404, "YouTube not configured — run setup_youtube_oauth.py on Pi")
        self.send_json({"access_token": token})

    # --- Video download handlers ---

    def handle_download_video(self, routine_id):
        job = _download_jobs.get(routine_id)
        if job and job["status"] not in ("complete", "error"):
            return self.send_json({"status": job["status"], "message": "Download already in progress"})

        youtube_url = get_youtube_url_for_routine(routine_id)
        if not youtube_url:
            return self.send_error_json(400, "No YouTube URL found for this routine")

        thread = threading.Thread(target=download_video, args=(routine_id, youtube_url), daemon=True)
        thread.start()
        self.send_json({"status": "started"})

    def handle_video_status(self, routine_id):
        video_path = os.path.join(VIDEOS_DIR, f"{routine_id}.mp4")
        available = os.path.isfile(video_path)
        size = os.path.getsize(video_path) if available else 0
        job = _download_jobs.get(routine_id, {"status": "idle", "error": None})
        self.send_json({
            "available": available,
            "size": size,
            "status": job["status"],
            "error": job.get("error"),
        })

    def handle_serve_video(self, routine_id):
        video_path = os.path.join(VIDEOS_DIR, f"{routine_id}.mp4")
        if not os.path.isfile(video_path):
            return self.send_error_json(404, "Video not downloaded yet")

        file_size = os.path.getsize(video_path)
        range_header = self.headers.get("Range")

        if range_header:
            range_match = range_header.strip().replace("bytes=", "")
            range_parts = range_match.split("-")
            start = int(range_parts[0]) if range_parts[0] else 0
            end = int(range_parts[1]) if range_parts[1] else file_size - 1
            length = end - start + 1

            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.send_header("Content-Length", str(length))
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            with open(video_path, "rb") as f:
                f.seek(start)
                self.wfile.write(f.read(length))
        else:
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(file_size))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            with open(video_path, "rb") as f:
                shutil.copyfileobj(f, self.wfile)

    # --- Helpers ---

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, status, message):
        self.send_json({"error": message}, status=status)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    init_db()
    os.makedirs(VIDEOS_DIR, exist_ok=True)
    server = ThreadedHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Dance Toolkit serving on port {PORT}")
    try:
        token = get_fresh_youtube_token()
        if token:
            print("YouTube OAuth: configured (client can upload directly)")
        else:
            print("YouTube OAuth: not configured (run setup_youtube_oauth.py)")
    except Exception:
        print("YouTube OAuth: not configured (run setup_youtube_oauth.py)")
    server.serve_forever()
