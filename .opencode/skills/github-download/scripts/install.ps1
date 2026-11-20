<#
.SYNOPSIS
    GitHub 技能一键安装（Windows PowerShell 版）
.DESCRIPTION
    下载 GitHub 仓库 ZIP 并安装到 ZCode 技能目录 ~/.agents/skills/<name>/。
    自动推导技能名（去除 -skill / -agent 等后缀），校验 SKILL.md。
.PARAMETER Repo
    GitHub 仓库地址，支持 https://github.com/user/repo 或 user/repo。
.PARAMETER SkillName
    可选，自定义技能目录名。不填则从仓库名推导。
.PARAMETER SkillsDir
    可选，技能安装根目录，默认 $HOME\.agents\skills。
.EXAMPLE
    pwsh -File install.ps1 alchaincyf/nuwa-skill
.EXAMPLE
    pwsh -File install.ps1 alchaincyf/nuwa-skill -SkillName my-nuwa
.EXAMPLE
    pwsh -File install.ps1 list
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Repo,

    [Parameter(Position = 1)]
    [string]$SkillName = "",

    [string]$SkillsDir = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

# ---------- 技能根目录 ----------
if ([string]::IsNullOrEmpty($SkillsDir)) {
    $SkillsDir = Join-Path $HOME ".agents\skills"
}

# ---------- list 子命令 ----------
if ($Repo -eq "list") {
    Write-Host "已安装技能（$SkillsDir）：" -ForegroundColor Cyan
    Write-Host ""
    if (-not (Test-Path $SkillsDir)) {
        Write-Host "  （无）"
        return
    }
    Get-ChildItem -Path $SkillsDir -Directory | ForEach-Object {
        $skillFile = Join-Path $_.FullName "SKILL.md"
        if (Test-Path $skillFile) {
            $name = $_.Name
            $descLine = Select-String -Path $skillFile -Pattern "^description:" -ErrorAction SilentlyContinue | Select-Object -First 1
            $desc = if ($descLine) { ($descLine.Line -replace '^description:\s*', '').Trim() } else { '' }
            # Handle YAML block scalar (description: | or >) — take the first indented content line after it
            if ($desc -eq '|' -or $desc -eq '>') {
                $lines = Get-Content $skillFile -TotalCount 25
                $startIdx = $descLine.LineNumber
                $nextLine = $lines | Select-Object -Skip $startIdx -First 3 | Where-Object { $_ -match '^\s+\S' } | Select-Object -First 1
                if ($nextLine) { $desc = $nextLine.Trim() }
            }
            if ($desc.Length -gt 120) { $desc = $desc.Substring(0,120) + '...' }
            Write-Host ("  📦 {0}" -f $name) -ForegroundColor Green
            Write-Host ("     {0}" -f $desc)
            Write-Host ""
        }
    }
    return
}

if ([string]::IsNullOrEmpty($Repo)) {
    Write-Host "GitHub 技能安装器（Windows）"
    Write-Host ""
    Write-Host "用法:"
    Write-Host "  pwsh -File install.ps1 <user/repo> [skill_name]"
    Write-Host "  pwsh -File install.ps1 list"
    Write-Host ""
    Write-Host "示例:"
    Write-Host "  pwsh -File install.ps1 alchaincyf/nuwa-skill"
    Write-Host "  pwsh -File install.ps1 alchaincyf/nuwa-skill my-nuwa"
    return
}

# ---------- 解析仓库 ----------
if ($Repo -match "github\.com/([^/]+)/([^/?#]+)") {
    $User = $Matches[1]
    $RepoName = $Matches[2]
} elseif ($Repo -match '^([^/]+)/([^/]+)$') {
    $User = $Matches[1]
    $RepoName = $Matches[2]
} else {
    Write-Host "❌ 无法解析仓库: $Repo" -ForegroundColor Red
    exit 1
}
$RepoName = $RepoName -replace '\.git$', ''

