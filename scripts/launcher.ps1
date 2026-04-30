$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "       APIQIK GG WebUI 启动器 v1.1" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# 1. 检查 Python 环境
$pythonCmd = "python"
try {
    & $pythonCmd --version | Out-Null
} catch {
    try {
        $pythonCmd = "python3"
        & $pythonCmd --version | Out-Null
    } catch {
        Write-Host "错误: 未检测到 Python 环境！" -ForegroundColor Red
        Write-Host "请确保已安装 Python 3.10+ 并已将其添加到系统环境变量(PATH)中。" -ForegroundColor Yellow
        Read-Host "按回车键退出"
        exit 1
    }
}

# 2. 检查关键依赖项
Write-Host "正在检查运行环境..." -ForegroundColor Gray
$modules = @(
    @{ Name = "fastapi"; Import = "fastapi" },
    @{ Name = "uvicorn"; Import = "uvicorn" },
    @{ Name = "pydantic"; Import = "pydantic" },
    @{ Name = "python-multipart"; Import = "multipart" },
    @{ Name = "boto3"; Import = "boto3" }
)

$missingModules = @()
foreach ($mod in $modules) {
    & $pythonCmd -c "import $($mod.Import)" 2>$null
    if ($LASTEXITCODE -ne 0) {
        $missingModules += $mod.Name
    }
}

if ($missingModules.Count -gt 0) {
    Write-Host ""
    Write-Host "检测到缺失以下依赖项:" -ForegroundColor Red
    foreach ($m in $missingModules) {
        Write-Host " - $m" -ForegroundColor Red
    }
    Write-Host ""
    Write-Host "请在当前文件夹打开 CMD 命令窗口，执行以下命令安装:" -ForegroundColor Yellow
    Write-Host "pip install -r requirements.txt" -ForegroundColor Cyan
    Write-Host ""
    Read-Host "按回车键退出"
    exit 1
}

Write-Host "环境检查通过！" -ForegroundColor Green

# 3. 端口设置
$port = "8080"
$inputPort = Read-Host "请输入运行端口 (默认 8080, 直接回车使用默认)"
if (-not [string]::IsNullOrWhiteSpace($inputPort)) {
    $port = $inputPort.Trim()
}

function Test-LocalPort {
    param([int]$Port)
    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($connection) {
        return [pscustomobject]@{ Available = $false; Reason = "in-use"; ProcessId = $connection.OwningProcess; Message = "端口 $Port 已被占用 (进程 PID: $($connection.OwningProcess))" }
    }
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse("127.0.0.1"), $Port)
    try {
        $listener.Start()
        return [pscustomobject]@{ Available = $true; Message = "端口 $Port 可用" }
    } catch {
        return [pscustomobject]@{ Available = $false; Reason = "bind-failed"; Message = "端口 $Port 绑定失败" }
    } finally {
        $listener.Stop()
    }
}

while ($true) {
    if ($port -notmatch '^[0-9]+$') {
        $port = (Read-Host "端口格式错误，请输入纯数字").Trim()
        if ([string]::IsNullOrWhiteSpace($port)) { exit 0 }
        continue
    }
    $portStatus = Test-LocalPort -Port ([int]$port)
    if ($portStatus.Available) { break }
    
    Write-Host ""
    Write-Host $portStatus.Message -ForegroundColor Yellow
    if ($portStatus.Reason -eq "in-use") {
        Write-Host "你可以选择: [K] 尝试自动杀掉占用进程, [P] 换个端口, [回车] 退出"
        $action = Read-Host "请输入"
        if ($action -ieq "K") {
            try {
                Stop-Process -Id $portStatus.ProcessId -Force
                Write-Host "已尝试终止占用进程，正在重试..." -ForegroundColor Green
                Start-Sleep -Seconds 1
                continue
            } catch {
                Write-Host "终止进程失败，权限不足。请手动处理或换个端口。" -ForegroundColor Red
            }
        }
    } else {
        $action = Read-Host "请按 [P] 换个端口，或直接按回车退出"
    }
    if ($action -ieq "P") {
        $port = (Read-Host "请输入新端口").Trim()
        if ([string]::IsNullOrWhiteSpace($port)) { exit 0 }
        continue
    }
    exit 0
}

# 4. 启动服务
Write-Host ""
Write-Host "正在启动后端服务 ($port)..." -ForegroundColor Green
Write-Host "浏览器将自动打开: http://127.0.0.1:$port/"
Write-Host ""

Start-Process powershell -WindowStyle Hidden -ArgumentList @(
    "-NoProfile",
    "-Command",
    "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:$port/'"
)

& $pythonCmd -m uvicorn main:app --host 127.0.0.1 --port $port --log-level info
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "服务运行出错，请检查上方日志信息。" -ForegroundColor Red
    Read-Host "按回车键退出"
}

