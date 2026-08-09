<#
  Single-command Orion launcher.

    .\start-orion.ps1          Start everything: llama-server (background),
                               the HUD (background), and the assistant in THIS
                               terminal (so you can talk to it / answer prompts).
    .\start-orion.ps1 -Stop    Stop everything and free GPU + RAM.

  Ctrl+C stops just the assistant; the server + HUD keep running so you can
  relaunch quickly. Use -Stop to shut the whole stack down.
#>
param([switch]$Stop)

$root = $PSScriptRoot
$py = Join-Path $root "orion_env\Scripts\python.exe"

function Stop-Orion {
    Get-Process hud -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*src\orion.py*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Write-Host "Orion stopped. GPU and RAM freed." -ForegroundColor Green
}

if ($Stop) { Stop-Orion; return }

# 1. llama-server (background, minimized) - skip if already running.
if (-not (Get-Process llama-server -ErrorAction SilentlyContinue)) {
    Write-Host "Starting llama-server (loading Gemma onto the GPU)..." -ForegroundColor Cyan
    Start-Process powershell -ArgumentList "-NoExit", "-File", "`"$root\start-orion-server.ps1`"" -WindowStyle Minimized
}
Write-Host "Waiting for the model to load..." -ForegroundColor Cyan
$ready = $false
$deadline = (Get-Date).AddSeconds(180)
while ((Get-Date) -lt $deadline) {
    try { if ((Invoke-RestMethod "http://127.0.0.1:8080/health" -TimeoutSec 2).status -eq "ok") { $ready = $true; break } } catch {}
    Start-Sleep -Seconds 2
}
if ($ready) { Write-Host "llama-server ready." -ForegroundColor Green }
else { Write-Host "Server did not report ready in time; starting anyway (Orion will warn if it is down)." -ForegroundColor Yellow }

# 2. HUD (background) - auto-reconnects until orion.py opens the bridge.
$hudExe = Join-Path $root "hud\src-tauri\target\release\hud.exe"
if (Get-Process hud -ErrorAction SilentlyContinue) {
    Write-Host "HUD already running." -ForegroundColor Green
} elseif (Test-Path $hudExe) {
    Start-Process $hudExe
    Write-Host "HUD launched (Ctrl+Alt+O toggles click-through)." -ForegroundColor Green
} else {
    Write-Host "HUD release exe not found. Run start-orion-hud.ps1 separately, or build it first." -ForegroundColor Yellow
}

# 3. The assistant - foreground here, so the wake word + terminal y/N prompts work.
Write-Host "`nStarting Orion. Say the wake word to talk; Ctrl+C to stop the assistant.`n" -ForegroundColor Cyan
& $py (Join-Path $root "src\orion.py")

Write-Host "`nAssistant exited. Server + HUD are still running. Run '.\start-orion.ps1 -Stop' to shut everything down." -ForegroundColor Yellow
