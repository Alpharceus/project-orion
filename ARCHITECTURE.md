# Project Orion — Architecture

A fully local, voice-driven desktop assistant ("Jarvis") with pluggable agentic
functions (pomodoro, 20/20/20 reminders, arXiv morning briefing, ...).
Everything runs on-device: no cloud calls, no API keys.

## Hardware budget

| Resource | Total | Owner |
|----------|-------|-------|
| GPU (RTX 5070 Ti) | 16 GB VRAM | Gemma 4 12B Q4_K_M (~7.1 GB weights + mmproj + KV cache ≈ 9–10 GB at 8k ctx) |
| CPU (Ryzen 7 9800X3D) | 8c/16t | PocketTTS (100M, ~2 cores, CPU-only by design), audio I/O, agent code |
| RAM | 32 GB DDR5 | Python runtime, buffers |

Rule: **the LLM owns the GPU; everything else runs on CPU.** PocketTTS via
PyTorch CPU never touches VRAM (upstream found no speedup on GPU at batch 1).

## Directory layout

```
Project Orion/
├── bin/llama/          # llama.cpp binaries + DLLs (build b9585 — includes the
│                       #   June 4 2026 Gemma 4 audio fix, PR #24118)
├── models/
│   ├── gemma-4-12b-it-Q4_K_M.gguf     # downloaded 2026-06-09 (post-fix conversion ✓)
│   ├── mmproj-F16.gguf                # audio/vision projector (unsloth, 2026-06-10)
│   ├── pocket_tts/
│   │   ├── raman_voice.safetensors    # cloned voice state (pocket-tts export-voice)
│   │   └── raman_voice_sample.wav     # source recording the clone was made from
│   └── wakeword/
│       └── hey_orion.onnx             # custom-trained wake word (openWakeWord)
├── src/
│   ├── orion.py        # entry point: wires listening → llm → speech together
│   ├── config.py       # ALL tuning knobs: paths, VAD timing, voice, persona
│   ├── listening.py    # mic capture, VAD-gated recording → base64 WAV
│   ├── llm.py          # llama-server client, streaming, tool-dispatch loop
│   ├── speech.py       # PocketTTS: cloned voice + streaming player + amplitude tap
│   ├── scheduler.py    # in-process daily scheduler (sleep-proof: re-checks wall clock)
│   ├── state.py        # formal state machine: idle/listening/thinking/speaking
│   ├── events.py       # thread-safe pub/sub hub (producers -> HUD bridge)
│   ├── hud_server.py   # local WebSocket bridge for the HUD (127.0.0.1:8765)
│   ├── wakeword.py     # openWakeWord CPU listener (custom "hey orion"); press-Enter fallback
│   ├── telemetry.py    # CPU/GPU/RAM (psutil/NVML) + weather (Open-Meteo) -> telemetry events
│   ├── memory.py       # persistent store: facts + arXiv dedup ledger + last briefing
│   └── agents/         # tool registry (__init__.py) + one module per agent
│                       #   (pomodoro, eye_care, terminal, arxiv_briefing, sleep,
│                       #    reminders, tasks, memory, movie) — 13 tools total
├── data/               # JSON stores: reminders.json, tasks.json, memory.json, movie.json
├── papers/             # arXiv PDFs downloaded via the download_paper tool
├── tests/              # test_agents.py (unit), test_e2e.py (needs llama-server),
│                       # test_phase3.py (scheduler + briefing unit),
│                       # test_phase4.py (state/events/bridge/amplitude unit),
│                       # test_phase4_e2e.py (full turn over bridge, needs llama-server),
│                       # test_tts_speed.py (voice load + CPU speed), play_voice_sample.py
├── orion_env/          # Python 3.12 venv (pocket-tts, openai, sounddevice, soundfile)
├── PocketTTS voice clone/  # upstream kyutai-labs/pocket-tts clone (reference + voice export)
├── wakeword_training/      # reproducible "hey orion" training (clips, trainer, verify, data)
├── hud/                    # Tauri + Svelte HUD overlay (Phase 5); demo_bridge.py to drive it
│                           #   src/lib/umbra/ = ported Project Umbra engines (movie mode);
│                           #   src/lib/{MovieMode,Reminders,Tasks}.svelte, movieWindows.js
├── start-orion.ps1         # one-command launcher: server + HUD + assistant; -Stop frees all
├── start-orion-hud.ps1     # launch the HUD (release exe, or dev fallback)
├── requirements.txt
└── ARCHITECTURE.md
```

