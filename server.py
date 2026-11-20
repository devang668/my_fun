import json
import os
import time
import posixpath
import secrets
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

ROOT = os.path.dirname(os.path.abspath(__file__))
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "123456"
ALLOWED_FILES = {"ielts/notes.md", "Bei-ming/note.md"}
TOKENS = set()


def json_response(handler, status, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def log_message(self, fmt, *args):
        pass

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 5 * 1024 * 1024:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    def _auth_ok(self):
        header = self.headers.get("Authorization") or ""
        if not header.startswith("Bearer "):
            return False
        return header[7:].strip() in TOKENS

    def _target_path(self, rel):
        if rel not in ALLOWED_FILES:
            return None
        full = os.path.normpath(os.path.join(ROOT, rel))
        if not full.startswith(ROOT + os.sep):
            return None
        return full

    def end_headers(self):
        if self.path.endswith((".md", ".html", ".js")):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_POST(self):
        if self.path == "/api/login":
            payload = self._read_json() or {}
            if (
                payload.get("username") == ADMIN_USERNAME
                and payload.get("password") == ADMIN_PASSWORD
            ):
                token = secrets.token_hex(16)
                TOKENS.add(token)
                json_response(self, 200, {"token": token})
                return
            json_response(self, 401, {"error": "用户名或密码错误"})
            return
        if self.path == "/api/logout":
            header = self.headers.get("Authorization") or ""
            TOKENS.discard(header[7:].strip())
            json_response(self, 200, {"ok": True})
            return
        self.send_error(404)

    def do_PUT(self):
        if self.path != "/api/note":
            self.send_error(404)
            return
        if not self._auth_ok():
            json_response(self, 401, {"error": "请先登录"})
            return
        payload = self._read_json() or {}
        full = self._target_path(payload.get("path") or "")
        content = payload.get("content")
        if full is None or not isinstance(content, str):
            json_response(self, 400, {"error": "参数不合法"})
            return
        try:
            with open(full, "w", encoding="utf-8") as handle:
                handle.write(content)
        except OSError as exc:
            json_response(self, 500, {"error": "写入失败: %s" % exc})
            return
        json_response(self, 200, {"ok": True, "bytes": len(content.encode("utf-8"))})

    def _query_path(self, default):
        if "?" not in self.path:
            return default
        query = self.path.split("?", 1)[1]
        for pair in query.split("&"):
            if pair.startswith("path="):
                return unquote(pair[5:])
        return default

    def do_GET(self):
        if self.path.startswith("/api/version"):
            rel = self._query_path("ielts/notes.md")
            full = self._target_path(rel)
            if full is None or not os.path.isfile(full):
                json_response(self, 404, {"error": "文件不存在"})
                return
            stat = os.stat(full)
            version = "%s-%d" % (
                time.strftime("%y%m%d-%H%M%S", time.localtime(stat.st_mtime)),
                stat.st_size,
            )
            json_response(
                self,
                200,
                {
                    "version": version,
                    "file": rel,
                    "mtime": int(stat.st_mtime),
                    "size": stat.st_size,
                },
            )
            return
        if self.path.startswith("/api/note"):
            rel = self._query_path("ielts/notes.md")
            full = self._target_path(rel)
            if full is None or not os.path.isfile(full):
                json_response(self, 404, {"error": "文件不存在"})
                return
            with open(full, encoding="utf-8") as handle:
                json_response(self, 200, {"path": rel, "content": handle.read()})
            return
        super().do_GET()


if __name__ == "__main__":
    os.chdir(ROOT)
    port = int(os.environ.get("PORT", "8000"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
