#!/bin/bash
# GitHub 下载脚本
# 使用镜像加速下载 GitHub 仓库
# 支持场景判断：快速下载、技能安装、大仓库

set -e

# 默认配置
DEFAULT_MIRROR="gh-proxy.com"
OUTPUT_DIR="${2:-/tmp}"
TIMEOUT="${3:-120}"
SCENARIO="${4:-download}"  # download 或 install

# 场景判断阈值
LARGE_REPO_THRESHOLD=10485760  # 10MB

# 解析 GitHub URL
parse_repo() {
    local input="$1"
    
    # 完整 URL 格式
    if [[ "$input" =~ github\.com/([^/]+)/([^/]+) ]]; then
        USER="${BASH_REMATCH[1]}"
        REPO="${BASH_REMATCH[2]}"
    # user/repo 格式（白名单正则：仅 GitHub 实际允许的字符，防注入字符混入）
    elif [[ "$input" =~ ^([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)$ ]]; then
        USER="${BASH_REMATCH[1]}"
        REPO="${BASH_REMATCH[2]}"
    else
        echo "错误：无法解析仓库地址"
        echo "格式：https://github.com/user/repo 或 user/repo"
        exit 1
    fi
    
    # 清理仓库名（去掉 .git 后缀）
    REPO="${REPO%.git}"
}

# 场景判断输出
print_scenario_info() {
    case "$SCENARIO" in
        "install")
            echo "📋 场景: 技能安装"
            echo "   将安装到: ~/.copaw/workspaces/default/skills/"
            ;;
        "download")
            echo "📋 场景: 仓库下载"
            echo "   将解压到: $OUTPUT_DIR"
            ;;
    esac
}

# 构建镜像 URL
build_mirror_url() {
    local branch="${1:-main}"
    
    case "$DEFAULT_MIRROR" in
        "gh-proxy.com")
            MIRROR_URL="https://gh-proxy.com/https://github.com/${USER}/${REPO}/archive/refs/heads/${branch}.zip"
            ;;
        "ghproxy.net")
            MIRROR_URL="https://ghproxy.net/https://github.com/${USER}/${REPO}/archive/refs/heads/${branch}.zip"
            ;;
        *)
            MIRROR_URL="https://gh-proxy.com/https://github.com/${USER}/${REPO}/archive/refs/heads/${branch}.zip"
            ;;
    esac
}

# 尝试下载
try_download() {
    local url="$1"
    local output_file="$2"
    
    echo "下载: $url"
    timeout "$TIMEOUT" curl -L -o "$output_file" "$url" 2>&1 | tail -3
    
    # 验证文件
    if [[ ! -f "$output_file" ]]; then
        return 1
    fi
    
    local size=$(stat -c%s "$output_file" 2>/dev/null || stat -f%z "$output_file" 2>/dev/null)
    
    if [[ "$size" -lt 100 ]]; then
        echo "文件太小 ($size bytes)，可能下载失败"
        cat "$output_file"
        return 1
    fi
    
    # 检查 ZIP 魔数
    local magic=$(head -c 4 "$output_file" | od -An -tx1 | tr -d ' ')
    if [[ "$magic" != "504b0304" ]]; then
        echo "不是有效的 ZIP 文件"
        return 1
    fi
    
    # 大仓库提示
    if [[ "$size" -gt "$LARGE_REPO_THRESHOLD" ]]; then
        local size_mb=$((size / 1048576))
        echo "⚠️  大仓库 (~${size_mb}MB)，解压可能需要一些时间"
    fi
    
    echo "✅ 下载成功: $output_file ($size bytes)"
    return 0
}

# 镜像列表（备选机制；mirror.ghproxy.com 已于 2026-10-12 清理：连接超时）
MIRRORS=("gh-proxy.com" "ghproxy.net")

# v1.3.0: git 浅克隆（大仓库首选 + ZIP 全灭兜底）
# 2026-11-09 nvzhuang 229MB 实测：archive ZIP 端点不支持 Range（curl 33），
# git smart HTTP 单 pack 流直连 github.com 稳定 ~76KB/s 一次成功
try_git_clone() {
    command -v git >/dev/null 2>&1 || { echo "  git 不可用，无法走克隆通道"; return 1; }
    local dest="$OUTPUT_DIR/${REPO}"
    rm -rf "$dest" 2>/dev/null
    if [[ -d "$dest" ]]; then
        echo "  无法清除残留目录 $dest（可能有进程占用）"
        return 1
    fi
    local url rc
    for url in "https://github.com/${USER}/${REPO}.git" "https://gh-proxy.com/https://github.com/${USER}/${REPO}.git"; do
        echo "git clone --depth 1: $url"
        git clone --depth 1 "$url" "$dest" 2>&1 | tail -2
        rc=${PIPESTATUS[0]}
        if [[ $rc -eq 0 && -d "$dest" ]]; then
            echo "✅ 克隆完成: $dest"
            return 0
        fi
        rm -rf "$dest" 2>/dev/null
    done
    echo "  git 克隆失败"
    return 1
}

