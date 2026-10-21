<#
.SYNOPSIS
  OtoMaker for Windows のインストーラー（install.cmd から呼ばれる）。

.DESCRIPTION
  展開した OtoMaker フォルダの中に、次を順に用意する。PATH やシステムの設定は変えない。
    1. uv        PATH の uv を使う。無ければ公式の配布物（バージョン固定、SHA256 照合）を runtime\uv\ に置く
    2. Python 3.12 と依存   uv sync --locked --extra tflite --no-dev（uv が管理する Python を runtime\python\ に）
    3. Stable Audio 3 のランタイム   上流コミット固定のアーカイブ（SHA256 照合）から stable-audio-3\optimized\tflite\ を展開
    4. モデル    otomaker-download を対話で起動（ライセンスの同意はそこで求める）
    5. MCP 登録  Claude Desktop と Claude Code に otomaker を登録（それぞれ Y/N で確認）

.PARAMETER SkipModels
  モデルの取得を飛ばす（後で download-models.cmd で取得できる）。
.PARAMETER NoPathUv
  PATH にある uv を使わず、固定バージョンの uv をダウンロードして使う。
.PARAMETER DesktopConfig
  Claude Desktop の設定ファイル。既定は %APPDATA%\Claude\claude_desktop_config.json。
.PARAMETER ClaudeCodeConfigDir
  Claude Code の設定フォルダ（CLAUDE_CONFIG_DIR としてこの処理の中だけで渡す）。既定は Claude Code 自体の既定。
.PARAMETER NoRegister
  MCP の登録を飛ばす。
.PARAMETER Yes
  確認（続行・登録）にすべて Y と答える。モデルのライセンス同意は代わりに答えない。
#>
param(
    [switch]$SkipModels,
    [switch]$NoPathUv,
    [string]$DesktopConfig = "",
    [string]$ClaudeCodeConfigDir = "",
    [switch]$NoRegister,
    [switch]$Yes
)
. (Join-Path $PSScriptRoot "common.ps1")
$script:AssumeYes = [bool]$Yes
if (-not $DesktopConfig) { $DesktopConfig = $DefaultDesktopConfig }

# Pinned downloads. To update: change the version / commit and paste the new SHA256
# (uv publishes <asset>.sha256 next to each asset; for the runtime archive, download it and run Get-FileHash).
$UvVersion = "0.12.23"
$UvAssets = @{
    "x86_64"  = "75d05de6762778c31ee183398de7dd15093fad0ed90b1f236d8205ea5ec00c90"
    "aarch64" = "13294e232ececbe709c06b74e6ced06f2a225ea5591476685362f22be56a50d5"
}
$UvMinVersion = [version]"0.6.0"   # older uv on PATH is not used
$Sa3Commit = "77e0398c26f7d22d801ec1bb036307e8b231f741"
$Sa3ArchiveSha256 = "04e85c047a1f85c3f66976768b1dd02e0774823944c6f1b2229c29e95cba71fe"
$Sa3Url = "https://github.com/Stability-AI/stable-audio-3/archive/$Sa3Commit.zip"

$RuntimeDir = Join-Path $Root "runtime"
$Sa3Dir = Join-Path $Root "stable-audio-3"
$TfliteDir = Join-Path $Sa3Dir "optimized\tflite"

