$ErrorActionPreference = 'Stop'
$projectPath = $PSScriptRoot
$env:YINGXU_LOCAL_MODE = '1'
$env:HOST = '127.0.0.1'
$pythonPath = Join-Path $projectPath '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { $pythonPath = (Get-Command python).Source }
$dataPath = Join-Path $projectPath 'private'
New-Item -ItemType Directory -Path $dataPath -Force | Out-Null
try {
    $status = Invoke-RestMethod -Uri 'http://127.0.0.1:8770/healthz' -TimeoutSec 3
    if ($status.status -eq 'ok') { Write-Host '映序已经运行：http://127.0.0.1:8770/studio.html'; exit 0 }
} catch {}
Start-Process -FilePath $pythonPath -ArgumentList @('-X','utf8','server.py') -WorkingDirectory $projectPath -WindowStyle Hidden -RedirectStandardOutput (Join-Path $dataPath 'server.stdout.log') -RedirectStandardError (Join-Path $dataPath 'server.stderr.log')
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    try {
        $status = Invoke-RestMethod -Uri 'http://127.0.0.1:8770/healthz' -TimeoutSec 2
        Write-Host '映序已启动：http://127.0.0.1:8770/studio.html'
        exit 0
    } catch { Start-Sleep -Milliseconds 250 }
}
throw '服务未启动，请检查 private/server.stderr.log，确认已安装 requirements.txt。'
