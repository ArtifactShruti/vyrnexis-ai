$ErrorActionPreference = "Continue"
$apiPort = 8001
if ($env:VYRNEXIS_API_PORT -match '^\d+$') { $apiPort = [int]$env:VYRNEXIS_API_PORT }
$apiUrl = "http://127.0.0.1:$apiPort"

for ($attempt = 1; $attempt -le 30; $attempt++) {
    try {
        $health = Invoke-RestMethod -Uri "$apiUrl/health" -TimeoutSec 2
        $frontend = Invoke-WebRequest -Uri "http://localhost:3000" -UseBasicParsing -TimeoutSec 2
        if ($health.status -eq "healthy" -and $frontend.StatusCode -eq 200) {
            Write-Output "Backend: $apiUrl/health"
            Write-Output "Frontend: http://localhost:3000"
            exit 0
        }
    } catch {}
    Start-Sleep -Milliseconds 500
}

Write-Error "VYRNEXIS services did not become healthy."
