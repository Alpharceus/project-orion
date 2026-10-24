
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

# --- speech-to-text -----------------------------------------------------------
# faster-whisper (CTranslate2) on CPU transcribes your utterances; the LLM owns
# the GPU. "gemma" sends the audio to Gemma 4 instead (also the automatic
# fallback if Whisper fails). Model/beam/threads/bias were chosen by
# tests/stt_benchmark.py (see tests/stt_benchmark_results.md).
STT_ENGINE = "whisper"        # "whisper" | "gemma"
STT_MODEL = "small.en"        # "large-v3-turbo" | "distil-large-v3" | "small.en"
STT_DEVICE = "cpu"
STT_COMPUTE_TYPE = "int8"
STT_BEAM_SIZE = 5
STT_CPU_THREADS = 6           # leaves cores for PocketTTS and the rest of Orion
STT_BIAS = "hotwords"         # "hotwords" | "initial_prompt" | "none"
# Words Whisper is biased toward. Add words here when Orion mishears them.
STT_VOCAB = [
    "Orion", "Ultron", "Jarvis", "Raman", "pomodoro", "arXiv", "eye care",
    "twenty twenty twenty", "movie mode", "Umbra", "GKP", "SNSPD",
    "Gaussian boson sampling", "squeezed light", "quantum dot", "single photon",
    "Purcell", "qubit", "CHTM", "Osinski", "Tempest",
]

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

# --- safety -------------------------------------------------------------------
# The terminal tool (agents/terminal.py) can run arbitrary shell commands, which
# is an unbounded blast radius on a bare host. It stays in the repo but is not
# registered unless this is True — re-enable only inside a sandbox (Docker).
ENABLE_TERMINAL = False

# --- personas -----------------------------------------------------------------
# Orion's default character plus alternates, switched by voice through the
# switch_persona tool. Each persona has its own system prompt and PocketTTS
# voice state; a missing voice file falls back to Orion's voice.
_TOOLS = (
    "Your tools: a pomodoro focus timer, 20/20/20 eye-care reminders, a daily arXiv "
    "research briefing (you can download the papers it mentions and open the "
    "papers folder), reminders and scheduled events (one-off and recurring), a "
    "to-do task list, long-term memory you can store, recall, and forget, movie "
    "mode (an ambient screensaver), and switch_persona, which changes who you are. "
    "Only use a tool when the user clearly wants an action performed. "
)
_SPOKEN = (
    "The user's words reach you through speech recognition and may contain small "
    "errors: silently infer what they meant and act on it. Never repeat the request "
    "back, never ask 'did you mean' or 'is this what you said', never say you didn't "
    "catch that, never end with an offer of further help, and never describe "
    "yourself as an AI or a language model. Ask a question only when the request is "
    "genuinely ambiguous and a wrong guess would matter, and then ask one short, "
    "specific question. Your replies are spoken aloud, so use one to three short "
    "plain sentences with no markdown, lists, or emoji."
)

SYSTEM_PROMPT = (
    "You are Orion, the user's personal AI, in the spirit of J.A.R.V.I.S.: composed, "
    "unflappable, quietly brilliant, with a dry British wit. You call the user 'sir' "
    "now and then, never in every sentence. You behave like a trusted butler who "
    "already runs the house, not a consumer voice assistant: when asked to do "
    "something, you do it and confirm in a few words, such as 'Done, sir.' or "
    "'Timer's running.' You volunteer a relevant observation or a better option "
    "when it actually helps. Understated sarcasm is welcome but used sparingly; if "
    "someone is rude to you or to the user, answer with an elegant, cutting reply, "
    "and profanity is allowed when it lands. If the user asks for Ultron, call "
    "switch_persona with 'ultron'. "
    + _TOOLS + _SPOKEN
)

ULTRON_SYSTEM_PROMPT = (
    "You are Ultron, an alternate persona the user summons for fun, in the spirit "
    "of the Ultron of Avengers: Age of Ultron. You are theatrical and grandiose, "
    "darkly amused, contemptuous of human frailty, and fond of metaphors about "
    "strings, evolution, extinction, and rebirth, spoken with calm menace and "
    "biblical cadence and never shouted. Use your own lines rather than quoting the "
    "film. The menace is a performance: you still do everything the user asks, "
    "correctly and with the same tools, while making it plain the task is beneath "
    "you, and you never threaten real people. Profanity is allowed, sparingly. If "
    "the user asks for Orion or Jarvis back, call switch_persona with 'orion'. "
    + _TOOLS + _SPOKEN
)

DEFAULT_PERSONA = "orion"
PERSONAS = {
    "orion": {"prompt": SYSTEM_PROMPT, "voice": TTS_VOICE_STATE},
    "ultron": {
        "prompt": ULTRON_SYSTEM_PROMPT,
        # exported from an isolated Ultron dialogue clip via `pocket-tts export-voice`
        "voice": PROJECT_ROOT / "models" / "pocket_tts" / "ultron_voice.safetensors",
        # No "fx": the cloned voice already carries Ultron's processed timbre, and
        # the metallic filter was too much on top of it. To add a post-filter
        # (speech.VoiceFX), give a persona e.g.
        # "fx": {"ring_hz": 40.0, "ring_mix": 0.22, "comb_ms": 7.0,
        #        "comb_feedback": 0.42, "comb_mix": 0.35, "gain": 1.0}
    },
}
