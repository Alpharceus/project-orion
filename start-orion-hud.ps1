# Launch the Orion HUD overlay (Tauri + Svelte). It's a pure client of the
# WebSocket bridge at ws://127.0.0.1:8765, which is started by src/orion.py
# (the assistant) - or by hud\demo_bridge.py for a standalone visual demo.
#
# Prefers the standalone release build; falls back to `npm run tauri dev` if it
# hasn't been built yet (needs Node + Rust on PATH).

$root = $PSScriptRoot
$exe = Join-Path $root "hud\src-tauri\target\release\hud.exe"

if (Test-Path $exe) {
    Start-Process $exe
    Write-Host "Orion HUD launched. Toggle click-through with Ctrl+Alt+O."
} else {
    Write-Host "No release build found. Building it is faster long-term:"
    Write-Host "  cd hud; npm run tauri build -- --no-bundle"
    Write-Host "Launching the dev HUD instead..."
    Push-Location (Join-Path $root "hud")
    npm run tauri dev
    Pop-Location
}
