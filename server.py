"""Dance Toolkit — API server + static file serving on port 8091."""

from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
import json
import mimetypes
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
SPEEDS_DIR = os.path.join(BASE_DIR, "speeds")

SPEED_TIERS = [0.25, 0.5, 0.75, 0.85, 1.0]

# Track generation jobs: { routine_id: { "status": "...", "error": "..." } }
_generation_jobs = {}


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


def generate_speed_tiers(routine_id, youtube_url):
    """Download video with yt-dlp and generate speed tier files with ffmpeg."""
    _generation_jobs[routine_id] = {"status": "downloading", "error": None}
    routine_dir = os.path.join(SPEEDS_DIR, str(routine_id))
    os.makedirs(routine_dir, exist_ok=True)

    original_path = os.path.join(routine_dir, "original.mp4")

    try:
        # Download with yt-dlp (skip if already downloaded)
        if not os.path.isfile(original_path):
            yt_dlp = shutil.which("yt-dlp") or os.path.expanduser("~/.local/bin/yt-dlp")
            result = subprocess.run(
                [yt_dlp, "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best",
                 "--merge-output-format", "mp4", "-o", original_path, youtube_url],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode != 0:
                _generation_jobs[routine_id] = {"status": "error", "error": f"yt-dlp failed: {result.stderr[:200]}"}
                return

            if not os.path.isfile(original_path):
                _generation_jobs[routine_id] = {"status": "error", "error": "Download produced no file"}
                return

        # Copy original as 1.0x tier
        tier_1x = os.path.join(routine_dir, "1.0.mp4")
        if not os.path.isfile(tier_1x):
            shutil.copy2(original_path, tier_1x)

        # Generate speed tiers with ffmpeg
        for rate in SPEED_TIERS:
            if rate == 1.0:
                continue
            _generation_jobs[routine_id] = {"status": f"generating {rate}x", "error": None}
            tier_path = os.path.join(routine_dir, f"{rate}.mp4")
            if os.path.isfile(tier_path):
                continue

            # atempo filter only accepts 0.5-2.0, chain for lower values
            atempo_filters = []
            remaining = rate
            while remaining < 0.5:
                atempo_filters.append("atempo=0.5")
                remaining /= 0.5
            atempo_filters.append(f"atempo={remaining:.4f}")
            atempo_chain = ",".join(atempo_filters)

            # Use faster preset for extreme slow tiers (they produce much longer videos)
            preset = "ultrafast" if rate < 0.5 else "fast"
            crf = "32" if rate < 0.5 else "28"

            # setpts for video speed, atempo chain for audio
            cmd = [
                "ffmpeg", "-i", original_path,
                "-filter:v", f"setpts={1/rate:.4f}*PTS",
                "-filter:a", atempo_chain,
                "-c:v", "libx264", "-preset", preset, "-crf", crf,
                "-c:a", "aac", "-b:a", "128k",
                "-y", tier_path
            ]
            # Longer timeout for slow tiers (0.25x creates 4x duration video)
            tier_timeout = int(1800 / rate)  # 30min for 1x, 2h for 0.25x
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=tier_timeout)
            if result.returncode != 0:
                _generation_jobs[routine_id] = {"status": "error", "error": f"ffmpeg failed for {rate}x: {result.stderr[:200]}"}
                return

        _generation_jobs[routine_id] = {"status": "complete", "error": None}

    except subprocess.TimeoutExpired:
        _generation_jobs[routine_id] = {"status": "error", "error": "Process timed out"}
    except Exception as e:
        _generation_jobs[routine_id] = {"status": "error", "error": str(e)[:200]}


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

        # /api/routines/123/speeds
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "routines" and parts[2].isdigit() and parts[3] == "speeds":
            return self.handle_list_speeds(int(parts[2]))

        # /api/routines/123/speeds/0.5
        if len(parts) == 5 and parts[0] == "api" and parts[1] == "routines" and parts[2].isdigit() and parts[3] == "speeds":
            return self.handle_serve_speed(int(parts[2]), parts[4])

        # Static file serving with SPA fallback
        file_path = os.path.join(STATIC_DIR, path.lstrip("/"))
        if not os.path.isfile(file_path) and not path.startswith("/assets/") and not path.startswith("/api/"):
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        body = self.read_body()

        if path == "/api/routines":
            return self.handle_create_routine(body)

        parts = path.strip("/").split("/")

        # /api/routines/123/alternates
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "routines" and parts[2].isdigit() and parts[3] == "alternates":
            return self.handle_create_alternate(int(parts[2]), body)

        # /api/routines/123/moves
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "routines" and parts[2].isdigit() and parts[3] == "moves":
            return self.handle_create_move(int(parts[2]), body)

        # /api/routines/123/generate-speeds
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "routines" and parts[2].isdigit() and parts[3] == "generate-speeds":
            return self.handle_generate_speeds(int(parts[2]))

        # /api/routines/123/moves/456/drill
        if len(parts) == 6 and parts[0] == "api" and parts[1] == "routines" and parts[3] == "moves" and parts[5] == "drill":
            return self.handle_drill_move(int(parts[4]))

        self.send_error_json(404, "Not found")

    def do_PUT(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        body = self.read_body()
        parts = path.strip("/").split("/")

        # /api/routines/123
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "routines" and parts[2].isdigit():
            return self.handle_update_routine(int(parts[2]), body)

        # /api/routines/123/alternates/456
        if len(parts) == 5 and parts[1] == "routines" and parts[3] == "alternates" and parts[4].isdigit():
            return self.handle_update_alternate(int(parts[4]), body)

        # /api/routines/123/moves/456
        if len(parts) == 5 and parts[1] == "routines" and parts[3] == "moves" and parts[4].isdigit():
            return self.handle_update_move(int(parts[4]), body)

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

    # --- Speed tier handlers ---

    def handle_generate_speeds(self, routine_id):
        # Check if already running
        job = _generation_jobs.get(routine_id)
        if job and job["status"] not in ("complete", "error"):
            return self.send_json({"status": job["status"], "message": "Generation already in progress"})

        youtube_url = get_youtube_url_for_routine(routine_id)
        if not youtube_url:
            return self.send_error_json(400, "No YouTube URL found for this routine")

        # Start generation in background thread
        thread = threading.Thread(target=generate_speed_tiers, args=(routine_id, youtube_url), daemon=True)
        thread.start()
        self.send_json({"status": "started", "tiers": SPEED_TIERS})

    def handle_list_speeds(self, routine_id):
        routine_dir = os.path.join(SPEEDS_DIR, str(routine_id))
        available = []
        if os.path.isdir(routine_dir):
            for rate in SPEED_TIERS:
                tier_path = os.path.join(routine_dir, f"{rate}.mp4")
                if os.path.isfile(tier_path):
                    size = os.path.getsize(tier_path)
                    available.append({"rate": rate, "size": size})

        job = _generation_jobs.get(routine_id, {"status": "idle", "error": None})
        self.send_json({
            "tiers": available,
            "status": job["status"],
            "error": job.get("error"),
        })

    def handle_serve_speed(self, routine_id, rate_str):
        # Strip .mp4 extension if present
        rate_str = rate_str.replace(".mp4", "")
        try:
            rate = float(rate_str)
        except ValueError:
            return self.send_error_json(400, "Invalid rate")

        tier_path = os.path.join(SPEEDS_DIR, str(routine_id), f"{rate}.mp4")
        if not os.path.isfile(tier_path):
            return self.send_error_json(404, "Speed tier not found")

        # Serve the video file with range request support
        file_size = os.path.getsize(tier_path)
        range_header = self.headers.get("Range")

        if range_header:
            # Parse range header
            range_match = range_header.strip().replace("bytes=", "")
            parts = range_match.split("-")
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if parts[1] else file_size - 1
            length = end - start + 1

            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.send_header("Content-Length", str(length))
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            with open(tier_path, "rb") as f:
                f.seek(start)
                self.wfile.write(f.read(length))
        else:
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(file_size))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            with open(tier_path, "rb") as f:
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
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    init_db()
    os.makedirs(SPEEDS_DIR, exist_ok=True)
    server = ThreadedHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Dance Toolkit serving on port {PORT}")
    server.serve_forever()
