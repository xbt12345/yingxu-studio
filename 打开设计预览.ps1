$ErrorActionPreference = 'Stop'
$projectPath = $PSScriptRoot
$previewUrl = 'http://127.0.0.1:8770/design-preview.html#home'

& (Join-Path $projectPath '启动映序.ps1')

$ready = $false
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    try {
        $response = Invoke-WebRequest -Uri $previewUrl -TimeoutSec 2
        if ($response.StatusCode -eq 200) { $ready = $true; break }
    } catch {}
    Start-Sleep -Milliseconds 250
}

if (-not $ready) { throw "预览服务未能启动：$previewUrl" }
Start-Process -FilePath $previewUrl
