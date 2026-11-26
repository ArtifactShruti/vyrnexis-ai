$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$env:PYTHONPATH = "$root\apps\api"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
$logDir = Join-Path $root ".dev-logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$runId = [guid]::NewGuid().ToString("N")
$stdout = Join-Path $logDir "pytest-$runId.out.log"
$stderr = Join-Path $logDir "pytest-$runId.err.log"
$previousDatabase = $env:DATABASE_URL
try {
    $env:DATABASE_URL = "sqlite:///./.dev-logs/vyrnexis-test-bootstrap-$runId.db"
    $test = Start-Process -FilePath "python" -ArgumentList @(
        "-m", "pytest", "tests", "-q", "-o", "faulthandler_timeout=30"
    ) -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
} finally {
    $env:DATABASE_URL = $previousDatabase
}

$testTimeoutSeconds = 180
if (-not $test.WaitForExit($testTimeoutSeconds * 1000)) {
    Stop-Process -Id $test.Id -Force -ErrorAction SilentlyContinue
    Write-Error "Backend tests exceeded the $testTimeoutSeconds-second limit. Logs: $stdout and $stderr"
    exit 124
}

if (Test-Path $stdout) { Get-Content $stdout }
if (Test-Path $stderr) { Get-Content $stderr }
if ($test.ExitCode -ne 0) { exit $test.ExitCode }
