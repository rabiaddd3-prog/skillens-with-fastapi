# Start SkillLens for a demo, optionally with a temporary public link (Cloudflare quick tunnel).
#
# Usage (from the project folder):
#   powershell -ExecutionPolicy Bypass -File scripts\start_public_link.ps1              full mode + public link
#   powershell -ExecutionPolicy Bypass -File scripts\start_public_link.ps1 -Light       light mode + public link
#   powershell -ExecutionPolicy Bypass -File scripts\start_public_link.ps1 -Light -LocalOnly   no public link
#
# Full mode loads the NLP models (about a minute). Light mode loads no model and starts in seconds;
# jobs show the model results saved in the database (good for the FastAPI presentation).
# A server already running on port 8000 is stopped first, so the chosen mode is the one that runs.
# The public link works while this window stays open and changes every time. Ctrl+C stops it.
# Needs cloudflared.exe in %USERPROFILE%\tools for the public link.
param([switch]$Light, [switch]$LocalOnly)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$cloudflared = Join-Path $env:USERPROFILE "tools\cloudflared.exe"
if (-not $LocalOnly -and -not (Test-Path $cloudflared)) {
    Write-Host "cloudflared.exe not found in $env:USERPROFILE\tools." -ForegroundColor Red
    Write-Host "Download cloudflared-windows-amd64.exe from https://github.com/cloudflare/cloudflared/releases, or use -LocalOnly."
    exit 1
}

function Test-App {
    try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 http://localhost:8000/health | Out-Null; return $true }
    catch { return $false }
}

# Stop a SkillLens server that is already running, so the requested mode is used.
Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -match "uvicorn api\.main:app" -or $_.CommandLine -match "fastapi.*main\.py" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1

$mode = if ($Light) { "light" } else { "full" }
Write-Host "Starting SkillLens in $mode mode on port 8000 (a second window opens)..."
$python = Join-Path $root ".venv\Scripts\python.exe"
$envs = "`$env:HF_HUB_OFFLINE='1'; `$env:HF_HUB_DISABLE_SYMLINKS_WARNING='1';"
if ($Light) { $envs += " `$env:SKILLLENS_LIGHT='1';" } else { $envs += " Remove-Item Env:SKILLLENS_LIGHT -ErrorAction SilentlyContinue;" }
$cmd = "$envs Set-Location '$root'; & '$python' -m uvicorn api.main:app --host 0.0.0.0 --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $cmd | Out-Null
for ($i = 0; $i -lt 120 -and -not (Test-App); $i++) { Start-Sleep -Seconds 2 }
if (-not (Test-App)) { Write-Host "The app did not start; check the second window." -ForegroundColor Red; exit 1 }

$ip = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias "Wi-Fi*" -ErrorAction SilentlyContinue | Select-Object -First 1).IPAddress
Write-Host ""
Write-Host "  SkillLens ($mode mode):  http://localhost:8000      API docs: http://localhost:8000/docs" -ForegroundColor Green
if ($ip) { Write-Host "  Same Wi-Fi:              http://${ip}:8000" -ForegroundColor Green }
Write-Host ""
if ($LocalOnly) { exit 0 }

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
