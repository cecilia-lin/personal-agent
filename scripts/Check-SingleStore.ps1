param([switch]$Management)
. "$PSScriptRoot\Common.ps1"
$env:PYTHONPATH = Join-Path $ProjectRoot 'apps\api'
if ($Management) {
    & $ProjectPython -m app.diagnostics --singlestore-management
} else {
    & $ProjectPython -m app.diagnostics --backend singlestore
}
Assert-Succeeded 'SingleStore diagnostic'
