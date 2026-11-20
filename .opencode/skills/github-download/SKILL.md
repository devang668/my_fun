---
name: github-download
slug: github-download
version: 1.3.0
displayName: GitHub 项目下载器
description: |
  GitHub 项目下载器：多通道自动切换（codeload 直连 + 镜像），断点续传（仅限支持 Range 的端点），下载 GitHub 仓库/Release 二进制/技能。
  大仓库（>50MB）或 ZIP 全灭自动回退 git 浅克隆；支持ZIP下载、Release 资产下载、Git克隆、技能一键安装、仓库改名/迁移检测，自动处理网络限制。

  使用场景：
  - 网络受限无法直接访问 GitHub
  - 需要下载仓库/技能/Release 二进制到本地
  - 仓库 404（可能已删除/改名/迁移，需要找新家）
  - 大仓库下载（ZIP 不可续传，自动走 git clone --depth 1）
  - 测试哪个镜像最快
  - 下载失败需要诊断网络/通道

  触发词（中文）：「下载GitHub」「下载仓库」「GitHub下载」「下载项目」「gh下载」「安装GitHub技能」「下载release」「仓库404了」
  触发词（英文）：「gh download」「github download」「clone github」「download repo」「download release」

  输出格式：下载的ZIP文件 + 解压后的目录（Release 模式输出资产文件；git 克隆路径输出仓库目录，保留 .git）
---

# GitHub 下载器

> 当前环境网络受限，自动选择可用通道与镜像加速下载；仓库消失时自动检测迁移。

## ⚠️ 平台选择（最重要）

| 平台 | 下载 | 安装技能 | 自检 |
|------|------|---------|------|
| **Windows**（默认） | `scripts/download.ps1` | `scripts/install.ps1` | `scripts/doctor.ps1` |
| macOS / Linux / Git Bash | `scripts/download.sh` | `scripts/install.sh` | （无，按错误表排查） |

检测到 `win32` 或 Windows 环境一律用 `.ps1`；`.sh` 保留原始 CoPaw 路径，仅作跨平台参考。

> **技能安装目录**：ZCode 环境装到 `~/.agents/skills/<name>/`，PowerShell 脚本默认指向此处。

## 核心功能

1. **多通道下载** — codeload 直连优先（墙内实测稳定，github.com 主站反而常不通），镜像做备选；断点续传仅在端点支持 Range 时有效（codeload/ghproxy 的 archive ZIP **不支持**，报 curl 33 时脚本自动删半截文件从 0 重下）
2. **大仓库自动克隆** — API 探测分支时顺手读 `size` 字段，>50MB 直接优先 `git clone --depth 1`（ZIP 只做克隆失败后的回退）；ZIP 通道全灭也自动回退克隆
3. **镜像测速** — 测试多个 GitHub 镜像选最快的（每镜像限量 1.5MB + 15 秒硬超时；配置 24h 新鲜期内直接复用）
4. **ZIP下载** — 下载仓库压缩包，魔数校验 + 分支自动探测；每通道独立临时文件，互不污染
5. **Release 资产下载** — `-Release <模式>` 下载最新 release 的二进制资产（如 yt-dlp.exe）
6. **仓库迁移检测** — 404 时区分「改名/迁移」（自动跟到新坐标）与「删除/转私有」（输出 REPO_GONE）
7. **技能安装** — 下载后自动安装到 skills 目录
8. **doctor 自检** — 下载失败先体检通道健康度，别盲目重试

---

## 镜像策略

镜像可用性随时间变化，**一切以运行时实测为准**：

1. `download.ps1` 运行时读取本目录 `mirror_config.json`，把 24h 内实测最快镜像排到镜像组首位；配置缺失/过期/损坏回退内置列表
2. 内置通道顺序：**codeload 直连 → ghproxy.net → gh-proxy.com**（2026-10-05 配对实测：ghproxy.net p75 快 4.8 倍）
3. 配置超过 24h → `python scripts/test_mirrors.py` 刷新（约 1 分钟）；测速失败也可直接下载
4. 历史教训：github.com 主站与 codeload.github.com 可达性**互相独立**（2026-09-29 主站超时但 codeload 可用），所以脚本保留两条互不依赖的通道
5. **镜像不总是更快**（2026-11-09 晚实测：codeload 直连 86KB/s，gh-proxy.com 仅 22KB/s、gh-proxy.com 克隆 3.5~76KB/s 波动）；git 克隆通道直连 `https://github.com/{user}/{repo}.git` 优先、镜像前缀兜底。决策前用 30 秒限速实测：`curl -L --max-time 30 -o /dev/null -w "%{speed_download}" <url>`

