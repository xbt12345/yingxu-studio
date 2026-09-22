$ErrorActionPreference = 'Stop'
$projectPath = $PSScriptRoot
$pythonPath = 'C:\anaconda\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { $pythonPath = (Get-Command python).Source }
try {
    $status = Invoke-RestMethod -Uri 'http://127.0.0.1:8770/api/workflows' -TimeoutSec 3
    if ($status[0].id -eq 'h3-reference') { Write-Host '映序已经运行：http://127.0.0.1:8770/studio.html#workflows'; exit 0 }
} catch {}
Start-Process -FilePath $pythonPath -ArgumentList @('-X','utf8','server.py') -WorkingDirectory $projectPath -WindowStyle Hidden -RedirectStandardOutput (Join-Path $projectPath 'private/server.stdout.log') -RedirectStandardError (Join-Path $projectPath 'private/server.stderr.log')
Write-Host '映序启动中：http://127.0.0.1:8770/studio.html#workflows'
