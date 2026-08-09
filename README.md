# Project Orion

A fully local, voice-driven desktop assistant ("Jarvis") for Windows. Everything
runs on-device — no cloud calls, no API keys. You say **"hey Orion"**, talk
naturally, and it answers out loud in a cloned voice while a translucent
Tauri/Svelte HUD shows state, transcripts, telemetry, reminders, and tasks.

## Stack

| Piece | What it is |
|---|---|
| LLM | Gemma 4 12B IT (Q4_K_M GGUF) served by **llama.cpp** (`llama-server`) on GPU, with the audio/vision mmproj for native speech understanding |
| TTS | **PocketTTS** (Kyutai, 100M params, CPU-only) with a custom cloned voice |
| Wake word | **openWakeWord** with a custom-trained "hey orion" ONNX model (training pipeline included in `wakeword_training/`) |
| VAD | Silero VAD gating the mic — speech in, base64 WAV out |
| HUD | Tauri + Svelte overlay, fed over a local WebSocket bridge (`127.0.0.1:8765`) |

Hardware target: RTX 5070 Ti (16 GB) for the LLM, everything else on CPU.
Rule of thumb: **the LLM owns the GPU; nothing else touches VRAM.**

## Agentic features (13 tools)

- Pomodoro focus timer and 20/20/20 eye-care reminders
- Daily arXiv research briefing on a configurable topic filter, with paper
  download, dedup ledger, and an open-papers-folder tool
- Reminders and scheduled events (one-off and recurring, sleep-proof scheduler)
- To-do task list
- Long-term memory (store / recall / forget facts, persisted as JSON)
- Terminal tool for running commands on the PC
- Movie mode: ambient blackout screensaver (10 themes / 6 engines) across
  secondary monitors, voice-selected
- Sleep / wake control

See `ARCHITECTURE.md` for the full design: state machine, event hub, HUD
protocol, scheduler, and per-phase history.

## Repo layout

```
src/                  # assistant core: orion.py entry, listening, llm, speech,
                      # wakeword, scheduler, state, events, hud_server, telemetry,
                      # memory, and agents/ (one module per tool)
hud/                  # Tauri + Svelte HUD overlay (demo_bridge.py to drive it standalone)
wakeword_training/    # reproducible "hey orion" trainer + verifier scripts
tests/                # unit + e2e tests (e2e ones need llama-server running)
models/wakeword/      # trained hey_orion.onnx (small, committed)
start-orion.ps1       # one-command launcher: server + HUD + assistant; -Stop frees all
requirements.txt
ARCHITECTURE.md
```

## Not in this repo (deliberately)

The `.gitignore` keeps out everything heavy, personal, or machine-specific.
You must supply these yourself:

| Path | What / where to get it |
|---|---|
| `models/gemma-4-12b-it-Q4_K_M.gguf` | Gemma 4 12B IT Q4_K_M GGUF (~6.7 GB) — use a conversion that includes the June 2026 audio fix (llama.cpp PR #24118) |
| `models/mmproj-F16.gguf` | matching audio/vision projector (unsloth) |
| `models/pocket_tts/<your_voice>.safetensors` | your own voice: record a sample, run `pocket-tts export-voice`, point `TTS_VOICE_STATE` in `src/config.py` at it |
| `bin/llama/` | llama.cpp Windows CUDA binaries, build **b9585 or newer** |
| `orion_env/` | Python 3.12 venv (see setup below) |
| `data/`, `papers/` | created at runtime (personal memory, reminders, downloaded PDFs) |

## Setup

```powershell
# 1. Python env
python -m venv orion_env
orion_env\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Drop the models and llama.cpp binaries into models/ and bin/llama/ (table above)

# 3. HUD (optional but recommended)
cd hud; npm install; npm run tauri build

# 4. Launch everything (llama-server + HUD + assistant)
.\start-orion.ps1
# ...and to shut it all down:
.\start-orion.ps1 -Stop
```

All tuning knobs — paths, VAD timing, wake-word threshold, persona prompt,
briefing time, arXiv topics, weather location — live in `src/config.py`.

## Tests

```powershell
python -m pytest tests/ -k "not e2e"   # unit tests, no server needed
.\start-orion-server.ps1               # then the e2e suites
python tests/test_e2e.py
```
