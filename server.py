"""Dance Toolkit — serves the built Svelte frontend on port 8091."""

from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
import json
import os

PORT = 8091
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def do_GET(self):
        if self.path == "/api/health":
            self.send_json({"status": "ok", "service": "dance-toolkit"})
            return

        # SPA fallback: serve index.html for non-file paths
        file_path = os.path.join(STATIC_DIR, self.path.lstrip("/"))
        if not os.path.isfile(file_path) and not self.path.startswith("/assets/"):
            self.path = "/index.html"

        super().do_GET()

    def send_json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # quiet logs


if __name__ == "__main__":
    server = ThreadedHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Dance Toolkit serving on port {PORT}")
    server.serve_forever()
