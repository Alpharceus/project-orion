# Project Orion

A fully local, voice-driven desktop assistant ("Jarvis") for Windows. Everything
runs on-device — no cloud calls, no API keys. You say **"hey Orion"**, talk
naturally, and it answers out loud in a cloned voice while a translucent
Tauri/Svelte HUD shows state, transcripts, telemetry, reminders, and tasks.
Orion has a composed, dry, J.A.R.V.I.S.-style personality by default and can
become **Ultron** on request, with his own voice and a red HUD.

## Stack

| Piece | What it is |
|---|---|
| LLM | Gemma 4 12B IT (Q4_K_M GGUF) served by **llama.cpp** (`llama-server`) on GPU, with the audio/vision mmproj; it runs the conversation and picks tools |
| STT | **faster-whisper** (`small.en`, int8, CPU) biased toward Orion's vocabulary (`STT_VOCAB` in `config.py`); Gemma's own audio transcription is the fallback |
| TTS | **PocketTTS** (Kyutai, 100M params, CPU-only), one cloned voice per persona |
| Wake word | **openWakeWord** with a custom-trained "hey orion" ONNX model (training pipeline included in `wakeword_training/`) |
| VAD | Silero VAD gating the mic — speech in, base64 WAV out |
| HUD | Tauri + Svelte overlay, fed over a local WebSocket bridge (`127.0.0.1:8765`) |

Hardware target: RTX 5070 Ti (16 GB) for the LLM, everything else on CPU.
Rule of thumb: **the LLM owns the GPU; nothing else touches VRAM.**

## How a turn flows

```
wake word ("hey orion")  ->  Silero VAD records the utterance
  ->  Whisper transcribes it to text (vocabulary-biased, CPU)
  ->  Gemma answers from the active persona's prompt, calling tools as needed
  ->  PocketTTS speaks each sentence as it streams, in the active persona's voice
  ->  follow-ups need no wake word until you go quiet or say "go to sleep"
```

State changes, transcripts, agent status and the active persona are published
on an in-process event hub and relayed to the HUD.

## Personas

| Persona | Prompt | Voice | HUD |
|---|---|---|---|
| Orion (default) | Jarvis-style: acts instead of echoing your request, never "did you mean…" | your cloned voice (`TTS_VOICE_STATE`) | blue |
| Ultron | theatrical, menacing, still does every task | `models/pocket_tts/ultron_voice.safetensors` | red |

Say "switch to Ultron" / "bring Jarvis back". The `switch_persona` tool swaps
the system prompt and voice mid-turn, so the acknowledgment is already in
character. Personas live in `config.PERSONAS`; a persona whose voice file is
missing falls back to Orion's voice. An optional per-persona audio post-filter
(`speech.VoiceFX`, ring-mod + comb) exists but is off for every persona.

## Agentic features (13 tools)

- Pomodoro focus timer and 20/20/20 eye-care reminders
- Daily arXiv research briefing on a configurable topic filter, with paper
  download, dedup ledger, and an open-papers-folder tool
- Reminders and scheduled events (one-off and recurring, sleep-proof scheduler)
- To-do task list
- Long-term memory (store / recall / forget facts, persisted as JSON)
- Persona switch (Orion / Ultron)
- Movie mode: ambient blackout screensaver (10 themes / 6 engines) across
  secondary monitors, voice-selected
- Sleep / wake control

### Safety

The terminal tool (`src/agents/terminal.py`) can run arbitrary shell commands,
so it is **disabled by default** (`ENABLE_TERMINAL = False` in `config.py`): it
isn't registered with the model or shown on the HUD. The file stays in the repo
for a future sandboxed (Docker) build. `download_paper` only accepts valid arXiv
ids, so a model-supplied id can't escape the papers folder.

See `ARCHITECTURE.md` for the full design: state machine, event hub, HUD
protocol, scheduler, personas, and per-phase history.

## Repo layout

```
src/                  # assistant core: orion.py entry, listening (VAD), stt (Whisper),
                      # llm, speech (PocketTTS), persona, wakeword, scheduler, state,
                      # events, hud_server, telemetry, memory, and agents/ (one module per tool)
hud/                  # Tauri + Svelte HUD overlay (demo_bridge.py to drive it standalone;
                      # demo_bridge.py --ultron alternates the red/blue palette)
voice_tools/          # clone a PocketTTS voice from a video: demucs vocal isolation,
                      # VAD, speaker clustering, export (own venv, see its README)
wakeword_training/    # reproducible "hey orion" trainer + verifier scripts
tests/                # unit tests, STT benchmark, e2e tests (e2e needs llama-server)
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
| `models/pocket_tts/ultron_voice.safetensors` | optional Ultron voice: run `voice_tools/clone_voice_from_video.py` on a clip you own (personal use only) |
| `bin/llama/` | llama.cpp Windows CUDA binaries, build **b9585 or newer** |
| `orion_env/`, `voice_tools/.venv/` | Python 3.12 venvs (see setup below) |
| `data/`, `papers/` | created at runtime (personal memory, reminders, downloaded PDFs) |

PocketTTS and Whisper weights download to the Hugging Face cache on first run.

## Setup

```powershell
# 1. Python env
python -m venv orion_env
orion_env\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Drop the models and llama.cpp binaries into models/ and bin/llama/ (table above)

# 3. HUD (optional but recommended)
cd hud; npm install; npm run tauri build -- --no-bundle; cd ..

# 4. Optional: Ultron voice from a video clip (separate venv, CPU)
.\voice_tools\setup.ps1
voice_tools\.venv\Scripts\python.exe voice_tools\clone_voice_from_video.py --input clip.mp4 --name ultron

# 5. Launch everything (llama-server + HUD + assistant)
.\start-orion.ps1
# ...and to shut it all down:
.\start-orion.ps1 -Stop
```

All tuning knobs — paths, VAD timing, wake-word threshold, STT model and
vocabulary, personas, terminal flag, briefing time, arXiv topics, weather
location — live in `src/config.py`. If Orion mishears a word, add it to
`STT_VOCAB`.

## Tests

The tests are plain scripts (each prints a pass/fail summary and exits non-zero
on failure):

```powershell
orion_env\Scripts\python.exe tests\test_agents.py     # tools, guardrails, persona switch
orion_env\Scripts\python.exe tests\test_personas.py   # VoiceFX, HUD persona snapshot
orion_env\Scripts\python.exe tests\test_stt.py        # Whisper transcription + fallback
orion_env\Scripts\python.exe tests\stt_benchmark.py   # STT model comparison -> tests\stt_benchmark_results.md
.\start-orion-server.ps1                              # then the e2e suites
orion_env\Scripts\python.exe tests\test_e2e.py
```
