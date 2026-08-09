r"""Speak a sample line in the currently configured Orion voice (audible)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import sounddevice as sd

import config
from speech import load_tts

tts, voice_state = load_tts()
audio = tts.generate_audio(
    voice_state,
    "Good evening. Orion systems are online, and this is my new voice. "
    "Sounds rather familiar, wouldn't you say?",
)
print(f"playing {audio.shape[-1] / tts.sample_rate:.1f}s sample: {config.TTS_VOICE_STATE.name}")
sd.play(audio.numpy(), tts.sample_rate)
sd.wait()