# v1.3.0: API 探测默认分支 + 仓库大小（大仓库预检数据源）
API_BRANCH=""
API_SIZE_KB=""
probe_api() {
    local json
    json=$(curl -sS --connect-timeout 10 --max-time 15 \
        -H "User-Agent: github-download-skill" \
        "https://api.github.com/repos/${USER}/${REPO}" 2>/dev/null || true)
    [[ -z "$json" ]] && return 0
    API_BRANCH=$(echo "$json" | sed -n 's/.*"default_branch"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)
    API_SIZE_KB=$(echo "$json" | sed -n 's/.*"size"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/p' | head -1)
    [[ -n "$API_BRANCH" ]] && echo "探测到默认分支: $API_BRANCH"
}

# 尝试所有镜像
try_all_mirrors() {
    local branch="$1"
    local output_file="$2"

    # codeload 直连优先（2026-10-05 实测墙内稳定；与 download.ps1 通道顺序一致）
    if try_download "https://codeload.github.com/${USER}/${REPO}/zip/refs/heads/${branch}" "$output_file"; then
        echo "使用通道: codeload直连"
        return 0
    fi
    echo "通道 codeload直连 失败，尝试镜像..."

    for mirror in "${MIRRORS[@]}"; do
        DEFAULT_MIRROR="$mirror"
        build_mirror_url "$branch"
        if try_download "$MIRROR_URL" "$output_file"; then
            echo "使用镜像: $mirror"
            return 0
        fi
        echo "镜像 $mirror 失败，尝试下一个..."
    done
    return 1
}

# 主流程
main() {
    local input="$1"
    
    parse_repo "$input"
    echo ""
    echo "═══════════════════════════════════════"
    echo "  GitHub 下载器"
    echo "═══════════════════════════════════════"
    echo ""
    echo "📦 仓库: $USER/$REPO"
    print_scenario_info
    echo "📁 输出: $OUTPUT_DIR"
    echo ""
    
    # 自动创建输出目录（边界条件修复）
    mkdir -p "$OUTPUT_DIR"

    cd "$OUTPUT_DIR"

    # v1.3.0: API 探测分支 + 大仓库预检
    probe_api

    # v1.3.0 大仓库预检：ZIP 端点不支持 Range（curl 33），>50MB 优先 git 浅克隆
    if [[ -n "$API_SIZE_KB" ]] && (( API_SIZE_KB / 1024 > 50 )); then
        echo "⚠️  大仓库 (~$((API_SIZE_KB / 1024))MB)：优先 git 浅克隆（ZIP 端点不支持断点续传）"
        if try_git_clone; then
            exit 0
        fi
        echo "git 克隆失败，回退 ZIP 通道..."
    fi

    local output_file="${REPO}.zip"
    local BRANCH=""

    # 分支遍历：API 探测优先，回退 main/master
    local branch_list=(main master)
    [[ -n "$API_BRANCH" ]] && branch_list=("$API_BRANCH")
    for branch in "${branch_list[@]}"; do
        if try_all_mirrors "$branch" "$output_file"; then
            BRANCH="$branch"
            break
        fi
        echo "分支 $branch 全部通道失败，尝试下一分支..."
    done

    if [[ -z "$BRANCH" ]]; then
        echo ""
        # v1.3.0: ZIP 全灭 → git 浅克隆兜底
        echo "ZIP 通道全灭，回退 git 浅克隆..."
        if try_git_clone; then
            exit 0
        fi
        echo ""
        echo "❌ 所有通道均失败，请检查："
        echo "   1. 仓库是否存在: https://github.com/${USER}/${REPO}"
        echo "   2. 网络是否可用"
        echo "   3. 稍后重试或手动下载"
        exit 1
    fi
    
    # 解压
    echo ""
    echo "📂 解压..."
    unzip -o "$output_file"
    
    local extract_dir="${REPO}-${BRANCH}"
    echo ""
    if [[ -d "$extract_dir" ]]; then
        echo "✅ 完成: $OUTPUT_DIR/$extract_dir"
        echo ""
        # 技能安装场景提示
        if [[ "$SCENARIO" == "install" ]]; then
            echo "💡 提示: 如需安装为技能，运行:"
            echo "   bash scripts/install.sh $USER/$REPO"
        fi
    else
        echo "✅ 完成: $OUTPUT_DIR"
    fi
}

# 运行
if [[ $# -lt 1 ]]; then
    echo "GitHub 下载器"
    echo ""
    echo "用法: $0 <github_url|user/repo> [output_dir] [timeout] [scenario]"
    echo ""
    echo "参数:"
    echo "  github_url   GitHub 仓库 URL 或 user/repo 格式"
    echo "  output_dir   输出目录，默认 /tmp"
    echo "  timeout      下载超时秒数，默认 120"
    echo "  scenario     download 或 install，默认 download"
    echo ""
    echo "示例:"
    echo "  $0 alchaincyf/nuwa-skill"
    echo "  $0 alchaincyf/nuwa-skill /tmp 120 install"
    exit 1
fi

main "$1"