"""Speech-to-text: faster-whisper (CTranslate2, int8) on CPU, biased toward Orion's vocabulary.

The LLM owns the GPU, so Whisper runs on CPU. The model loads lazily, once.
"""

import base64
import io
import threading

import numpy as np
import soundfile as sf

import config

_model = None
_lock = threading.Lock()

# Whisper tends to emit these on near-silence; only trusted as junk on short clips.
_JUNK = {"thank you", "thanks for watching", "you", "bye"}
_NO_SPEECH_MAX = 0.6
_JUNK_MAX_SECONDS = 1.0


def _get_model():
    """Load the WhisperModel once (thread-safe)."""
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel
            _model = WhisperModel(
                config.STT_MODEL, device=config.STT_DEVICE,
                compute_type=config.STT_COMPUTE_TYPE, cpu_threads=config.STT_CPU_THREADS,
            )
        return _model


def preload():
    """Load the model now (startup) so the first utterance isn't slow."""
    _get_model()


def decode_wav(audio_b64: str) -> np.ndarray:
    """Base64 WAV -> mono float32 at the file's rate (Orion records 16 kHz)."""
    audio, rate = sf.read(io.BytesIO(base64.b64decode(audio_b64)), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if rate != 16000:
        n = int(len(audio) * 16000 / rate)
        audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)
    return audio


def run(model, audio: np.ndarray, bias: str, beam_size: int) -> str:
    """Transcribe a float32 16 kHz array; `bias` is hotwords | initial_prompt | none."""
    kwargs = {}
    vocab = ", ".join(config.STT_VOCAB)
    if bias == "hotwords":
        kwargs["hotwords"] = vocab
    elif bias == "initial_prompt":
        kwargs["initial_prompt"] = vocab + "."
    segments, _ = model.transcribe(
        audio, language="en", beam_size=beam_size, vad_filter=False,
        condition_on_previous_text=False, **kwargs,
    )
    segments = list(segments)
    if not segments or all(s.no_speech_prob > _NO_SPEECH_MAX for s in segments):
        return ""
    text = " ".join(s.text.strip() for s in segments).strip()
    if len(audio) / 16000 < _JUNK_MAX_SECONDS and text.lower().strip(" .!?,") in _JUNK:
        return ""
    return text


def transcribe(audio_b64: str) -> str:
    return run(_get_model(), decode_wav(audio_b64), config.STT_BIAS, config.STT_BEAM_SIZE)
