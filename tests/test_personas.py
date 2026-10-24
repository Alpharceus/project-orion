r"""Unit tests for persona voice FX and the HUD persona snapshot — no audio or TTS needed.

Run from the project root:  orion_env\Scripts\python.exe tests\test_personas.py
"""

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config
import events
import hud_server
from speech import VoiceFX

PASS, FAIL = 0, []


def check(name: str, condition: bool, detail: str = ""):
    global PASS
    if condition:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL {name}  {detail}")


SR = 24000
# No persona uses the filter right now; exercise VoiceFX with its old Ultron settings.
fx_cfg = {"ring_hz": 40.0, "ring_mix": 0.22, "comb_ms": 7.0,
          "comb_feedback": 0.42, "comb_mix": 0.35, "gain": 1.0}
check("orion has no fx", not config.PERSONAS["orion"].get("fx"))
check("ultron has no fx", not config.PERSONAS["ultron"].get("fx"))

rng = np.random.default_rng(0)
sig = (0.3 * rng.standard_normal(SR)).astype(np.float32)

print("VoiceFX:")
fx = VoiceFX(SR, **fx_cfg)
one = fx.process(sig)
check("same length", one.shape == sig.shape)
check("float32 out", one.dtype == np.float32, str(one.dtype))
check("output differs from input", float(np.max(np.abs(one - sig))) > 1e-3)

fx.reset()
parts, pos = [], 0
for n in (137, 1000, 1, 2400) * 20:
    if pos >= len(sig):
        break
    parts.append(fx.process(sig[pos:pos + n]))
    pos += n
if pos < len(sig):
    parts.append(fx.process(sig[pos:]))
chunked = np.concatenate(parts)
check("chunked == one-shot", chunked.shape == one.shape and float(np.max(np.abs(chunked - one))) < 1e-5,
      f"max diff {float(np.max(np.abs(chunked - one))):.2e}")

fx.reset()
check("reset restores identical output", np.array_equal(fx.process(sig), one))

loud = (0.99 * np.sin(2 * np.pi * 200 * np.arange(SR) / SR)).astype(np.float32)
fx.reset()
out = fx.process(loud)
check("bounded in [-1, 1]", float(np.max(np.abs(out))) <= 1.0, f"peak {float(np.max(np.abs(out))):.3f}")

fx.reset()
t0 = time.perf_counter()
fx.process(sig)
dt = (time.perf_counter() - t0) * 1000
check("1 s of audio < 50 ms", dt < 50, f"{dt:.1f} ms")

print("HUD snapshot:")
check("default snapshot has orion persona",
      {"type": "persona", "name": "orion"} in hud_server._snapshot())
event = {"type": "persona", "name": "ultron"}
events.publish(event)
# _relay is the loop-thread cache updater; call it directly (no sockets/loop needed)
hud_server._relay(event)
check("snapshot includes ultron persona event", event in hud_server._snapshot())
check("persona is a relayed type", "persona" in hud_server._RELAY_TYPES)

print(f"\n{PASS} passed, {len(FAIL)} failed" + (f": {FAIL}" if FAIL else ""))
sys.exit(1 if FAIL else 0)