function Get-VerifiedDownload([string]$Url, [string]$Dest, [string]$Sha256) {
    New-Item -ItemType Directory -Force -Path (Split-Path $Dest -Parent) | Out-Null
    $part = "$Dest.part"
    if (Test-Path -LiteralPath $part) { Remove-Item -LiteralPath $part -Force }
    Write-Info "ダウンロード中: $Url"
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $part
    $got = (Get-FileHash -LiteralPath $part -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($got -ne $Sha256.ToLowerInvariant()) {
        Remove-Item -LiteralPath $part -Force
        throw "SHA256 が一致しません（改ざんか配布元の変更の可能性）: $Url`n  期待値 $Sha256`n  実際   $got"
    }
    Move-Item -LiteralPath $part -Destination $Dest -Force
    Write-Ok "SHA256 を照合しました ($got)"
}

function Get-UvVersion([string]$Exe) {
    $r = Invoke-Captured $Exe @("--version")
    if ($r.Code -ne 0) { return $null }
    $m = [regex]::Match(($r.Lines -join " "), '(\d+\.\d+\.\d+)')
    if ($m.Success) { return [version]$m.Groups[1].Value }
    return $null
}

function Resolve-Uv {
    if (-not $NoPathUv) {
        $c = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($c) {
            $v = Get-UvVersion $c.Source
            if ($v -and $v -ge $UvMinVersion) {
                Write-Ok "PATH の uv を使います: $($c.Source) ($v)"
                return $c.Source
            }
            Write-Warn2 "PATH の uv ($($c.Source), $v) は古いため使いません。"
        }
    }
    $uvDir = Join-Path $RuntimeDir "uv"
    $uvExe = Join-Path $uvDir "uv.exe"
    if ((Test-Path -LiteralPath $uvExe) -and ((Get-UvVersion $uvExe) -eq [version]$UvVersion)) {
        Write-Ok "OtoMaker フォルダ内の uv を使います: $uvExe ($UvVersion)"
        return $uvExe
    }
    $arch = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
    $triple = if ($arch -eq "ARM64") { "aarch64" } else { "x86_64" }
    $asset = "uv-$triple-pc-windows-msvc.zip"
    $zip = Join-Path $uvDir $asset
    Get-VerifiedDownload "https://github.com/astral-sh/uv/releases/download/$UvVersion/$asset" $zip $UvAssets[$triple]
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    foreach ($n in @("uv.exe", "uvx.exe", "uvw.exe")) {
        $p = Join-Path $uvDir $n
        if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Force }
    }
    [System.IO.Compression.ZipFile]::ExtractToDirectory($zip, $uvDir)
    Remove-Item -LiteralPath $zip -Force
    $v = Get-UvVersion $uvExe
    if ($v -ne [version]$UvVersion) { throw "uv を展開しましたが起動できません: $uvExe" }
    Write-Ok "uv $UvVersion を OtoMaker フォルダ内に用意しました: $uvExe"
    return $uvExe
}

