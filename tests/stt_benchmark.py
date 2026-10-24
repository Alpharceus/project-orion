r"""STT benchmark: Gemma vs faster-whisper models/biasing on PocketTTS clips of the user's voice.

Run from the project root:  orion_env\Scripts\python.exe tests\stt_benchmark.py
Writes tests/stt_benchmark_results.md. Clips are cached in tests/stt_clips/.
Also provides ensure_clips() / CLIPS for tests/test_stt.py.
"""

import base64
import gc
import io
import re
import sys
import time
from pathlib import Path

import numpy as np
import psutil
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import config  # noqa: E402

CLIP_DIR = ROOT / "tests" / "stt_clips"
RESULTS = ROOT / "tests" / "stt_benchmark_results.md"

# (id, text, is_command). Commands exercise the vocabulary; the rest are plain.
CLIPS = [
    ("c01", "Switch to Ultron.", True),
    ("c02", "Bring back Jarvis.", True),
    ("c03", "Hey Orion, start a pomodoro for thirty minutes.", True),
    ("c04", "Download the GKP paper from this morning's arXiv briefing.", True),
    ("c05", "Any new SNSPD papers?", True),
    ("c06", "Turn on movie mode.", True),
    ("c07", "Start the eye care reminders.", True),
    ("c08", "Switch back to Orion.", True),
    ("c09", "What's the temperature from Tempest?", True),
    ("c10", "Search arXiv for Gaussian boson sampling.", True),
    ("c11", "Find papers about squeezed light.", True),
    ("c12", "Remind me to email Osinski tomorrow at nine.", True),
    ("c13", "Remember that the quantum dot sample is in the CHTM lab.", True),
    ("c14", "Show me single photon source papers.", True),
    ("c15", "Is there a Purcell enhancement paper today?", True),
    ("c16", "Add a task to simulate the qubit readout.", True),
    ("c17", "Change the movie mode theme to Umbra.", True),
    ("c18", "Raman needs a twenty twenty twenty reminder.", True),
    ("p01", "Remind me to call mom at six fifteen.", False),
    ("p02", "What time is it in Tokyo right now?", False),
    ("p03", "Set a timer for ten minutes.", False),
    ("p04", "I have a meeting at three thirty on Friday.", False),
    ("p05", "How many ounces are in a pound?", False),
    ("p06", "Add milk and eggs to my shopping list.", False),
    ("p07", "What's the weather going to be like tomorrow?", False),
    ("p08", "Wake me up at seven o'clock.", False),
    ("p09", "Tell me a joke about physics.", False),
    ("p10", "Cancel my appointment on the twenty second.", False),
    ("p11", "Read me the last three messages.", False),
    ("p12", "Turn the volume down a little.", False),
]
NOISY = ["c01", "c03", "c04", "c06", "p01", "p04"]  # also tested with -25 dB pink noise

_DIGITS = "zero one two three four five six seven eight nine".split()
_TEENS = ("ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen").split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _num_words(n: int) -> str:
    if n < 10:
        return _DIGITS[n]
    if n < 20:
        return _TEENS[n - 10]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else " " + _DIGITS[n % 10])
    if n < 1000:
        rest = n % 100
        return _DIGITS[n // 100] + " hundred" + ("" if rest == 0 else " " + _num_words(rest))
    return str(n)


def normalize(text: str) -> str:
    """Lowercase, drop punctuation, digits -> words, '6:15' -> 'six fifteen'."""
    t = text.lower().replace("-", " ").replace(":", " ")
    t = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", t)
    t = re.sub(r"\d+", lambda m: " " + _num_words(int(m.group())) + " ", t)
    t = re.sub(r"[^a-z' ]", " ", t.replace("'s", "s").replace("o'clock", "oclock"))
    t = t.replace("'", "")
    return " ".join(t.split())


def wer(ref: str, hyp: str) -> tuple[int, int]:
    r, h = normalize(ref).split(), normalize(hyp).split()
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)], len(r)


def vocab_hits(ref: str, hyp: str) -> tuple[int, int]:
    """(vocab words found in hyp, vocab words present in ref); spaces ignored."""
    r, h = normalize(ref).replace(" ", ""), normalize(hyp).replace(" ", "")
    present = [normalize(v).replace(" ", "") for v in config.STT_VOCAB]
    present = [v for v in present if v in r]
    return sum(v in h for v in present), len(present)


def _pink_noise(n: int, rng) -> np.ndarray:
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.arange(len(spec))
    f[0] = 1
    noise = np.fft.irfft(spec / np.sqrt(f), n)
    return noise / (np.sqrt(np.mean(noise ** 2)) + 1e-9)


def _write(path: Path, audio: np.ndarray):
    sf.write(path, audio.astype(np.float32), 16000, subtype="PCM_16")


def ensure_clips(ids=None) -> dict:
    """Return {clip_id: (text, path)}, synthesizing missing clips with PocketTTS."""
    CLIP_DIR.mkdir(exist_ok=True)
    wanted = [c for c in CLIPS if ids is None or c[0] in ids]
    missing = [c for c in wanted if not (CLIP_DIR / f"{c[0]}.wav").exists()]
    if missing:
        from speech import load_tts
        print(f"Synthesizing {len(missing)} clips with PocketTTS...")
        tts, voice = load_tts()
        for cid, text, _ in missing:
            chunks = [c.numpy() for c in tts.generate_audio_stream(voice, text)]
            audio = np.concatenate(chunks)
            n = int(len(audio) * 16000 / tts.sample_rate)
            audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio)
            _write(CLIP_DIR / f"{cid}.wav", np.clip(audio, -1, 1))
    out = {c[0]: (c[1], CLIP_DIR / f"{c[0]}.wav") for c in wanted}
    rng = np.random.default_rng(0)
    for cid in NOISY:
        if cid in out:
            p = CLIP_DIR / f"{cid}_noisy.wav"
            if not p.exists():
                audio, _ = sf.read(out[cid][1], dtype="float32")
                rms = np.sqrt(np.mean(audio ** 2))
                noisy = audio + _pink_noise(len(audio), rng) * rms * 10 ** (-25 / 20)
                _write(p, np.clip(noisy, -1, 1))
            out[cid + "_noisy"] = (out[cid][0], p)
    return out


