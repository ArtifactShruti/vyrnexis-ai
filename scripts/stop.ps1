$ErrorActionPreference = "Continue"
$root = (Resolve-Path (Split-Path -Parent $PSScriptRoot)).Path
$apiPort = 8001
if ($env:VYRNEXIS_API_PORT -match '^\d+$') { $apiPort = [int]$env:VYRNEXIS_API_PORT }

$stopped = @()
foreach ($port in 3000, $apiPort) {
    $connections = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    foreach ($connection in $connections) {
        $owner = Get-CimInstance Win32_Process -Filter "ProcessId = $($connection.OwningProcess)" -ErrorAction SilentlyContinue
        if (-not $owner) { continue }

        $isProjectApi = $false
        $isProjectWeb = $false
        $webEntryId = $null
        $cursor = $owner
        for ($depth = 0; $cursor -and $depth -lt 8; $depth++) {
            $commandLine = [string]$cursor.CommandLine
            if ($port -eq $apiPort -and $commandLine -match 'uvicorn\s+app\.main:app' -and $commandLine -like "*$root\apps\api*") {
                $isProjectApi = $true
            }
            if ($port -eq 3000 -and $commandLine -like "*$root\apps\web*" -and $commandLine -match 'next.*\b(dev|start)\b') {
                $isProjectWeb = $true
                $webEntryId = $cursor.ProcessId
            }
            if (-not $cursor.ParentProcessId) { break }
            $cursor = Get-CimInstance Win32_Process -Filter "ProcessId = $($cursor.ParentProcessId)" -ErrorAction SilentlyContinue
        }

        if ($isProjectApi -or $isProjectWeb) {
            Stop-Process -Id $connection.OwningProcess -Force -ErrorAction SilentlyContinue
            if ($webEntryId -and $webEntryId -ne $connection.OwningProcess) {
                Stop-Process -Id $webEntryId -Force -ErrorAction SilentlyContinue
            }
            $stopped += $connection.OwningProcess
        } else {
            Write-Warning "Left unrelated process $($connection.OwningProcess) on port $port untouched."
        }
    }
}

if ($stopped.Count) { Write-Output "Stopped VYRNEXIS process(es): $($stopped -join ', ')" }
else { Write-Output "No matching VYRNEXIS listeners were stopped; unrelated listeners were left untouched." }
