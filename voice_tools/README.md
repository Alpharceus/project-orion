# voice_tools

Hands-off voice cloning for Orion's PocketTTS: give it a video, get a clean
single-speaker reference clip and the `.safetensors` voice export.

## Setup (once)

```powershell
powershell -ExecutionPolicy Bypass -File voice_tools/setup.ps1
```

Creates `voice_tools/.venv` (Python 3.12, CPU torch). `orion_env` is never touched.

## Usage

```powershell
voice_tools\.venv\Scripts\python.exe voice_tools\clone_voice_from_video.py --input movie.mp4 --name ultron
```

Outputs (in `models/pocket_tts/` by default, override with `--out-dir`):
`<name>_voice_sample.wav` (24 kHz mono, ~25 s) and `<name>_voice.safetensors`.
Existing outputs are not overwritten unless `--force`.

Useful options:

- `--reference WAV` keep only segments that match this speaker (cosine >= `--min-sim`, default 0.55). Without it, the largest speaker cluster is used (`--cluster-threshold`, default 0.6).
- `--target-seconds N` sample length (default 25, max 30).
- `--keep-work DIR` keep intermediates (`vocals.wav`, `no_vocals.wav`, `segments.csv`).
- `--start S --duration D` process only part of a long film (demucs on CPU is slow and memory-hungry on full-length movies).
- `--no-export` write the sample wav only.

## Stages

1. Extract audio with ffmpeg (44.1 kHz stereo WAV).
2. Isolate vocals with demucs `htdemucs` (CPU).
3. Find speech with Silero VAD; keep segments of 1.5-12 s, merging gaps under 0.25 s.
4. Pick the target speaker with SpeechBrain ECAPA embeddings (reference match or clustering; a cluster table is printed).
5. Rank segments by how dominant the voice is over the rest of the mix, take the best up to the target length, join in time order with 0.3 s gaps, normalise to -1 dBFS, write 24 kHz mono.
6. Export with `orion_env/Scripts/pocket-tts.exe export-voice`.

Fails with a one-line error if ffmpeg is missing, the input is missing, or under 8 s of usable speech is found.

## Self-test

```powershell
voice_tools\.venv\Scripts\python.exe voice_tools\selftest.py
```

Builds a synthetic two-speaker video from PocketTTS built-in voices under `voice_tools/work/test/` and checks the whole pipeline.

## Notes

Cloned voices of real people are for personal, local use only. Samples and exports stay out of git (`*.wav`, `*.safetensors`, `models/pocket_tts/`, `voice_tools/work/` and `voice_tools/.venv/` are ignored). The first run downloads the demucs and ECAPA models.

## Short clips (under ~1 minute)

Speaker clustering needs enough speech to separate voices; on a 30 s clip of a
heavily processed voice (the Ultron voice was built this way) it fragments the
target into several clusters and finds too little usable speech. In that case,
run with `--keep-work DIR --no-export`, check which segments are the target
(transcribe them, or listen), then build the sample straight from the demucs
stem and export it:

```
ffmpeg -i DIR/vocals.wav -ss <start> -af "silenceremove=start_periods=1:start_threshold=-45dB:stop_periods=-1:stop_duration=0.35:stop_threshold=-45dB,highpass=f=70,loudnorm=I=-18:TP=-1.5:LRA=11" -ac 1 -ar 24000 models/pocket_tts/<name>_voice_sample.wav
orion_env\Scripts\pocket-tts.exe export-voice models/pocket_tts/<name>_voice_sample.wav models/pocket_tts/<name>_voice.safetensors
```