## 🔴 关键事实：archive ZIP 端点不支持断点续传（v1.3.0）

2026-11-09 下载 229MB 仓库实测推翻旧假设：

- `codeload.github.com/{u}/{r}/zip/...` 与 `ghproxy.net/.../archive/...` 是**动态生成的 ZIP 流，不支持 Range 请求**，`curl -C -` 必报错误 33（`HTTP server does not seem to support byte ranges`）
- 超时留下的半截 ZIP 是死重；脚本 v1.3.0 起每通道用独立临时文件 + 检测到错误 33 删档从 0 重下
- **大仓库唯一稳定路径是 git 浅克隆**：git smart HTTP 单 pack 流稳定（实测 76KB/s 直连 github.com 一次成功下完 216MB），git 对象协议天然支持恢复语义
- gh-download-embedai（PyPI）等多镜像并行分段工具同样只对**真二进制 release 资产**有用，对源码 ZIP 无解（Range 探测 0/3 回退单流主站直连会被墙强断）

## 执行流程

### Phase 1: 解析输入

用户输入：GitHub URL（`https://github.com/user/repo`）、简写（`user/repo`）、`下载 xxx`、技能安装（`安装 xxx 技能`）。
解析出：用户名、仓库名、分支（默认自动探测）、操作类型（download / install / release）。

#### 🔴 CHECKPOINT 1：场景判断（下载前）

| 场景 | 是否确认 | 确认内容 |
|------|---------|---------|
| **快速下载** | ❌ 跳过 | 直接执行，输出结果 |
| **技能安装** | ✅ 必须 | "将安装到 skills/{name}/，确认？" |
| **大仓库(>10MB)** | ⚠️ 提示 | "仓库较大(~XXMB)，预计等待XX秒" |
| **模糊输入** | ✅ 必须 | "解析为 user/repo，正确？" |

### Phase 2: 构建下载URL

```
源码 ZIP（直连）: https://codeload.github.com/{user}/{repo}/zip/refs/heads/{branch}    # 不支持 Range，仅小仓库
源码 ZIP（镜像）: https://ghproxy.net/https://github.com/{user}/{repo}/archive/refs/heads/{branch}.zip
Release 资产:    https://ghproxy.net/https://github.com/{user}/{repo}/releases/download/{tag}/{asset}   # 真二进制资产才可分段加速
Git 克隆（大仓库首选）: git clone --depth 1 https://github.com/{user}/{repo}.git   # 直连优先，慢则前缀 https://gh-proxy.com/
```

### Phase 3: 执行下载（Windows）

```powershell
# 源码 ZIP（自动解压；实际一律用脚本，勿手拼 curl）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/download.ps1 <user/repo> [-OutputDir <dir>] [-TimeoutSec <s>] [-Branch <b>]

# Release 资产（不解压；值为资产名通配模式）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/download.ps1 <user/repo> -Release "*.exe" -NoExtract
```

脚本自动完成：API 探测默认分支 + **读取仓库 size**（失败回退 main→master）→ **size>50MB 优先 git 浅克隆**（克隆失败才走 ZIP）→ 逐通道尝试（每通道独立临时文件；curl 33 = 端点不支持 Range，删半截文件从 0 重下）→ ZIP 魔数校验（`PK\x03\x04`，文件 >100 字节）→ 解压。ZIP 全灭自动回退 git 克隆。

#### 🔴 CHECKPOINT 2：下载完成确认

| 场景 | 确认行为 |
|------|---------|
| **快速下载** | ❌ 跳过，直接展示"下载完成：{路径}" |
| **技能安装** | ✅ 必须，展示："下载完成，将安装到 skills/{name}/，确认安装？" |
| **大仓库** | ⚠️ 提示，展示："下载完成(~XXMB)，已解压到 {路径}" |

### Phase 4: 解压安装（技能安装场景）

直接调用 `scripts/install.ps1`（已封装下载+解压+复制+校验）：

```powershell
pwsh -File scripts/install.ps1 <user/repo> [skill_name]
pwsh -File scripts/install.ps1 list   # 查看已安装技能
```

安装完成后展示：已安装文件列表 + SKILL.md 前 20 行。

---

## ⚠️ 仓库 404 / 迁移处置（重要）

实战案例：`tonhowtf/omniget` 404，实际是改名迁移到 `OpenSelena/omniget`。
脚本按退出码与结构化输出区分两种情况：

