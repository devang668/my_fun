<#
.SYNOPSIS
    GitHub 仓库下载脚本（Windows PowerShell 版）
.DESCRIPTION
    多通道下载仓库 ZIP 或 Release 资产：直连 codeload 优先（2026-10-05 实测墙内可达、
    github.com 主站反而不通），镜像做备选；无需 Git Bash。
    支持 main/master 分支回退、ZIP 完整性校验、curl 断点续传重试、仓库改名/迁移检测。
    大仓库（API size >50MB）或 ZIP 通道全灭时自动回退 git clone --depth 1
    （2026-11-09 nvzhuang 229MB 实测：archive ZIP 端点不支持 Range，克隆是唯一稳定路径）。
.PARAMETER Repo
    GitHub 仓库地址，支持 https://github.com/user/repo 或 user/repo。
.PARAMETER OutputDir
    输出目录，默认 $env:TEMP。
.PARAMETER TimeoutSec
    单次下载超时秒数，默认 600（实测 30MB+ 仓库 @94KB/s 需 ~340s）。
.PARAMETER Branch
    指定分支，默认自动探测（GitHub API 查 default_branch，失败再按 main -> master）。
.PARAMETER Release
    下载 Release 资产而非源码 ZIP。值为资产名匹配模式（支持通配符，如 "omniget-cli*"、
    "*.exe"），取最新 release 的第一个匹配资产。
.PARAMETER NoExtract
    只下载不解压（Release 二进制、或想自己处理 ZIP 时用）。
.EXAMPLE
    pwsh -File download.ps1 alchaincyf/nuwa-skill
.EXAMPLE
    pwsh -File download.ps1 alchaincyf/nuwa-skill -OutputDir D:\repos -TimeoutSec 180
.EXAMPLE
    pwsh -File download.ps1 yt-dlp/yt-dlp -Release "yt-dlp.exe" -NoExtract
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Repo,

    [Parameter(Position = 1)]
    [string]$OutputDir = "",

    [Parameter(Position = 2)]
    # 默认 600s：实测 30MB+ 仓库在 codeload 直连 ~94KB/s 时需 ~340s，120s 必超时（2026-10-12 nuwa-skill 实测）
    [int]$TimeoutSec = 600,

    [string]$Branch = "",

    [string]$Release = "",

    [switch]$NoExtract
)

$ErrorActionPreference = "Stop"
# PS5.1 的 Invoke-WebRequest 渲染进度条会显著拖慢下载；UTF-8 输出避免控制台乱码（v1.1.0 引入）
$ProgressPreference = "SilentlyContinue"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
# PS 5.1 默认可能不带 TLS 1.2，现代 CDN/镜像普遍只收 TLS 1.2+
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

# ---------- 解析仓库 ----------
if ($Repo -match "github\.com/([^/]+)/([^/?#]+)") {
    $User = $Matches[1]
    $RepoName = $Matches[2]
} elseif ($Repo -match '^([\w.-]+)/([\w.-]+)$') {
    # 白名单正则：仅 GitHub 实际允许的字符（防注入字符混入下游命令）
    $User = $Matches[1]
    $RepoName = $Matches[2]
} else {
    Write-Host "错误：无法解析仓库地址 $Repo" -ForegroundColor Red
    Write-Host "格式：https://github.com/user/repo 或 user/repo"
    exit 1
}
$RepoName = $RepoName -replace '\.git$', ''

# ---------- 输出目录 ----------
if ([string]::IsNullOrEmpty($OutputDir)) {
    $OutputDir = $env:TEMP
}
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
}

# ---------- 通道与镜像 ----------
# 通道优先级（2026-10-05 配对实测）：codeload.github.com 直连在墙内可达（github.com 主站 443 超时），
# 排第一；ghproxy.net p75 比 gh-proxy.com 快 4.8 倍（perf/报告.md），排镜像组首位。
# 若 mirror_config.json 测速新鲜（<24h），以测速最快的镜像开头。
$Mirrors = @(
    @{ Name = "ghproxy.net";  Prefix = "https://ghproxy.net/https://github.com/" },
    @{ Name = "gh-proxy.com"; Prefix = "https://gh-proxy.com/https://github.com/" }
)

