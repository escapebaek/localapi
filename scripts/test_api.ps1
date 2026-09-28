# Smoke test: health check + one real generation through the gateway.
#   powershell -ExecutionPolicy Bypass -File scripts\test_api.ps1 [-Url http://127.0.0.1:8000] [-Model qwen3.5:2b]
param([string]$Url = "http://127.0.0.1:8000", [string]$Model = "")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$key = ((Get-Content .env -Encoding UTF8) | Where-Object { $_ -match '^API_KEYS=' }) -replace '^API_KEYS=', '' -split ',' | Select-Object -First 1

# Decode as UTF-8 explicitly; PowerShell 5.1 would otherwise garble Korean text.
function Invoke-Api([string]$Method, [string]$Path, $Body) {
    $params = @{ Uri = "$Url$Path"; Method = $Method; UseBasicParsing = $true; TimeoutSec = 600
                 Headers = @{ Authorization = "Bearer $key" } }
    if ($Body) {
        $params.Body = [Text.Encoding]::UTF8.GetBytes(($Body | ConvertTo-Json -Compress))
        $params.ContentType = "application/json; charset=utf-8"
    }
    $resp = Invoke-WebRequest @params
    $reader = New-Object IO.StreamReader($resp.RawContentStream, [Text.Encoding]::UTF8)
    return $reader.ReadToEnd() | ConvertFrom-Json
}

Write-Host "== /health"
Invoke-Api GET "/health" | Format-List

Write-Host "== /v1/models"
(Invoke-Api GET "/v1/models").data | Format-Table id, installed

Write-Host "== /v1/generate (first call loads the model; may take 10-60s longer)"
$body = @{
    system = "Answer in Korean."
    prompt = "Explain in about five sentences what general anesthesia is."
}
if ($Model) { $body.model = $Model }
$out = Invoke-Api POST "/v1/generate" $body
Write-Host $out.response
Write-Host ""
Write-Host ("model            : {0}" -f $out.model)
Write-Host ("total            : {0:N1} s" -f ($out.duration_ms / 1000))
Write-Host ("  model load     : {0:N1} s   (0 when already loaded)" -f ($out.load_ms / 1000))
Write-Host ("  read prompt    : {0:N1} s   ({1} tokens)" -f ($out.prompt_eval_ms / 1000), $out.prompt_tokens)
Write-Host ("  generate       : {0:N1} s   ({1} tokens)" -f ($out.eval_ms / 1000), $out.completion_tokens)
Write-Host ("GENERATION SPEED : {0:N1} tok/s  <- use this number" -f ($out.completion_tokens / [Math]::Max($out.eval_ms / 1000, 0.001)))
