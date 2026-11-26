$ErrorActionPreference = "Stop"
& "$PSScriptRoot\start.ps1"
Start-Process "http://127.0.0.1:3000"
$apiPort = 8001
if ($env:VYRNEXIS_API_PORT -match '^\d+$') { $apiPort = [int]$env:VYRNEXIS_API_PORT }
Start-Process "http://127.0.0.1:$apiPort/docs"
