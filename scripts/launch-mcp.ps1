<#
.SYNOPSIS
    Bootstrap and start the baba-credits MCP server (Windows / PowerShell 5.1+).

.DESCRIPTION
    1. Finds a Python >= 3.10 interpreter (mcp SDK requires it).
    2. Creates a local virtualenv at <repo>\.venv if missing.
    3. Installs the three MCP runtime deps (mcp, httpx, pydantic) if missing.
    4. Loads <repo>\.env.mcp if present.
    5. Health-checks the gateway URL.
    6. Launches `python -m baba_mcp.server` and exits with its code.

.PARAMETER NoPip
    Skip the dependency check (faster relaunch when you know deps are installed).

.PARAMETER Reinstall
    Force reinstall of MCP deps even if already present.

.PARAMETER SkipGatewayCheck
    Skip the gateway health-check before launching.

.EXAMPLE
    .\scripts\launch-mcp.ps1

.EXAMPLE
    $env:MCP_TRANSPORT = 'http'; .\scripts\launch-mcp.ps1

.EXAMPLE
    .\scripts\launch-mcp.ps1 -Reinstall

.NOTES
    Exit codes:
        0 — server exited cleanly (e.g. Ctrl-C)
        1 — bootstrap failure
        2 — gateway health-check failed
#>
[CmdletBinding()]
param(
    [switch]$NoPip,
    [switch]$Reinstall,
    [switch]$SkipGatewayCheck
)

$ErrorActionPreference = 'Stop'

# ----- Paths --------------------------------------------------------------
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = (Resolve-Path (Join-Path $ScriptDir '..')).Path
$VenvDir   = Join-Path $RepoRoot '.venv'
$VenvPy    = Join-Path $VenvDir 'Scripts\python.exe'
$EnvFile   = Join-Path $RepoRoot '.env.mcp'

# ----- Helpers ------------------------------------------------------------
function Ok($msg)   { Write-Host ("[OK]  " + $msg) -ForegroundColor Green }
function Warn($msg) { Write-Host ("[WARN] " + $msg) -ForegroundColor Yellow }
function Fail($msg) { Write-Host ("[FAIL] " + $msg) -ForegroundColor Red; exit 1 }
function Step($msg) { Write-Host ""; Write-Host $msg -ForegroundColor Cyan }

function Test-PythonOk($exe) {
    try {
        $ver = & $exe -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>$null
        if (-not $ver) { return $false }
        $parts = $ver -split '\.'
        $major = [int]$parts[0]; $minor = [int]$parts[1]
        return ($major -gt 3) -or ($major -eq 3 -and $minor -ge 10)
    } catch { return $false }
}

# ----- 1. Find Python >= 3.10 ---------------------------------------------
Step "1. Locating a Python >= 3.10 interpreter"
$PyBin = $null
$candidates = @('py', 'python', 'python3')
# `py -3.x` launcher is the recommended way on Windows
$pyLauncher = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($v in @('-3.13', '-3.12', '-3.11', '-3.10')) {
        $exe = & py $v -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe) {
            if (Test-PythonOk $exe) { $PyBin = $exe; break }
        }
    }
}
if (-not $PyBin) {
    foreach ($cand in $candidates) {
        if (Get-Command $cand -ErrorAction SilentlyContinue) {
            $exe = (Get-Command $cand).Source
            if (Test-PythonOk $exe) { $PyBin = $exe; break }
        }
    }
}
if (-not $PyBin) {
    Write-Host "[FAIL] No Python >= 3.10 found in PATH." -ForegroundColor Red
    Write-Host "       Install from https://www.python.org/downloads/ (3.11+ recommended)" -ForegroundColor Red
    Write-Host "       or run: winget install Python.Python.3.11" -ForegroundColor Red
    exit 1
}
$ver = & $PyBin -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])'
Ok "Found $PyBin (Python $ver)"