| 脚本输出 | 含义 | 处置 |
|---------|------|------|
| `MIGRATED_TO: owner/repo` | GitHub API 301 探测到新坐标 | **脚本沿用原坐标继续下载，GitHub 301 重定向自动落到新坐标**，无需干预；向用户说明迁移即可（迁移探测仅在 ZIP 模式且未指定 `-Branch` 时执行；Release 模式只识别 REPO_GONE） |
| 退出码 3 + `REPO_GONE` | API 返回 404：已删除/转私有/整账号消失 | **不要直接放弃**：用 WebSearch 搜「user/repo」和仓库名关键词，常见结果是迁移到了新 org 或有镜像；找到新坐标后向用户确认再下载 |

#### 🔴 CHECKPOINT 3：新坐标确认（REPO_GONE 处置中）

搜索到疑似新坐标后，**必须向用户展示证据（搜索结果/新仓库链接）并确认**，再用新坐标发起下载——不要拿着猜测的坐标直接下载。

---

## 工具脚本

### download.ps1 — Windows 下载（推荐）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/download.ps1 <github_url> [-OutputDir <dir>] [-TimeoutSec <s>] [-Branch <b>] [-Release <模式>] [-NoExtract]
```

参数：`github_url`（位置 0，URL 或 user/repo）；`-OutputDir`（默认 `$env:TEMP`，自动创建）；`-TimeoutSec`（默认 **600**——实测 30MB+ 仓库 @94KB/s 需 ~340s，120s 必超时）；`-Branch`（默认 API 探测）；`-Release`（资产名通配模式，如 `"*.exe"`）；`-NoExtract`（只下载不解压）。

特性：
- ✅ codeload 直连 + 双镜像备选，mirror_config.json 测速新鲜时自动置顶最快镜像
- ✅ 自动探测默认分支（GitHub API），失败按 main→master 回退；同时读 size 供大仓库预检
- ✅ 大仓库（>50MB）优先 `git clone --depth 1`（直连优先、gh-proxy.com 前缀兜底）；ZIP 全灭也自动回退克隆
- ✅ curl 33（端点不支持 Range）自动删半截文件从 0 重下；每通道独立临时文件互不污染
- ✅ ZIP 魔数校验、下载速度统计
- ✅ 仓库改名/迁移自动跟随（MIGRATED_TO）；删除/转私有输出 REPO_GONE（退出码 3）
- ✅ `-Release` 资产下载（走 releases/latest API，资产名通配匹配）
- ✅ 克隆前自动清理残留目录（删不掉先结束遗留 git 进程——tmp_pack 文件锁实测坑）

### doctor.ps1 — 体检（下载失败先跑这个）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/doctor.ps1
```

检查：PowerShell 版本、curl.exe（续传依赖）、各通道连通性、镜像测速配置新鲜度、git。每项输出 ✅/⚠️/❌ + 修复建议。

### install.ps1 — Windows 一键安装技能

```powershell
pwsh -File scripts/install.ps1 <user/repo> [skill_name]
pwsh -File scripts/install.ps1 list   # 查看已安装技能
```

### test_mirrors.py — 镜像测速

```bash
python scripts/test_mirrors.py [timeout]
```

每镜像限量 1.5MB + 15 秒硬超时（防慢速滴流拖死），输出速度排序并写入 `mirror_config.json`（24h 有效）。建议每天跑一次。

### install.sh / download.sh — POSIX 跨平台参考

`.sh` 脚本默认装到原始 CoPaw 目录（`~/.copaw/...`），ZCode 环境**不要用**，仅作参考。

---

## ⛔ 反例黑名单（不要做什么）

