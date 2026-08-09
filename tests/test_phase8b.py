r"""Phase 8 follow-ups: TTS chunk splitting, movie agent-node event, open-folder.

Run from the project root:  orion_env\Scripts\python.exe tests\test_phase8b.py
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config
import events

PASS, FAIL = 0, []


def check(name, condition, detail=""):
    global PASS
    if condition:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL {name}  {detail}")


# --- TTS chunk splitting (no model: word-count heuristic) --------------------
print("tts splitting:")
from speech import _pack, _split_units, _TTS_MAX_TOKENS

WC = lambda s: max(1, round(len(s.split()) * 1.4))  # same heuristic as the fallback

# A long, comma-free sentence is exactly what triggered the PocketTTS warning.
long_sentence = ("This approach is significant because it can drastically reduce the "
                 "computational overhead of the entire pipeline while still preserving "
                 "the fidelity of the reconstructed quantum state across many runs and "
                 "different hardware backends without any manual retuning whatsoever.")
units = _split_units(long_sentence, WC)
check("long comma-free sentence is split", len(units) > 1, str(len(units)))
check("every unit within budget", all(WC(u) <= _TTS_MAX_TOKENS for u in units),
      str([WC(u) for u in units]))
check("split preserves all words",
      " ".join(units).split() == long_sentence.split())

packed = _pack(units, WC)
check("packed chunks within budget", all(WC(c) <= _TTS_MAX_TOKENS for c in packed),
      str([WC(c) for c in packed]))

# Short text passes through as a single piece.
short = "Movie mode is on."
check("short text stays one piece", _pack(_split_units(short, WC), WC) == [short])

# Multi-sentence: normal sentences are kept whole, packed near budget.
para = "First short sentence. Second one here. Third sentence to consider."
check("multi-sentence preserved", " ".join(_pack(_split_units(para, WC), WC)).split() == para.split())

# --- movie agent-node event ---------------------------------------------------
print("movie node:")
_tmp = Path(tempfile.mkdtemp())
config.DATA_DIR = _tmp
from agents import dispatch, movie
movie.STORE = _tmp / "movie.json"
movie._state.update({"on": False, "index": 0})

seen = []
events.subscribe(lambda e: seen.append(e) if e.get("type") == "agent" and e.get("id") == "movie" else None)
dispatch("movie_mode", {"action": "set", "number": 2})
ev = next((e for e in reversed(seen) if e["id"] == "movie"), None)
check("movie node goes active when on", ev and ev["status"] == "active", str(ev))
check("movie node carries the animation name", ev and ev.get("meta") == "Dust Motes", str(ev))
dispatch("movie_mode", {"action": "off"})
ev = next((e for e in reversed(seen) if e["id"] == "movie"), None)
check("movie node idle when off", ev and ev["status"] == "idle", str(ev))

# --- open papers folder tool --------------------------------------------------
print("open papers folder:")
import agents
check("open_papers_folder registered",
      "open_papers_folder" in [s["function"]["name"] for s in agents.tool_specs()])
config.PAPERS_DIR = _tmp / "papers"
opened = {}
_orig = os.startfile if hasattr(os, "startfile") else None
os.startfile = lambda p: opened.setdefault("path", p)  # don't really pop Explorer in tests
out = dispatch("open_papers_folder", {})
check("opens the papers dir", "path" in opened and "papers" in str(opened["path"]).lower(), str(opened))
check("reports empty folder", "empty" in out.lower(), out)
(config.PAPERS_DIR).mkdir(parents=True, exist_ok=True)
(config.PAPERS_DIR / "2506.12345.pdf").write_bytes(b"%PDF-1.4 test")
out2 = dispatch("open_papers_folder", {})
check("reports paper count", "1 paper" in out2, out2)
if _orig:
    os.startfile = _orig

print(f"\n{PASS} passed, {len(FAIL)} failed" + (f": {FAIL}" if FAIL else ""))
sys.exit(1 if FAIL else 0)
