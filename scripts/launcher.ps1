$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)

Write-Host ""
Write-Host "APIQIK Image Generation Launcher" -ForegroundColor Cyan
Write-Host ""

$port = "8080"
$inputPort = Read-Host "Enter port (default 8080, press Enter to use default)"
if (-not [string]::IsNullOrWhiteSpace($inputPort)) {
    $port = $inputPort.Trim()
}

function Test-LocalPort {
    param([int]$Port)
    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($connection) {
        return [pscustomobject]@{ Available = $false; Reason = "in-use"; ProcessId = $connection.OwningProcess; Message = "Port $Port is in use by PID: $($connection.OwningProcess)" }
    }
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse("127.0.0.1"), $Port)
    try {
        $listener.Start()
        return [pscustomobject]@{ Available = $true; Message = "Port $Port is available" }
    } catch {
        return [pscustomobject]@{ Available = $false; Reason = "bind-failed"; Message = "Port $Port bind failed: $($_.Exception.InnerException.Message)" }
    } finally {
        $listener.Stop()
    }
}

while ($true) {
    if ($port -notmatch '^[0-9]+$') {
        $port = (Read-Host "Invalid port. Enter numbers only").Trim()
        if ([string]::IsNullOrWhiteSpace($port)) { exit 0 }
        continue
    }
    $portStatus = Test-LocalPort -Port ([int]$port)
    if ($portStatus.Available) { break }
    
    Write-Host ""
    Write-Host $portStatus.Message -ForegroundColor Yellow
    if ($portStatus.Reason -eq "in-use") {
        $action = Read-Host "Choose: [K] Kill process, [P] New port, [Enter] Exit"
        if ($action -ieq "K") {
            Stop-Process -Id $portStatus.ProcessId -Force
            Start-Sleep -Seconds 1
            continue
        }
    } else {
        $action = Read-Host "Choose: [P] New port, [Enter] Exit"
    }
    if ($action -ieq "P") {
        $port = (Read-Host "Enter new port").Trim()
        if ([string]::IsNullOrWhiteSpace($port)) { exit 0 }
        continue
    }
    exit 0
}

Write-Host ""
Write-Host "Starting service on port $port..." -ForegroundColor Green
Write-Host "Opening browser: http://127.0.0.1:$port/"
Write-Host ""

Start-Process powershell -WindowStyle Hidden -ArgumentList @(
    "-NoProfile",
    "-Command",
    "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:$port/'"
)

python -m uvicorn main:app --host 127.0.0.1 --port $port --log-level info
if ($LASTEXITCODE -ne 0) {
    Write-Host "Server failed to start." -ForegroundColor Red
    Read-Host "Press Enter to exit"
}
