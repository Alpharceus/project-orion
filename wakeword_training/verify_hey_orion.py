r"""Verify the trained hey_orion.onnx: detection rate on held-out positives vs.
false-accept rate on adversarial near-misses and on silence/noise.

Streams each clip through openWakeWord.Model in 1280-sample frames exactly like
the live wakeword.py listener, and records the peak score per clip.

Usage:
  orion_env\Scripts\python.exe wakeword_training\verify_hey_orion.py [model.onnx]
"""

import glob
import sys
from pathlib import Path

import numpy as np
import scipy.io.wavfile
from openwakeword.model import Model

BASE = Path(__file__).resolve().parent
MODEL = sys.argv[1] if len(sys.argv) > 1 else str(BASE / "artifacts" / "hey_orion.onnx")
FRAME = 1280
rng = np.random.default_rng(0)


def peak_score(model, key, audio_i16: np.ndarray) -> float:
    """Stream audio in 1280-sample frames; return the max wake score seen."""
    model.reset()
    best = 0.0
    for i in range(0, len(audio_i16) - FRAME, FRAME):
        scores = model.predict(audio_i16[i:i + FRAME])
        best = max(best, scores.get(key, 0.0))
    return best


def framed_clip(path: str, pad_to=40000) -> np.ndarray:
    """Load a clip and place it in a ~2.5 s noisy buffer (realistic stream)."""
    _, a = scipy.io.wavfile.read(path)
    a = a.astype(np.float32) / 32768.0
    buf = rng.normal(0, 0.01, pad_to).astype(np.float32)
    off = int(rng.integers(0, max(1, pad_to - len(a))))
    buf[off:off + len(a)] += a[:pad_to]
    np.clip(buf, -1, 1, out=buf)
    return (buf * 32767).astype(np.int16)


def scores_for(model, key, clip_dir):
    return [peak_score(model, key, framed_clip(p)) for p in glob.glob(str(clip_dir / "*.wav"))]


def main():
    if not Path(MODEL).exists():
        print(f"model not found: {MODEL}")
        sys.exit(1)
    model = Model(wakeword_models=[MODEL], inference_framework="onnx")
    key = next(iter(model.models))
    print(f"loaded model key: {key}\n")

    pos = scores_for(model, key, BASE / "positives_test")
    adv = scores_for(model, key, BASE / "adversarial_negatives")
    # pure noise/silence negatives
    sil = [peak_score(model, key, (rng.normal(0, 0.01, 40000) * 32767).astype(np.int16))
           for _ in range(40)]

    for thr in (0.3, 0.5, 0.7):
        det = np.mean([s >= thr for s in pos]) * 100
        fa_adv = np.mean([s >= thr for s in adv]) * 100
        fa_sil = np.mean([s >= thr for s in sil]) * 100
        print(f"thr={thr}:  positives detected {det:5.1f}%   "
              f"near-miss false-accept {fa_adv:5.1f}%   silence false-accept {fa_sil:5.1f}%")

    print(f"\npositive peak scores: median={np.median(pos):.3f} "
          f"mean={np.mean(pos):.3f} min={np.min(pos):.3f} max={np.max(pos):.3f}")
    print(f"near-miss peak scores: median={np.median(adv):.3f} max={np.max(adv):.3f}")
    print(f"silence peak scores:   median={np.median(sil):.3f} max={np.max(sil):.3f}")


if __name__ == "__main__":
    main()
