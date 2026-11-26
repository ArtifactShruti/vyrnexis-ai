$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r apps/api/requirements.txt

$nodeDir = "C:\Program Files\nodejs"
if (Test-Path $nodeDir) {
    $env:PATH = "$nodeDir;$env:PATH"
}
npm.cmd install

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}

Write-Output "VYRNEXIS setup complete."
