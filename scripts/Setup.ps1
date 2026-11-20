. "$PSScriptRoot\Common.ps1"
if (-not (Test-Path -LiteralPath $ProjectPython)) {
    & $PythonCommand -m venv .venv
    Assert-Succeeded 'Create virtual environment'
}
& $ProjectPython -m pip install -r apps/api/requirements.lock.txt
Assert-Succeeded 'Install backend dependencies'
& $PnpmCommand --dir apps/web install --frozen-lockfile --store-dir "$ProjectRoot\.local\pnpm-store"
Assert-Succeeded 'Install frontend dependencies'
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
Write-Output 'Ready. Run scripts/Start-Api.ps1 -DemoOnly and scripts/Start-Web.ps1 in separate terminals.'
