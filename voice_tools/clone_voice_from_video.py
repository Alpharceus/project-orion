"""Clone a voice for PocketTTS from a movie/video file, hands-off.

Pipeline (one function per stage):
  1. extract_audio   - ffmpeg -> 44.1 kHz stereo WAV
  2. isolate_vocals  - demucs htdemucs (two stems: vocals / no_vocals), CPU
  3. segment_speech  - Silero VAD on the vocal stem (16 kHz mono)
  4. pick_speaker    - SpeechBrain ECAPA embeddings; reference-match or clustering
  5. assemble_sample - rank by voice dominance, join best segments, 24 kHz mono wav
  6. export_voice    - orion_env pocket-tts export-voice -> .safetensors

Run with the tool venv (see setup.ps1), never with orion_env:
  voice_tools\\.venv\\Scripts\\python.exe voice_tools\\clone_voice_from_video.py ^
      --input movie.mp4 --name ultron

Cloned voices of real people are for personal, local use only.
"""
import argparse
import csv
import os
import shutil
import subprocess
import sys
import tempfile
from math import gcd
from pathlib import Path

# Quiet the HF symlink warning on Windows (symlinks need admin / dev mode).
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
POCKET_TTS = REPO / "orion_env" / "Scripts" / "pocket-tts.exe"

SEG_MIN, SEG_MAX = 1.5, 12.0   # seconds, kept segment length range
MERGE_GAP = 0.25               # seconds, merge VAD segments closer than this
MIN_USABLE = 8.0               # seconds of usable speech required
JOIN_SILENCE = 0.3             # seconds of silence between joined segments
OUT_SR = 24000                 # PocketTTS sample rate


class Fail(Exception):
    """A clear, one-line reason the pipeline cannot continue."""


def log(msg):
    print(msg, flush=True)


