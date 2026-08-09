r"""Verify the cloned PocketTTS voice loads and measure CPU TTS speed (no playback)."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config
from speech import load_tts

t0 = time.perf_counter()
tts, voice_state = load_tts()
print(f"model + voice state ({config.TTS_VOICE_STATE.name}) loaded in "
      f"{time.perf_counter() - t0:.1f}s, sample rate {tts.sample_rate} Hz")

t0 = time.perf_counter()
audio = tts.generate_audio(voice_state, "Hello, this is the cloned Orion voice test.")
dt = time.perf_counter() - t0
seconds = audio.shape[-1] / tts.sample_rate
print(f"synthesized {seconds:.2f}s of audio in {dt:.2f}s ({seconds/dt:.1f}x realtime)")

# Streaming latency: time to first audio chunk (what the user actually hears).
t0 = time.perf_counter()
first = next(tts.generate_audio_stream(voice_state, "Latency check, first chunk timing."))
print(f"first streamed chunk ({first.shape[-1]} samples) after {time.perf_counter() - t0:.2f}s")
