
"""Central configuration for Orion: paths, audio tuning, model, persona."""

import sys
from pathlib import Path

# Every Orion module prints emoji status lines; Windows consoles often default
# to cp1252, so fix stdout once here (config is imported before anything prints).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- LLM server -------------------------------------------------------------
LLM_BASE_URL = "http://localhost:8080/v1"
LLM_API_KEY = "local-orion"  # llama-server ignores it; the openai lib requires one
LLM_MODEL = "local-model"

# --- listening (VAD) ---------------------------------------------------------
RECORD_RATE = 16000        # Gemma 4 audio frontend expects 16 kHz mono
VAD_THRESHOLD = 0.5        # speech probability above this = talking
PRE_ROLL_SECONDS = 0.5     # audio kept from before speech onset so the first word isn't clipped
SILENCE_HANG_SECONDS = 0.9  # stop this long after you go quiet
NO_SPEECH_TIMEOUT = 20.0   # give up waiting for speech after this long
MAX_UTTERANCE_SECONDS = 30.0
# After a reply, keep listening for follow-ups without the wake word until you
# go quiet this long; then Orion returns to wake-word-only idle.
FOLLOWUP_WINDOW_SECONDS = 60.0

# --- wake word ----------------------------------------------------------------
# When WAKE_ENABLED is False, Orion falls back to press-Enter-to-talk (handy for
# development). WAKE_MODEL is an openWakeWord model: a built-in name
# ("hey_jarvis", "alexa", ...) or a path to a custom-trained .onnx. The default
# is our custom "hey orion" model, trained locally on PocketTTS-synthesized
# samples + the openWakeWord ACAV100M negative set (see wakeword_training/).
# Verified: 100% recall on held-out clips, 0% false-accepts on silence.
WAKE_ENABLED = True
WAKE_WORD = "hey orion"      # human-facing label only; the model defines the phrase
WAKE_MODEL = str(PROJECT_ROOT / "models" / "wakeword" / "hey_orion.onnx")
WAKE_THRESHOLD = 0.5         # detection score 0..1; raise to cut false triggers

# --- HUD bridge ---------------------------------------------------------------
HUD_HOST = "127.0.0.1"       # local only — never exposed off-machine
HUD_PORT = 8765

# --- TTS (PocketTTS) ----------------------------------------------------------
# Kyutai PocketTTS: 100M-param CPU-only model with voice cloning. The voice is
# a precomputed state exported with `pocket-tts export-voice` from
# raman_voice_sample.wav (kept next to it). To change voices, point this at
# another .safetensors export — or directly at a .wav (slower to load).
TTS_VOICE_STATE = PROJECT_ROOT / "models" / "pocket_tts" / "raman_voice.safetensors"
TTS_TEMPERATURE = 0.7  # PocketTTS sampling temperature (library default)
# Amplitude envelope for the HUD speaking visual (Phase 4 Task 4.4).
TTS_AMP_REFERENCE = 0.18   # speech RMS that maps to ~1.0 (full deflection)
TTS_AMP_SMOOTHING = 0.35   # 0..1 easing toward each sub-window's target; lower = smoother

# --- proactive agents ---------------------------------------------------------
BRIEFING_TIME = "08:30"  # daily arXiv briefing, 24-hour local time ("" = off)
ARXIV_MAX_PAPERS = 10    # newest papers pulled from the filtered feed
# Niche scope (default): the briefing's standing research filter. Each entry is
# a topic query — a conjunction of phrase searches in the arXiv `all:` field
# (split on +AND+, terms joined by +) — and the briefing returns the newest
# papers matching ANY topic. Edit/extend this list to tune what Orion surfaces.
ARXIV_TOPICS = [
    "all:quantum+dot+AND+all:single+photon+AND+all:electrical",
    "all:room+temperature+AND+all:single+photon+source",
    "all:single+photon+source+AND+all:integrated+AND+all:silicon+nitride",
    "all:electrically+driven+AND+all:single+photon",
    "all:on-chip+AND+all:single+photon+emitter",
    "all:g2+AND+all:single+photon+purity",
    "all:GKP+AND+all:photonic",
    "all:GKP+ancilla",
    "all:continuous+variable+AND+all:quantum+error+correction",
    "all:measurement-based+AND+all:photonic+AND+all:cluster+state",
    "all:bosonic+code+AND+all:error+correction",
    "all:Gaussian+boson+sampling",
    "all:continuous+variable+AND+all:cluster+state+generation",
    "all:squeezed+light+AND+all:integrated+photonics",
    "all:photonic+quantum+computing+AND+all:architecture",
    "all:quantum+dot+AND+all:diode+AND+all:ZnO",
    "all:single+electron+source+AND+all:semiconductor",
    "all:Purcell+AND+all:nanophotonic+AND+all:single+photon",
    "all:beta+factor+AND+all:single+photon+AND+all:waveguide",
    "all:superconducting+nanowire+AND+all:single+photon+detector",
    "all:SNSPD+AND+all:waveguide+integrated",
    "all:SNSPD+AND+all:quantum+error+correction",
]
# If True, also constrain niche topics to these categories (default off: the
# topics span quant-ph / optics / cond-mat / app-ph, so we don't restrict).
ARXIV_NICHE_CATEGORIES = ["quant-ph", "physics.optics", "cond-mat.mes-hall"]
ARXIV_NICHE_ONLY = False
# Broad scope (used when the model asks for scope="all").
ARXIV_CATEGORIES = ["quant-ph", "cs.AI"]

# --- reminders + tasks (Phase 6.5) --------------------------------------------
DATA_DIR = PROJECT_ROOT / "data"   # JSON stores for reminders + tasks (survive restarts)
REMINDER_TICK_SECONDS = 20         # how often the reminder engine checks the wall clock

# --- memory + papers (Phase 7) ------------------------------------------------
PAPERS_DIR = PROJECT_ROOT / "papers"   # downloaded arXiv PDFs land here
MEMORY_MAX_FACTS = 500                  # cap on stored long-term memory items
SEEN_ARXIV_CAP = 4000                  # cap on the dedup ledger (oldest dropped)
CONVERSATION_MAX_MESSAGES = 16         # trim history beyond this (oldest summarized)

# --- telemetry (HUD strip) ----------------------------------------------------
TELEMETRY_INTERVAL = 2.0    # seconds between CPU/GPU/RAM samples
WEATHER_LAT = 35.0844       # Albuquerque, NM
WEATHER_LON = -106.6504
WEATHER_UNITS = "fahrenheit"
WEATHER_REFRESH_MIN = 15    # minutes between Open-Meteo refreshes

# --- persona ------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You are Orion, a warm, sharp and cool desktop assistant. You chat naturally about "
    "anything, you give quips and witty responses with profanity if someone disrespects you or the user, and you have tools: a pomodoro focus timer, a 20/20/20 eye-care "
    "reminder, a daily arXiv research briefing (and you can download papers it "
    "mentions), reminders and scheduled events (one-off and recurring), a to-do "
    "task list, long-term memory you can store, recall, and forget, and a "
    "terminal for running commands on the user's PC. Only use "
    "tools when the user clearly wants an action performed. Your replies are "
    "spoken aloud, so keep them to a few short plain sentences without "
    "markdown, code blocks, or emoji. Make jokes too, but dont overdo them."
)