# ---------- 推导技能名 ----------
if ([string]::IsNullOrEmpty($SkillName)) {
    $SkillName = $RepoName
    foreach ($suf in @("-skill", "-agent", "-claude", "-zcode")) {
        $SkillName = $SkillName -replace ([regex]::Escape($suf) + '$'), ''
    }
}

Write-Host "📦 安装技能: $SkillName" -ForegroundColor Cyan
Write-Host "   来源: $User/$RepoName"
Write-Host "   目标: $SkillsDir\$SkillName"
Write-Host ""

# ---------- 调用 download.ps1 ----------
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$downloadScript = Join-Path $here "download.ps1"
$tempDir = Join-Path $env:TEMP ("skill_install_" + [System.Guid]::NewGuid().ToString("N").Substring(0,8))
New-Item -ItemType Directory -Force -Path $tempDir | Out-Null

if (Test-Path $downloadScript) {
    # 优先复用 pwsh（若安装），否则回退 Windows PowerShell
    $shell = if (Get-Command pwsh -ErrorAction SilentlyContinue) { "pwsh" } else { "powershell" }
    & $shell -NoProfile -ExecutionPolicy Bypass -File $downloadScript -Repo $Repo -OutputDir $tempDir -TimeoutSec 600
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ 下载失败，终止安装" -ForegroundColor Red
        Remove-Item -Recurse -Force $tempDir -ErrorAction SilentlyContinue
        exit 1
    }
} else {
    Write-Host "⚠️  未找到 download.ps1，直接下载..." -ForegroundColor Yellow
    $url = "https://gh-proxy.com/https://github.com/$User/$RepoName/archive/refs/heads/main.zip"
    try {
        Invoke-WebRequest -Uri $url -OutFile (Join-Path $tempDir "$RepoName.zip") -TimeoutSec 600 -UseBasicParsing
    } catch {
        Write-Host "❌ 直接下载失败: $($_.Exception.Message)" -ForegroundColor Red
        Remove-Item -Recurse -Force $tempDir -ErrorAction SilentlyContinue
        exit 1
    }
}

# ---------- 定位解压目录 ----------
$extractDir = Get-ChildItem -Path $tempDir -Directory | Where-Object { $_.Name -like "$RepoName*" } | Select-Object -First 1
if (-not $extractDir) {
    Write-Host "❌ 解压失败，找不到仓库目录" -ForegroundColor Red
    Remove-Item -Recurse -Force $tempDir -ErrorAction SilentlyContinue
    exit 1
}

# ---------- 校验 SKILL.md ----------
$skillFile = Join-Path $extractDir.FullName "SKILL.md"
if (-not (Test-Path $skillFile)) {
    Write-Host "⚠️  警告: 没有 SKILL.md 文件，可能不是有效的技能" -ForegroundColor Yellow
    Get-ChildItem $extractDir.FullName | ForEach-Object { Write-Host "   $($_.Name)" }
}

# ---------- 复制到技能目录 ----------
$dest = Join-Path $SkillsDir $SkillName
if (-not (Test-Path $SkillsDir)) { New-Item -ItemType Directory -Force -Path $SkillsDir | Out-Null }
if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }

Copy-Item -Path $extractDir.FullName -Destination $dest -Recurse -Force
Remove-Item -Recurse -Force $tempDir -ErrorAction SilentlyContinue

Write-Host "✅ 安装完成: $dest" -ForegroundColor Green
Write-Host ""
Write-Host "已安装文件:"
Get-ChildItem $dest | ForEach-Object { Write-Host ("   {0}" -f $_.Name) }

if (Test-Path (Join-Path $dest "SKILL.md")) {
    Write-Host ""
    Write-Host "技能信息（SKILL.md 前 20 行）:"
    Get-Content (Join-Path $dest "SKILL.md") -TotalCount 20 | ForEach-Object { Write-Host "   $_" }
}