function Install-Runtime {
    $marker = Join-Path $TfliteDir "scripts\sa3_gradio.py"
    if (Test-Path -LiteralPath $marker) {
        Write-Ok "ランタイムは用意済みです: $TfliteDir"
        return
    }
    if (Test-Path -LiteralPath $Sa3Dir) {
        throw "$Sa3Dir はありますが、中に optimized\tflite\scripts\sa3_gradio.py がありません。フォルダ名を変えるか削除してから、もう一度実行してください。"
    }
    $zip = Join-Path $RuntimeDir "downloads\stable-audio-3-$($Sa3Commit.Substring(0, 7)).zip"
    if (-not (Test-Path -LiteralPath $zip) -or
        (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Sa3ArchiveSha256) {
        Get-VerifiedDownload $Sa3Url $zip $Sa3ArchiveSha256
    }
    # Only the parts OtoMaker loads: optimized/tflite/ (self-contained) and the licence.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $prefix = "stable-audio-3-$Sa3Commit/"
    $tmp = Join-Path $Root "stable-audio-3.partial"
    if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Recurse -Force }
    $z = [System.IO.Compression.ZipFile]::OpenRead($zip)
    $count = 0
    try {
        foreach ($e in $z.Entries) {
            if (-not $e.FullName.StartsWith($prefix)) { continue }
            $rel = $e.FullName.Substring($prefix.Length)
            $keep = $rel.StartsWith("optimized/tflite/") -or $rel -in @("LICENSE", "README.md")
            if (-not $keep -or $e.Name -eq "") { continue }
            $dest = Join-Path $tmp ($rel -replace '/', '\')
            New-Item -ItemType Directory -Force -Path (Split-Path $dest -Parent) | Out-Null
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($e, $dest, $true)
            $count++
        }
    } finally {
        $z.Dispose()
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $tmp "optimized\tflite\models\tflite") | Out-Null
    Set-Content -LiteralPath (Join-Path $tmp "OTOMAKER_RUNTIME.txt") -Encoding ASCII -Value @(
        "Stability-AI/stable-audio-3 commit $Sa3Commit (MIT)",
        "Extracted by OtoMaker install.ps1 from $Sa3Url (optimized/tflite, LICENSE, README.md only)")
    Rename-Item -LiteralPath $tmp -NewName "stable-audio-3"
    if (-not (Test-Path -LiteralPath $marker)) { throw "ランタイムの展開に失敗しました: $marker がありません" }
    Remove-Item -LiteralPath $zip -Force
    Write-Ok "ランタイム（コミット $($Sa3Commit.Substring(0, 7))、$count ファイル）を展開しました: $TfliteDir"
}

function Register-Desktop {
    Write-Info "設定ファイル: $DesktopConfig"
    $exists = Test-Path -LiteralPath (Split-Path $DesktopConfig -Parent)
    if (-not $exists) { Write-Info "（Claude Desktop の設定フォルダが見つかりません。未インストールなら N で構いません）" }
    if (-not (Read-YesNo "Claude Desktop に otomaker を登録しますか？ (Register in Claude Desktop?)" $exists)) {
        Write-Info "Claude Desktop への登録を飛ばしました。"
        return $false
    }
    $r = Invoke-Captured $VenvPython @("-I", "-m", "otomaker.mcp_config", "add", "--config", $DesktopConfig, "--command", $McpExe)
    $r.Lines | ForEach-Object { Write-Info $_ }
    if ($r.Code -eq 3) {
        Write-Err2 "設定ファイルを JSON として読めないため、変更していません。手で次を mcpServers に追加してください:"
        Write-Info ('"otomaker": { "command": "' + ($McpExe -replace '\\', '\\') + '", "args": [] }')
        return $false
    }
    if ($r.Code -ne 0) { throw "Claude Desktop の設定の書き込みに失敗しました（終了コード $($r.Code)）" }
    Write-Ok "Claude Desktop に登録しました。"
    return $true
}

function Register-ClaudeCode {
    $claude = Find-ClaudeCli
    $manual = "claude mcp add --scope user otomaker -- `"$McpExe`""
    if (-not $claude) {
        Write-Info "Claude Code（claude コマンド）が見つかりません。使う場合は、インストール後に次を実行してください:"
        Write-Info "  $manual"
        return $false
    }
    Write-Info "claude コマンド: $claude"
    if (-not (Read-YesNo "Claude Code に otomaker を登録しますか？（同名の登録は置き換えます） (Register in Claude Code?)" $true)) {
        Write-Info "Claude Code への登録を飛ばしました。後で登録するには: $manual"
        return $false
    }
    # Replace an earlier registration of the same name, if any (an error here just means there was none).
    $null = Invoke-Captured $claude @("mcp", "remove", "--scope", "user", "otomaker")
    $r = Invoke-Captured $claude @("mcp", "add", "--scope", "user", "otomaker", "--", $McpExe)
    $r.Lines | ForEach-Object { Write-Info $_ }
    if ($r.Code -ne 0) {
        Write-Err2 "Claude Code への登録に失敗しました（終了コード $($r.Code)）。手で次を実行してください:"
        Write-Info "  $manual"
        return $false
    }
    Write-Ok "Claude Code に登録しました。"
    return $true
}

try {
    Write-Host "OtoMaker for Windows インストーラー" -ForegroundColor Cyan
    Write-Host "インストール先 (folder): $Root"
    if (-not (Test-Path -LiteralPath (Join-Path $Root "pyproject.toml"))) {
        throw "pyproject.toml が見つかりません。zip をすべて展開してから、展開したフォルダの install.cmd を実行してください。"
    }

    # A folder with non-ASCII characters is fine: the TFLite runtime cannot open such paths itself,
    # so the sa3-tflite backend hands it ASCII forms (8.3 short name, or relative to the runtime folder).

    Write-Step "1/5 uv（Python のパッケージ管理ツール）"
    $uv = Resolve-Uv

    Write-Step "2/5 Python 3.12 と依存パッケージ（数分かかります）"
    # Everything uv downloads stays inside the OtoMaker folder; only this process sees these variables.
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $RuntimeDir "python"
    $env:UV_CACHE_DIR = Join-Path $RuntimeDir "uv-cache"
    $env:UV_PYTHON_PREFERENCE = "only-managed"
    Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue
    Remove-Item Env:UV_PROJECT_ENVIRONMENT -ErrorAction SilentlyContinue
    & $uv sync --directory $Root --locked --extra tflite --no-dev
    if ($LASTEXITCODE -ne 0) { throw "uv sync に失敗しました（終了コード $LASTEXITCODE）。ネットワークを確かめて、もう一度 install.cmd を実行してください。" }
    if (-not (Test-Venv)) { throw "uv sync は終わりましたが $McpExe がありません。" }
    $r = Invoke-Captured $VenvPython @("-I", "-c", "import ai_edge_litert, sentencepiece, huggingface_hub, psutil, otomaker.server; print('ok')")
    if ($r.Code -ne 0) { throw "CPU 版に必要なパッケージが読み込めません:`n$($r.Lines -join "`n")" }
    Write-Ok "Python と依存パッケージ（tflite を含む）を入れました: $McpExe"

    Write-Step "3/5 Stable Audio 3 のランタイム（Stability-AI/stable-audio-3、MIT）"
    Install-Runtime
    if (-not (Get-Command ffmpeg -CommandType Application -ErrorAction SilentlyContinue)) {
        Write-Warn2 "ffmpeg が見つかりません。リサンプルとラウドネス処理（process_audio）に使います。"
        Write-Info "入れるには: winget install --id Gyan.FFmpeg -e （その後 Claude を再起動）"
    }

    Write-Step "4/5 モデルファイル（Hugging Face から。アカウント不要）"
    if ($SkipModels) {
        Write-Info "モデルの取得を飛ばしました (-SkipModels)。後で download-models.cmd から取得できます。"
    } else {
        $null = Invoke-ModelDownload
    }

    Write-Step "5/5 MCP クライアントへの登録"
    $registered = @()
    if ($NoRegister) {
        Write-Info "登録を飛ばしました (-NoRegister)。"
    } else {
        if ($ClaudeCodeConfigDir) {
            New-Item -ItemType Directory -Force -Path $ClaudeCodeConfigDir | Out-Null
            $env:CLAUDE_CONFIG_DIR = (Resolve-Path -LiteralPath $ClaudeCodeConfigDir).Path
            Write-Info "Claude Code の設定フォルダ: $env:CLAUDE_CONFIG_DIR (-ClaudeCodeConfigDir)"
        }
        if (Register-Desktop) { $registered += "Claude Desktop" }
        if (Register-ClaudeCode) { $registered += "Claude Code" }
    }
    Write-Info "他のクライアント（Cursor など）では、MCP 設定の command に次を書きます:"
    Write-Info "  $McpExe"

    Write-Host ""
    Write-Host "インストールが終わりました。(Done.)" -ForegroundColor Green
    if ($registered.Count) {
        Write-Host ("登録先: " + ($registered -join "、"))
        Write-Host "Claude を再起動してください。Claude Desktop はタスクトレイのアイコンから「終了」してから起動し直します。" -ForegroundColor Yellow
        Write-Host "(Restart Claude so it picks up the otomaker server.)"
    }
    exit 0
} catch {
    Write-Host ""
    Write-Err2 "$($_.Exception.Message)"
    Write-Host "インストールを中止しました。(Installation stopped.)" -ForegroundColor Red
    exit 1
}
