r"""Train a custom "hey orion" openWakeWord model — fully local, CPU only.

Reuses openWakeWord's OWN training code (the Model class: 3-sequence auto_train,
FP-rate model selection, checkpoint averaging, ONNX export) by importing it past
a stub of openwakeword.data, which avoids the speechbrain/piper/TensorFlow stack
the upstream pipeline needs but won't install on Windows + Python 3.12.

Data:
  - positives: PocketTTS "hey orion" clips (generate_clips.py), placed into 2 s
    windows with light gain/noise augmentation, embedded with the official
    AudioFeatures so they're byte-compatible with the negative features.
  - adversarial negatives: PocketTTS near-miss phrases (label 0, hard negatives).
  - negatives: davidscripka/openwakeword_features ACAV100M (5.6M (16,96) windows).
  - FP validation: validation_set_features.npy (481k (96,) frame stream).

Run with the project venv (after generate_clips.py and the feature downloads):
  orion_env\Scripts\python.exe wakeword_training\train_hey_orion.py
"""

import glob
import sys
import types
from pathlib import Path

import numpy as np
import scipy.io.wavfile
import torch

# --- import openWakeWord's Model without triggering data.py's heavy imports ---
_stub = types.ModuleType("openwakeword.data")
_stub.generate_adversarial_texts = lambda *a, **k: []
_stub.augment_clips = lambda *a, **k: []
_stub.mmap_batch_generator = lambda *a, **k: iter([])
sys.modules["openwakeword.data"] = _stub
from openwakeword.train import Model            # noqa: E402
from openwakeword.utils import AudioFeatures    # noqa: E402

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
ARTIFACTS = BASE / "artifacts"
TOTAL = 32000          # 2.0 s @ 16 kHz -> (16, 96) embedding
ROUNDS = 4             # augmentation passes per source clip
STEPS = 10000          # auto_train sequence-1 steps (then /10, /10)
rng = np.random.default_rng(0)

af = AudioFeatures(inference_framework="onnx", ncpu=4)


def _load_clip(path: str) -> np.ndarray:
    _, a = scipy.io.wavfile.read(path)
    return a.astype(np.float32) / 32768.0


def clips_to_features(clip_dir: Path, rounds: int) -> np.ndarray:
    """Place each clip randomly in a 2 s window with gain+noise, embed -> (N,16,96)."""
    paths = glob.glob(str(clip_dir / "*.wav"))
    windows = []
    for p in paths:
        clip = _load_clip(p)[:TOTAL]
        for _ in range(rounds):
            buf = rng.normal(0, rng.uniform(0.002, 0.03), TOTAL).astype(np.float32)
            seg = clip * rng.uniform(0.5, 1.0)
            off = int(rng.integers(0, max(1, TOTAL - len(seg))))
            buf[off:off + len(seg)] += seg
            np.clip(buf, -1.0, 1.0, out=buf)
            windows.append((buf * 32767).astype(np.int16))
    if not windows:
        return np.zeros((0, 16, 96), np.float32)
    feats = af.embed_clips(np.stack(windows), batch_size=64)
    return feats.astype(np.float32)


ARTIFACTS.mkdir(exist_ok=True)
_cache = ARTIFACTS / "features.npz"
if _cache.exists():
    print("loading cached features...")
    _z = np.load(_cache)
    pos, pos_val, adv = _z["pos"], _z["pos_val"], _z["adv"]
else:
    print("computing positive + adversarial-negative features...")
    pos = clips_to_features(BASE / "positives_train", ROUNDS)
    pos_val = clips_to_features(BASE / "positives_test", 2)
    adv = clips_to_features(BASE / "adversarial_negatives", ROUNDS)
    np.savez(_cache, pos=pos, pos_val=pos_val, adv=adv)
print(f"  positives(train)={len(pos)}  positives(val)={len(pos_val)}  adversarial_neg={len(adv)}")
if len(pos) < 200 or len(pos_val) < 10:
    print("ERROR: not enough positive features — run generate_clips.py first.")
    sys.exit(1)

neg = np.load(DATA / "openwakeword_features_ACAV100M_2000_hrs_16bit.npy", mmap_mode="r")  # (5.6M,16,96) f16
val_stream = np.load(DATA / "validation_set_features.npy")  # (481345, 96) f32
print(f"  negatives(mmap)={neg.shape}  fp_val_stream={val_stream.shape}")


class TrainData:
    """Infinite, re-iterable stream of mixed positive/negative batches."""
    def __init__(self, pos, adv, neg, n_pos=256, n_adv=256, n_neg=512):
        self.pos, self.adv, self.neg = pos, adv, neg
        self.n_pos, self.n_adv, self.n_neg = n_pos, n_adv, n_neg

    def __iter__(self):
        r = np.random.default_rng()
        while True:
            xb = np.concatenate([
                self.pos[r.integers(0, len(self.pos), self.n_pos)],
                self.adv[r.integers(0, len(self.adv), self.n_adv)],
                self.neg[np.sort(r.integers(0, len(self.neg), self.n_neg))].astype(np.float32),
            ])
            yb = np.concatenate([np.ones(self.n_pos),
                                 np.zeros(self.n_adv + self.n_neg)]).astype(np.float32)
            perm = r.permutation(len(yb))
            yield torch.from_numpy(xb[perm]).float(), torch.from_numpy(yb[perm]).float()


class FPVal:
    """Re-iterable batches of all-negative 16-frame windows from the FP stream."""
    def __init__(self, stream, batch=4096):
        win = np.lib.stride_tricks.sliding_window_view(stream, 16, axis=0)  # (N-15,96,16)
        self.win = np.moveaxis(win, -1, 1)  # -> (N-15,16,96), still a view
        self.batch = batch

    def __iter__(self):
        for i in range(0, self.win.shape[0], self.batch):
            x = torch.from_numpy(np.ascontiguousarray(self.win[i:i + self.batch])).float()
            yield x, torch.zeros(x.shape[0])


# balanced positive/negative validation batch for accuracy/recall tracking
xv = np.concatenate([pos_val, neg[np.sort(rng.integers(0, len(neg), len(pos_val)))].astype(np.float32)])
yv = np.concatenate([np.ones(len(pos_val)), np.zeros(len(pos_val))]).astype(np.float32)
X_val = [(torch.from_numpy(xv).float(), torch.from_numpy(yv).float())]

print(f"training on CPU: {STEPS} + {STEPS//10} + {STEPS//10} steps...")
oww = Model(n_classes=1, input_shape=(16, 96), layer_dim=128)
best = oww.auto_train(
    X_train=TrainData(pos, adv, neg),
    X_val=X_val,
    false_positive_val_data=FPVal(val_stream),
    steps=STEPS,
    max_negative_weight=1500,
    target_fp_per_hour=0.2,
)

# Persist the weights FIRST (state_dict, not the object — oWW's Net class is
# defined locally inside Model.__init__ and can't be pickled whole) so a flaky
# export can never cost us the training run.
torch.save(best.state_dict(), ARTIFACTS / "hey_orion_state.pt")
print(f"saved state_dict: {ARTIFACTS / 'hey_orion_state.pt'}")

# Export ONNX with the legacy exporter (dynamo=False) so it doesn't pull
# onnxscript; signature matches the pretrained models: input (1,16,96) -> (1,1).
onnx_path = ARTIFACTS / "hey_orion.onnx"
torch.onnx.export(best.to("cpu"), torch.rand(1, 16, 96), str(onnx_path),
                  opset_version=13, input_names=["x"], output_names=["score"],
                  dynamo=False)
print(f"exported: {onnx_path}")
