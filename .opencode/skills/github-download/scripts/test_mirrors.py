#!/usr/bin/env python3
"""
GitHub 镜像测速脚本
测试常见 GitHub 镜像站点的可用性和下载速度

设计约束（实测教训，勿回退）：
- 限量下载：每个镜像最多读 MAX_TEST_BYTES（默认 1.5MB）即断开，
  用 已下载字节/耗时 估算速度，避免为测速下载整个大仓库。
- 硬超时：read_deadline 限制整个读取阶段（默认 15s），
  防止慢速滴流镜像把 urlopen 的"单次读超时"无限拖延。
- 配置落盘：保存到本技能根目录（scripts/ 的上一级），
  供 download.ps1 / download.sh 读取，跨平台不再写死 /root。
"""

import time
import json
import sys
import os
import urllib.request
import urllib.error
import socket

# 测试用的实际仓库（走真实 archive 链路；下载量由 MAX_TEST_BYTES 控制）
TEST_REPO = "alchaincyf/nuwa-skill"
TEST_URL_PATH = f"{TEST_REPO}/archive/refs/heads/main.zip"

# 2026-10-12 实测清理：hub.fastgit.xyz / hub.gitmirror.com / hub.gitmirror.cn
# DNS 已失效，gitclone.com HTTP 500，gh.api.99988866.xyz SSL 握手失败，
# ghps.cc 返回 HTML 错误页，mirror.ghproxy.com 连接超时 —— 均已移除，不再浪费超时等待。
MIRRORS = [
    # 代理型镜像（在 GitHub URL 前加前缀）
    {
        "name": "gh-proxy.com",
        "type": "prefix",
        "prefix": "https://gh-proxy.com/https://github.com/",
        "build_url": lambda: f"https://gh-proxy.com/https://github.com/{TEST_URL_PATH}",
    },
    {
        "name": "ghproxy.net",
        "type": "prefix",
        "prefix": "https://ghproxy.net/https://github.com/",
        "build_url": lambda: f"https://ghproxy.net/https://github.com/{TEST_URL_PATH}",
    },
    {
        "name": "gh.llkk.cc",
        "type": "prefix",
        "prefix": "https://gh.llkk.cc/https://github.com/",
        "build_url": lambda: f"https://gh.llkk.cc/https://github.com/{TEST_URL_PATH}",
    },
    {
        "name": "gh-proxy.ygxz.in",
        "type": "prefix",
        "prefix": "https://gh-proxy.ygxz.in/https://github.com/",
        "build_url": lambda: f"https://gh-proxy.ygxz.in/https://github.com/{TEST_URL_PATH}",
    },
    # 直接 GitHub（对照组，确认是否真的需要镜像）
    {
        "name": "github.com (direct)",
        "type": "direct",
        "prefix": "",
        "build_url": lambda: f"https://github.com/{TEST_URL_PATH}",
    },
]

# 每个镜像最多读取的字节数（速度估算样本量）
MAX_TEST_BYTES = 1536 * 1024
# 读取阶段硬超时（秒）：无论读没读完，到点即停
READ_DEADLINE_SECONDS = 15
# 无效样本判定：少于该字节数无法可靠估算速度
MIN_VALID_BYTES = 32 * 1024


