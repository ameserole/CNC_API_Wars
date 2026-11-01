<#
.SYNOPSIS
    Builds GeneralsGameCode (Zero Hour) with VS 2022 Build Tools and optionally deploys/runs it from GameFiles.

.EXAMPLE
    .\scripts\build.ps1                      # configure + build win32-debug, target z_generals
    .\scripts\build.ps1 -Deploy -Run         # ...then copy outputs into GameFiles and launch windowed
    .\scripts\build.ps1 -Preset win32 -Clean # clean release build
    .\scripts\build.ps1 -Tests               # also build and run the script API unit tests
#>
param(
    [string]$Preset = "win32-debug",
    [string[]]$Target = @("z_generals"),
    [switch]$Clean,
    [switch]$Tests,
    [switch]$Deploy,
    [switch]$Run,
    [string[]]$GameArgs = @("-win", "-nologo", "-noshellmap")
)

$ErrorActionPreference = "Stop"
$Root     = Split-Path -Parent $PSScriptRoot
$Source   = Join-Path $Root "ZeroHourFork\GeneralsGameCode"
$GameDir  = Join-Path $Root "GameFiles"
$BuildDir = Join-Path $Source "build\$Preset"
$Config   = if ($Preset -like "*-debug") { "Debug" } else { "Release" }

# --- Import the x86 MSVC environment (equivalent of "x86 Native Tools Command Prompt") ---
function Import-VsEnvironment {
    if ($env:VSCMD_ARG_TGT_ARCH -eq "x86") { return }
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path $vswhere)) { throw "vswhere.exe not found; install VS 2022 Build Tools." }
    $vsPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if (-not $vsPath) { throw "No VS installation with the C++ x86/x64 tools found." }
    $vcvars = Join-Path $vsPath "VC\Auxiliary\Build\vcvarsall.bat"
    Write-Host "Using MSVC from $vsPath"
    # vcvarsall calls vswhere by name; without this it prints a harmless "not recognized" error.
    $env:PATH = "$(Split-Path $vswhere);$env:PATH"
    cmd /c "`"$vcvars`" x86 >nul && set" | ForEach-Object {
        if ($_ -match "^([^=]+)=(.*)$") { Set-Item -Path "env:$($Matches[1])" -Value $Matches[2] }
    }
}

Import-VsEnvironment

# CMake may not be on PATH in shells opened before it was installed.
if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) {
    $env:PATH = "$env:ProgramFiles\CMake\bin;$env:PATH"
}
foreach ($tool in "cmake", "ninja", "cl") {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool not found on PATH." }
}

if ($Clean -and (Test-Path $BuildDir)) {
    Write-Host "Removing $BuildDir"
    Remove-Item -Recurse -Force $BuildDir
}

Push-Location $Source
try {
    $testsFlag = if ($Tests) { "ON" } else { "OFF" }
    Write-Host "== Configure ($Preset)"
    # Multi-instance lets several game clients run side by side (integration tests, LAN bot matches).
    $multiInstance = if ($Config -eq "Debug") { "ON" } else { "OFF" }
    cmake --preset $Preset -DRTS_BUILD_OPTION_SCRIPT_API=ON "-DRTS_BUILD_OPTION_TESTS=$testsFlag" "-DRTS_DEBUG_MULTI_INSTANCE=$multiInstance"
    if ($LASTEXITCODE) { throw "CMake configure failed." }

    $targets = @($Target)
    if ($Tests) { $targets += "scriptapi_googletest" }
    Write-Host "== Build ($($targets -join ', '), $Config)"
    cmake --build $BuildDir --config $Config --target $targets
    if ($LASTEXITCODE) { throw "Build failed." }
}
finally {
    Pop-Location
}

if ($Tests) {
    $testExe = Get-ChildItem -Path $BuildDir -Recurse -Filter "scriptapi_googletest.exe" | Select-Object -First 1
    Write-Host "== Unit tests ($($testExe.FullName))"
    & $testExe.FullName --gtest_brief=1
    if ($LASTEXITCODE) { throw "Unit tests failed." }
}

if ($Target -notcontains "z_generals") { return }

$exe = Get-ChildItem -Path $BuildDir -Recurse -Filter "generalszh.exe" | Select-Object -First 1
if (-not $exe) { throw "Build finished but generalszh.exe was not found under $BuildDir." }
Write-Host "Built $($exe.FullName)"

if ($Deploy -or $Run) {
    # Copy the exe plus any DLLs/PDBs that sit next to it.
    Get-ChildItem -Path $exe.DirectoryName -File |
        Where-Object { $_.Extension -in ".exe", ".dll", ".pdb" -and $_.Name -notlike "*test*" } |
        ForEach-Object {
            Copy-Item $_.FullName -Destination $GameDir -Force
            Write-Host "Deployed $($_.Name)"
        }
}

if ($Run) {
    # Steam only registers the Zero Hour key; debug builds assert if the base Generals InstallPath is missing.
    $genKey = "HKCU:\Software\Electronic Arts\EA Games\Generals"
    if (-not (Get-ItemProperty -Path $genKey -Name InstallPath -ErrorAction SilentlyContinue)) {
        New-Item -Path $genKey -Force | Out-Null
        Set-ItemProperty -Path $genKey -Name InstallPath -Value (Join-Path $GameDir "ZH_Generals\")
        Write-Host "Registered Generals InstallPath -> $GameDir\ZH_Generals\"
    }

    Write-Host "Launching generalszh.exe $GameArgs"
    Start-Process -FilePath (Join-Path $GameDir "generalszh.exe") -ArgumentList $GameArgs -WorkingDirectory $GameDir
}
