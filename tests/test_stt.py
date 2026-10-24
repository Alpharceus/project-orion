r"""STT tests: faster-whisper transcription of cached TTS clips, silence guard, and llm routing/fallback.

Run from the project root:  orion_env\Scripts\python.exe tests\test_stt.py
Clips come from tests/stt_clips/ (synthesized with PocketTTS if missing). No llama-server needed.
"""

import base64
import io
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import llm
import stt
from stt_benchmark import clip_b64, ensure_clips

PASS, FAIL = 0, []


def check(name: str, condition: bool, detail: str = ""):
    global PASS
    if condition:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL {name}  {detail}")


clips = ensure_clips({"c01", "c03", "c04", "p01"})

print("transcription")
text = stt.transcribe(clip_b64(clips["c01"][1]))
check("ultron recognized", "ultron" in text.lower(), repr(text))
text = stt.transcribe(clip_b64(clips["c03"][1]))
check("pomodoro recognized", "pomodoro" in text.lower(), repr(text))
text = stt.transcribe(clip_b64(clips["c04"][1]))
check("GKP recognized", "gkp" in text.lower(), repr(text))
text = stt.transcribe(clip_b64(clips["p01"][1]))
check("plain sentence non-empty", "mom" in text.lower(), repr(text))

print("silence")
buf = io.BytesIO()
sf.write(buf, np.zeros(8000, dtype=np.float32), 16000, format="WAV")
silent = base64.b64encode(buf.getvalue()).decode("ascii")
check("0.5 s silence -> empty", stt.transcribe(silent) == "")

print("llm routing")
orig_stt, orig_gemma, orig_engine = stt.transcribe, llm._gemma_transcribe, config.STT_ENGINE
try:
    config.STT_ENGINE = "whisper"
    stt.transcribe = lambda a: "from-stt"
    llm._gemma_transcribe = lambda a: "from-gemma"
    check("routes to stt", llm.transcribe("x") == "from-stt")

    def boom(a):
        raise RuntimeError("boom")
    stt.transcribe = boom
    check("falls back to gemma when stt raises", llm.transcribe("x") == "from-gemma")

    config.STT_ENGINE = "gemma"
    stt.transcribe = lambda a: "from-stt"
    check("engine=gemma skips stt", llm.transcribe("x") == "from-gemma")
finally:
    stt.transcribe, llm._gemma_transcribe, config.STT_ENGINE = orig_stt, orig_gemma, orig_engine

print(f"\n{PASS} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:", ", ".join(FAIL))
    sys.exit(1)
