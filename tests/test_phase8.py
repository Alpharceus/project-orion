r"""Unit tests for Phase 8 (movie mode) — no LLM, isolated temp store.

Run from the project root:  orion_env\Scripts\python.exe tests\test_phase8.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config
import events
from agents import dispatch, movie

# Isolate the JSON store.
_tmp = Path(tempfile.mkdtemp())
config.DATA_DIR = _tmp
movie.STORE = _tmp / "movie.json"
movie._state.update({"on": False, "index": 0})

PASS, FAIL = 0, []


def check(name, condition, detail=""):
    global PASS
    if condition:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL {name}  {detail}")


# Capture movie events published to the HUD.
seen = []
events.subscribe(lambda e: seen.append(e) if e.get("type") == "movie" else None)


def last_movie():
    return next((e for e in reversed(seen) if e["type"] == "movie"), None)


# --- on / off ----------------------------------------------------------------
print("on/off:")
out = dispatch("movie_mode", {"action": "on"})
m = last_movie()
check("on turns movie on + emits event", m and m["on"] is True, str(m))
check("on reply names the animation", "Cosmic Drift" in out, out)

dispatch("movie_mode", {"action": "off"})
check("off turns movie off", last_movie()["on"] is False, str(last_movie()))

# --- set by number -----------------------------------------------------------
print("set:")
out = dispatch("movie_mode", {"action": "set", "number": 3})
m = last_movie()
check("set 3 -> index 2 (0-based) + on", m and m["index"] == 2 and m["on"], str(m))
check("set 3 names Abyssal Fluid", m["name"] == "Abyssal Fluid" and "Abyssal Fluid" in out, str(m))

check("set out of range rejected", "between 1 and 10" in dispatch("movie_mode", {"action": "set", "number": 99}))
check("set with no number asks", "1 to 10" in dispatch("movie_mode", {"action": "set"}))
check("all 10 names present", len(movie.ANIMATIONS) == 10 and movie.ANIMATIONS[-1] == "Solar Corona")

# --- screens (which monitors) -------------------------------------------------
print("screens:")
check("defaults to others", movie._state["screens"] == "others")
dispatch("movie_mode", {"action": "on", "screens": "all"})
check("screens=all takes + appears in event",
      movie._state["screens"] == "all" and last_movie()["screens"] == "all", str(last_movie()))
dispatch("movie_mode", {"action": "set", "number": 4, "screens": "others"})
check("screens=others on set",
      movie._state["screens"] == "others" and last_movie()["screens"] == "others", str(last_movie()))

# --- persistence round-trip --------------------------------------------------
print("persistence:")
dispatch("movie_mode", {"action": "set", "number": 7})
movie._state.update({"on": False, "index": 0})   # wipe in-memory
movie._load()
check("reloads index 6 + on from disk", movie._state["index"] == 6 and movie._state["on"] is True, str(movie._state))

# start() should re-emit the restored state for the HUD snapshot.
seen.clear()
movie.start()
m = last_movie()
check("start re-emits restored state", m and m["index"] == 6 and m["on"] is True, str(m))

print(f"\n{PASS} passed, {len(FAIL)} failed" + (f": {FAIL}" if FAIL else ""))
sys.exit(1 if FAIL else 0)
