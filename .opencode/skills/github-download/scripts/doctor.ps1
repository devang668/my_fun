<#
.SYNOPSIS
    github-download 技能自检脚本（借鉴 OmniGet 的 doctor 模式：体检 + 错误表 + 修复建议）
.DESCRIPTION
    检查运行环境与各下载通道健康度，输出逐项结果与修复建议。下载失败时先跑这个。
.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File doctor.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"
# PS 5.1 默认可能不带 TLS 1.2，现代 CDN/镜像普遍只收 TLS 1.2+
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$results = New-Object System.Collections.Generic.List[object]

function Add-Check {
    param([string]$Name, [string]$Status, [string]$Detail, [string]$Fix)
    $results.Add([pscustomobject]@{ Item = $Name; Status = $Status; Detail = $Detail; Fix = $Fix })
}

function Test-UrlReachable {
    # 只探 1KB（curl --range）；判定标准=收到任意字节或正常结束。
    # 注意：部分服务器不响应 Range（动态生成 zip），max-time 掐断时 exit 28 但已收到字节 → 通道仍是活的
    param([string]$Url, [int]$TimeoutSec = 12)
    $curlExe = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curlExe) {
        $info = & $curlExe.Source -L --range 0-1023 -o NUL -sS --connect-timeout $TimeoutSec `
            --max-time $TimeoutSec -A "github-download-skill" `
            -w "http=%{http_code} bytes=%{size_download}" $Url 2>$null | Select-Object -Last 1
        if ($info -match 'bytes=(\d+)') { return @{ Ok = ([int]$Matches[1] -gt 0); Ms = -1 } }
        return @{ Ok = $false; Ms = -1 }
    }
    try {
        Invoke-WebRequest -Uri $Url -TimeoutSec $TimeoutSec -UseBasicParsing -ErrorAction Stop `
            -Headers @{ "User-Agent" = "github-download-skill" } | Out-Null
        return @{ Ok = $true; Ms = -1 }
    } catch {
        return @{ Ok = $false; Ms = -1 }
    }
}

Write-Host ""
Write-Host "═══════════════════════════════════════"
Write-Host "  github-download 体检 (doctor)"
Write-Host "═══════════════════════════════════════"
Write-Host ""

# 1. PowerShell 版本
$psVer = $PSVersionTable.PSVersion
if ($psVer.Major -ge 5) {
    Add-Check "PowerShell" "OK" "v$psVer" ""
} else {
    Add-Check "PowerShell" "FAIL" "v$psVer 过旧" "升级到 PowerShell 5.1+"
}

# 2. curl.exe（断点续传依赖，可选）
$curl = Get-Command curl.exe -ErrorAction SilentlyContinue
if ($curl) {
    $cv = & $curl.Source --version 2>$null | Select-Object -First 1
    Add-Check "curl.exe" "OK" ($cv -replace ' \(.*', '') ""
} else {
    Add-Check "curl.exe" "WARN" "未找到，续传重试退化为 Invoke-WebRequest" "Win10+ 自带；否则可忽略"
}

# 3. 各下载通道（探针仓库用永活的 octocat/Hello-World；2026-10-05 发现 alchaincyf/huashu-flash 已 404，
#    曾导致 doctor 把全部通道误报 FAIL——探针仓库本身必须稳定存在）
$probe = "octocat/Hello-World"
$channels = @(
    @{ Name = "codeload 直连"; Url = "https://codeload.github.com/$probe/zip/refs/heads/master" },
    @{ Name = "api.github.com"; Url = "https://api.github.com/repos/$probe" },
    @{ Name = "ghproxy.net 镜像"; Url = "https://ghproxy.net/https://github.com/$probe/archive/refs/heads/master.zip" },
    @{ Name = "gh-proxy.com 镜像"; Url = "https://gh-proxy.com/https://github.com/$probe/archive/refs/heads/master.zip" }
)

foreach ($ch in $channels) {
    $r = Test-UrlReachable -Url $ch.Url
    if ($r.Ok) {
        Add-Check $ch.Name "OK" "可达" ""
    } else {
        Add-Check $ch.Name "FAIL" "不可达" "若全部通道 FAIL = 断网或防火墙；单通道 FAIL = 该通道被墙，脚本会自动跳过"
    }
}

# 4. 测速配置新鲜度
$cfgPath = Join-Path $PSScriptRoot "..\mirror_config.json"
if (Test-Path $cfgPath) {
    try {
        $cfg = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $ageH = [math]::Round(((Get-Date) - [datetime]::Parse($cfg.test_time)).TotalHours, 1)
        if ($ageH -le 24) {
            Add-Check "镜像测速配置" "OK" "最快=$($cfg.best_mirror.name)，${ageH}h 前测速" ""
        } else {
            Add-Check "镜像测速配置" "WARN" "已过期（${ageH}h 前测速）" "运行 python scripts/test_mirrors.py 刷新"
        }
    } catch {
        Add-Check "镜像测速配置" "WARN" "解析失败: $($_.Exception.Message)" "删除 mirror_config.json 或重跑 test_mirrors.py"
    }
} else {
    Add-Check "镜像测速配置" "WARN" "不存在（用内置默认顺序）" "可选：运行 python scripts/test_mirrors.py 生成"
}

# 5. git（git clone 通道，可选）
$git = Get-Command git -ErrorAction SilentlyContinue
if ($git) {
    Add-Check "git" "OK" "git clone 通道可用" ""
} else {
    Add-Check "git" "WARN" "未安装（仅影响镜像 git 克隆，ZIP 下载不受影响）" "可选：winget install Git.Git"
}

# ---------- 汇总 ----------
Write-Host ""
foreach ($r in $results) {
    $color = switch ($r.Status) {
        "OK" { "Green" }
        "WARN" { "Yellow" }
        default { "Red" }
    }
    $icon = switch ($r.Status) {
        "OK" { "✅" }
        "WARN" { "⚠️ " }
        default { "❌" }
    }
    Write-Host ("{0} {1,-18} {2}" -f $icon, $r.Item, $r.Status) -ForegroundColor $color
    if ($r.Detail) { Write-Host ("     {0}" -f $r.Detail) }
    if ($r.Fix)   { Write-Host ("     修复: {0}" -f $r.Fix) -ForegroundColor Cyan }
}

$fail = @($results | Where-Object { $_.Status -eq "FAIL" }).Count
$warn = @($results | Where-Object { $_.Status -eq "WARN" }).Count
Write-Host ""
if ($fail -eq 0) {
    Write-Host "体检通过（$warn 项可忽略的警告）。" -ForegroundColor Green
    exit 0
} else {
    Write-Host "发现 $fail 项故障。所有通道都 FAIL 时先查网络；单通道 FAIL 脚本会自动切换，不阻塞下载。" -ForegroundColor Red
    exit 1
}
