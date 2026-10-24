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
from pathlib import Path

import numpy as np
import sounddevice as sd
from pocket_tts import TTSModel

import config
import events
import persona
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


def load_persona_voices(model: TTSModel, loaded: dict | None = None) -> dict[str, dict]:
    """Load the voice state of every persona whose voice file exists.

    `loaded` maps persona names to voice states already in memory (e.g. Orion's
    from load_tts) so they aren't loaded twice. Missing files are warned about
    and omitted; the player then falls back to Orion's voice for them.
    """
    voices = dict(loaded or {})
    for name, cfg in config.PERSONAS.items():
        if name in voices:
            continue
        path = cfg["voice"]
        if Path(path).exists():
            voices[name] = model.get_state_for_audio_prompt(str(path))
        else:
            print(f"[Orion] No voice file for persona '{name}' ({path}); it will use Orion's voice.")
    return voices


class VoiceFX:
    """Streaming metallic voice filter: ring mod + feedback comb + soft clip.

    Stateful (carrier sample counter + comb delay line) so chunked processing
    equals one-shot processing. Fully vectorized; the feedback comb runs in
    slices no longer than its delay, so each slice only reads output that is
    already computed.
    """

    def __init__(self, sample_rate: int, ring_hz: float, ring_mix: float,
                 comb_ms: float, comb_feedback: float, comb_mix: float, gain: float):
        self.sample_rate = sample_rate
        self.ring_hz = ring_hz
        self.ring_mix = ring_mix
        self.delay = max(1, int(round(sample_rate * comb_ms / 1000.0)))
        self.feedback = comb_feedback
        self.comb_mix = comb_mix
        self.gain = gain
        self.reset()

    def reset(self) -> None:
        self._n = 0                                            # carrier sample counter
        self._hist = np.zeros(self.delay, dtype=np.float64)    # last `delay` comb outputs

    def process(self, samples: np.ndarray) -> np.ndarray:
        x = np.asarray(samples, dtype=np.float64)
        n = x.shape[0]
        if n == 0:
            return np.asarray(samples, dtype=np.float32)
        idx = self._n + np.arange(n, dtype=np.float64)
        self._n += n
        carrier = np.sin(2.0 * np.pi * self.ring_hz / self.sample_rate * idx)
        y = x * (1.0 - self.ring_mix) + x * carrier * self.ring_mix

        c = np.empty(n, dtype=np.float64)
        d = self.delay
        for s in range(0, n, d):
            e = min(s + d, n)
            # c[k-d] for this slice is the oldest part of the history window
            c[s:e] = y[s:e] + self.feedback * self._hist[:e - s]
            self._hist = np.concatenate((self._hist[e - s:], c[s:e]))
        out = y * (1.0 - self.comb_mix) + c * self.comb_mix
        # tanh keeps quiet signals ~linear and bounds the loud ones to [-1, 1]
        return np.tanh(out * self.gain).astype(np.float32)


class SpeechPlayer:
    """Plays sentences through PocketTTS on a background thread, in order.

    Lets us start speaking the first sentence while the model is still
    generating the rest of its reply. Each sentence is itself streamed
    chunk-by-chunk from PocketTTS into the output device, so audio starts
    ~200 ms after a sentence is queued instead of after full synthesis.
    """

    def __init__(self, tts: TTSModel, voice_state: dict, persona_voices: dict | None = None):
        self.tts = tts
        self.voice_state = voice_state
        self.persona_voices = persona_voices or {}
        self.queue = queue.Queue()
        self._amp = 0.0  # smoothed amplitude carried across chunks
        self._fx: dict[str, VoiceFX | None] = {}  # per-persona filter, built lazily
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

    def _fx_for(self, name: str) -> "VoiceFX | None":
        """The persona's VoiceFX (reset for a fresh sentence), or None if it has no fx."""
        if name not in self._fx:
            cfg = config.PERSONAS.get(name, {}).get("fx")
            self._fx[name] = VoiceFX(self.tts.sample_rate, **cfg) if cfg else None
        fx = self._fx[name]
        if fx is not None:
            fx.reset()
        return fx

    def _worker(self):
        while True:
            text = self.queue.get()
            try:
                state.set(state.SPEAKING)
                with sd.OutputStream(
                    samplerate=self.tts.sample_rate, channels=1, dtype="float32"
                ) as out:
                    # copy_state (default) keeps the voice state pristine for
                    # the next sentence.
                    name = persona.current()
                    voice = self.persona_voices.get(name, self.voice_state)
                    fx = self._fx_for(name)
                    for chunk in self.tts.generate_audio_stream(voice, text):
                        samples = chunk.numpy()
                        if fx is not None:
                            samples = fx.process(samples)
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
