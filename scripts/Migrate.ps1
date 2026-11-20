param([switch]$PrintSchema)
. "$PSScriptRoot\Common.ps1"
$env:PYTHONPATH = Join-Path $ProjectRoot 'apps\api'
if ($PrintSchema) { & $ProjectPython -m app.diagnostics --print-schema }
else { & $ProjectPython -m app.diagnostics --init-schema }
Assert-Succeeded 'Database migration or diagnostic'