# ----- 2. Create / reuse virtualenv ---------------------------------------
Step "2. Setting up virtualenv at $VenvDir"
$needNewVenv = $true
if (Test-Path $VenvPy) {
    if (Test-PythonOk $VenvPy) {
        $vver = & $VenvPy -c 'import sys; print("%d.%d" % sys.version_info[:2])'
        Ok "Reusing existing venv (Python $vver)"
        $needNewVenv = $false
    } else {
        Warn "Existing venv too old, recreating"
        Remove-Item -Recurse -Force $VenvDir
    }
}
if ($needNewVenv) {
    & $PyBin -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { Fail "Failed to create venv" }
    Ok "Venv created"
}

# ----- 3. Install MCP deps ------------------------------------------------
Step "3. Verifying MCP dependencies"
$needInstall = $Reinstall.IsPresent
if (-not $Reinstall.IsPresent -and -not $NoPip.IsPresent) {
    & $VenvPy -c 'import mcp, httpx, pydantic' 2>$null
    if ($LASTEXITCODE -ne 0) { $needInstall = $true }
}
if ($needInstall -and -not $NoPip.IsPresent) {
    & $VenvPy -m pip install --upgrade pip | Out-Null
    $reqFile = Join-Path $RepoRoot 'requirements.txt'
    if (Test-Path $reqFile) {
        & $VenvPy -m pip install -r $reqFile
    } else {
        & $VenvPy -m pip install 'mcp>=1.0.0' 'httpx>=0.27.0' 'pydantic>=2.5.0'
    }
    if ($LASTEXITCODE -ne 0) { Fail "pip install failed" }
    Ok "Dependencies installed"
} else {
    Ok "All deps already present (use -Reinstall to force)"
}

# ----- 4. Load .env.mcp ---------------------------------------------------
Step "4. Loading environment"
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith('#') -and $line -match '^([^=]+)=(.*)$') {
            $k = $Matches[1].Trim()
            $v = $Matches[2].Trim().Trim('"').Trim("'")
            [Environment]::SetEnvironmentVariable($k, $v, 'Process')
        }
    }
    Ok "Loaded $EnvFile"
} else {
    Warn "$EnvFile not found — using defaults / shell env vars only"
}
if (-not $env:BABA_GATEWAY_URL) { $env:BABA_GATEWAY_URL = 'http://127.0.0.1:5000' }
if (-not $env:MCP_TRANSPORT)    { $env:MCP_TRANSPORT    = 'stdio' }
if (-not $env:MCP_HTTP_HOST)    { $env:MCP_HTTP_HOST    = '127.0.0.1' }
if (-not $env:MCP_HTTP_PORT)    { $env:MCP_HTTP_PORT    = '7000' }
Write-Host ("  Gateway:   " + $env:BABA_GATEWAY_URL)
$transportLine = "  Transport: " + $env:MCP_TRANSPORT
if ($env:MCP_TRANSPORT -eq 'http') {
    $transportLine += " on " + $env:MCP_HTTP_HOST + ":" + $env:MCP_HTTP_PORT
}
Write-Host $transportLine

# ----- 5. Gateway health-check --------------------------------------------
Step "5. Gateway health-check"
if ($SkipGatewayCheck.IsPresent -or $env:SKIP_GATEWAY_CHECK -eq '1') {
    Warn "Skipped"
} else {
    try {
        $resp = Invoke-RestMethod -Uri ($env:BABA_GATEWAY_URL + '/api/Diag/GetSupply') `
                                  -Method Post -Body '{}' -ContentType 'application/json' `
                                  -TimeoutSec 5 -SkipCertificateCheck:$true
        if ($resp.success) {
            Ok "Gateway reachable (Diag/GetSupply returned success)"
        } else {
            Warn "Gateway reachable but response unexpected"
        }
    } catch {
        Write-Host "[FAIL] Gateway unreachable at $($env:BABA_GATEWAY_URL): $_" -ForegroundColor Red
        Write-Host "       Set BABA_GATEWAY_URL, start the gateway, or pass -SkipGatewayCheck" -ForegroundColor Red
        exit 2
    }
}

# ----- 6. Launch ----------------------------------------------------------
Step "6. Starting MCP server"
Set-Location $RepoRoot
& $VenvPy -m baba_mcp.server
exit $LASTEXITCODE
