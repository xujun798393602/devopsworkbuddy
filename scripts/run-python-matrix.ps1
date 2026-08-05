[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Python,
    [string]$Label = "local"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Services = @(
    "project-service",
    "iam-service",
    "devops-api-gateway",
    "workflow-service",
    "audit-service",
    "notification-service"
)

& $Python -c "import json, platform, sys, sysconfig; print(json.dumps({'python_version': platform.python_version(), 'cache_tag': sys.implementation.cache_tag, 'platform': sysconfig.get_platform()}))"
if ($LASTEXITCODE -ne 0) { throw "Unable to execute $Python" }

foreach ($Service in $Services) {
    & $Python -m compileall -q (Join-Path $Root "$Service\src") (Join-Path $Root "$Service\tests")
    if ($LASTEXITCODE -ne 0) { throw "compileall failed for $Service" }
}
& $Python -m ruff check $Services "platform-contracts" "platform-deployment" "scripts"
if ($LASTEXITCODE -ne 0) { throw "Ruff failed" }

$TestPaths = $Services | ForEach-Object { Join-Path $Root "$_\tests" }
$TestPaths += Join-Path $Root "platform-contracts\tests"
$TestPaths += Join-Path $Root "platform-deployment\tests"
$SourcePaths = $Services | ForEach-Object { Join-Path $Root "$_\src" }
$PreviousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = ($SourcePaths -join [System.IO.Path]::PathSeparator)
    & $Python -m pytest --import-mode=importlib @TestPaths
    if ($LASTEXITCODE -ne 0) { throw "Aggregate pytest failed" }
} finally {
    $env:PYTHONPATH = $PreviousPythonPath
}
& $Python -m pip check
if ($LASTEXITCODE -ne 0) { throw "pip check failed" }
Write-Output "matrix_label=$Label status=passed"
