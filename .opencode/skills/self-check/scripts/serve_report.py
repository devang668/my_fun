#!/usr/bin/env python3
"""Serve the workspace as a static report server and track heartbeat / downtime."""

import argparse
import json
import os
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HEARTBEAT_INTERVAL = 30
DOWNTIME_THRESHOLD = 90


class Stats:
    def __init__(self, workspace):
        self.path = os.path.join(workspace, ".self-check-heartbeat.json")
        self.lock = threading.Lock()
        self.data = self._load()
        self.started_at = time.time()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            pass
        return {
            "down_total_sec": 0,
            "count": 0,
            "last_event": None,
            "last_beat": int(time.time()),
            "online_sec": 0,
        }

    def save(self):
        with self.lock:
            try:
                with open(self.path, "w", encoding="utf-8") as handle:
                    json.dump(self.data, handle, ensure_ascii=False, indent=2)
            except OSError:
                pass

    def beat(self):
        now = int(time.time())
        with self.lock:
            last = int(self.data.get("last_beat") or now)
            gap = now - last
            if gap > DOWNTIME_THRESHOLD:
                duration = gap - HEARTBEAT_INTERVAL
                if duration > 0:
                    self.data["count"] = int(self.data.get("count") or 0) + 1
                    self.data["down_total_sec"] = int(
                        self.data.get("down_total_sec") or 0
                    ) + duration
                    self.data["last_event"] = {
                        "kind": "sleep",
                        "start": last + HEARTBEAT_INTERVAL,
                        "end": now,
                        "duration": duration,
                    }
            self.data["last_beat"] = now
            self.data["online_sec"] = now - self.started_at
        self.save()

    def snapshot(self):
        with self.lock:
            data = dict(self.data)
        data["online_sec"] = int(time.time() - self.started_at)
        data["heartbeat_seconds"] = HEARTBEAT_INTERVAL
        return data


def start_heartbeat(stats):
    def loop():
        while True:
            stats.beat()
            time.sleep(HEARTBEAT_INTERVAL)

    threading.Thread(target=loop, daemon=True).start()


class Handler(SimpleHTTPRequestHandler):
    stats = None

    def do_GET(self):
        if self.path.split("?")[0] == "/hbstat.json":
            body = json.dumps(self.stats.snapshot(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, fmt, *args):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8930)
    parser.add_argument("--dir", default="/workspace")
    args = parser.parse_args()

    workspace = os.path.abspath(args.dir)
    Handler.stats = Stats(workspace)
    Handler.stats.beat()
    start_heartbeat(Handler.stats)

    handler = lambda *a, **kw: Handler(*a, directory=workspace, **kw)
    server = ThreadingHTTPServer(("0.0.0.0", args.port), handler)
    print("report server listening on %d, dir=%s" % (args.port, workspace), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()