<#
.SYNOPSIS
  OtoMaker の MCP 登録を外す（uninstall.cmd から呼ばれる）。
.DESCRIPTION
  Claude Desktop と Claude Code と OpenAI Codex から otomaker の登録を外す（それぞれ Y/N で確認）。
  Codex は config.toml の [mcp_servers.otomaker] の節（子の表を含む）だけを消す。
  Claude Desktop の登録は、このフォルダの otomaker-mcp.exe を指している場合だけ外す。
  フォルダとダウンロード済みのモデルは消さない（生成した音声 outputs\ が入っているため、削除は利用者が行う）。
.PARAMETER DesktopConfig
  Claude Desktop の設定ファイル。既定は %APPDATA%\Claude\claude_desktop_config.json。
.PARAMETER ClaudeCodeConfigDir
  Claude Code の設定フォルダ（CLAUDE_CONFIG_DIR としてこの処理の中だけで渡す）。
.PARAMETER CodexHome
  Codex の設定フォルダ（CODEX_HOME としてこの処理の中だけで渡す）。既定は CODEX_HOME、無ければ %USERPROFILE%\.codex。
.PARAMETER Yes
  確認にすべて Y と答える。
#>
param(
    [string]$DesktopConfig = "",
    [string]$ClaudeCodeConfigDir = "",
    [string]$CodexHome = "",
    [switch]$Yes
)
. (Join-Path $PSScriptRoot "common.ps1")
$script:AssumeYes = [bool]$Yes
if (-not $DesktopConfig) { $DesktopConfig = $DefaultDesktopConfig }

