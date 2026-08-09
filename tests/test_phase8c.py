r"""Phase 8 follow-up: 'go to sleep' must register in movie mode (and survive a
trailing 'keep the movie on' clause + filler), while movie mode keeps playing.

Run from the project root:  orion_env\Scripts\python.exe tests\test_phase8c.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from orion import _is_sleep_command

PASS, FAIL = 0, []


def check(name, condition, detail=""):
    global PASS
    if condition:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL {name}  {detail}")


# Should sleep (the whole point: works in movie mode, keeps the movie).
SLEEP = [
    "go to sleep",
    "go to sleep but keep the movie on",
    "go to sleep but leave the animation running",
    "okay orion go to sleep please",
    "go to sleep, and goodbye",
    "you can go to sleep now",
    "never mind",
    "that's all, thanks",
    "go idle but keep movie mode on",
    "go to bed",
]
for u in SLEEP:
    check(f"sleeps: {u!r}", _is_sleep_command(u), "did not match")

# Should NOT sleep (embedded mention, or a real request — leave to the model).
KEEP_AWAKE = [
    "remind me to go to sleep at ten",
    "what time should I go to sleep",
    "set the movie animation to three",
    "movie mode animation five",
    "tell me about the abyssal fluid animation",
    "add a task to fix the sleep timer",
]
for u in KEEP_AWAKE:
    check(f"stays awake: {u!r}", not _is_sleep_command(u), "false dismissal")

print(f"\n{PASS} passed, {len(FAIL)} failed" + (f": {FAIL}" if FAIL else ""))
sys.exit(1 if FAIL else 0)