$cfgPath = Join-Path $PSScriptRoot "..\mirror_config.json"
if (Test-Path $cfgPath) {
    try {
        # -Encoding UTF8:PS 5.1 默认按系统 ANSI 读无 BOM 文件,中文会破坏 JSON
        $cfg = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $maxAge = if ($cfg.update_interval_hours) { [double]$cfg.update_interval_hours } else { 24 }
        $ageHours = ((Get-Date) - [datetime]::Parse($cfg.test_time)).TotalHours
        $prefix = $cfg.best_mirror.prefix
        if ($ageHours -le $maxAge -and $prefix -like "https://*") {
            $rest = @($Mirrors | Where-Object { $_.Name -ne $cfg.best_mirror.name })
            $Mirrors = @(@{ Name = $cfg.best_mirror.name; Prefix = $prefix }) + $rest
            Write-Host "镜像顺序来自测速配置: $($cfg.best_mirror.name) ($($cfg.test_time))"
        }
    } catch {
        Write-Host "跳过镜像配置: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

# ---------- 结果分类 ----------
# 迁移提示输出为结构化行（MIGRATED_TO: owner/repo / REPO_GONE），调用方（agent）可据此走搜索流程
$script:RepoGone = $false
$script:MigratedTo = ""
# API 探测分支时顺手读 size 字段（KB），供大仓库预检（>50MB 优先 git 浅克隆）
$script:RepoSizeKB = 0

function Get-RepoInfo {
    # 探测默认分支 + 迁移检测：仓库改名后 api.github.com 会对旧坐标返回 301，
    # Invoke-WebRequest 跟随重定向后可从最终 URI 读出新坐标（2026-10-05 OpenSelena/omniget 实测路径）
    foreach ($api in @(
                "https://api.github.com/repos/${User}/${RepoName}",
                "https://gh-proxy.com/https://api.github.com/repos/${User}/${RepoName}"
            )) {
        try {
            $resp = Invoke-WebRequest -Uri $api -TimeoutSec 10 -UseBasicParsing -ErrorAction Stop `
                -Headers @{ "User-Agent" = "github-download-skill" }
            $json = $resp.Content | ConvertFrom-Json
            if ($json.full_name -and $json.full_name -ine "${User}/${RepoName}") {
                $script:MigratedTo = [string]$json.full_name
            }
            if ($json.size) { $script:RepoSizeKB = [long]$json.size }
            if ($json.default_branch) { return [string]$json.default_branch }
            return $null
        } catch {
            $r = $_.Exception.Response
            if ($r -ne $null -and [int]$r.StatusCode -eq 404) {
                $script:RepoGone = $true
            }
        }
    }
    return $null
}

function Invoke-ResumableGet {
    # 断点续传下载：优先 curl.exe -C -（Win10+ 自带）。
    # 2026-11-09 nvzhuang 实测：codeload/ghproxy 的 archive ZIP 是动态生成流，不支持 Range，
    # 有半截文件时 curl -C - 必报错误 33（确定性失败，原样重试无意义）——删半截文件从 0 重下
    param([string]$Url, [string]$OutFile)
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        & $curl.Source -L --fail --retry 1 --connect-timeout 15 `
            -C - -o $OutFile --max-time $TimeoutSec `
            -A "github-download-skill" -sS $Url
        if ($LASTEXITCODE -eq 33) {
            Write-Host "  端点不支持断点续传 (curl 33)，删除半截文件从头下载" -ForegroundColor Yellow
            Remove-Item $OutFile -Force -ErrorAction SilentlyContinue
            & $curl.Source -L --fail --connect-timeout 15 `
                -o $OutFile --max-time $TimeoutSec `
                -A "github-download-skill" -sS $Url
            return ($LASTEXITCODE -eq 0)
        }
        return ($LASTEXITCODE -eq 0)
    }
    try {
        Invoke-WebRequest -Uri $Url -OutFile $OutFile -TimeoutSec $TimeoutSec -UseBasicParsing -ErrorAction Stop
        return $true
    } catch {
        Write-Host "  请求失败: $($_.Exception.Message)" -ForegroundColor Yellow
        return $false
    }
}

function Test-ValidZip {
    param([string]$OutFile)
    if (-not (Test-Path $OutFile)) { return $false }
    $size = (Get-Item $OutFile).Length
    if ($size -lt 100) {
        Write-Host "  文件太小 ($size bytes)，可能不是有效下载" -ForegroundColor Yellow
        Get-Content $OutFile -Raw -ErrorAction SilentlyContinue | Write-Host
        return $false
    }
    # ZIP 魔数校验：PK\x03\x04
    $bytes = [System.IO.File]::ReadAllBytes($OutFile)[0..3]
    $magic = ($bytes | ForEach-Object { $_.ToString("x2") }) -join ""
    if ($magic -ne "504b0304") {
        Write-Host "  不是有效的 ZIP 文件（魔数 $magic）" -ForegroundColor Yellow
        return $false
    }
    return $true
}

function Show-SizeStats {
    param([string]$OutFile, [System.Diagnostics.Stopwatch]$Sw)
    $size = (Get-Item $OutFile).Length
    $sizeMB = [math]::Round($size / 1MB, 2)
    $speed = if ($Sw.Elapsed.TotalSeconds -gt 0) { [math]::Round($size / 1KB / $Sw.Elapsed.TotalSeconds, 1) } else { 0 }
    Write-Host ("✅ 下载成功: {0} ({1} MB, {2} KB/s)" -f $OutFile, $sizeMB, $speed) -ForegroundColor Green
    if ($size -gt 10MB) {
        Write-Host "⚠️  大文件 (~${sizeMB}MB)，解压可能需要一些时间" -ForegroundColor Cyan
    }
}

function Invoke-GitClone {
    # git 浅克隆兜底/大仓库首选通道（2026-11-09 nvzhuang 229MB 实战：ZIP 三通道全灭，
    # git smart HTTP 单 pack 流直连 github.com 稳定 76KB/s 一次成功；同入口镜像前缀做备选）
    param([string]$DestDir)
    $git = Get-Command git.exe -ErrorAction SilentlyContinue
    if (-not $git) {
        Write-Host "  git 不可用，无法走克隆通道" -ForegroundColor Yellow
        return $false
    }
    # 残留目录删不掉多半是上次中断的 git 进程锁着 .git/objects/pack/tmp_pack_*（Device or resource busy 实测）：
    # 先温和清理，失败再杀 git 进程后重清
    if (Test-Path $DestDir) {
        Remove-Item $DestDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path $DestDir) {
        Write-Host "  残留目录删不掉，尝试结束遗留 git 进程后重清..." -ForegroundColor Yellow
        Get-Process git -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
        Remove-Item $DestDir -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path $DestDir) {
            Write-Host "  无法清除残留目录 $DestDir（可能有进程占用）" -ForegroundColor Red
            return $false
        }
    }
    foreach ($u in @(
                "https://github.com/${User}/${RepoName}.git",
                "https://gh-proxy.com/https://github.com/${User}/${RepoName}.git"
            )) {
        Write-Host "git clone --depth 1: $u"
        & $git.Source clone --depth 1 $u $DestDir 2>&1 | ForEach-Object { Write-Host "  $_" }
        if ($LASTEXITCODE -eq 0 -and (Test-Path $DestDir)) { return $true }
        if (Test-Path $DestDir) { Remove-Item $DestDir -Recurse -Force -ErrorAction SilentlyContinue }
    }
    return $false
}

# ---------- 源码 ZIP 下载 ----------
function Invoke-ZipDownload {
    param([string]$Url, [string]$OutFile)
    Write-Host "下载: $Url"
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $ok = Invoke-ResumableGet -Url $Url -OutFile $OutFile
    $sw.Stop()
    if (-not $ok) {
        Write-Host "  下载失败" -ForegroundColor Yellow
        return $false
    }
    if (-not (Test-ValidZip -OutFile $OutFile)) { return $false }
    Show-SizeStats -OutFile $OutFile -Sw $sw
    return $true
}

# ---------- Release 资产下载 ----------
function Get-ReleaseAsset {
    # api releases/latest 拿资产清单 -> 匹配模式 -> 经镜像前缀下载（release 走 github.com 域名，可被镜像加速）
    $apiPaths = @(
        "https://api.github.com/repos/${User}/${RepoName}/releases/latest",
        "https://gh-proxy.com/https://api.github.com/repos/${User}/${RepoName}/releases/latest"
    )
    foreach ($api in $apiPaths) {
        try {
            $resp = Invoke-WebRequest -Uri $api -TimeoutSec 15 -UseBasicParsing -ErrorAction Stop `
                -Headers @{ "User-Agent" = "github-download-skill" }
            $rel = $resp.Content | ConvertFrom-Json
            $assets = @($rel.assets | Where-Object { $_.name -like $Release })
            if ($assets.Count -eq 0) {
                $names = ($rel.assets | ForEach-Object { $_.name }) -join ", "
                Write-Host "错误：最新 release ($($rel.tag_name)) 无匹配资产「$Release」" -ForegroundColor Red
                Write-Host "可用资产: $names"
                exit 1
            }
            $asset = $assets[0]
            Write-Host "选中资产: $($asset.name)（release $($rel.tag_name)，$([math]::Round($asset.size/1MB,1)) MB）"
            return [string]$asset.browser_download_url
        } catch {
            $r = $_.Exception.Response
            if ($r -ne $null -and [int]$r.StatusCode -eq 404) { $script:RepoGone = $true }
        }
    }
    return $null
}

# ---------- 主流程 ----------
Write-Host ""
Write-Host "═══════════════════════════════════════"
Write-Host "  GitHub 下载器 (Windows PowerShell)"
Write-Host "═══════════════════════════════════════"
Write-Host ""
Write-Host "📦 仓库: $User/$RepoName"
Write-Host "📁 输出: $OutputDir"
if ($Release) { Write-Host "🏷️  模式: Release 资产（匹配 $Release）" }
Write-Host ""

$outFile = if ($Release) {
    # 资产名先未知，占位文件名；拿到真实 URL 后重命名
    Join-Path $OutputDir "$RepoName-release.asset"
} else {
    Join-Path $OutputDir "$RepoName.zip"
}
if (Test-Path $outFile) { Remove-Item $outFile -Force }

$success = $false
$usedLabel = ""

if ($Release) {
    # ---- Release 模式：资产 URL（github.com 域）逐通道前缀下载 ----
    $assetUrl = Get-ReleaseAsset
    if (-not $assetUrl) {
        if ($script:RepoGone) {
            Write-Host "REPO_GONE: $User/$RepoName 不存在（已删除/转私有/改名）" -ForegroundColor Red
            exit 3
        }
        Write-Host "❌ 无法获取 release 信息（API 不可达）" -ForegroundColor Red
        exit 1
    }
    :relLoop foreach ($m in $Mirrors) {
        $url = "$($m.Prefix)" + ($assetUrl -replace '^https://github\.com/', '')
        Write-Host "下载: $url"
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        if (Invoke-ResumableGet -Url $url -OutFile $outFile) {
            $sw.Stop()
            if ((Test-Path $outFile) -and (Get-Item $outFile).Length -gt 100) {
                $assetName = [uri]::UnescapeDataString(([uri]$assetUrl).Segments[-1])
                $finalPath = Join-Path $OutputDir $assetName
                Move-Item $outFile $finalPath -Force
                $outFile = $finalPath
                Show-SizeStats -OutFile $outFile -Sw $sw
                $success = $true
                $usedLabel = $m.Name
                break relLoop
            }
        }
        Write-Host "  通道 $($m.Name) 失败，尝试下一个..." -ForegroundColor Yellow
    }
    if (-not $success) {
        Write-Host "❌ 所有通道均失败。可手动下载: $assetUrl" -ForegroundColor Red
        exit 1
    }
} else {
    # ---- 源码 ZIP 模式：codeload 直连 + 镜像 ----
    if ([string]::IsNullOrEmpty($Branch)) {
        $db = Get-RepoInfo
        if ($script:MigratedTo) {
            Write-Host "MIGRATED_TO: $script:MigratedTo（仓库已改名/迁移，沿用原坐标下载，GitHub 301 重定向自动落新坐标）" -ForegroundColor Cyan
        }
        if ($db) {
            $Branch = $db
            Write-Host "探测到默认分支: $db"
        }
    }

    if ($script:RepoGone) {
        Write-Host ""
        Write-Host "REPO_GONE: $User/$RepoName 不存在（已删除/转私有/改名）" -ForegroundColor Red
        Write-Host "处置建议：用 WebSearch 搜索「$User/$RepoName」或仓库名关键词，找新坐标（org 迁移常留 README 指路），确认后再发起下载。"
        exit 3
    }

    $branches = if ([string]::IsNullOrEmpty($Branch)) { @("main", "master") } else { @($Branch) }

    # ---------- 大仓库预检（2026-11-09 nvzhuang 229MB 实测）----------
    # codeload/镜像 archive ZIP 均不支持 Range，大仓库单流必超时且中断即废；
    # API 探测时已读 size 字段，>50MB 且 git 可用 → 优先 git 浅克隆（ZIP 只做克隆失败后的回退）
    $sizeMB = if ($script:RepoSizeKB -gt 0) { [math]::Round($script:RepoSizeKB / 1024, 1) } else { 0 }
    $gitCmd = Get-Command git.exe -ErrorAction SilentlyContinue
    if ($sizeMB -gt 50 -and $gitCmd) {
        Write-Host ("⚠️  大仓库 (~{0}MB)：ZIP 端点不支持断点续传，优先 git 浅克隆" -f $sizeMB) -ForegroundColor Cyan
        $cloneDest = Join-Path $OutputDir $RepoName
        if (Invoke-GitClone -DestDir $cloneDest) {
            Write-Host ""
            Write-Host "✅ 完成: $cloneDest" -ForegroundColor Green
            exit 0
        }
        Write-Host "git 克隆失败，回退 ZIP 通道..." -ForegroundColor Yellow
    }

    # codeload 直连通道（不经镜像，2026-10-05 实测墙内稳定）
    $channels = @( @{ Name = "codeload直连"; Prefix = "" } ) + $Mirrors

    $success = $false
    $usedBranch = ""
    :zipLoop foreach ($br in $branches) {
        foreach ($ch in $channels) {
            if ($ch.Prefix -eq "") {
                $url = "https://codeload.github.com/${User}/${RepoName}/zip/refs/heads/${br}"
            } else {
                # Prefix 自带 https://github.com/，直接拼 user/repo（勿再拼 github.com，会双重前缀 404）
                $url = "$($ch.Prefix)${User}/${RepoName}/archive/refs/heads/${br}.zip"
            }
            # 每通道独立临时文件（2026-11-09 教训：共用同一半截文件会把上一通道的
            # 续传失败传染给下一通道），成功后归位为最终文件名
            $safeCh = $ch.Name -replace '\W', '_'
            $chFile = Join-Path $OutputDir "$RepoName.$safeCh.zip"
            if (Test-Path $chFile) { Remove-Item $chFile -Force -ErrorAction SilentlyContinue }
            if (Invoke-ZipDownload -Url $url -OutFile $chFile) {
                Move-Item $chFile $outFile -Force
                $success = $true
                $usedBranch = $br
                $usedLabel = $ch.Name
                Write-Host "使用通道: $($ch.Name)  分支: $br"
                break zipLoop
            }
            Remove-Item $chFile -Force -ErrorAction SilentlyContinue
            Write-Host "通道 $($ch.Name) / 分支 $br 失败，尝试下一个..."
        }
    }

    if (-not $success) {
        # ---------- ZIP 全灭 → git 浅克隆兜底 ----------
        if ($gitCmd) {
            Write-Host ""
            Write-Host "ZIP 通道全灭，回退 git 浅克隆..." -ForegroundColor Cyan
            $cloneDest = Join-Path $OutputDir $RepoName
            if (Invoke-GitClone -DestDir $cloneDest) {
                Write-Host ""
                Write-Host "✅ 完成: $cloneDest" -ForegroundColor Green
                exit 0
            }
        }
        Write-Host ""
        Write-Host "❌ 所有通道均失败，请检查：" -ForegroundColor Red
        Write-Host "   1. 仓库是否存在: https://github.com/$User/$RepoName（404 = 可能已删除/改名/转私有）"
        Write-Host "   2. 网络是否可用（可运行 doctor.ps1 体检各通道）"
        Write-Host "   3. 稍后重试或手动下载"
        exit 1
    }
}

# ---------- 解压 ----------
if ($NoExtract) {
    Write-Host ""
    Write-Host "✅ 完成（未解压）: $outFile" -ForegroundColor Green
    exit 0
}

Write-Host ""
Write-Host "📂 解压..."
if ($Release) {
    Write-Host "✅ 完成（Release 资产不自动解压）: $outFile" -ForegroundColor Green
    exit 0
}

$extractBase = Join-Path $OutputDir "$RepoName-$usedBranch"
if (Test-Path $extractBase) { Remove-Item $extractBase -Recurse -Force }
Expand-Archive -Path $outFile -DestinationPath $OutputDir -Force

if (Test-Path $extractBase) {
    Write-Host "✅ 完成: $extractBase" -ForegroundColor Green
} else {
    Write-Host "✅ 完成: $OutputDir" -ForegroundColor Green
}