## Runtime components

```
┌─────────────┐  wake word    ┌──────────────────────────┐  state/transcript/  ┌────────────┐
│  microphone  │ ────────────▶ │  src/orion.py (CPU)      │  agent/amplitude    │  HUD client │
│             │  16 kHz WAV   │  - wakeword.py (CPU oWW)  │ ══════════════════▶ │  (Phase 5,  │
└─────────────┘   (base64)    │  - records audio          │  ws://127.0.0.1:8765│   Tauri)    │
                              │  - state machine          │ ◀═══ commands ═════ │            │
┌─────────────┐               │  - OpenAI-compatible call │     (hud_server.py) └────────────┘
│   speaker    │ ◀──────────── │  - tool dispatch loop     │
└─────────────┘    samples    │  - PocketTTS @ 24 kHz    │
                              └─────────┬────────────────┘
                                        │ http://localhost:8080/v1
                              ┌─────────▼────────────────┐
                              │  llama-server (GPU)       │
                              │  Gemma 4 12B unified      │
                              │  text + audio + vision in │
                              └──────────────────────────┘
```
The HUD bridge is optional: the assistant runs fully with no client connected.

- **llama-server** is a long-running process; start it before orion.py with
  `.\start-orion-server.ps1` (the source of truth for flags). It runs:
  ```
  bin\llama\llama-server.exe -m models\gemma-4-12b-it-Q4_K_M.gguf ^
      --mmproj models\mmproj-F16.gguf --jinja -ngl 99 -np 1 -c 8192 ^
      --no-mmap -fa on -ctk q8_0 -ctv q8_0 --port 8080
  ```
  orion.py refuses to start unless `llm.server_ready()` (a `/health` probe)
  passes, and if the server dies mid-conversation it catches the
  `APIConnectionError`, drops the unanswered turn, and prompts a restart
  instead of crashing.
- **STT** is native to Gemma 4 (audio tokens via mmproj) — no separate
  whisper process. Audio must be 16 kHz mono WAV, sent base64 in the
  `input_audio` content part.
- **TTS** is Kyutai PocketTTS (pip `pocket-tts`, 100M params, PyTorch CPU,
  ~200 ms to first audio chunk, streamed). Output is **24 kHz** — play at
  24000, not 16000. The voice is a clone: `TTS_VOICE_STATE` in config.py points
  at `models/pocket_tts/raman_voice.safetensors`, exported from
  `raman_voice_sample.wav` with `pocket-tts export-voice`. Model weights
  auto-download from HuggingFace (kyutai/pocket-tts) to the HF cache on first
  load — the only network touch, one time.
- **Measured performance** (2026-06-11, CUDA confirmed): prompt eval
  1,400–1,900 tok/s, generation ~80 tok/s, ~9.7 GB VRAM. llama-server must run
  with `-np 1` — without it the auto-fitter creates 4 slots and quadruples
  KV-cache VRAM. Task Manager shows ~10 GB *committed* for llama-server but
  <0.5 GB is physically resident (an artifact of `--no-mmap`); real RAM
  pressure is low.
- **Tools/agents** are plain Python functions registered in the `tools=`
  parameter of the chat call; orion.py dispatches tool_calls and loops until
  the model produces a final answer.

## Roadmap

