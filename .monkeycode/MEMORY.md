# User Instruction Memory

This file records user instructions, preferences, and teachings for reference in future interactions.

## Format

### User Instruction Entry
[User Instruction Summary]
- Date: [YYYY-MM-DD]
- Context: [Mentioned scenario or time]
- Instructions:
  - [Content of user teaching or instruction, described line by line]

### Project Knowledge Entry
[Project Knowledge Summary]
- Date: [YYYY-MM-DD]
- Context: Discovered by Agent while performing [specific task description]
- Category: [Operations & Deployment|Build Methods|Testing Methods|Troubleshooting & Debugging|Workflow & Collaboration|Environment Configuration]
- Instructions:
  - [Specific knowledge points, described line by line]

## Deduplication Strategy
- Before adding a new entry, check for similar or identical instructions.
- If a duplicate is found, skip the new entry or merge it with the existing one.
- When merging, update the context or date information.
- This helps avoid redundant entries and keeps the memory file tidy.

## Entries

[User Instruction Summary]
- Date: 2026-11-18
- Context: 用户要求把学习笔记持续写入仓库，并说明"每一次都应该推送"
- Category: Workflow & Collaboration
- Instructions:
  - 每次更新笔记（Bei-ming/note.md）或其他文件后，都要立即 git commit 并 push 到 origin/main，不需要用户再次提醒。

[Project Knowledge Summary]
- Date: 2026-11-19
- Context: Discovered by Agent while building the notes web viewer
- Category: Build Methods
- Instructions:
  - 站点必须用 `cd /workspace && python3 server.py` 启动（不是 `python3 -m http.server`），因为编辑保存依赖 server.py 提供的 /api/login、/api/note 接口。
  - 服务端口固定 8000；修改 server.py 后需重启后台终端才生效。
  - 页面入口：/web/index.html（学习笔记）、/ielts/index.html（雅思口语）。
  - server.py 中的 admin/123456 仅为本地预览用的演示账号，不能用于生产环境。
[Project Knowledge Summary]
- Date: 2026-11-20
- Context: Discovered by Agent while installing the self-check skill into the project
- Category: Operations & Deployment
- Instructions:
  - 项目技能安装于 `.opencode/skills/self-check/`，入口页为 `/skills/index.html`，自检报告页为 `/self-check.html`。
  - 扫描命令：`python3 .opencode/skills/self-check/scripts/selfcheck_scan.py`；报告服务器：`python3 .opencode/skills/self-check/scripts/serve_report.py --port 8930 --dir /workspace`。
  - 扫描会跳过 8930 和 >=32768 的动态端口，避免把临时端口计入服务清单。
  - 新增 opencode 技能或修改 `.opencode/` 下的文件后，需要重启 opencode 才能加载。

[Project Knowledge Summary]
- Date: 2026-11-20
- Context: Discovered by Agent while mirroring the self-check skill to the platform skill directory
- Category: Environment Configuration
- Instructions:
  - 平台级技能目录为 `/root/.codingmatrix/project-tpl/.ai-ready/skills/<name>/`，每个技能含 `SKILL.md`、可选 `scripts/`，以及 `.agent-resource-version` 版本标记文件。
  - self-check 技能已同时安装到平台目录，脚本路径为 `/root/.codingmatrix/project-tpl/.ai-ready/skills/self-check/scripts/`。

[User Instruction Summary]
- Date: 2026-11-20
- Context: 用户要求安装 SkillHub 商店并确认设为优先技能安装源
- Category: Environment Configuration
- Instructions:
  - SkillHub CLI 已安装于 `/root/.local/bin/skillhub`（版本 2026.8.5），PATH 需包含 `/root/.local/bin`。
  - 已确认将 SkillHub 设为优先技能安装源：技能搜索/安装/升级时优先 `skillhub`，不可用或无匹配再回退 `clawhub`，安装前先汇总来源、版本与风险供用户确认。
  - 项目技能目录为 `/workspace/.opencode/skills`，安装命令示例：`skillhub install <name> --dir /workspace/.opencode/skills`。
  - 已安装技能：`find-skills`、`skillhub-preference`（另有本地 self-check）。
