# Shared helpers for install.ps1 / download-models.ps1 / uninstall.ps1.
# Windows PowerShell 5.1. This file is UTF-8 with BOM so 5.1 reads the Japanese text.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest is very slow in 5.1 with the progress bar
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch { }
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

# The OtoMaker folder (this file is in <OtoMaker>\installer\).
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$Venv = Join-Path $Root ".venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$McpExe = Join-Path $Venv "Scripts\otomaker-mcp.exe"
$DownloadExe = Join-Path $Venv "Scripts\otomaker-download.exe"
$DefaultDesktopConfig = Join-Path $env:APPDATA "Claude\claude_desktop_config.json"

function Write-Step([string]$Text) {
    Write-Host ""
    Write-Host "== $Text" -ForegroundColor Cyan
}
function Write-Ok([string]$Text) { Write-Host "  OK  $Text" -ForegroundColor Green }
function Write-Info([string]$Text) { Write-Host "      $Text" }
function Write-Warn2([string]$Text) { Write-Host "  !!  $Text" -ForegroundColor Yellow }
function Write-Err2([string]$Text) { Write-Host "  NG  $Text" -ForegroundColor Red }

# Y/N question. $script:AssumeYes answers yes without asking (non-interactive runs).
function Read-YesNo([string]$Question, [bool]$Default = $true) {
    if ($script:AssumeYes) {
        Write-Host "$Question -> Y (-Yes)"
        return $true
    }
    $hint = if ($Default) { "[Y/n]" } else { "[y/N]" }
    while ($true) {
        $a = Read-Host "$Question $hint"
        if ($null -eq $a) { return $Default }
        $a = $a.Trim().ToLowerInvariant()
        if ($a -eq "") { return $Default }
        if ($a -in @("y", "yes", "はい")) { return $true }
        if ($a -in @("n", "no", "いいえ")) { return $false }
        Write-Host "  y か n で答えてください (answer y or n)."
    }
}

# Run a program, capture stdout+stderr as text lines, never throw on stderr output.
function Invoke-Captured([string]$Exe, [string[]]$Arguments) {
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = & $Exe @Arguments 2>&1 | ForEach-Object { "$_" }
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $old
    }
    return [pscustomobject]@{ Code = $code; Lines = @($out) }
}

function Test-Venv {
    return (Test-Path -LiteralPath $VenvPython) -and (Test-Path -LiteralPath $McpExe)
}

# The Claude Code CLI (claude.exe or the npm claude.cmd), or $null.
function Find-ClaudeCli {
    $c = Get-Command claude -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) { return $c.Source }
    return $null
}

# Model menu, then otomaker-download (which shows the licence terms and asks y/N itself).
function Invoke-ModelDownload {
    if (-not (Test-Path -LiteralPath $DownloadExe)) {
        Write-Err2 "otomaker-download.exe がありません。先に install.cmd を実行してください。"
        return $false
    }
    Write-Host "どのモデルを取得しますか？ (Which models?)"
    Write-Host "  1) sfx + music  効果音と音楽の小型モデル（おすすめ。最大 120 秒）"
    Write-Host "  2) sfx          効果音の小型モデルだけ"
    Write-Host "  3) music        音楽の小型モデルだけ"
    Write-Host "  4) all          上の 2 つと medium（大きめの音楽モデル、最大 380 秒。容量が大きい）"
    Write-Host "  0) 今は取得しない (skip)"
    Write-Host "  取得していないモデルは、取得するまで生成に使えません（後で download-models.cmd から取得できます）。"
    $map = @{ "1" = @("sfx", "music"); "2" = @("sfx"); "3" = @("music"); "4" = @("all") }
    while ($true) {
        $a = Read-Host "番号を入力 (1-4, 0) [1]"
        if ($null -eq $a -or $a.Trim() -eq "") { $a = "1" }
        $a = $a.Trim()
        if ($a -eq "0") {
            Write-Info "モデルの取得を飛ばしました。後で download-models.cmd から取得できます。"
            return $true
        }
        if ($map.ContainsKey($a)) { break }
        Write-Host "  1-4 か 0 を入力してください。"
    }
    Write-Host ""
    Write-Host "次にファイルの一覧とライセンス条件が表示されます。同意する場合は y を入力してください。"
    Write-Host "(The licence terms follow; type y to agree and download.)"
    # Start-Process keeps the program on this console: its "[y/N]" prompt has no line end and
    # would stay hidden if its output went through the PowerShell pipeline.
    $p = Start-Process -FilePath $DownloadExe -ArgumentList $map[$a] -NoNewWindow -Wait -PassThru
    $code = $p.ExitCode
    if ($code -eq 0) { Write-Ok "モデルの準備ができました。"; return $true }
    if ($code -eq 1) {
        Write-Warn2 "同意しなかったため、何もダウンロードしていません。後で download-models.cmd から取得できます。"
        return $true
    }
    if ($code -eq 4) {
        Write-Warn2 "同意を尋ねる画面（コンソール）が見つからなかったため、何もダウンロードしていません。コマンドプロンプトから download-models.cmd を実行してください。"
        return $false
    }
    Write-Err2 "モデルの取得に失敗しました（終了コード $code）。ネットワークを確かめて download-models.cmd を実行し直してください。"
    return $false
}
