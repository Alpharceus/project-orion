"""Always-on wake-word listener (CPU only — never loads Gemma).

Wraps openWakeWord. The model runs entirely on CPU via onnxruntime and idles
cheaply. `wait()` blocks until the phrase is heard, owning the microphone only
during the idle wait and releasing it the instant it returns, so listening.py
can take the mic for the actual utterance.

Default detector is our custom **hey_orion** model (models/wakeword/hey_orion.onnx),
trained locally — see wakeword_training/ for the reproducible pipeline (PocketTTS
positives + openWakeWord's ACAV100M negatives, no piper/TensorFlow). config.WAKE_MODEL
can point at any other .onnx or a built-in name ("hey_jarvis", "alexa", ...).
"""

import numpy as np
import sounddevice as sd

import config

FRAME = 1280  # openWakeWord expects 80 ms frames at 16 kHz


class WakeWordUnavailable(RuntimeError):
    """Raised when openWakeWord or its models can't be loaded."""


class WakeWord:
    def __init__(self):
        try:
            from openwakeword.model import Model
        except ImportError as e:
            raise WakeWordUnavailable(f"openwakeword not installed: {e}") from e
        try:
            self._model = Model(
                wakeword_models=[config.WAKE_MODEL], inference_framework="onnx"
            )
        except Exception as e:
            raise WakeWordUnavailable(f"could not load wake model {config.WAKE_MODEL!r}: {e}") from e
        # The score dict is keyed by model name (or a custom file's stem); take
        # whatever the model actually loaded so a custom path Just Works.
        self._key = next(iter(self._model.models))

    def wait(self) -> bool:
        """Block until the wake phrase is detected. Returns True on detection.

        Opens its own 16 kHz input stream and closes it before returning so the
        microphone is free for the utterance recording that follows.
        """
        self._model.reset()
        with sd.InputStream(
            samplerate=config.RECORD_RATE, channels=1, dtype="int16", blocksize=FRAME
        ) as stream:
            while True:
                data, _ = stream.read(FRAME)
                scores = self._model.predict(data.reshape(-1))
                if scores.get(self._key, 0.0) >= config.WAKE_THRESHOLD:
                    return True
