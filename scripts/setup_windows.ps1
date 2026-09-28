# Local AI API setup (Windows). Run from the repo folder in PowerShell:
#   powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1 [-Model qwen3.5:4b]
# (Messages are in English because Windows PowerShell 5.1 misreads non-ASCII in BOM-less scripts.)
param([string]$Model = "qwen3.5:4b")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

function Test-RealPython {
    # "python" may be the Microsoft Store stub, which prints nothing useful.
    try { return ((& python --version 2>&1) -match "Python 3\.(1[0-9])") } catch { return $false }
}

# 1) Python 3.10+
if (-not (Test-RealPython)) {
    Write-Host "[1/6] Installing Python 3.12..."
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    Refresh-Path
    if (-not (Test-RealPython)) {
        throw "Python not found after install. Open a NEW PowerShell window and run this script again."
    }
} else { Write-Host "[1/6] Python OK: $(& python --version 2>&1)" }

# 2) Ollama
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "[2/6] Installing Ollama..."
    winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
    Refresh-Path
} else { Write-Host "[2/6] Ollama OK: $(& ollama --version 2>&1)" }

# Keep Ollama bound to this PC only; the gateway is the only thing exposed.
[Environment]::SetEnvironmentVariable("OLLAMA_HOST", "127.0.0.1:11434", "User")
[Environment]::SetEnvironmentVariable("OLLAMA_KEEP_ALIVE", "30m", "User")

# Make sure the Ollama server is running before pulling.
function Test-Ollama {
    try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:11434/api/version | Out-Null; return $true } catch { return $false }
}
if (-not (Test-Ollama)) {
    $app = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama app.exe"
    if (Test-Path $app) { Start-Process $app } else { Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden }
    for ($i = 0; $i -lt 30 -and -not (Test-Ollama); $i++) { Start-Sleep 1 }
    if (-not (Test-Ollama)) { throw "Ollama server did not start. Launch 'Ollama' from the Start menu and rerun." }
}

# 3) Model (about 3.4GB for qwen3.5:4b)
Write-Host "[3/6] Downloading model $Model ..."
ollama pull $Model

# 4) GPU check
Write-Host "[4/6] GPU check"
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
} else {
    Write-Warning "nvidia-smi not found: install the latest NVIDIA driver (otherwise CPU only)."
}

# 5) Python venv + dependencies
Write-Host "[5/6] Installing gateway dependencies..."
if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -q --upgrade pip
.\.venv\Scripts\python.exe -m pip install -q -r requirements.txt

# 6) Create .env with a random API key
if (-not (Test-Path .env)) {
    $key = .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
    (Get-Content .env.example -Encoding UTF8) `
        -replace '^API_KEYS=.*', "API_KEYS=$key" `
        -replace '^DEFAULT_MODEL=.*', "DEFAULT_MODEL=$Model" | Set-Content .env -Encoding UTF8
    Write-Host "[6/6] Created .env. Your API key: $key"
} else { Write-Host "[6/6] .env already exists (kept as is)." }

Write-Host ""
Write-Host "Done! Next:"
Write-Host "  1) Quit Ollama from the tray icon and start it again (applies OLLAMA_HOST)."
Write-Host "  2) Start the gateway:   scripts\start_windows.bat"
Write-Host "  3) Test (new window):   powershell -ExecutionPolicy Bypass -File scripts\test_api.ps1"