### Phase 1 — working voice loop  ✅
- [x] Python 3.12 venv, kokoro-onnx verified (2026-06-10; replaced by PocketTTS 2026-06-12)
- [x] Project restructure
- [x] Download mmproj file (mmproj-F16.gguf from unsloth, 2026-06-10)
- [x] Fix orion.py bugs (base64 audio, choices[0], 24 kHz playback, tools=
      registration + dispatch loop, TTS loaded once, conversation loop,
      UTF-8 stdout for Windows consoles)
- [x] End-to-end test passed 2026-06-10 (synthetic voice → STT → tool call → answer)
- [x] VAD listening: record until trailing silence instead of a fixed 5 s window
      (pysilero-vad / Silero ONNX on CPU; fixed 5 s window was truncating speech
      and causing "I'm not sure what you mean" replies)
- [x] Streamed TTS: speak sentence-by-sentence while the model is still generating

### Phase 2 — agent framework  ✅ tested 2026-06-11
- [x] Tool registry: one module per agent function under `src/agents/`
  (pomodoro, 20/20/20 reminder, terminal commands)
- [x] Proper tool-call dispatch loop with results fed back to the model
- [x] Guardrails on `run_terminal_command` (allowlist, blocklist, y/N
      confirmation at the console for everything else)
- [x] Tests: `tests/test_agents.py` (unit, no LLM) and `tests/test_e2e.py`
      (text → Gemma → tool calls, needs llama-server running)

### Phase 3 — proactive features  ✅ tested 2026-06-12
- [x] Scheduler: in-process daily jobs (src/scheduler.py). Waits in 30 s slices
      against the wall clock so a job fires late instead of skipping if the PC
      slept through its time. Jobs only run while orion.py is up.
- [x] arXiv briefing: agents/arxiv_briefing.py — fetch newest papers
      (export.arxiv.org Atom API, the one runtime network call) → summarize
      via Gemma `oneshot()` (llm.py, no tools) → spoken through notify().
      Auto-scheduled at startup from config.BRIEFING_TIME ("" disables);
      also a model tool: actions now / schedule / cancel / status.
      Knobs: BRIEFING_TIME, ARXIV_CATEGORIES, ARXIV_MAX_PAPERS (config.py).
      Verified e2e 2026-06-12: live fetch + Gemma summary reads naturally;
      model picks the tool from "schedule my research briefing for 9".

