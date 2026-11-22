# Compile the report and the slides with MiKTeX (Windows). Usage: .\scripts\build_report.ps1
# Output: docs\report\main.pdf and docs\slides\slides.pdf. Errors (lines starting with "!") are printed.
$bin = "$env:LOCALAPPDATA\Programs\MiKTeX\miktex\bin\x64"
if (-not (Test-Path "$bin\pdflatex.exe")) { Write-Error "MiKTeX not found in $bin"; exit 1 }

Push-Location "$PSScriptRoot\..\docs\report"
& "$bin\pdflatex.exe" -interaction=nonstopmode main.tex *> $null
& "$bin\bibtex.exe" main *> $null
& "$bin\pdflatex.exe" -interaction=nonstopmode main.tex *> $null
& "$bin\pdflatex.exe" -interaction=nonstopmode main.tex *> $null
Select-String -Path main.log -Pattern "^!|Output written" | ForEach-Object { "report: " + $_.Line }
Pop-Location

Push-Location "$PSScriptRoot\..\docs\slides"
& "$bin\pdflatex.exe" -interaction=nonstopmode slides.tex *> $null
& "$bin\pdflatex.exe" -interaction=nonstopmode slides.tex *> $null
Select-String -Path slides.log -Pattern "^!|Output written" | ForEach-Object { "slides: " + $_.Line }
Pop-Location
