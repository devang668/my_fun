#!/usr/bin/env python3
"""Scan listening TCP ports, probe HTTP health, update manifest and report page."""

import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request

WORKSPACE = os.environ.get("SELF_CHECK_WORKSPACE", "/workspace")
MANIFEST = os.path.join(WORKSPACE, ".self-check-manifest.json")
REPORT = os.path.join(WORKSPACE, "self-check.html")
SKIP_PORTS = {8930}
DYNAMIC_PORT_MIN = 32768
PROBE_TIMEOUT = 2.0


def listening_ports():
    ports = set()
    for name in ("tcp", "tcp6"):
        path = "/proc/net/" + name
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as handle:
            next(handle, None)
            for line in handle:
                fields = line.split()
                if len(fields) < 4:
                    continue
                if fields[3] != "0A":
                    continue
                try:
                    port = int(fields[1].split(":")[1], 16)
                except (IndexError, ValueError):
                    continue
                if port >= DYNAMIC_PORT_MIN:
                    continue
                ports.add(port)
    return sorted(ports)


def probe(port):
    url = "http://127.0.0.1:%d/" % port
    try:
        with urllib.request.urlopen(url, timeout=PROBE_TIMEOUT) as resp:
            return {"state": "ok", "http": resp.status}
    except urllib.error.HTTPError as exc:
        return {"state": "ok", "http": exc.code}
    except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as exc:
        return {"state": "down", "error": type(exc).__name__}


def load_manifest():
    try:
        with open(MANIFEST, encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict) and isinstance(data.get("ports"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"version": 1, "ports": {}}


def save_manifest(data):
    with open(MANIFEST, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def uptime_days():
    try:
        with open("/proc/uptime", encoding="utf-8") as handle:
            return float(handle.read().split()[0]) / 86400.0
    except (OSError, ValueError):
        return 0.0


def render_report(rows, summary):
    now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    items = "\n".join(
        '      <tr><td>%d</td><td>%s</td><td class="%s">%s</td></tr>'
        % (
            row["port"],
            row["label"],
            "ok" if row["state"] == "ok" else "bad",
            "正常 (HTTP %s)" % row["http"] if row["state"] == "ok" else "无响应",
        )
        for row in rows
    )
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>服务自检报告</title>
<style>
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; background: #f5f6f8; color: #22303d; margin: 0; padding: 28px 16px; }
  .wrap { max-width: 760px; margin: 0 auto; background: #fff; border: 1px solid #e3e6ea; border-radius: 12px; padding: 24px 28px; }
  h1 { font-size: 22px; margin: 0 0 6px; }
  .meta { color: #6b7a8c; font-size: 13px; margin-bottom: 18px; }
  table { width: 100%%; border-collapse: collapse; font-size: 14px; }
  th, td { text-align: left; padding: 9px 10px; border-bottom: 1px solid #eef1f4; }
  th { color: #6b7a8c; font-weight: 600; font-size: 13px; }
  td.ok { color: #2f7d4f; }
  td.bad { color: #b3261e; }
  .summary { margin-top: 18px; font-size: 14px; line-height: 1.9; color: #3c4a58; }
  a { color: #2f5d8c; }
</style>
</head>
<body>
<div class="wrap">
  <h1>服务自检报告</h1>
  <div class="meta">生成时间 %(now)s · 容器运行 %(uptime).1f 天 · 共 %(total)d 项</div>
  <table>
    <thead><tr><th>端口</th><th>服务</th><th>状态</th></tr></thead>
    <tbody>
%(items)s
    </tbody>
  </table>
  <div class="summary">%(summary)s</div>
</div>
</body>
</html>
""" % {
        "now": now,
        "uptime": summary["uptime"],
        "total": len(rows),
        "items": items or '      <tr><td colspan="3">暂无监听服务</td></tr>',
        "summary": summary["text"],
    }
    with open(REPORT, "w", encoding="utf-8") as handle:
        handle.write(html)


def main():
    previous = load_manifest()
    old_ports = set()
    for key in previous.get("ports", {}):
        try:
            old_ports.add(int(key))
        except (TypeError, ValueError):
            continue
    ports = [p for p in listening_ports() if p not in SKIP_PORTS]
    current = set(ports)

    rows = []
    for port in ports:
        result = probe(port)
        rows.append(
            {
                "port": port,
                "label": "服务 %d" % port,
                "state": result["state"],
                "http": result.get("http"),
            }
        )

    now = int(time.time())
    ports_meta = {}
    previous_meta = previous.get("ports", {})
    for port in ports:
        key = str(port)
        entry = previous_meta.get(key, {})
        entry["first_seen"] = entry.get("first_seen", now)
        entry["last_seen"] = now
        ports_meta[key] = entry
    for key in list(ports_meta):
        if int(key) not in current:
            del ports_meta[key]

    manifest = {
        "version": 1,
        "updated_at": now,
        "ports": ports_meta,
    }
    save_manifest(manifest)

    added = sorted(current - old_ports)
    removed = sorted(old_ports - current)
    ok = sum(1 for row in rows if row["state"] == "ok")
    down = [row["port"] for row in rows if row["state"] != "ok"]
    unchanged = len(current & old_ports)

    summary_text = (
        "本次扫描 %d 项：正常 %d 项，无响应 %d 项；新增 %d 项，移除 %d 项。"
        % (len(rows), ok, len(down), len(added), len(removed))
    )
    render_report(rows, {"uptime": uptime_days(), "text": summary_text})

    payload = {
        "added": added,
        "removed": removed,
        "ok": ok,
        "down": down,
        "uptime": round(uptime_days(), 2),
        "unchanged": unchanged,
        "page": REPORT,
        "ports": ports,
    }
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()