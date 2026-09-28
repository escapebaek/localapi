# Local AI API setup (Windows). Run from the repo folder in PowerShell:
#   powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1 [-Model qwen3.5:4b]
# (Messages are in English because Windows PowerShell 5.1 misreads non-ASCII in BOM-less scripts.)
param([string]$Model = "qwen3.5:4b")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

# 1) Install Ollama
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "Installing Ollama..."
    winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

# 2) Keep Ollama bound to this PC only; the gateway is the only thing exposed.
[Environment]::SetEnvironmentVariable("OLLAMA_HOST", "127.0.0.1:11434", "User")
[Environment]::SetEnvironmentVariable("OLLAMA_KEEP_ALIVE", "30m", "User")
Write-Host "Set OLLAMA_HOST=127.0.0.1:11434 (quit and restart the Ollama tray app to apply)."

# 3) Download the model
ollama pull $Model

# 4) GPU check
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
} else {
    Write-Warning "nvidia-smi not found: install the latest NVIDIA driver (otherwise CPU only)."
}

# 5) Python venv + dependencies
if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -q --upgrade pip
.\.venv\Scripts\python.exe -m pip install -q -r requirements.txt

# 6) Create .env with a random API key
if (-not (Test-Path .env)) {
    $key = .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
    (Get-Content .env.example -Encoding UTF8) `
        -replace '^API_KEYS=.*', "API_KEYS=$key" `
        -replace '^DEFAULT_MODEL=.*', "DEFAULT_MODEL=$Model" | Set-Content .env -Encoding UTF8
    Write-Host "`nCreated .env. API key: $key"
}

Write-Host "`nDone! Start with: scripts\start_windows.bat"