def clip_b64(path: Path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


def _summarize(name, rows, rss_mb):
    errs = sum(r["err"] for r in rows)
    words = sum(r["n"] for r in rows)
    vh = sum(r["vh"] for r in rows)
    vn = sum(r["vn"] for r in rows)
    lat = np.array([r["lat"] for r in rows])
    short = np.array([r["lat"] for r in rows if r["dur"] <= 5.0]) if rows else lat
    return {
        "name": name, "wer": 100 * errs / max(words, 1), "vocab": 100 * vh / max(vn, 1),
        "mean": lat.mean(), "p90": np.percentile(lat, 90),
        "p90_short": np.percentile(short, 90) if len(short) else float("nan"),
        "rss": rss_mb,
    }


def _eval(fn, clips, rows_extra=None):
    rows, details = [], []
    for cid, (text, path) in clips.items():
        dur = sf.info(path).duration
        t0 = time.perf_counter()
        hyp = fn(path)
        lat = time.perf_counter() - t0
        e, n = wer(text, hyp)
        vh, vn = vocab_hits(text, hyp)
        rows.append({"err": e, "n": n, "vh": vh, "vn": vn, "lat": lat, "dur": dur})
        if e or vh < vn:
            details.append(f"{cid}: ref={text!r} hyp={hyp!r}")
    return rows, details


def main():
    import llm
    import stt

    clips = ensure_clips()
    print(f"{len(clips)} clips")
    results, notes = [], []
    proc = psutil.Process()

    if llm.server_ready():
        rows, det = _eval(lambda p: llm._gemma_transcribe(clip_b64(p)), clips)
        results.append(_summarize("gemma (GPU, llama-server)", rows, float("nan")))
        notes += [f"[gemma] {d}" for d in det]
    else:
        notes.append("Gemma skipped: llama-server did not answer /health.")

    from faster_whisper import WhisperModel
    for model_name in ("large-v3-turbo", "distil-large-v3", "small.en"):
        t0 = time.perf_counter()
        model = WhisperModel(model_name, device="cpu", compute_type="int8",
                             cpu_threads=config.STT_CPU_THREADS)
        print(f"{model_name} loaded in {time.perf_counter() - t0:.1f}s")
        audio0 = stt.decode_wav(clip_b64(next(iter(clips.values()))[1]))
        model.transcribe(audio0[:16000], language="en", beam_size=1)  # warm-up
        for bias in ("none", "hotwords", "initial_prompt"):
            rss = 0.0

            def fn(p, bias=bias):
                nonlocal rss
                audio, _ = sf.read(p, dtype="float32")
                out = stt.run(model, audio, bias, config.STT_BEAM_SIZE)
                rss = max(rss, proc.memory_info().rss / 2 ** 20)
                return out

            rows, det = _eval(fn, clips)
            label = f"{model_name} / {bias}"
            results.append(_summarize(label, rows, rss))
            notes += [f"[{label}] {d}" for d in det]
            r = results[-1]
            print(f"{label}: WER {r['wer']:.1f}% vocab {r['vocab']:.1f}% p90 {r['p90']:.2f}s")
        del model
        gc.collect()

    whisper = [r for r in results if not r["name"].startswith("gemma")]
    ok = [r for r in whisper if r["p90_short"] <= 1.2]
    if ok:
        best = min(ok, key=lambda r: (-round(r["vocab"], 1), r["wer"]))
        rule = "highest vocab accuracy among configs with p90 <= 1.2 s (clips <= 5 s), ties by WER"
    else:
        cand = [r for r in whisper if r["vocab"] >= 95] or whisper
        best = min(cand, key=lambda r: r["p90_short"])
        rule = "no whisper config met p90 <= 1.2 s; fastest with vocab accuracy >= 95%"

    lines = [
        "# STT benchmark results", "",
        f"Clips: {len(clips)} PocketTTS clips in the user's cloned voice "
        f"({len(CLIPS)} base + {len([k for k in clips if k.endswith('_noisy')])} with -25 dB pink noise).",
        f"CPU int8, beam {config.STT_BEAM_SIZE}, {config.STT_CPU_THREADS} threads. "
        "Latency is per clip, measured while Orion (llama-server + orion.py) was running live, "
        "so numbers include contention. RSS is the benchmark process's resident size (includes "
        "earlier-loaded models and the TTS), not an isolated per-model peak.", "",
        "| config | WER % | vocab acc % | mean s | p90 s | p90 s (<=5 s clips) | RSS MB |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        rss = "n/a" if np.isnan(r["rss"]) else f"{r['rss']:.0f}"
        lines.append(f"| {r['name']} | {r['wer']:.1f} | {r['vocab']:.1f} | {r['mean']:.2f} | "
                     f"{r['p90']:.2f} | {r['p90_short']:.2f} | {rss} |")
    lines += ["", f"Chosen: **{best['name']}** ({rule}).", ""]
    lines += ["## Misses", ""] + [f"- {n}" for n in notes]
    RESULTS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:len(results) + 8]))
    print(f"\nChosen: {best['name']}")


if __name__ == "__main__":
    main()
