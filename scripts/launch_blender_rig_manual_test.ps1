<#
.SYNOPSIS
Starts Blender with the COA Tools 2 checkout containing this script.

.DESCRIPTION
The default mode uses a new temporary Blender profile. Use -UseCurrentProfile
to load the normal Blender preferences while temporarily overriding only the
user scripts directory for the launched process. No installed add-on files are
deleted or overwritten in either mode. When -BlenderExecutable is omitted, the
newest version found under Program Files\Blender Foundation is selected.
The sample switches enable this checkout first and then open a temporary copy
of the requested rig demo, so its Driver namespace is ready.

.EXAMPLE
.\scripts\launch_blender_rig_manual_test.ps1

.EXAMPLE
.\scripts\launch_blender_rig_manual_test.ps1 -UseCurrentProfile

.EXAMPLE
.\scripts\launch_blender_rig_manual_test.ps1 -OpenSemanticSample

.EXAMPLE
.\scripts\launch_blender_rig_manual_test.ps1 -OpenAnimationControlsSample

.EXAMPLE
.\scripts\launch_blender_rig_manual_test.ps1 -BlenderExecutable "D:\Blender\blender.exe"
#>
[CmdletBinding()]
param(
    [Parameter()]
    [string]$BlenderExecutable = "",

    [Parameter()]
    [switch]$UseCurrentProfile,

    [Parameter()]
    [switch]$OpenSemanticSample,

    [Parameter()]
    [switch]$OpenAnimationControlsSample
)

$ErrorActionPreference = "Stop"

function Find-BlenderExecutable {
    $installationRoot = Join-Path $env:ProgramFiles "Blender Foundation"
    $installations = @()
    if (Test-Path -LiteralPath $installationRoot -PathType Container) {
        foreach ($directory in Get-ChildItem -LiteralPath $installationRoot -Directory) {
            if ($directory.Name -notmatch '^Blender\s+(\d+(?:\.\d+){1,2})$') {
                continue
            }
            $candidate = Join-Path $directory.FullName "blender.exe"
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                $installations += [PSCustomObject]@{
                    Version = [version]$Matches[1]
                    Path = $candidate
                }
            }
        }
    }

    $newest = $installations | Sort-Object Version -Descending | Select-Object -First 1
    if ($null -ne $newest) {
        return $newest.Path
    }

    throw "No Blender installation was found under '$installationRoot'. Pass -BlenderExecutable with the full blender.exe path."
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
$sampleSource = ""
$sampleFileName = ""
if ($OpenSemanticSample -and $OpenAnimationControlsSample) {
    throw "Choose only one sample switch per Blender session."
}
if ($OpenSemanticSample) {
    $sampleFileName = "semantic_character_rig_demo.blend"
}
elseif ($OpenAnimationControlsSample) {
    $sampleFileName = "semantic_animation_controls_demo.blend"
}
if ($sampleFileName) {
    $sampleSource = Join-Path $repositoryRoot "samples\$sampleFileName"
    if (-not (Test-Path -LiteralPath $sampleSource -PathType Leaf)) {
        throw "Rig sample was not found: $sampleSource"
    }
    $sampleSource = (Resolve-Path -LiteralPath $sampleSource).Path
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$testRoot = Join-Path ([System.IO.Path]::GetTempPath()) "coa_tools2-rig-manual-$timestamp"
$scriptsRoot = Join-Path $testRoot "scripts"
$addonsRoot = Join-Path $scriptsRoot "addons"
$configRoot = Join-Path $testRoot "config"
$datafilesRoot = Join-Path $testRoot "datafiles"
$addonDestination = Join-Path $addonsRoot "coa_tools2"
$sample = ""

New-Item -ItemType Directory -Path $addonsRoot, $configRoot, $datafilesRoot | Out-Null
Copy-Item -LiteralPath $addonSource -Destination $addonDestination -Recurse
if ($sampleSource) {
    $sample = Join-Path $testRoot $sampleFileName
    Copy-Item -LiteralPath $sampleSource -Destination $sample
}

$environmentNames = @(
    "BLENDER_USER_SCRIPTS",
    "COA_TOOLS2_TEST_ADDONS",
    "COA_TOOLS2_TEST_BLEND_FILE"
)
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
if ($sample) {
    Write-Host "Blend:     $sample"
}
Write-Host "Test data: $testRoot"
Write-Host "Close Blender to return to this console." -ForegroundColor DarkGray

$blenderExitCode = 0
try {
    $env:BLENDER_USER_SCRIPTS = $scriptsRoot
    $env:COA_TOOLS2_TEST_ADDONS = $addonsRoot
    if ($sample) {
        $env:COA_TOOLS2_TEST_BLEND_FILE = $sample
    }
    else {
        [Environment]::SetEnvironmentVariable(
            "COA_TOOLS2_TEST_BLEND_FILE",
            $null,
            [EnvironmentVariableTarget]::Process
        )
    }
    if (-not $UseCurrentProfile) {
        $env:BLENDER_USER_CONFIG = $configRoot
        $env:BLENDER_USER_DATAFILES = $datafilesRoot
    }

    $bootstrapScript = Join-Path $PSScriptRoot "blender_rig_manual_bootstrap.py"
    $blenderArguments = @()
    if (-not $UseCurrentProfile) {
        $blenderArguments += "--factory-startup"
    }
    $blenderArguments += @("--python", $bootstrapScript)

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
