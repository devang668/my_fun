---
name: self-check
description: Use when the user says 自检 / 服务巡检 / 检查运行中的服务 / 服务列表 / 端口检查 / self-check. Scans listening ports, probes HTTP health, updates a service manifest, writes a report page, serves it on port 8930 and returns a preview URL with downtime and token stats.
---

# 自检技能（Self-Check）

一键巡检当前容器里跑着的服务：增量对比端口清单、探测 HTTP 健康状态、生成报告页并给出预览地址。

## 触发词

"自检"、"服务巡检"、"检查运行中的服务"、"服务列表"、"端口检查"、"self-check"

## 依赖（随技能自带，路径相对本技能目录）

| 文件 | 用途 |
|---|---|
| `scripts/selfcheck_scan.py` | 端口扫描 + HTTP 健康探测 + 写回清单与报告页 |
| `scripts/serve_report.py` | 报告页服务器（默认 8930），内置心跳与掉线统计 |
| `/workspace/.self-check-manifest.json` | 服务清单（增量基准，首次运行时自动生成） |
| `/workspace/.self-check-heartbeat.json` | 心跳落盘（运行报告服务器时自动生成） |
| `/workspace/self-check.html` | 报告页（首次扫描时自动生成） |

如果环境里已有平台版脚本（例如 `/root/.codingmatrix/project-tpl/.ai-ready/skills/self-check/scripts/selfcheck_scan.py`），优先使用平台版；不存在时使用本技能自带的 `scripts/`。

## 执行流程

### 1. 增量扫描

```bash
python3 .opencode/skills/self-check/scripts/selfcheck_scan.py
```

输出 JSON 字段：`added` / `removed` / `ok` / `down` / `uptime` / `unchanged` / `page`。

- 全部正常且无增减：直接跳到回复模板
- `removed` 非空：告知用户哪些端口的服务已停止
- `down` 非空：报告中对应条目标「无响应」

### 2. 确保报告服务器在跑

```bash
ss -tlnp 2>/dev/null | grep :8930
```

未监听时用后台终端工具启动（已存在则复用，勿重复启动）：

```bash
python3 .opencode/skills/self-check/scripts/serve_report.py --port 8930 --dir /workspace
```

### 3. 获取公网地址

调用 `request_preview(8930)` 得到 `https://8930-<环境后缀>.monkeycode-ai.online`，报告页完整地址 = 该地址 + `/self-check.html`。

### 4. 掉线统计

```bash
python3 -c "import json,urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8930/hbstat.json')))"
```

字段：`down_total_sec`（累计秒）、`count`（次数）、`last_event`（最近区间，含 `kind` = sleep/restart）、`online_sec`（本次在线秒）。时间戳一律按 UTC+8 换算：`datetime.fromtimestamp(ts + 8*3600)`。

### 5. Token 图表（可选）

```bash
python3 /root/.codingmatrix/project-tpl/.ai-ready/skills/token-stats/scripts/token_stats.py
```

该脚本属于平台技能，不存在时跳过本步，不影响自检主流程。

## 回复模板

第一行给报告页完整 URL，之后附服务表格与速览：

```text
https://8930-<环境后缀>.monkeycode-ai.online/self-check.html

| 端口 | 服务 |
|---|---|
| 8000 | 笔记站点 |
（按 manifest 逐行列出）

清单无增减，N 项服务全部正常，M 个公网服务均 200。

- 容器运行 X 天，无重启
- 累计掉线 X 小时 / N 次（全部休眠），最近一次 MM-DD HH:MM → HH:MM（X 小时）
- 本次在线 X 分钟
- Token（当日）：总 X 万，生成 X 万，缓存读 X 万；累计 X 亿
```

## 约束

- 只读操作：不重启、不杀已有服务；仅 8930 报告服务器可用后台终端管理
- 所有日期/时间一律使用 UTC+8，禁止依赖容器或设备时区
- 停止后台进程必须用后台终端管理工具 + 终端 ID，禁止 `pkill` / `killall`
- 清单稳定时不必提交报告页；刷新了 token 图表或新增服务时，再提交 `self-check.html` 与 manifest
- 掉线统计口径：服务端每 30 秒落盘一次心跳，间隔超过 90 秒记一次掉线；容器重启的终点用 PID 1 启动时刻校准（秒级精度），其余为休眠/网络中断（±30 秒）
