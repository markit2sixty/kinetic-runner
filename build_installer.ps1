param(
    [string]$AppVersion = '1.1.0',
    [switch]$SkipRunnerBuild
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$engineDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$distDir = Join-Path $engineDir 'dist'
$runnerExe = Join-Path $distDir 'PositionAnalyzer\PositionAnalyzer.exe'
$issPath = Join-Path $engineDir 'PositionAnalyzerInstaller.iss'
$buildRunnerScript = Join-Path $engineDir 'build_runner.ps1'
$localProgramDir = Join-Path $env:LOCALAPPDATA 'Programs'
$repoToolsDir = Join-Path $engineDir 'tools'

if (-not $SkipRunnerBuild) {
    & $buildRunnerScript
    if ($LASTEXITCODE -ne 0) {
        throw "Runner build failed with exit code $LASTEXITCODE"
    }
}

if (-not (Test-Path $runnerExe)) {
    throw "Packaged runner not found at $runnerExe"
}

if (-not (Test-Path $issPath)) {
    throw "Installer script not found at $issPath"
}

$isccCandidates = @(@(
    (Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
    (Join-Path $repoToolsDir 'Inno Setup 7\ISCC.exe'),
    (Join-Path $repoToolsDir 'Inno Setup 6\ISCC.exe'),
    (Join-Path $localProgramDir 'Inno Setup 7\ISCC.exe'),
    (Join-Path $localProgramDir 'Inno Setup 6\ISCC.exe'),
    'C:\Program Files (x86)\Inno Setup 7\ISCC.exe',
    'C:\Program Files\Inno Setup 7\ISCC.exe',
    'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
    'C:\Program Files\Inno Setup 6\ISCC.exe'
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique)

if (-not $isccCandidates) {
    throw "Inno Setup compiler not found. Install Inno Setup 6 or 7 so ISCC.exe is available, then rerun this script."
}

$isccExe = $isccCandidates | Select-Object -First 1

& $isccExe "/DMyAppVersion=$AppVersion" $issPath
if ($LASTEXITCODE -ne 0) {
    throw "Installer build failed with exit code $LASTEXITCODE"
}

$installerPath = Join-Path $distDir 'PositionAnalyzer-Setup.exe'
if (Test-Path $installerPath) {
    Write-Host "Built installer: $installerPath"
} else {
    throw "Installer build completed without producing $installerPath"
}