try {
    Write-Host "OtoMaker for Windows: 登録の解除 (uninstall)" -ForegroundColor Cyan
    Write-Host "フォルダ (folder): $Root"
    $failed = $false

    Write-Step "Claude Desktop"
    if (-not (Test-Path -LiteralPath $DesktopConfig)) {
        Write-Info "設定ファイルがありません（登録なし）: $DesktopConfig"
    } elseif (-not (Test-Path -LiteralPath $VenvPython)) {
        Write-Warn2 "$VenvPython が無いため自動では外せません。$DesktopConfig の mcpServers から ""otomaker"" を手で削除してください。"
        $failed = $true
    } else {
        $r = Invoke-Captured $VenvPython @("-I", "-m", "otomaker.mcp_config", "show", "--config", $DesktopConfig)
        if ($r.Code -eq 3) {
            Write-Warn2 "設定ファイルを JSON として読めません。mcpServers から ""otomaker"" を手で削除してください: $DesktopConfig"
            $failed = $true
        } elseif (-not ($r.Lines -join "")) {
            Write-Info "otomaker は登録されていません。"
        } elseif (Read-YesNo "Claude Desktop から otomaker の登録を外しますか？ (Remove from Claude Desktop?)" $true) {
            $r = Invoke-Captured $VenvPython @("-I", "-m", "otomaker.mcp_config", "remove", "--config", $DesktopConfig, "--only-under", $Root)
            $r.Lines | ForEach-Object { Write-Info $_ }
            if ($r.Code -eq 0) { Write-Ok "Claude Desktop の登録を外しました。" }
            elseif ($r.Code -eq 1) { Write-Info "登録は別の場所の otomaker を指しているため、そのままにしました。" }
            else { Write-Err2 "外せませんでした（終了コード $($r.Code)）。"; $failed = $true }
        }
    }

    Write-Step "Claude Code"
    if ($ClaudeCodeConfigDir) { $env:CLAUDE_CONFIG_DIR = (Resolve-Path -LiteralPath $ClaudeCodeConfigDir).Path }
    $claude = Find-ClaudeCli
    if (-not $claude) {
        Write-Info "claude コマンドが見つかりません。登録している場合は claude mcp remove --scope user otomaker を実行してください。"
    } else {
        $g = Invoke-Captured $claude @("mcp", "get", "otomaker")
        $text = $g.Lines -join "`n"
        if ($g.Code -ne 0) {
            Write-Info "otomaker は登録されていません。"
        } else {
            $here = $text.IndexOf($Root, [StringComparison]::OrdinalIgnoreCase) -ge 0
            if (-not $here) { Write-Info "登録されている otomaker は、このフォルダ以外を指しているようです:"; $g.Lines | ForEach-Object { Write-Info $_ } }
            if (Read-YesNo "Claude Code から otomaker の登録（user スコープ）を外しますか？ (Remove from Claude Code?)" $here) {
                $r = Invoke-Captured $claude @("mcp", "remove", "--scope", "user", "otomaker")
                $r.Lines | ForEach-Object { Write-Info $_ }
                if ($r.Code -eq 0) { Write-Ok "Claude Code の登録を外しました。" }
                else { Write-Err2 "外せませんでした（終了コード $($r.Code)）。登録が user 以外のスコープにある場合は claude mcp remove otomaker を実行してください。"; $failed = $true }
            }
        }
    }

    Write-Step "OpenAI Codex"
    if ($CodexHome) { $env:CODEX_HOME = (Resolve-Path -LiteralPath $CodexHome).Path }
    $codexHomeDir = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE ".codex" }
    $codexConfig = Join-Path $codexHomeDir "config.toml"
    if (-not (Test-Path -LiteralPath $codexConfig)) {
        Write-Info "設定ファイルがありません（登録なし）: $codexConfig"
    } elseif (-not (Test-Path -LiteralPath $VenvPython)) {
        Write-Warn2 "$VenvPython が無いため自動では外せません。$codexConfig から [mcp_servers.otomaker] の節を手で削除してください。"
        $failed = $true
    } else {
        $r = Invoke-Captured $VenvPython @("-I", "-m", "otomaker.codex_config", "show")
        if ($r.Code -eq 3) {
            Write-Warn2 "設定ファイルを読めません。[mcp_servers.otomaker] の節を手で削除してください: $codexConfig"
            $failed = $true
        } elseif (-not ($r.Lines -join "")) {
            Write-Info "otomaker は登録されていません。"
        } elseif (Read-YesNo "Codex から otomaker の登録を外しますか？ (Remove from Codex?)" $true) {
            $r = Invoke-Captured $VenvPython @("-I", "-m", "otomaker.codex_config", "remove", "--only-under", $Root)
            $r.Lines | ForEach-Object { Write-Info $_ }
            if ($r.Code -eq 0) { Write-Ok "Codex の登録を外しました。" }
            elseif ($r.Code -eq 1) { Write-Info "登録は別の場所の otomaker を指しているため、そのままにしました。" }
            else { Write-Err2 "外せませんでした（終了コード $($r.Code)）。[mcp_servers.otomaker] の節を手で削除してください: $codexConfig"; $failed = $true }
        }
    }

    Write-Host ""
    Write-Host "登録の解除が終わりました。Claude（と Codex）を再起動してください。" -ForegroundColor Green
    Write-Host "OtoMaker 本体は消していません。不要なら、Claude を終了してから次を手で削除してください:"
    Write-Host "  - このフォルダ（生成した音声の outputs\ も入っています）: $Root"
    $hf = if ($env:HF_HOME) { $env:HF_HOME } else { Join-Path $env:USERPROFILE ".cache\huggingface" }
    Write-Host "  - ダウンロードしたモデル（他のツールと共有していなければ）:"
    Write-Host "      $(Join-Path $hf 'hub\models--stabilityai--stable-audio-3-optimized')"
    Write-Host "      $(Join-Path $hf 'hub\models--Comfy-Org--stable-audio-3')（GPU 用を取得した場合）"
    if ($failed) { exit 1 }
    exit 0
} catch {
    Write-Err2 "$($_.Exception.Message)"
    exit 1
}
