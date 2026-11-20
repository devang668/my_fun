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