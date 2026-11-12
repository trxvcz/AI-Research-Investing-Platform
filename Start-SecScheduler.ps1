$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$statePath = Join-Path $PSScriptRoot '.local-postgres/sec-scheduler.pid'
$hasher = [System.Security.Cryptography.SHA256]::Create()
try { $workspaceHash = [BitConverter]::ToString($hasher.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($PSScriptRoot))).Replace('-','').Substring(0,12).ToLowerInvariant() }
finally { $hasher.Dispose() }
$schedulerName = 'local-scheduler-' + $workspaceHash
if (Test-Path -LiteralPath $statePath) {
    $schedulerPid = 0
    if ([int]::TryParse((Get-Content -Raw -LiteralPath $statePath).Trim(), [ref]$schedulerPid)) {
        $existing = Get-CimInstance Win32_Process -Filter "ProcessId=$schedulerPid" -ErrorAction SilentlyContinue
        if ($existing -and $existing.CommandLine -match 'alphasense\.sec_scheduler' -and $existing.CommandLine -match [regex]::Escape($schedulerName)) { return }
    }
}
$env:PYTHONPATH = Join-Path $PSScriptRoot 'services/backend/src'
if (-not $env:ALPHASENSE_DATABASE_URL) {
    $env:ALPHASENSE_DATABASE_URL = (Get-Content -Raw -LiteralPath '.local-postgres/dev-connection.json' | ConvertFrom-Json).url
}
$pythonPath = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
$scheduler = Start-Process -FilePath $pythonPath -ArgumentList '-m','alphasense.sec_scheduler','--forever','--worker-id',$schedulerName -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru
$scheduler.Id | Set-Content -LiteralPath $statePath
