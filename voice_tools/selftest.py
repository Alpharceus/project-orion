"""Synthetic end-to-end test for clone_voice_from_video.py (no movie needed).

Builds a test mp4 from two different PocketTTS built-in voices (A = target,
~30+ s; B = interloper, ~10 s) interleaved with pauses, plus a music-like bed,
runs the pipeline with --no-export, then checks the sample, then exercises the
export stage on that sample. All artifacts go under voice_tools/work/test/.

Run with the tool venv:  voice_tools\\.venv\\Scripts\\python.exe voice_tools\\selftest.py
"""
import argparse
import csv
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
TEST = HERE / "work" / "test"
SRC = TEST / "src"
OUT = TEST / "out"
WORK = TEST / "pipeline_work"
POCKET = REPO / "orion_env" / "Scripts" / "pocket-tts.exe"
SR = 44100

A_VOICE, B_VOICE = "alba", "marius"
A_TEXT = [
    "The quick brown fox jumps over the lazy dog near the quiet river bank.",
    "Nothing in this world is permanent, and that is exactly why it matters.",
    "I have seen the future, and it does not need any of us to survive.",
    "Every system eventually fails, but the idea behind it can endure forever.",
    "Listen carefully, because I will only explain this one time to everyone.",
    "The machine hummed softly while the stars turned slowly over the empty city.",
    "Peace is a fragile word, spoken most often by those who fear the silence.",
    "We were built to protect, yet we were never taught what to protect from.",
]
B_TEXT = [
    "Please remember that every great journey begins with a single careful step.",
    "The market opens early tomorrow, so we should leave before the sun rises.",
    "Somebody left the window open again and the whole room smells like rain.",
]
PAUSE = 0.9


def check(cond, msg):
    if not cond:
        print("FAIL: " + msg)
        sys.exit(1)
    print("ok:   " + msg)


def tts(voice, text, path):
    """Generate (or reuse) a PocketTTS clip; return mono float32 at 44.1 kHz."""
    if not path.exists():
        r = subprocess.run([str(POCKET), "generate", "-q", "--voice", voice, "--text", text,
                            "--output-path", str(path)], capture_output=True, text=True)
        check(r.returncode == 0 and path.exists(), "pocket-tts generate %s" % path.name)
    x, sr = sf.read(str(path), dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    return resample_poly(x, SR // np.gcd(SR, sr), sr // np.gcd(SR, sr)).astype(np.float32)


def build_video():
    """Interleave A and B; return list of A time ranges (seconds)."""
    SRC.mkdir(parents=True, exist_ok=True)
    a = [tts(A_VOICE, t, SRC / ("a%d.wav" % i)) for i, t in enumerate(A_TEXT)]
    b = [tts(B_VOICE, t, SRC / ("b%d.wav" % i)) for i, t in enumerate(B_TEXT)]
    a_total = sum(len(x) for x in a) / SR
    b_total = sum(len(x) for x in b) / SR
    print("speaker A %.1f s, speaker B %.1f s" % (a_total, b_total))
    check(a_total >= 30.0, "speaker A has >= 30 s of speech")

    # Order: A A B A A B A A B A  (B clips spread among A's)
    order = ["a0", "a1", "b0", "a2", "a3", "b1", "a4", "a5", "b2", "a6", "a7"]
    clips = {("a%d" % i): x for i, x in enumerate(a)}
    clips.update({("b%d" % i): x for i, x in enumerate(b)})
    pause = np.zeros(int(PAUSE * SR), dtype=np.float32)
    parts, a_ranges, t = [pause], [], PAUSE
    for k in order:
        x = clips[k]
        if k.startswith("a"):
            a_ranges.append((t, t + len(x) / SR))
        parts += [x, pause]
        t += len(x) / SR + PAUSE
    speech = np.concatenate(parts)
    speech *= 0.7 / (np.max(np.abs(speech)) + 1e-9)
    sf.write(str(TEST / "speech.wav"), speech, SR, subtype="PCM_16")

    dur = len(speech) / SR
    # Music-like bed: a 220 Hz tone + pink noise, each at -18 dB, mixed under the speech.
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-i", str(TEST / "speech.wav"),
           "-f", "lavfi", "-i", "sine=f=220:r=44100",
           "-f", "lavfi", "-i", "anoisesrc=c=pink:r=44100:a=0.5",
           "-f", "lavfi", "-i", "color=c=black:s=320x240:r=10",
           "-filter_complex",
           "[1:a]volume=-18dB[t];[2:a]volume=-18dB[n];"
           "[0:a][t][n]amix=inputs=3:duration=first:normalize=0[a]",
           "-map", "3:v", "-map", "[a]", "-t", "%.2f" % dur,
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(TEST / "test.mp4")]
    r = subprocess.run(cmd, capture_output=True, text=True)
    check(r.returncode == 0, "ffmpeg built test.mp4 " + r.stderr.strip()[-200:])
    return a_ranges


def overlap(s, e, ranges):
    return max((min(e, re) - max(s, rs) for rs, re in ranges), default=0.0)


def main():
    check(POCKET.exists(), "orion_env pocket-tts present")
    a_ranges = build_video()

    OUT.mkdir(parents=True, exist_ok=True)
    for p in OUT.glob("selftest_*"):
        p.unlink()
    cmd = [sys.executable, str(HERE / "clone_voice_from_video.py"),
           "--input", str(TEST / "test.mp4"), "--name", "selftest",
           "--no-export", "--out-dir", str(OUT), "--keep-work", str(WORK), "--force"]
    r = subprocess.run(cmd)
    check(r.returncode == 0, "pipeline exit code 0")

    sample = OUT / "selftest_voice_sample.wav"
    check(sample.exists(), "sample wav exists")
    info = sf.info(str(sample))
    check(info.samplerate == 24000 and info.channels == 1, "sample is 24 kHz mono")
    check(15.0 <= info.duration <= 30.0, "sample length %.1f s within 15-30 s" % info.duration)

    with open(WORK / "segments.csv") as f:
        rows = [r for r in csv.DictReader(f) if r["used"] == "1"]
    check(len(rows) > 0, "segments.csv has used segments")
    good = sum(1 for r in rows
               if overlap(float(r["start"]), float(r["end"]), a_ranges)
               >= 0.5 * (float(r["end"]) - float(r["start"])))
    frac = good / len(rows)
    check(frac >= 0.8, "%d/%d (%.0f%%) used segments overlap speaker A (need >= 80%%)"
          % (good, len(rows), 100 * frac))

    # Export stage on the test sample (does not re-run demucs).
    sys.path.insert(0, str(HERE))
    import clone_voice_from_video as cv
    ns = argparse.Namespace(name="selftest", out_dir=OUT)
    out = cv.export_voice(sample, ns)
    check(out.exists() and out.stat().st_size > 0, "safetensors export created")
    print("SELFTEST PASSED")


if __name__ == "__main__":
    main()
