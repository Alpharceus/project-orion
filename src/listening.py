"""Microphone capture: VAD-gated recording that returns base64 WAV for the LLM."""

import base64
import collections
import io

import numpy as np
import sounddevice as sd
import soundfile as sf
from pysilero_vad import SileroVoiceActivityDetector

import config
import state


def record_voice(vad: SileroVoiceActivityDetector, no_speech_timeout: float | None = None) -> str | None:
    """Listen until speech starts, record until it stops, return base64 WAV.

    Returns None if no speech is heard within `no_speech_timeout` seconds
    (defaults to config.NO_SPEECH_TIMEOUT). The conversation follow-up loop
    passes a longer window so quiet pauses don't end the conversation.
    """
    if no_speech_timeout is None:
        no_speech_timeout = config.NO_SPEECH_TIMEOUT
    vad.reset()
    chunk = vad.chunk_samples()  # 512 samples = 32 ms at 16 kHz
    chunks_per_sec = config.RECORD_RATE / chunk
    pre_roll = collections.deque(maxlen=int(config.PRE_ROLL_SECONDS * chunks_per_sec))
    frames = []
    speech_started = False
    silent_chunks = 0
    waited_chunks = 0

    print("🎤 [Orion] Listening — speak whenever you're ready...")
    state.set(state.LISTENING)
    with sd.InputStream(samplerate=config.RECORD_RATE, channels=1, dtype="int16",
                        blocksize=chunk) as stream:
        while True:
            data, _ = stream.read(chunk)
            data = data.reshape(-1)
            prob = vad(data.tobytes())

            if not speech_started:
                pre_roll.append(data.copy())
                waited_chunks += 1
                if prob >= config.VAD_THRESHOLD:
                    speech_started = True
                    frames.extend(pre_roll)
                    print("🔴 [Orion] Recording...")
                elif waited_chunks / chunks_per_sec > no_speech_timeout:
                    return None
            else:
                frames.append(data.copy())
                silent_chunks = silent_chunks + 1 if prob < config.VAD_THRESHOLD else 0
                if (silent_chunks / chunks_per_sec >= config.SILENCE_HANG_SECONDS
                        or len(frames) / chunks_per_sec >= config.MAX_UTTERANCE_SECONDS):
                    break

    audio = np.concatenate(frames)
    print(f"✅ [Orion] Captured {len(audio) / config.RECORD_RATE:.1f}s of speech.")
    buf = io.BytesIO()
    sf.write(buf, audio, config.RECORD_RATE, format="WAV")
    return base64.b64encode(buf.getvalue()).decode("ascii")
