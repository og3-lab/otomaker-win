<#
.SYNOPSIS
  OtoMaker のモデルファイルを取得する（download-models.cmd から呼ばれる）。
  モデルを選び、otomaker-download がライセンス条件を表示して同意（y/N）を求める。
#>
. (Join-Path $PSScriptRoot "common.ps1")
try {
    Write-Host "OtoMaker for Windows: モデルの取得 (download models)" -ForegroundColor Cyan
    if (-not (Test-Venv)) { throw "OtoMaker がまだインストールされていません。先に install.cmd を実行してください。" }
    if (Invoke-ModelDownload) { exit 0 }
    exit 1
} catch {
    Write-Err2 "$($_.Exception.Message)"
    exit 1
}
