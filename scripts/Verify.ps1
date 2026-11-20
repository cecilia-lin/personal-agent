. "$PSScriptRoot\Common.ps1"
& $ProjectPython -m pytest apps/api/tests -q
Assert-Succeeded 'Backend invariants'
& $PnpmCommand --dir apps/web run build
Assert-Succeeded 'Frontend typecheck and production build'