| # | 反模式 | 后果 | 正确做法 |
|---|--------|------|---------|
| 1 | 直接 `curl github.com` 主站下载 | 墙内常 443 超时 | 走 `download.ps1`（codeload 直连优先） |
| 2 | 依赖文档/记忆里的静态镜像状态 | 镜像随时会死（mirror.ghproxy.com 已失效） | 以 `mirror_config.json` 实测为准，过期先测速 |
| 3 | 不校验魔数直接解压 | HTML 错误页被当 ZIP，unzip 报错难排查 | 校验 `PK\x03\x04` + >100 字节（脚本已内置） |
| 4 | Git Bash 调 `.ps1` 时 `-OutputDir` 传 `/tmp` | PowerShell 不识别 POSIX 路径 | 传 Windows 路径（`$TEMP/xxx` 或 `C:\...`） |
| 5 | 见到 REPO_GONE 就放弃 | 错过改名迁移的仓库 | 按「404/迁移处置」搜索新坐标，确认后再下 |
| 6 | 用 `.sh` 脚本在 ZCode 装技能 | 装到 `~/.copaw/...` 错误目录 | Windows 用 `.ps1` |
| 7 | 手写/伪造 `mirror_config.json` | 假测速数据毒化后续下载 | 只用 `test_mirrors.py` 生成 |
| 8 | 用 `powershell` 改完 `.ps1` 后发现中文乱码就重下脚本 | 真因是 BOM 丢失（PS5.1 按 ANSI 读） | 检查文件头 UTF-8 BOM（`EF BB BF`） |
| 9 | 对 codeload/ghproxy 半截 ZIP 反复 `curl -C -` 重试 | 错误 33 是确定性失败（端点不支持 Range），重试 N 次都是秒败 | 检测到 33 删档从 0 重下，或直接换 git 浅克隆 |
| 10 | 大仓库（>50MB）死磕 ZIP 通道 | 单流 600s 只能拉 ~70-95MB，必超时且中断即废 | 让脚本走大仓库预检（自动克隆），或手动 `git clone --depth 1` |
| 11 | 多通道共用同一个半截下载文件 | 上一通道的续传失败传染给下一通道（某通道从未被从 0 试过） | 每通道独立临时文件（v1.3.0 已内置） |
| 12 | 克隆目标目录有残留直接重跑 | `destination path already exists`；被杀 git 进程锁 tmp_pack 报 Device or resource busy | 先 `taskkill //F //IM git.exe` + `rm -rf`（v1.3.0 克隆函数已内置） |

死镜像存档（2026-10-12 清理）：`mirror.ghproxy.com`（超时）、`hub.gitmirror.com` / `hub.fastgit.xyz`（DNS 失效）、`gitclone.com`（HTTP 500）。

---

## 错误处理

| 错误 | 退出码 | 一线修复 | 仍失败兜底 |
|------|--------|---------|-----------|
| 用法错误/地址无法解析 | 1 | 检查输入格式 | — |
| 所有通道失败（网络类） | 1 | 跑 `doctor.ps1` 定位断网还是单通道被墙 | 换时段重试 |
| REPO_GONE（仓库不存在） | 3 | 走「404/迁移处置」：搜索新坐标 → 确认 → 重下 | — |
| 分支 404 | — | 自动尝试下一个分支（API 探测优先） | — |
| curl 33（不支持 Range） | — | 脚本自动删半截文件从 0 重下 | 大仓库直接换 git 浅克隆 |
| 下载超时 | — | ZIP 通道换下一个；大仓库走克隆 | 大仓库加大 `-TimeoutSec` 意义不大（单流必然超时），克隆是正解 |
| 文件太小/ZIP 无效 | — | 清理后自动换下一个通道 | — |
| 克隆目标目录删不掉 | — | 脚本自动结束遗留 git 进程后重清 | 手动 `taskkill //F //IM git.exe` |
| 输出目录不存在 | — | 自动创建 | — |

## 边界条件处理

| 场景 | 行为 |
|------|------|
| 仓库名带 .git 后缀 | 自动清理 |
| 分支名不确定 | 先直连 GitHub API 探测（gh-proxy.com 兜底透传），避免盲试 404 |
| 仓库已改名 | API 301 自动发现新坐标并继续下载 |
| Release 无匹配资产 | 列出全部资产名后退出，供选择正确模式 |
| **大仓库（API size >50MB）** | **优先 `git clone --depth 1`（直连→镜像前缀），ZIP 仅作克隆失败回退**；克隆目录含 .git，只要源码可自行删除 |
| ZIP 通道全灭 | 自动回退 git 浅克隆；克隆也失败才报 exit 1 |
| 用户中断下载（Ctrl+C） | 进程即停；ZIP 通道半截文件不可续传（下次自动删档重来），克隆重跑前脚本自动清残留 |

---

## 配置文件

`mirror_config.json`（test_mirrors.py 生成，download.ps1 自动读取）：

```json
{
  "best_mirror": { "name": "ghproxy.net", "type": "prefix", "prefix": "https://ghproxy.net/https://github.com/", "speed_kbps": 662 },
  "available_mirrors": [ ... ],
  "test_time": "2026-09-27 03:40:00",
  "update_interval_hours": 24
}
```

## 注意事项

1. 网络受限环境保持多通道自动切换，不要只盯一个镜像
2. 部分镜像对特定仓库失效，自动切换备选；镜像列表以 mirror_config.json 为准
3. Release 资产只支持「最新 release」；要旧版本 tag 用 `-Branch`（源码）或手动拼 releases/download URL
4. 技能安装前检查 SKILL.md 是否存在（install.ps1 已内置校验）
5. Windows 环境优先 `.ps1`；从网络下载的脚本执行可能需要 `-ExecutionPolicy Bypass`
