$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    python scripts/init_postgres_demo.py
    if ($LASTEXITCODE -ne 0) { throw 'Could not initialize local PostgreSQL stack settings.' }
    docker compose --env-file .env.postgres -f docker-compose.postgres.yml up -d --build --wait --wait-timeout 120
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL demo stack failed to start.' }
    Write-Output 'PostgreSQL demo: http://localhost:3001'
    Write-Output 'API documentation: http://127.0.0.1:8002/docs'
} finally {
    Pop-Location
}
