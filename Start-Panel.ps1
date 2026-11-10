$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$url = 'http://127.0.0.1:8082/panel/'
function Test-Panel {
    try {
        $page = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 2
        return $page.StatusCode -eq 200 -and $page.Headers['Referrer-Policy'] -contains 'no-referrer'
    } catch { return $false }
}
if (-not (Test-Panel)) {
    if (-not (Test-Path -LiteralPath 'apps/panel/dist/index.html')) {
        throw 'Brak zbudowanego panelu. W apps/panel wykonaj npm ci oraz npm run build.'
    }
    $env:PYTHONPATH = Join-Path $PSScriptRoot 'services/backend/src'
    if (-not $env:ALPHASENSE_DATABASE_URL) {
        $env:ALPHASENSE_DATABASE_URL = (Get-Content -Raw -LiteralPath '.local-postgres/dev-connection.json' | ConvertFrom-Json).url
    }
    if (-not $env:ALPHASENSE_SEC_USER_AGENT -and (Test-Path -LiteralPath '.local-postgres/sec-user-agent.txt')) {
        $env:ALPHASENSE_SEC_USER_AGENT = (Get-Content -Raw -LiteralPath '.local-postgres/sec-user-agent.txt').Trim()
    }
    $server = Start-Process -FilePath '.venv/Scripts/python.exe' -ArgumentList '-m','uvicorn','alphasense.panel_server:app','--host','127.0.0.1','--port','8082' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru
    for ($i = 0; $i -lt 30; $i++) {
        if (Test-Panel) { break }
        if ($server.HasExited) { throw 'Nie udalo sie uruchomic panelu na porcie 8082.' }
        Start-Sleep -Milliseconds 400
    }
    if (-not (Test-Panel)) { throw 'Panel nie odpowiedzial na porcie 8082.' }
}
& (Join-Path $PSScriptRoot 'Start-TaskWorker.ps1')
& (Join-Path $PSScriptRoot 'Start-DocumentWorker.ps1')
& (Join-Path $PSScriptRoot 'Start-SecScheduler.ps1')
Start-Process $url
