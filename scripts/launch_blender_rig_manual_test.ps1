<#
.SYNOPSIS
Starts Blender with the COA Tools 2 checkout containing this script.

.DESCRIPTION
The default mode uses a new temporary Blender profile. Use -UseCurrentProfile
to load the normal Blender preferences while temporarily overriding only the
user scripts directory for the launched process. No installed add-on files are
deleted or overwritten in either mode.

.EXAMPLE
.\scripts\launch_blender_rig_manual_test.ps1

.EXAMPLE
.\scripts\launch_blender_rig_manual_test.ps1 -UseCurrentProfile

.EXAMPLE
.\scripts\launch_blender_rig_manual_test.ps1 -BlenderExecutable "D:\Blender\blender.exe"
#>
[CmdletBinding()]
param(
    [Parameter()]
    [string]$BlenderExecutable = "",

    [Parameter()]
    [switch]$UseCurrentProfile
)

$ErrorActionPreference = "Stop"

function Find-BlenderExecutable {
    $candidates = @(
        "C:\Program Files\Blender Foundation\Blender 5.0\blender.exe",
        "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe",
        "C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"
    )

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }

    throw "Blender 4.5, 5.0, or 5.1 was not found. Pass -BlenderExecutable with the full blender.exe path."
}

if ([string]::IsNullOrWhiteSpace($BlenderExecutable)) {
    $BlenderExecutable = Find-BlenderExecutable
}

if (-not (Test-Path -LiteralPath $BlenderExecutable -PathType Leaf)) {
    throw "Blender executable was not found: $BlenderExecutable"
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$addonSource = Join-Path $repositoryRoot "coa_tools2"
if (-not (Test-Path -LiteralPath (Join-Path $addonSource "__init__.py") -PathType Leaf)) {
    throw "COA Tools 2 add-on source was not found: $addonSource"
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$testRoot = Join-Path ([System.IO.Path]::GetTempPath()) "coa_tools2-rig-manual-$timestamp"
$scriptsRoot = Join-Path $testRoot "scripts"
$addonsRoot = Join-Path $scriptsRoot "addons"
$configRoot = Join-Path $testRoot "config"
$datafilesRoot = Join-Path $testRoot "datafiles"
$addonDestination = Join-Path $addonsRoot "coa_tools2"

New-Item -ItemType Directory -Path $addonsRoot, $configRoot, $datafilesRoot | Out-Null
Copy-Item -LiteralPath $addonSource -Destination $addonDestination -Recurse

$environmentNames = @("BLENDER_USER_SCRIPTS")
if (-not $UseCurrentProfile) {
    $environmentNames += @(
        "BLENDER_USER_CONFIG",
        "BLENDER_USER_DATAFILES"
    )
}
$previousEnvironment = @{}
foreach ($name in $environmentNames) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable(
        $name,
        [EnvironmentVariableTarget]::Process
    )
}

$sessionMode = if ($UseCurrentProfile) {
    "current Blender profile with a temporary add-on override"
}
else {
    "isolated factory profile"
}
Write-Host "Starting COA Tools 2 rig test session..." -ForegroundColor Cyan
Write-Host "Mode:      $sessionMode"
Write-Host "Blender:   $BlenderExecutable"
Write-Host "Add-on:    $addonSource"
Write-Host "Test data: $testRoot"
Write-Host "Close Blender to return to this console." -ForegroundColor DarkGray

$blenderExitCode = 0
try {
    $env:BLENDER_USER_SCRIPTS = $scriptsRoot
    if (-not $UseCurrentProfile) {
        $env:BLENDER_USER_CONFIG = $configRoot
        $env:BLENDER_USER_DATAFILES = $datafilesRoot
    }

    $enableAddon = "import addon_utils; addon_utils.disable('coa_tools2', default_set=False); module = addon_utils.enable('coa_tools2', default_set=False, persistent=True); print('COA Tools 2 test source:', module.__file__ if module else 'LOAD FAILED')"
    $blenderArguments = @()
    if (-not $UseCurrentProfile) {
        $blenderArguments += "--factory-startup"
    }
    $blenderArguments += @("--python-expr", $enableAddon)

    & $BlenderExecutable @blenderArguments
    $blenderExitCode = $LASTEXITCODE
}
finally {
    foreach ($name in $environmentNames) {
        $previousValue = $previousEnvironment[$name]
        if ($null -eq $previousValue) {
            [Environment]::SetEnvironmentVariable(
                $name,
                $null,
                [EnvironmentVariableTarget]::Process
            )
        }
        else {
            [Environment]::SetEnvironmentVariable(
                $name,
                $previousValue,
                [EnvironmentVariableTarget]::Process
            )
        }
    }
}

if ($blenderExitCode -ne 0) {
    throw "Blender exited with code $blenderExitCode. Test data remains at: $testRoot"
}

Write-Host "Blender closed normally. Test data remains at:" -ForegroundColor Green
Write-Host $testRoot
