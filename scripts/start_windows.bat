@echo off
REM Start the gateway. See README "auto start" to run it at boot.
cd /d "%~dp0.."
.venv\Scripts\python.exe -m gateway
