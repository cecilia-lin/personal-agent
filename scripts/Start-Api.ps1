param([switch]$DemoOnly, [switch]$Reload)
. "$PSScriptRoot\Common.ps1"
if (-not (Test-Path -LiteralPath $ProjectPython)) { throw 'Run scripts/Setup.ps1 first.' }
if ($DemoOnly) {
    $env:APP_MODE = 'demo'
    $env:DB_BACKEND = 'sqlite'
    $env:INTEGRATIONS_ENABLED = 'false'
    Write-Output 'Starting the explicit offline demo. External integrations are disabled for this process.'
}
$ApiArguments = @('-m', 'uvicorn', 'app.main:app', '--app-dir', 'apps/api', '--host', '127.0.0.1', '--port', '8000')
if ($Reload) { $ApiArguments += '--reload' }
& $ProjectPython @ApiArguments
