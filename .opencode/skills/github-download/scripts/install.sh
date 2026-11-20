#!/bin/bash
# GitHub 技能一键安装脚本
# 下载并安装技能到 CoPaw skills 目录

set -e

SKILLS_DIR="${HOME}/.copaw/workspaces/default/skills"
DOWNLOAD_SCRIPT="$(dirname "$0")/download.sh"

# 安装技能
install_skill() {
    local repo="$1"
    local skill_name="${2:-}"
    
    # 解析仓库名
    if [[ "$repo" =~ ^([^/]+)/([^/]+)$ ]]; then
        user="${BASH_REMATCH[1]}"
        repo_name="${BASH_REMATCH[2]}"
    elif [[ "$repo" =~ github\.com/([^/]+)/([^/]+) ]]; then
        user="${BASH_REMATCH[1]}"
        repo_name="${BASH_REMATCH[2]}"
    else
        echo "❌ 无法解析仓库: $repo"
        exit 1
    fi
    
    # 确定技能名称
    if [[ -z "$skill_name" ]]; then
        # 从仓库名推导技能名（去掉 -skill / -agent 等后缀，与 install.ps1 一致）
        skill_name="${repo_name%-skill}"
        skill_name="${skill_name%-agent}"
        skill_name="${skill_name%-claude}"
        skill_name="${skill_name%-zcode}"
    fi
    
    echo "📦 安装技能: $skill_name"
    echo "   来源: $user/$repo_name"
    echo "   目标: $SKILLS_DIR/$skill_name"
    
    # 创建临时目录
    TEMP_DIR="/tmp/skill_install_$$"
    mkdir -p "$TEMP_DIR"
    
    # 下载仓库
    if [[ -x "$DOWNLOAD_SCRIPT" ]]; then
        bash "$DOWNLOAD_SCRIPT" "$repo" "$TEMP_DIR" 120
    else
        # 直接下载
        timeout 120 curl -L -o "$TEMP_DIR/repo.zip" \
            "https://gh-proxy.com/https://github.com/${user}/${repo_name}/archive/refs/heads/main.zip" \
            2>&1 | tail -3
        
        # 尝试 master 分支
        if [[ ! -f "$TEMP_DIR/repo.zip" ]] || [[ $(stat -c%s "$TEMP_DIR/repo.zip") -lt 100 ]]; then
            timeout 120 curl -L -o "$TEMP_DIR/repo.zip" \
                "https://gh-proxy.com/https://github.com/${user}/${repo_name}/archive/refs/heads/master.zip" \
                2>&1 | tail -3
        fi
        
        unzip -o "$TEMP_DIR/repo.zip" -d "$TEMP_DIR"
    fi
    
    # 查找解压目录
    EXTRACT_DIR=$(find "$TEMP_DIR" -maxdepth 1 -type d -name "${repo_name}*" | head -1)
    
    if [[ -z "$EXTRACT_DIR" ]]; then
        echo "❌ 解压失败，找不到仓库目录"
        exit 1
    fi
    
    # 检查是否有 SKILL.md
    if [[ ! -f "$EXTRACT_DIR/SKILL.md" ]]; then
        echo "⚠️  警告: 没有 SKILL.md 文件，可能不是有效的技能"
        echo "   仓库内容:"
        ls -la "$EXTRACT_DIR"
    fi
    
    # 创建目标目录并安装
    mkdir -p "$SKILLS_DIR/$skill_name"
    cp -r "$EXTRACT_DIR"/* "$SKILLS_DIR/$skill_name/"
    
    # 清理临时文件
    rm -rf "$TEMP_DIR"
    
    echo "✅ 安装完成: $SKILLS_DIR/$skill_name"
    echo ""
    echo "已安装文件:"
    ls -la "$SKILLS_DIR/$skill_name/"
    
    # 验证安装
    if [[ -f "$SKILLS_DIR/$skill_name/SKILL.md" ]]; then
        echo ""
        echo "技能信息:"
        head -20 "$SKILLS_DIR/$skill_name/SKILL.md"
    fi
}

# 查看已安装技能
list_skills() {
    echo "已安装技能:"
    echo ""
    for dir in "$SKILLS_DIR"/*/; do
        if [[ -f "$dir/SKILL.md" ]]; then
            name=$(basename "$dir")
            desc=$(grep -A2 "^description:" "$dir/SKILL.md" | head -3)
            echo "  📦 $name"
            echo "     $desc"
            echo ""
        fi
    done
}

# 主流程
main() {
    case "${1:-}" in
        "list")
            list_skills
            ;;
        "install")
            if [[ -z "${2:-}" ]]; then
                echo "用法: $0 install <user/repo> [skill_name]"
                exit 1
            fi
            install_skill "$2" "${3:-}"
            ;;
        *)
            if [[ -n "${1:-}" ]]; then
                # 直接安装
                install_skill "$1" "${2:-}"
            else
                echo "GitHub 技能安装器"
                echo ""
                echo "用法:"
                echo "  $0 <user/repo> [skill_name]  # 安装技能"
                echo "  $0 install <user/repo>       # 安装技能"
                echo "  $0 list                      # 查看已安装技能"
                echo ""
                echo "示例:"
                echo "  $0 alchaincyf/nuwa-skill"
                echo "  $0 alchaincyf/darwin-skill"
                echo "  $0 octocat/Hello-World hello-world"
            fi
            ;;
    esac
}

main "$@"