Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$engineDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $engineDir
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
$entryScript = Join-Path $engineDir 'run_web_gui.py'
$distDir = Join-Path $engineDir 'dist'
$workDir = Join-Path $engineDir 'build'

if (-not (Test-Path $pythonExe)) {
    throw "Virtual environment Python not found at $pythonExe"
}

if (-not (Test-Path $entryScript)) {
    throw "Runner entry script not found at $entryScript"
}

$hasPyInstaller = (& $pythonExe -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('PyInstaller') else 1)")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is not installed in the workspace virtual environment. Run: $pythonExe -m pip install pyinstaller"
}

$previousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Continue'
    & $pythonExe -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --onedir `
        --name PositionAnalyzer `
        --distpath $distDir `
        --workpath $workDir `
        --specpath $engineDir `
        --hidden-import pynput.keyboard._win32 `
        --collect-submodules pynput.keyboard `
        --collect-submodules pynput.mouse `
        $entryScript

    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed with exit code $LASTEXITCODE"
    }
}
finally {
    $ErrorActionPreference = $previousErrorActionPreference
}

$exePath = Join-Path $distDir 'PositionAnalyzer\PositionAnalyzer.exe'
if (Test-Path $exePath) {
    Write-Host "Built executable: $exePath"
} else {
    throw "Build completed without producing $exePath"
}