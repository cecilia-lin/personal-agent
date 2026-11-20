param([Parameter(ValueFromRemainingArguments = $true)][string[]]$CliArgs)
. "$PSScriptRoot\Common.ps1"

# Keep the platform CLI out of the Python API and frontend dependencies.
if (-not $CliArgs) { $CliArgs = @('--help') }
$InstalledGuild = Get-Command guild -ErrorAction SilentlyContinue
$NpxCommand = Get-Command npx -ErrorAction SilentlyContinue
if ($InstalledGuild) {
    & $InstalledGuild.Source @CliArgs
} elseif ($NpxCommand) {
    & $NpxCommand.Source --yes --package=@guildai/cli@0.32.0 guild @CliArgs
} else {
    & $PnpmCommand --package=npm dlx npx --yes --package=@guildai/cli@0.32.0 guild @CliArgs
}
Assert-Succeeded 'Guild CLI'