def test_mirror(mirror, connect_timeout=10):
    """测试单个镜像：限量读取 + 硬超时，返回结果字典"""
    result = {
        "name": mirror["name"],
        "type": mirror["type"],
        "prefix": mirror.get("prefix", ""),
        "available": False,
        "speed_kbps": 0,
        "speed_mbps": 0,
        "time_seconds": 0,
        "file_size_kb": 0,
        "error": None,
    }

    test_url = mirror["build_url"]()
    downloaded = 0
    magic = b""
    start_time = time.time()

    try:
        req = urllib.request.Request(test_url, headers={"User-Agent": "github-download-mirror-test/1.0"})
        with urllib.request.urlopen(req, timeout=connect_timeout) as resp:
            deadline = time.time() + READ_DEADLINE_SECONDS
            while downloaded < MAX_TEST_BYTES:
                if time.time() > deadline:
                    break  # 慢速滴流：到点即停，按已有样本估算
                chunk = resp.read(65536)
                if not chunk:
                    break
                if downloaded == 0:
                    magic = chunk[:4]
                downloaded += len(chunk)

        elapsed = max(time.time() - start_time, 0.001)

        if downloaded == 0:
            result["error"] = "Empty response"
        elif magic != b"PK\x03\x04":
            result["error"] = "Not a ZIP stream (HTML error page?)"
        elif downloaded < MIN_VALID_BYTES:
            result["error"] = f"Too slow: only {downloaded}B in {READ_DEADLINE_SECONDS}s"
        else:
            result["available"] = True
            result["file_size_kb"] = downloaded / 1024
            result["time_seconds"] = elapsed
            result["speed_kbps"] = downloaded / elapsed / 1024
            result["speed_mbps"] = result["speed_kbps"] / 1024

    except urllib.error.HTTPError as e:
        result["error"] = f"HTTP {e.code}"
    except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
        result["error"] = "Timeout" if isinstance(e, (socket.timeout, TimeoutError)) else str(e)[:50]
    except Exception as e:
        result["error"] = str(e)[:50]

    return result


def test_all_mirrors(connect_timeout=10):
    """测试所有镜像并返回结果"""
    results = []

    print(f"测试 {len(MIRRORS)} 个 GitHub 镜像站点（每个最多 {MAX_TEST_BYTES // 1024}KB / {READ_DEADLINE_SECONDS}s）...")
    print(f"测试仓库: {TEST_REPO}")
    print("=" * 70)

    for mirror in MIRRORS:
        name = mirror["name"]
        print(f"测试 {name}...", end=" ", flush=True)
        result = test_mirror(mirror, connect_timeout)
        results.append(result)

        if result["available"]:
            speed_str = f"{result['speed_mbps']:.2f} MB/s" if result['speed_mbps'] >= 1 else f"{result['speed_kbps']:.1f} KB/s"
            print(f"✓ {speed_str} ({result['time_seconds']:.1f}s, {result['file_size_kb']:.1f}KB 样本)")
        else:
            print(f"✗ {result['error']}")

    print("=" * 70)

    available = [r for r in results if r["available"]]
    available.sort(key=lambda x: x["speed_kbps"], reverse=True)

    print(f"\n可用镜像: {len(available)}/{len(MIRRORS)}")

    if available:
        print("\n最快的镜像:")
        for i, r in enumerate(available[:5], 1):
            speed_str = f"{r['speed_mbps']:.2f} MB/s" if r['speed_mbps'] >= 1 else f"{r['speed_kbps']:.1f} KB/s"
            print(f"  {i}. {r['name']}: {speed_str}")

        best = available[0]
        print(f"\n★★ 推荐使用: {best['name']} ★★")
        return best, available, results
    else:
        print("\n⚠️ 没有可用的镜像!")
        return None, [], results


def skill_root_dir():
    """配置文件所在目录：本脚本位于 <skill>/scripts/，配置写到 <skill>/"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def save_config(best, available, output_dir=None):
    """保存镜像配置到技能根目录（跨平台）"""
    if output_dir is None:
        output_dir = skill_root_dir()

    config = {
        "best_mirror": {
            "name": best["name"],
            "type": best["type"],
            "prefix": best["prefix"],
            "speed_kbps": round(best["speed_kbps"], 1),
        },
        "available_mirrors": [
            {
                "name": m["name"],
                "type": m["type"],
                "prefix": m["prefix"],
                "speed_kbps": round(m["speed_kbps"], 1),
            }
            for m in available
        ],
        "test_repo": TEST_REPO,
        "test_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "update_interval_hours": 24,  # 建议 24 小时重新测试
    }

    os.makedirs(output_dir, exist_ok=True)
    config_file = os.path.join(output_dir, "mirror_config.json")
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    print(f"\n配置已保存到: {config_file}")
    return config_file


if __name__ == "__main__":
    connect_timeout = int(sys.argv[1]) if len(sys.argv) > 1 else 10

    best, available, results = test_all_mirrors(connect_timeout)

    if best:
        save_config(best, available)
