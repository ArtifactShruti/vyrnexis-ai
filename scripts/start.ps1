$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# Import simple KEY=VALUE entries from the project-local environment file.
if (Test-Path -LiteralPath (Join-Path $root ".env")) {
    foreach ($line in Get-Content -LiteralPath (Join-Path $root ".env")) {
        if ($line -match '^\s*#' -or $line -notmatch '^\s*([^=\s]+)\s*=(.*)$') { continue }
        $name = $Matches[1]
        $value = $Matches[2].Trim()
        if (-not (Test-Path "Env:$name")) { Set-Item "Env:$name" $value }
    }
}

$nodeDir = "C:\Program Files\nodejs"
if (Test-Path $nodeDir) { $env:PATH = "$nodeDir;$env:PATH" }
$apiPort = 8001
if ($env:VYRNEXIS_API_PORT -match '^\d+$') { $apiPort = [int]$env:VYRNEXIS_API_PORT }
$env:VYRNEXIS_API_URL = "http://127.0.0.1:$apiPort"

$backend = Get-NetTCPConnection -State Listen -LocalPort $apiPort -ErrorAction SilentlyContinue
if ($backend) {
    try {
        $health = Invoke-RestMethod -Uri "$($env:VYRNEXIS_API_URL)/health" -TimeoutSec 2
        if ($health.status -ne "healthy") { throw "API returned an unhealthy status." }
    } catch {
        throw "Port $apiPort is occupied but is not a healthy VYRNEXIS API. The existing process was left untouched."
    }
} else {
    $apiCommand = "Set-Location '$root'; python -m uvicorn app.main:app --app-dir '$root\apps\api' --host 127.0.0.1 --port $apiPort"
    Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $apiCommand
    ) -WorkingDirectory $root -WindowStyle Hidden
}

$frontend = Get-NetTCPConnection -State Listen -LocalPort 3000 -ErrorAction SilentlyContinue
if ($frontend) {
    try {
        $page = Invoke-WebRequest -Uri "http://127.0.0.1:3000/login" -UseBasicParsing -TimeoutSec 3
        if ($page.StatusCode -ne 200 -or $page.Content -notmatch 'VYRNEXIS') {
            throw "The response did not match the VYRNEXIS sign-in page."
        }
    } catch {
        throw "Port 3000 is occupied by a server that did not pass the VYRNEXIS page check. The existing process was left untouched."
    }
} else {
    $webCommand = "Set-Location '$root\apps\web'; npm.cmd run dev -- --hostname 127.0.0.1"
    Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $webCommand
    ) -WorkingDirectory "$root\apps\web" -WindowStyle Hidden
}

& "$PSScriptRoot\health-check.ps1"
