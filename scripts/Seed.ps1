param([switch]$Reset)
$ErrorActionPreference = 'Stop'
$SeedRoute = if ($Reset) { 'reset' } else { 'seed' }
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/demo/$SeedRoute" | ConvertTo-Json
