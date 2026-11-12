$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$statePath = Join-Path $PSScriptRoot '.local-postgres/document-worker.pid'
$hasher = [System.Security.Cryptography.SHA256]::Create()
try { $workspaceHash = [BitConverter]::ToString($hasher.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($PSScriptRoot))).Replace('-','').Substring(0,12).ToLowerInvariant() }
finally { $hasher.Dispose() }
$workerName = 'local-document-' + $workspaceHash
if (Test-Path -LiteralPath $statePath) {
    $documentWorkerPid = 0
    if ([int]::TryParse((Get-Content -Raw -LiteralPath $statePath).Trim(), [ref]$documentWorkerPid)) {
        $existing = Get-CimInstance Win32_Process -Filter "ProcessId=$documentWorkerPid" -ErrorAction SilentlyContinue
        if ($existing -and $existing.CommandLine -match 'alphasense\.document_task_worker' -and $existing.CommandLine -match [regex]::Escape($workerName)) { return }
    }
}
$env:PYTHONPATH = Join-Path $PSScriptRoot 'services/backend/src'
if (-not $env:ALPHASENSE_DATABASE_URL) {
    $env:ALPHASENSE_DATABASE_URL = (Get-Content -Raw -LiteralPath '.local-postgres/dev-connection.json' | ConvertFrom-Json).url
}
$pythonPath = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
$worker = Start-Process -FilePath $pythonPath -ArgumentList '-m','alphasense.document_task_worker','--forever','--worker-id',$workerName -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru
$worker.Id | Set-Content -LiteralPath $statePath
