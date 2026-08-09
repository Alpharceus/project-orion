r"""Generate "hey orion" positive clips (and adversarial negatives) with PocketTTS.

Replaces openWakeWord's piper-sample-generator (which is painful on Windows)
with the project's own PocketTTS. Each voice is sampled at temp>0, so repeated
generations of the same phrase vary in prosody; across ~20 catalog voices that
gives broad speaker/accent diversity. Output: clean 16 kHz mono int16 wavs of
varying length — the trainer pads them into 2 s windows with augmentation.

Run with the project venv:
  orion_env\Scripts\python.exe wakeword_training\generate_clips.py
"""

import random
import sys
from pathlib import Path

import numpy as np
import scipy.io.wavfile
import scipy.signal
from pocket_tts import TTSModel

OUT = Path(__file__).resolve().parent
POS_TRAIN = OUT / "positives_train"
POS_TEST = OUT / "positives_test"
NEG = OUT / "adversarial_negatives"
for d in (POS_TRAIN, POS_TEST, NEG):
    d.mkdir(parents=True, exist_ok=True)

# PocketTTS built-in English voices (see PocketTTS README catalog).
VOICES = [
    "anna", "azelma", "bill_boerst", "caro_davy", "charles", "cosette",
    "eponine", "eve", "fantine", "george", "jane", "jean", "javert",
    "marius", "mary", "michael", "paul", "peter_yearsley", "stuart_bell", "vera",
]

POSITIVE_TEXTS = ["Hey Orion.", "Hey, Orion.", "Hey Orion", "hey orion"]
# Phonetically nearby phrases — teach the model NOT to fire on these.
NEGATIVE_TEXTS = [
    "Hey Ryan.", "Hey Brian.", "Hey Marion.", "Hey Leon.", "Orion.",
    "Hey iron.", "Hey Orin.", "A try on.", "Hey Sienna.", "Hayley on.",
    "Hey Ariel.", "Hey Onyx.", "Hey Aria.", "Ryan.", "Hey Owen.",
]

PER_VOICE_TRAIN = 36      # positive clips per voice for training
PER_VOICE_TEST = 4        # held-out positive clips per voice
NEG_PER_VOICE = 14        # adversarial negatives per voice


def to_16k_int16(audio_24k: np.ndarray) -> np.ndarray:
    """24 kHz float tensor -> 16 kHz mono int16, peak-normalized and trimmed."""
    resampled = scipy.signal.resample_poly(audio_24k, up=2, down=3)  # 24k -> 16k
    peak = np.max(np.abs(resampled)) or 1.0
    resampled = resampled / peak * 0.85
    # trim leading/trailing near-silence
    mask = np.abs(resampled) > 0.02
    if mask.any():
        lo, hi = np.argmax(mask), len(mask) - np.argmax(mask[::-1])
        resampled = resampled[max(0, lo - 800):hi + 800]  # keep 50 ms padding
    return (resampled * 32767).astype(np.int16)


def main():
    random.seed(1234)
    print("loading PocketTTS...")
    model = TTSModel.load_model(temp=0.85)  # temp>0 => stochastic prosody per call

    made = {"train": 0, "test": 0, "neg": 0}
    for vi, voice in enumerate(VOICES):
        try:
            vstate = model.get_state_for_audio_prompt(voice)
        except Exception as e:
            print(f"  skip voice {voice!r}: {e}")
            continue
        print(f"[{vi+1}/{len(VOICES)}] {voice}: generating...", flush=True)

        for i in range(PER_VOICE_TRAIN + PER_VOICE_TEST):
            text = random.choice(POSITIVE_TEXTS)
            try:
                audio = model.generate_audio(vstate, text).numpy()
            except Exception as e:
                print(f"    gen fail: {e}")
                continue
            clip = to_16k_int16(audio)
            if len(clip) < 3200:  # < 0.2 s => bad generation, skip
                continue
            split = "test" if i >= PER_VOICE_TRAIN else "train"
            dest = (POS_TEST if split == "test" else POS_TRAIN) / f"{voice}_{i:03d}.wav"
            scipy.io.wavfile.write(dest, 16000, clip)
            made["test" if split == "test" else "train"] += 1

        for j in range(NEG_PER_VOICE):
            text = random.choice(NEGATIVE_TEXTS)
            try:
                audio = model.generate_audio(vstate, text).numpy()
            except Exception:
                continue
            clip = to_16k_int16(audio)
            if len(clip) < 3200:
                continue
            scipy.io.wavfile.write(NEG / f"{voice}_{j:03d}.wav", 16000, clip)
            made["neg"] += 1

    print(f"\ndone: {made['train']} train, {made['test']} test positives, "
          f"{made['neg']} adversarial negatives")
    if made["train"] < 100:
        print("WARNING: very few positives generated — check voice availability.")
        sys.exit(1)


if __name__ == "__main__":
    main()
