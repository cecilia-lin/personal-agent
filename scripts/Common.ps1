$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BundledRoot = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies'
$ProjectPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$BundledPython = Join-Path $BundledRoot 'python\python.exe'
$BundledPnpm = Join-Path $BundledRoot 'bin\fallback\pnpm.cmd'
$PythonCommand = if (Test-Path -LiteralPath $BundledPython) { $BundledPython } else { (Get-Command python -ErrorAction Stop).Source }
$PnpmCommand = if (Test-Path -LiteralPath $BundledPnpm) { $BundledPnpm } else { (Get-Command pnpm -ErrorAction Stop).Source }
Set-Location -LiteralPath $ProjectRoot
function Assert-Succeeded([string]$Step) { if ($LASTEXITCODE -ne 0) { throw "$Step failed (exit $LASTEXITCODE)." } }
