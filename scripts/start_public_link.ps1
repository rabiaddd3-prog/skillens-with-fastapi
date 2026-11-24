# Start SkillLens and a temporary public link (Cloudflare quick tunnel) for a live demo.
#
# Usage (from the project folder):
#   powershell -ExecutionPolicy Bypass -File scripts\start_public_link.ps1
#
# - Starts the app on port 8000 if it is not running yet (in a separate window).
# - Opens a tunnel and prints the https://....trycloudflare.com link. Anyone with the link can open the
#   site while this window stays open; the link changes every time. Close the window (or Ctrl+C) to stop.
# - Needs cloudflared.exe in %USERPROFILE%\tools (official build from github.com/cloudflare/cloudflared).

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$cloudflared = Join-Path $env:USERPROFILE "tools\cloudflared.exe"
if (-not (Test-Path $cloudflared)) {
    Write-Host "cloudflared.exe not found in $env:USERPROFILE\tools." -ForegroundColor Red
    Write-Host "Download it from https://github.com/cloudflare/cloudflared/releases (cloudflared-windows-amd64.exe)."
    exit 1
}

function Test-App {
    try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 http://localhost:8000/health | Out-Null; return $true }
    catch { return $false }
}

if (-not (Test-App)) {
    Write-Host "Starting SkillLens on port 8000 (a second window opens; the model takes a little while to load)..."
    $python = Join-Path $root ".venv\Scripts\python.exe"
    $cmd = "`$env:HF_HUB_OFFLINE='1'; `$env:HF_HUB_DISABLE_SYMLINKS_WARNING='1'; Set-Location '$root'; & '$python' -m uvicorn api.main:app --host 0.0.0.0 --port 8000"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $cmd | Out-Null
    for ($i = 0; $i -lt 90 -and -not (Test-App); $i++) { Start-Sleep -Seconds 2 }
    if (-not (Test-App)) { Write-Host "The app did not start; check the second window." -ForegroundColor Red; exit 1 }
}
Write-Host "SkillLens is running on http://localhost:8000" -ForegroundColor Green
Write-Host "Opening the public link (keep this window open)..."

& $cloudflared tunnel --no-autoupdate --url http://localhost:8000 2>&1 | ForEach-Object {
    $line = "$_"
    if ($line -match "https://[a-z0-9-]+\.trycloudflare\.com") {
        Write-Host ""
        Write-Host "  Public link:  $($Matches[0])" -ForegroundColor Green
        Write-Host "  API docs:     $($Matches[0])/docs" -ForegroundColor Green
        Write-Host ""
    }
}