### Phase 4 — Wake word + state machine + HUD bridge  ✅ tested 2026-06-13
Backend foundation for the HUD (no visual work yet — that's Phase 5). See
`ORION_PHASE4_PLUS.md` for the full Phase 4–7 spec and `orion_hud_mockup.html`
for the visual reference.
- [x] **Wake word** (`wakeword.py`): openWakeWord on CPU (ONNX, never loads
      Gemma). `WakeWord.wait()` blocks until the phrase, owning the mic only
      during the idle wait and releasing it for the utterance. Detector is our
      **custom "hey orion"** model (`models/wakeword/hey_orion.onnx`), trained
      locally — see `wakeword_training/` for the reproducible pipeline (PocketTTS
      positives + openWakeWord ACAV100M negatives; no piper/TensorFlow needed).
      Verified 2026-06-13: 100% recall on held-out clips, 0% false-accepts on
      silence (~13% on deliberately homophone-like near-misses). `WAKE_ENABLED`
      falls back to press-Enter. Knobs: `WAKE_ENABLED/WAKE_WORD/WAKE_MODEL/WAKE_THRESHOLD`.
- [x] **State machine** (`state.py`): explicit idle→listening→thinking→speaking
      →idle. listening.py sets LISTENING on record; llm.py sets THINKING on
      request; speech.py sets SPEAKING on first audio and IDLE on queue drain;
      orion.py guarantees a final IDLE. Every transition publishes a `state` event.
- [x] **Event hub** (`events.py`) + **HUD bridge** (`hud_server.py`): thread-safe
      pub/sub feeds an asyncio `websockets` server on `127.0.0.1:8765` (started
      after `server_ready()`). Broadcasts state/transcript/agent/amplitude as
      compact JSON; caches state + active agents for a connect snapshot; relays
      inbound commands (dismiss) back onto the hub. **The assistant runs fine
      with no client connected** — events are dropped silently. Pomodoro and
      eye-care emit `agent` active/idle events.
- [x] **TTS amplitude tap** (`speech.py`): smoothed RMS envelope over ~20 ms
      sub-windows, published as `amplitude` events at ~50 Hz while speaking, to
      drive the Phase 5 speaking visual. Knobs: `TTS_AMP_REFERENCE/TTS_AMP_SMOOTHING`.
- Verified 2026-06-13: 20/20 `test_phase4.py` unit (incl. a real WebSocket
      client) + 5/5 `test_phase4_e2e.py` (live turn: idle→…→idle over the bridge,
      real amplitude, Gemma transcript). No regressions (test_agents 23/23,
      test_phase3 25/25).
- Conversation memory (the old Phase 4 checkbox) is **deferred to Phase 7**,
      built properly there (within-session history + persistent SQLite memory).

### Phase 5 — The HUD (Tauri + Svelte overlay)  ✅ verified 2026-06-13
On-screen overlay in `hud/`, matching `orion_hud_mockup.html`. A pure client of
the Phase 4 bridge — the assistant runs fine without it.
- **Shell** (`hud/src-tauri/`): transparent, frameless, always-on-top,
  skip-taskbar window; positions itself on the portrait monitor; global hotkey
  **Ctrl+Alt+O** toggles click-through (passthrough when dormant, interactive
  when summoned); reflects interactivity back to the bridge. `useHttpsScheme:false`.
- **Frontend** (`hud/src/`, Svelte 5 + SvelteKit static SPA): `Core.svelte`
  (canvas core, all four states, speaking driven by real `amplitude` events),
  dormant↔summoned compositions, wake edge-sweep, listening frame-glow, vignette,
  `Agents.svelte` (boot-cascade), `Telemetry/Transcript/Ticker`. Cold Star palette,
  locally-bundled fonts (no network).
- **Transport gotcha (important):** WebView2 blocks the webview from opening
  `ws://127.0.0.1` (private-network access), so the HUD connects through the
  **Tauri WebSocket plugin** (`tauri-plugin-websocket`) which runs the socket in
  Rust. `src/lib/ws.js` uses the plugin under Tauri and falls back to the native
  WebSocket in a plain browser.
- **Run it:** `.\start-orion-hud.ps1` (release exe), or `cd hud; npm run tauri dev`.
  Drive it without the assistant via `hud\demo_bridge.py`. NOTE: a plain debug
  `cargo build` exe loads the *dev-server URL*, so only `tauri dev` or a release
  `tauri build` produces a runnable standalone — don't run the debug exe directly.
- Toolchain: Node + Rust (rustup, MSVC) installed via winget; WebView2 already present.

### Phase 6 — Live data: telemetry + niche arXiv  ✅ tested 2026-06-13
- [x] **Telemetry** (`telemetry.py`): CPU%/RAM% (psutil) + GPU VRAM-GB/util%
      (NVML/pynvml) sampled every `TELEMETRY_INTERVAL` (2 s), folded with weather
      (Open-Meteo, no key, default Albuquerque, refreshed `WEATHER_REFRESH_MIN`),
      emitted as one combined `telemetry` event per tick. CPU-only; missing
      GPU/network just omits those fields. Started in orion.py.
- [x] **Niche arXiv** (`agents/arxiv_briefing.py`): default scope returns the
      newest papers matching ANY of `ARXIV_TOPICS` — Raman's standing list of ~22
      topic queries, each a conjunction of phrase searches, OR'd into one
      server-side query (`build_query`/`_topic_to_query`; ~1.2 KB, well within
      arXiv limits). Tool gained `keywords`/`keyword_mode` (extend|replace)/`scope`
      (niche|all) so the model steers per request — **verified live 2026-06-14**:
      Gemma picks `scope=all` for "across all of physics" and `keyword_mode=replace`
      for "only cat qubits". The scheduled job keeps the topic defaults; zero-result
      days fall back to niche-category newest-N and say so aloud.
- [x] **Ticker** (Task 6.4): a briefing run emits a `ticker` event with the
      on-topic titles; `hud_server` caches it for the connect snapshot.
- Verified 2026-06-13: 26/26 `test_phase6.py` + live telemetry over the bridge
      (real CPU/GPU/RAM + live weather) + live niche query returning on-topic
      papers. No regressions (agents 23, phase3 25, phase4 20).
- Knobs (config.py): `TELEMETRY_INTERVAL`, `WEATHER_LAT/LON/UNITS/REFRESH_MIN`,
      `ARXIV_TOPICS` (Raman's ~22 standing topic queries, finalized 2026-06-14),
      `ARXIV_NICHE_CATEGORIES`/`ARXIV_NICHE_ONLY` (optional category constraint,
      off by default), `ARXIV_CATEGORIES` (broad scope).

### Phase 6.5 — Event scheduler + task manager  ✅ tested 2026-06-14
- [x] **Reminders / events** (`agents/reminders.py`): persisted (data/reminders.json)
      one-off + recurring reminders. One tick thread (`REMINDER_TICK_SECONDS`)
      fires due items through notify(); overdue ones fire on the next tick after
      startup so nothing is silently lost. One-off via absolute time / specific
      date / relative ("in N min"); recurring daily / weekdays / weekly-on-days.
      Relative times resolved server-side so the model needn't know the clock.
      `reminder` tool: add / list / cancel.
- [x] **Tasks** (`agents/tasks.py`): persisted (data/tasks.json) to-do list with
      optional due (date+time → auto-creates a reminder; completing/removing the
      task clears it) and priority (low/normal/high, sorts the list). `task` tool:
      add / list / complete / remove.
- [x] Both surface as persistent HUD agent nodes (reminders ◴, tasks ▤) with a
      live count; started in orion.py. Verified: 23/23 `test_phase65.py`, no
      regressions (120 tests total green).

### Phase 7 — Memory  ✅ tested 2026-06-14
Storage is **JSON** (`data/memory.json`, via `src/memory.py`) — consistent with
the other stores and easy to seed/paste; recall is keyword-based (no embeddings).
- [x] **Long-term memory**: durable facts loaded into the system prompt at
      startup (`memory.preamble()`); model tools `memory_store` / `memory_recall`
      / `memory_forget`. `remember_many()` bulk-seeds a pasted "LLM memory".
- [x] **Within-session memory**: each utterance is transcribed to text
      (`llm.transcribe`) and kept as rolling **text** history (no audio-blob
      bloat), trimmed/summarized past `CONVERSATION_MAX_MESSAGES` (`llm.trim_history`).
      Bonus: the user's transcript now reaches the HUD, not just Orion's.
- [x] **arXiv dedup**: `memory.seen_arxiv` ledger; `run_briefing` skips papers
      already surfaced and says "nothing new" when there's nothing fresh.
- [x] **Article download**: `download_paper` tool — by arXiv id or by a title
      query matched against the last briefing — saves the PDF to `papers/`.
- [x] HUD: a `memory` node (◈) shows the fact count. Verified 2026-06-14:
      27/27 `test_phase7.py`, live transcription + dedup-across-briefings + a real
      PDF download; ~149 tests green overall.

### Phase 7.5 — HUD polish: side panels + always-visible agents  ✅ 2026-06-14
- [x] **Schedule + Tasks panels** (`Reminders.svelte`, `Tasks.svelte`): reminders
      and tasks moved off the agent row into two edge-hugging panels under the
      telemetry strip — Schedule (soonest-first) on the left, Tasks (priority-dotted:
      red=high, amber=normal, slate=low) on the right, center kept clear for the orb.
      Backend `reminders.py`/`tasks.py` now publish full-list snapshot events
      (`reminders_list`/`tasks_list`) instead of agent nodes; `hud_server` caches +
      snapshots them; `ws.js` has matching stores.
- [x] **Always-visible agent row** (`Agents.svelte`): the row is now a HARDCODED
      fixed list of the core tools so nodes are guaranteed visible regardless of
      backend event timing (fixed a recurring "inactive tools invisible" bug). Each
      node merges its live `agent` status: **idle = orange, active = blue**, with the
      boot-cascade on summon. `HUD_AGENT_IDS` is the backend mirror.
- [x] **Briefing detail**: `BRIEFING_SYSTEM_PROMPT` now names each highlighted
      paper's **title + lead author**. New `open_papers_folder` tool opens the
      `papers/` folder in Explorer ("show them to me").
- [x] **TTS chunk splitting** (`speech.py`): `say()` splits text to ≤46 tokens
      (sentence → clause `,;:—` → word windows, via the model's own tokenizer with a
      word-count fallback) so PocketTTS never warns / skips words on long spans.

### Phase 8 — Movie mode: ambient blackout screensaver  ✅ 2026-06-14
Idle animations ported from **Project Umbra** (`../project umbra`, a procedural
ambient screensaver) — voice-controlled, no networking ported.
- [x] **Engines** (`hud/src/lib/umbra/`): 10 animations over 6 Canvas-2D engines
      (cosmic drift, dust motes, abyssal fluid, volumetric smoke, glacial nebula,
      macro rain, digital rainfall, slow matrix, strata shift, solar corona). They
      are classic scripts sharing global lexical bindings (UmbraRenderer/ThemeBase/
      EngineBase), so `umbra-loader.js` imports them as raw strings (Vite `?raw`) and
      runs them as ONE inline script — bundled, not runtime-fetched (a `/umbra/*.js`
      fetch silently failed in the packaged webview; lesson: don't runtime-fetch
      assets in the Tauri webview).
- [x] **Blackout look**: `MovieMode.svelte` fills the monitor with SOLID BLACK and
      runs the animation on top (a screensaver to kill light/distraction on non-main
      screens). The animation layer is z-index 1, pointer-events:none — BELOW the HUD
      (z 10) and core orb (z 20), so the HUD stays above it when active. (Briefly
      built see-through first; user wanted the opaque blackout.)
- [x] **Multi-monitor** (`movieWindows.js`): default blacks out every monitor EXCEPT
      the main/primary one. The main HUD window spawns one fullscreen opaque,
      always-on-top, click-through, no-focus Tauri `WebviewWindow` per target monitor
      that isn't its own (each loads `/?blackout=1` → +page's blackout branch → a
      black `<MovieMode>` driven by its own ws feed, so "animation 3" updates every
      screen). The HUD's own monitor uses the in-HUD canvas, gated by `selfBlackout`.
      `screens` option: `others` (default) | `all` (include main). Tauri capabilities
      gained `core:webview:allow-create-webview-window` + `core:window:allow-close`
      and a `blackout-*` window glob. Scope: per-monitor (not cross-screen-continuous).
- [x] **Backend** (`agents/movie.py`): `movie_mode` tool (on / off / set 1-10, +
      `screens`); persists `data/movie.json`; publishes a `movie` event (drives the
      animation) AND an `agent` event (lights the ❖ Movie node blue/orange).
      `hud_server` relays/snapshots `movie`; `orion.py` restores it at startup.
- [x] **Sleep + movie**: movie mode is independent of the state machine and persists
      through sleep (it IS the idle animation). `orion._is_sleep_command` was hardened
      so "go to sleep **but keep the movie on**" (and leading/trailing filler) still
      registers as a dismissal — Orion goes dormant, the blackout keeps playing; only
      "movie mode off" stops it. `go_to_sleep` is told not to touch movie mode.
- Verified 2026-06-14: `test_phase8.py` 13/13, `test_phase8b.py` 13/13 (TTS split,
      movie node, open-folder), `test_phase8c.py` 16/16 (sleep-in-movie phrasing);
      phase65 23/23, phase6 28/28. HUD release rebuilt.
