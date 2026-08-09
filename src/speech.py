"""PocketTTS speech: cloned-voice synthesis and a background sentence player.

Beyond playback, the player owns two HUD-facing signals:
  - the SPEAKING state (set when audio starts, cleared to IDLE when the queue
    drains), so both conversational replies and proactive announcements light
    the HUD uniformly;
  - a live amplitude envelope (smoothed RMS, 0..1) emitted at ~50 Hz while
    speaking, which drives the speaking visual in the HUD.
"""

import queue
import re
import threading

import numpy as np
import sounddevice as sd
from pocket_tts import TTSModel

import config
import events
import state

# PocketTTS synthesizes in chunks and warns ("Chunk has N tokens (max 50),
# generation may skip words") when a single span has no sentence/clause
# punctuation to split on. We keep every piece we hand it under this budget so it
# never has to, by splitting on sentences, then clauses, then (last resort) words.
_TTS_MAX_TOKENS = 46
_SENT_RE = re.compile(r"[^.!?]+[.!?]*")
_CLAUSE_RE = re.compile(r"[^,;:—]+[,;:—]*")


def _split_units(text: str, count) -> list[str]:
    """Break text into units that each fit the token budget (`count` -> #tokens)."""
    units: list[str] = []
    for sent in _SENT_RE.findall(text):
        sent = sent.strip()
        if not sent:
            continue
        if count(sent) <= _TTS_MAX_TOKENS:
            units.append(sent)
            continue
        for clause in _CLAUSE_RE.findall(sent):
            clause = clause.strip()
            if not clause:
                continue
            if count(clause) <= _TTS_MAX_TOKENS:
                units.append(clause)
                continue
            buf: list[str] = []  # punctuation-free run: fall back to word windows
            for w in clause.split():
                if buf and count(" ".join(buf + [w])) > _TTS_MAX_TOKENS:
                    units.append(" ".join(buf))
                    buf = [w]
                else:
                    buf.append(w)
            if buf:
                units.append(" ".join(buf))
    return units


def _pack(units: list[str], count) -> list[str]:
    """Greedily merge consecutive units up to the budget to minimize prosody seams."""
    chunks: list[str] = []
    cur = ""
    for u in units:
        cand = f"{cur} {u}".strip()
        if cur and count(cand) > _TTS_MAX_TOKENS:
            chunks.append(cur)
            cur = u
        else:
            cur = cand
    if cur:
        chunks.append(cur)
    return chunks


def load_tts() -> tuple[TTSModel, dict]:
    """Load the PocketTTS model (CPU-only) and the cloned Orion voice state.

    Both are slow to create and cheap to keep, so load once and reuse. The
    voice state is a precomputed .safetensors export (see config.TTS_VOICE_STATE);
    loading it is just a kv-cache read, much faster than re-processing the
    original voice sample.
    """
    model = TTSModel.load_model(temp=config.TTS_TEMPERATURE)
    voice_state = model.get_state_for_audio_prompt(str(config.TTS_VOICE_STATE))
    return model, voice_state


class SpeechPlayer:
    """Plays sentences through PocketTTS on a background thread, in order.

    Lets us start speaking the first sentence while the model is still
    generating the rest of its reply. Each sentence is itself streamed
    chunk-by-chunk from PocketTTS into the output device, so audio starts
    ~200 ms after a sentence is queued instead of after full synthesis.
    """

    def __init__(self, tts: TTSModel, voice_state: dict):
        self.tts = tts
        self.voice_state = voice_state
        self.queue = queue.Queue()
        self._amp = 0.0  # smoothed amplitude carried across chunks
        self._tok = self._find_tokenizer()
        threading.Thread(target=self._worker, daemon=True).start()

    def _find_tokenizer(self):
        """The PocketTTS sentencepiece tokenizer, for exact token counts (or None)."""
        try:
            return self.tts.flow_lm.conditioner.tokenizer
        except Exception:
            return None

    def _count_tokens(self, s: str) -> int:
        if self._tok is not None:
            try:
                return len(self._tok(s).tokens[0].tolist())
            except Exception:
                pass
        return max(1, round(len(s.split()) * 1.4))  # heuristic fallback

    def _worker(self):
        while True:
            text = self.queue.get()
            try:
                state.set(state.SPEAKING)
                with sd.OutputStream(
                    samplerate=self.tts.sample_rate, channels=1, dtype="float32"
                ) as out:
                    # copy_state (default) keeps self.voice_state pristine for
                    # the next sentence.
                    for chunk in self.tts.generate_audio_stream(self.voice_state, text):
                        samples = chunk.numpy()
                        self._emit_amplitude(samples)
                        out.write(samples)
            except Exception as e:
                print(f"\n[TTS error: {e}]")
            finally:
                self.queue.task_done()
                # Once nothing else is queued, stop the speaking visual. Return
                # to IDLE only for proactive announcements (fired while dormant);
                # mid-conversation, orion.py flows straight into the next listen,
                # so we leave the state alone to avoid a speaking->idle->listening
                # flash that would bounce the HUD.
                if self.queue.empty():
                    self._amp = 0.0
                    events.publish({"type": "amplitude", "value": 0.0})
                    if not state.in_conversation():
                        state.set(state.IDLE)

    def _emit_amplitude(self, samples: np.ndarray) -> None:
        """Publish a smoothed 0..1 envelope over ~20 ms sub-windows (~50 Hz)."""
        window = max(1, int(self.tts.sample_rate * 0.02))  # 20 ms
        for start in range(0, len(samples), window):
            block = samples[start:start + window]
            if block.size == 0:
                continue
            rms = float(np.sqrt(np.mean(block.astype(np.float32) ** 2)))
            # Normalize against a reference speech RMS, then ease toward it so the
            # envelope flows rather than jitters (the HUD smooths further).
            target = min(1.0, rms / config.TTS_AMP_REFERENCE)
            self._amp += (target - self._amp) * config.TTS_AMP_SMOOTHING
            events.publish({"type": "amplitude", "value": round(self._amp, 4)})

    def say(self, text: str):
        text = text.strip()
        if not text:
            return
        # Split long text so no piece exceeds PocketTTS's per-chunk token budget.
        for piece in _pack(_split_units(text, self._count_tokens), self._count_tokens) or [text]:
            self.queue.put(piece)

    def wait_until_done(self):
        self.queue.join()
