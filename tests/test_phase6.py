r"""Unit tests for Phase 6 (telemetry + niche/keyword arXiv + ticker) — no LLM.

Run from the project root:  orion_env\Scripts\python.exe tests\test_phase6.py
The live arXiv fetch at the end needs internet; it reports but does not fail.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config
import events
import telemetry
from agents import arxiv_briefing as ab
from agents import dispatch, set_notifier

PASS, FAIL = 0, []


def check(name, condition, detail=""):
    global PASS
    if condition:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL {name}  {detail}")


# --- weather code mapping -----------------------------------------------------
print("weather mapping:")
check("clear", telemetry.weather_label(0) == "clear")
check("cloudy", telemetry.weather_label(3) == "cloudy")
check("rain", telemetry.weather_label(63) == "rain")
check("snow", telemetry.weather_label(75) == "snow")
check("storm", telemetry.weather_label(95) == "storm")
check("unknown -> dash", telemetry.weather_label(123) == "—")

# --- telemetry combined event -------------------------------------------------
print("telemetry event:")
tele = []
events.subscribe(lambda e: tele.append(e) if e.get("type") == "telemetry" else None)
stop = telemetry.start()
deadline = time.monotonic() + 5
while not tele and time.monotonic() < deadline:
    time.sleep(0.2)
stop.set()
check("a telemetry event was published", len(tele) > 0, str(tele))
if tele:
    e = tele[-1]
    check("cpu is an int 0..100", isinstance(e.get("cpu"), int) and 0 <= e["cpu"] <= 100, str(e))
    check("ram is an int 0..100", isinstance(e.get("ram"), int) and 0 <= e["ram"] <= 100, str(e))
    check("gpu fields present (NVML)", "gpu_gb" in e and "gpu_pct" in e, str(e))

# --- arXiv query building -----------------------------------------------------
print("query building:")
check("topic phrase conversion",
      ab._topic_to_query("all:quantum+dot+AND+all:single+photon")
      == '(all:"quantum dot" AND all:"single photon")')
niche = ab.build_query()  # standing topics
check("niche is a topic OR-group", " OR " in niche and 'all:"GKP"' in niche, niche)
check("niche topics use AND'd phrases", 'all:"single photon source"' in niche, niche)
check("niche unconstrained by category by default", "cat:" not in niche, niche)
allq = ab.build_query(scope="all")
check("scope=all uses broad cats", "cat:cs.AI" in allq, allq)
check("scope=all drops topics", "all:" not in allq, allq)
ext = ab.build_query(keywords=["cat qubit"], keyword_mode="extend")
check("extend keeps standing topics + adds new", 'all:"GKP"' in ext and 'all:"cat qubit"' in ext, ext)
rep = ab.build_query(keywords=["cat qubit"], keyword_mode="replace")
check("replace drops standing topics", 'all:"GKP"' not in rep and 'all:"cat qubit"' in rep, rep)
empty = ab.build_query(keywords=[], keyword_mode="replace")
check("empty replace -> category fallback", "all:" not in empty and "cat:quant-ph" in empty, empty)

# --- briefing pipeline: ticker + zero-result fallback -------------------------
print("briefing pipeline:")
import llm
import memory
import tempfile
memory.STORE = Path(tempfile.mkdtemp()) / "memory.json"
memory._data.update({"facts": {}, "seen_arxiv": [], "last_briefing": []})
real_fetch, real_oneshot = ab.fetch_papers, llm.oneshot
PAPER = [{"id": "2506.9999", "title": "Fallback Paper", "summary": "x",
          "authors": ["A"], "category": "quant-ph", "pdf": "u"}]

set_notifier(lambda *_: None)
ticker = []
events.subscribe(lambda e: ticker.append(e) if e.get("type") == "ticker" else None)

# (1) normal: keyword query returns papers -> no fallback, ticker emitted
calls = []
ab.fetch_papers = lambda keywords=None, keyword_mode="extend", scope="niche": (calls.append(keywords), PAPER)[1]
captured = {}
llm.oneshot = lambda system, user: captured.setdefault("user", user) or "spoken"
ticker.clear()
memory._data["seen_arxiv"] = []  # unseen, so the briefing speaks
ab.run_briefing()
check("normal run fetches once", len(calls) == 1, str(calls))
check("ticker emitted with titles", ticker and ticker[-1]["titles"] == ["Fallback Paper"], str(ticker))
check("no fallback note in prompt", "matched nothing" not in captured.get("user", ""))

# (2) fallback: keyword query empty -> retries category-only, notes it
calls2 = []
def fake_fetch(keywords=None, keyword_mode="extend", scope="niche"):
    calls2.append((keywords, keyword_mode))
    return PAPER if keywords == [] else []
ab.fetch_papers = fake_fetch
captured.clear()
ticker.clear()
memory._data["seen_arxiv"] = []  # unseen again, so the fallback path runs
ab.run_briefing()
check("fallback retries with empty keywords",
      calls2 == [(None, "extend"), ([], "replace")], str(calls2))
check("fallback ticker still emitted", bool(ticker), str(ticker))
check("fallback note added to prompt", "matched nothing" in captured.get("user", ""))
ab.fetch_papers, llm.oneshot = real_fetch, real_oneshot

# --- tool surface -------------------------------------------------------------
print("tool:")
out = dispatch("arxiv_briefing", {"action": "status"})
check("status mentions topic filtering", "topics" in out.lower(), out)
check("status names a research area", "GKP" in out or "single-photon" in out.lower(), out)

# --- live niche fetch (informational) -----------------------------------------
print("live arXiv niche fetch:")
try:
    live = ab.fetch_papers()  # standing topics
    print(f"  niche topic query returned {len(live)} papers")
    if live:
        print(f"      e.g. [{live[0]['category']}] {live[0]['title'][:70]}")
    broad = ab.fetch_papers(scope="all")
    check("scope=all returns papers", len(broad) > 0, str(len(broad)))
except Exception as e:
    print(f"  skip live fetch ({e})")

print(f"\n{PASS} passed, {len(FAIL)} failed" + (f": {FAIL}" if FAIL else ""))
sys.exit(1 if FAIL else 0)
