# Register the gateway to start automatically (hidden, no console window) when you log on.
# Run in an *Administrator* PowerShell from the repo folder:
#   powershell -ExecutionPolicy Bypass -File scripts\autostart_windows.ps1            # register
#   powershell -ExecutionPolicy Bypass -File scripts\autostart_windows.ps1 -Remove    # unregister
param([switch]$Remove)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$name = "LocalAI-Gateway"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    Write-Host "Removed scheduled task '$name'."
    return
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw "Run this from an Administrator PowerShell (right-click > Run as administrator)." }

New-Item -ItemType Directory -Force (Join-Path $root "logs") | Out-Null
$bat = Join-Path $root "scripts\start_windows.bat"
$log = Join-Path $root "logs\gateway.log"
$user = "$env:USERDOMAIN\$env:USERNAME"

$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"`"$bat`" >> `"$log`" 2>&1`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
# S4U = runs as you but without a visible window; no password is stored.
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType S4U -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $name
Write-Host "Registered '$name'. It starts at every logon; log file: $log"
Write-Host "Check: http://127.0.0.1:8000/health"
