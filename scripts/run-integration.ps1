<#
.SYNOPSIS
    Runs the script API Python tests against the game deployed in GameFiles.

.EXAMPLE
    .\scripts\run-integration.ps1              # unit + integration tests against the deployed exe
    .\scripts\run-integration.ps1 -Build       # build.ps1 -Tests -Deploy first
    .\scripts\run-integration.ps1 -k lifecycle # extra arguments go to pytest
#>
# Deliberately not an advanced script (no [Parameter] attributes): PowerShell would then add common
# parameters such as -PipelineVariable, which pytest flags like -p would match. Everything except
# -Build ends up in $args and goes to pytest unchanged.
param(
    [switch]$Build
)
$PytestArgs = @($args)

$ErrorActionPreference = "Stop"
$Root      = Split-Path -Parent $PSScriptRoot
$PythonDir = Join-Path $Root "python"
$Venv      = Join-Path $PythonDir ".venv"
$Python    = Join-Path $Venv "Scripts\python.exe"

if ($Build) {
    & (Join-Path $PSScriptRoot "build.ps1") -Tests -Deploy
    if ($LASTEXITCODE) { throw "Build failed." }
}

if (-not (Test-Path $Python)) {
    Write-Host "Creating Python venv in $Venv"
    py -3.12 -m venv $Venv
    & $Python -m pip install -q --upgrade pip
    & $Python -m pip install -q -e "$PythonDir[test]"
}

$env:GENERALS_TEST_RESULTS = Join-Path $Root ("test-results\" + (Get-Date -Format "yyyyMMdd-HHmmss"))
Write-Host "Results: $env:GENERALS_TEST_RESULTS"

Push-Location $PythonDir
try {
    # Paths given in the pass-through replace the default "tests".
    $hasPath = @($PytestArgs | Where-Object { $_ -and -not $_.StartsWith("-") -and (Test-Path $_) }).Count -gt 0
    if ($hasPath) { & $Python -m pytest @PytestArgs } else { & $Python -m pytest tests @PytestArgs }
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
