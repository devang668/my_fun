#!/usr/bin/env python3
"""Build the skill registry consumed by /skills/index.html."""

import io
import json
import os
import re
import time

WORKSPACE = "/workspace"
PROJECT_SKILLS = os.path.join(WORKSPACE, ".opencode/skills")
EXTERNAL_SKILLS = "/root/.claude/skills"
OUTPUT = os.path.join(WORKSPACE, "skills/registry.json")

SOURCE_HINTS = {
    "self-check": "本地安装",
    "github-download": "SkillHub · @user_ab062dcd",
    "find-skills": "SkillHub 官方",
    "skillhub-preference": "SkillHub 官方",
    "claude-drawing": "GitHub · cloveric/claude-drawing-skill",
    "ink-wash-restyle": "GitHub · zhaimengrica-bit/ai-design-skills-ink-wash-restyle",
    "watercolor-svg": "GitHub · ABYR1206/watercolor-svg",
    "procedural-painting": "GitHub · dogum/procedural-art",
    "procedural-realism": "GitHub · dogum/procedural-art",
    "procedural-terrain-art": "GitHub · dogum/procedural-art",
}


def frontmatter(text):
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not match:
        return {}
    data = {}
    key = None
    for line in match.group(1).split("\n"):
        if re.match(r"^\s+", line) and key:
            continue
        found = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if found:
            key = found.group(1)
            data[key] = found.group(2).strip().strip("|").strip()
    return data


def collect(base, scope):
    items = []
    if not os.path.isdir(base):
        return items
    for entry in sorted(os.listdir(base)):
        if entry.startswith(".") or entry.startswith("@"):
            continue
        skill_dir = os.path.join(base, entry)
        skill_file = os.path.join(skill_dir, "SKILL.md")
        if not os.path.isfile(skill_file):
            continue
        with io.open(skill_file, encoding="utf-8") as handle:
            text = handle.read()
        meta = frontmatter(text)
        name = meta.get("name") or entry
        description = meta.get("description") or ""
        description = re.sub(r"\s+", " ", description).strip()
        if len(description) > 260:
            description = description[:257] + "..."
        items.append(
            {
                "name": name,
                "folder": entry,
                "scope": scope,
                "path": skill_dir,
                "version": meta.get("version") or meta.get("slug") or "",
                "description": description,
                "source": SOURCE_HINTS.get(entry, "本地安装"),
                "hasScripts": os.path.isdir(os.path.join(skill_dir, "scripts")),
            }
        )
    return items


def main():
    items = collect(PROJECT_SKILLS, "项目技能") + collect(EXTERNAL_SKILLS, "全局技能")
    payload = {
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "total": len(items),
        "skills": items,
    }
    with io.open(OUTPUT, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print("wrote %s with %d skills" % (OUTPUT, len(items)))


if __name__ == "__main__":
    main()