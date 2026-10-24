# Creates voice_tools/.venv (Python 3.12) and installs the pipeline requirements.
# CPU-only torch comes from the PyTorch CPU wheel index. orion_env is never touched.
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $here ".venv"
$py = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "Creating venv at $venv"
    py -3.12 -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
}
& $py -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
& $py -m pip install -r (Join-Path $here "requirements.txt") --extra-index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) { throw "requirements install failed" }
& $py -c "import demucs, silero_vad, speechbrain, sklearn; print('voice_tools venv OK')"
if ($LASTEXITCODE -ne 0) { throw "import check failed" }