def resample(x, sr_in, sr_out):
    """Polyphase resample along axis 0."""
    if sr_in == sr_out:
        return x
    g = gcd(sr_in, sr_out)
    return resample_poly(x, sr_out // g, sr_in // g, axis=0)


# --------------------------------------------------------------------------
# Stage 1: extract
# --------------------------------------------------------------------------
def extract_audio(video, work, start=None, duration=None):
    if shutil.which("ffmpeg") is None:
        raise Fail("ffmpeg not found on PATH")
    out = work / "audio.wav"
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if start is not None:
        cmd += ["-ss", str(start)]
    cmd += ["-i", str(video)]
    if duration is not None:
        cmd += ["-t", str(duration)]
    cmd += ["-vn", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(out)]
    log("[1/6] extracting audio with ffmpeg ...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        raise Fail("ffmpeg failed to extract audio: " + (r.stderr.strip().splitlines() or ["?"])[-1])
    return out


# --------------------------------------------------------------------------
# Stage 2: vocal isolation
# --------------------------------------------------------------------------
def isolate_vocals(audio_path, work):
    """Return (vocals, residual) float32 arrays, shape (n, 2) at 44.1 kHz."""
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    log("[2/6] isolating vocals with demucs htdemucs (CPU, this is the slow step) ...")
    wav, sr = sf.read(str(audio_path), dtype="float32", always_2d=True)
    model = get_model("htdemucs")
    model.eval()
    if sr != model.samplerate:
        raise Fail("unexpected sample rate %d from extraction" % sr)
    mix = torch.from_numpy(wav.T.copy())            # (channels, n)
    # demucs expects the input normalised by its mean/std, undone afterwards.
    ref = mix.mean(0)
    mix_n = (mix - ref.mean()) / (ref.std() + 1e-8)
    with torch.no_grad():
        out = apply_model(model, mix_n[None], device="cpu", split=True,
                          overlap=0.25, progress=True)[0]
    out = out * (ref.std() + 1e-8) + ref.mean()
    vocals = out[model.sources.index("vocals")].numpy().T.astype(np.float32)
    residual = (wav - vocals).astype(np.float32)    # == no_vocals stem
    sf.write(str(work / "vocals.wav"), vocals, sr, subtype="PCM_16")
    sf.write(str(work / "no_vocals.wav"), residual, sr, subtype="PCM_16")
    return vocals, residual


# --------------------------------------------------------------------------
# Stage 3: VAD segmentation
# --------------------------------------------------------------------------
def segment_speech(vocals, sr=44100):
    """Silero VAD on the vocal stem -> list of (start, end) seconds."""
    import torch
    from silero_vad import get_speech_timestamps, load_silero_vad

    log("[3/6] detecting speech with Silero VAD ...")
    mono16 = resample(vocals.mean(axis=1), sr, 16000).astype(np.float32)
    vad = load_silero_vad()
    ts = get_speech_timestamps(torch.from_numpy(mono16), vad, sampling_rate=16000,
                               return_seconds=True)
    # Merge gaps shorter than MERGE_GAP.
    merged = []
    for t in ts:
        s, e = float(t["start"]), float(t["end"])
        if merged and s - merged[-1][1] < MERGE_GAP:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    # Keep SEG_MIN..SEG_MAX; split overlong runs into equal pieces <= SEG_MAX.
    segs = []
    for s, e in merged:
        d = e - s
        if d < SEG_MIN:
            continue
        n = int(np.ceil(d / SEG_MAX))
        step = d / n
        for i in range(n):
            segs.append((s + i * step, s + (i + 1) * step))
    log("      %d candidate segments, %.1f s total" % (len(segs), sum(e - s for s, e in segs)))
    return segs, mono16


# --------------------------------------------------------------------------
# Stage 4: speaker selection
# --------------------------------------------------------------------------
def _load_encoder(cache_dir):
    from speechbrain.inference.speaker import EncoderClassifier
    from speechbrain.utils.fetching import LocalStrategy
    # COPY instead of SYMLINK: symlinks need admin rights on Windows.
    return EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb", savedir=str(cache_dir),
        run_opts={"device": "cpu"}, local_strategy=LocalStrategy.COPY)


def _embed(encoder, wav16):
    import torch
    with torch.no_grad():
        e = encoder.encode_batch(torch.from_numpy(wav16.astype(np.float32))[None])
    e = e.squeeze().numpy()
    return e / (np.linalg.norm(e) + 1e-9)


def pick_speaker(segs, mono16, args):
    """Return (cluster_ids, sims, keep_mask). cluster_ids is 0/-1 in reference mode."""
    log("[4/6] embedding segments with SpeechBrain ECAPA ...")
    encoder = _load_encoder(HERE / "work" / "ecapa_model")
    embs = np.stack([_embed(encoder, mono16[int(s * 16000):int(e * 16000)]) for s, e in segs])
    n = len(segs)

    if args.reference:
        ref, sr = sf.read(str(args.reference), dtype="float32", always_2d=True)
        ref16 = resample(ref.mean(axis=1), sr, 16000)[:16000 * 30]
        ref_emb = _embed(encoder, ref16)
        sims = embs @ ref_emb
        keep = sims >= args.min_sim
        clusters = np.where(keep, 0, -1)
        log("      reference mode: %d of %d segments with cosine >= %.2f"
            % (keep.sum(), n, args.min_sim))
        return clusters, sims, keep

    from sklearn.cluster import AgglomerativeClustering
    if n == 1:
        clusters = np.zeros(1, dtype=int)
    else:
        clusters = AgglomerativeClustering(
            n_clusters=None, metric="cosine", linkage="average",
            distance_threshold=args.cluster_threshold).fit_predict(embs)
    durs = np.array([e - s for s, e in segs])
    totals = {c: durs[clusters == c].sum() for c in np.unique(clusters)}
    best = max(totals, key=totals.get)
    log("      cluster  segments  seconds")
    for c in sorted(totals, key=totals.get, reverse=True):
        log("      %-8d %-9d %-8.1f%s" % (c, (clusters == c).sum(), totals[c],
                                          "  <- target" if c == best else ""))
    centroid = embs[clusters == best].mean(axis=0)
    centroid /= np.linalg.norm(centroid) + 1e-9
    sims = embs @ centroid
    return clusters, sims, clusters == best


# --------------------------------------------------------------------------
# Stage 5: rank + assemble
# --------------------------------------------------------------------------
def _dominance_db(voc, res):
    """How dominant the voice is over the rest of the mix, in dB (higher = cleaner)."""
    pv = float(np.mean(voc ** 2)) + 1e-12
    pr = float(np.mean(res ** 2)) + 1e-12
    return 10.0 * np.log10(pv / pr)


def assemble_sample(segs, clusters, sims, keep, vocals, residual, args, work):
    sr = 44100
    target = min(args.target_seconds, 30.0)
    scores = np.array([_dominance_db(vocals[int(s * sr):int(e * sr)],
                                     residual[int(s * sr):int(e * sr)]) for s, e in segs])
    usable = [i for i in range(len(segs)) if keep[i] and scores[i] >= args.min_dominance]
    usable_s = sum(segs[i][1] - segs[i][0] for i in usable)
    log("[5/6] %.1f s of usable target-speaker speech (%d segments)" % (usable_s, len(usable)))

    used = set()
    if usable_s >= MIN_USABLE:
        total = 0.0
        for i in sorted(usable, key=lambda i: scores[i], reverse=True):
            d = segs[i][1] - segs[i][0]
            if total + d <= target:
                used.add(i)
                total += d
    # CSV first so it exists even on failure.
    with open(work / "segments.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["start", "end", "cluster", "sim", "score", "used"])
        for i, (s, e) in enumerate(segs):
            w.writerow(["%.3f" % s, "%.3f" % e, int(clusters[i]), "%.3f" % sims[i],
                        "%.2f" % scores[i], int(i in used)])
    if usable_s < MIN_USABLE:
        raise Fail("only %.1f s of usable speech found (need %.0f s)" % (usable_s, MIN_USABLE))
    if not used:
        raise Fail("no segments fit within --target-seconds")

    gap = np.zeros(int(JOIN_SILENCE * sr), dtype=np.float32)
    fade = int(0.01 * sr)
    ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
    parts = []
    for i in sorted(used):                       # original time order
        s, e = segs[i]
        x = vocals[int(s * sr):int(e * sr)].mean(axis=1).astype(np.float32)
        x[:fade] *= ramp
        x[-fade:] *= ramp[::-1]
        parts += [x, gap]
    audio = np.concatenate(parts[:-1])
    audio = resample(audio, sr, OUT_SR).astype(np.float32)
    peak = float(np.max(np.abs(audio))) + 1e-9
    audio *= (10 ** (-1.0 / 20.0)) / peak         # peak-normalise to -1 dBFS
    out = args.out_dir / (args.name + "_voice_sample.wav")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    sf.write(str(out), audio, OUT_SR, subtype="PCM_16")
    log("      wrote %s (%.1f s, %d segments)" % (out, len(audio) / OUT_SR, len(used)))
    return out


# --------------------------------------------------------------------------
# Stage 6: export
# --------------------------------------------------------------------------
def export_voice(sample, args):
    out = args.out_dir / (args.name + "_voice.safetensors")
    if not POCKET_TTS.exists():
        raise Fail("pocket-tts not found at %s" % POCKET_TTS)
    log("[6/6] exporting voice with pocket-tts ...")
    r = subprocess.run([str(POCKET_TTS), "export-voice", str(sample), str(out)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        tail = (r.stderr.strip() or r.stdout.strip()).splitlines()
        raise Fail("pocket-tts export-voice failed: " + (tail[-1] if tail else "?"))
    log("      wrote %s" % out)
    return out


# --------------------------------------------------------------------------
def parse_args(argv):
    p = argparse.ArgumentParser(description="Clone a PocketTTS voice from a video.")
    p.add_argument("--input", required=True, type=Path, help="video (or audio) file")
    p.add_argument("--name", required=True, help="voice name, e.g. ultron")
    p.add_argument("--reference", type=Path, help="WAV of the target speaker; skips clustering")
    p.add_argument("--min-sim", type=float, default=0.55, help="cosine threshold for --reference")
    p.add_argument("--cluster-threshold", type=float, default=0.6,
                   help="agglomerative cosine distance threshold")
    p.add_argument("--target-seconds", type=float, default=25.0, help="sample length (cap 30)")
    p.add_argument("--min-dominance", type=float, default=0.0,
                   help="min vocal-vs-residual RMS ratio in dB to keep a segment")
    p.add_argument("--keep-work", type=Path, metavar="DIR", help="keep intermediates in DIR")
    p.add_argument("--out-dir", type=Path, default=REPO / "models" / "pocket_tts")
    p.add_argument("--no-export", action="store_true", help="skip the safetensors export")
    p.add_argument("--force", action="store_true", help="overwrite existing outputs")
    p.add_argument("--start", type=float, help="only process from this many seconds in")
    p.add_argument("--duration", type=float, help="only process this many seconds")
    return p.parse_args(argv)


def run(args):
    if not args.input.exists():
        raise Fail("input not found: %s" % args.input)
    if args.reference and not args.reference.exists():
        raise Fail("reference not found: %s" % args.reference)
    if shutil.which("ffmpeg") is None:
        raise Fail("ffmpeg not found on PATH")
    sample = args.out_dir / (args.name + "_voice_sample.wav")
    voice = args.out_dir / (args.name + "_voice.safetensors")
    outputs = [sample] if args.no_export else [sample, voice]
    clash = [p for p in outputs if p.exists()]
    if clash and not args.force:
        raise Fail("%s already exists (use --force to overwrite)" % clash[0])
    if not args.no_export and not POCKET_TTS.exists():
        raise Fail("pocket-tts not found at %s" % POCKET_TTS)

    tmp = None
    if args.keep_work:
        work = args.keep_work
        work.mkdir(parents=True, exist_ok=True)
    else:
        tmp = tempfile.TemporaryDirectory(prefix="voice_clone_")
        work = Path(tmp.name)
    try:
        audio = extract_audio(args.input, work, args.start, args.duration)
        vocals, residual = isolate_vocals(audio, work)
        segs, mono16 = segment_speech(vocals)
        if not segs:
            raise Fail("no speech segments found")
        clusters, sims, keep = pick_speaker(segs, mono16, args)
        sample = assemble_sample(segs, clusters, sims, keep, vocals, residual, args, work)
        if not args.no_export:
            export_voice(sample, args)
    finally:
        if tmp is not None:
            tmp.cleanup()
    log("done.")


def main(argv=None):
    args = parse_args(argv)
    try:
        run(args)
    except Fail as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
