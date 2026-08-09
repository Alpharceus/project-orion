r"""Unit tests for Phase 3 (scheduler + arXiv briefing) — no LLM or audio needed.

Run from the project root:  orion_env\Scripts\python.exe tests\test_phase3.py
The live-fetch check needs internet; it reports but does not fail offline.
"""

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import agents
import llm
import scheduler
from agents import arxiv_briefing as briefing_mod
from agents import dispatch, set_notifier

PASS, FAIL = 0, []


def check(name: str, condition: bool, detail: str = ""):
    global PASS
    if condition:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL {name}  {detail}")


notifications = []
set_notifier(notifications.append)

# --- scheduler ----------------------------------------------------------------
print("scheduler:")
for bad in ("8am", "25:00", "08:61", "08"):
    try:
        scheduler.parse_time(bad)
        check(f"rejects {bad!r}", False)
    except ValueError:
        check(f"rejects {bad!r}", True)
check("parses HH:MM", scheduler.parse_time("08:30") == (8, 30, 0))

fired = []
at = (datetime.now() + timedelta(seconds=2)).strftime("%H:%M:%S")
scheduler.schedule_daily("t_job", at, lambda: fired.append(time.monotonic()))
check("status while scheduled", scheduler.scheduled_time("t_job") == at)
time.sleep(3.5)
check("job fired at its time", len(fired) == 1, str(fired))
check("cancel", scheduler.cancel("t_job") is True)
check("status after cancel", scheduler.scheduled_time("t_job") is None)
check("cancel unknown job", scheduler.cancel("t_job") is False)

# rescheduling replaces the old job rather than stacking a second timer
fired.clear()
at = (datetime.now() + timedelta(seconds=2)).strftime("%H:%M:%S")
scheduler.schedule_daily("t_job", "23:59", lambda: fired.append("old"))
scheduler.schedule_daily("t_job", at, lambda: fired.append("new"))
time.sleep(3.5)
check("reschedule replaces job", fired == ["new"], str(fired))
scheduler.cancel("t_job")

# --- arXiv feed parsing --------------------------------------------------------
print("feed parsing:")
CANNED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Quantum  Fisher
 Information Bounds</title>
    <summary>  We derive new bounds.
  Across two lines.  </summary>
    <author><name>A. Researcher</name></author>
    <author><name>B. Scientist</name></author>
    <category term="quant-ph"/>
  </entry>
  <entry>
    <title>Second Paper</title>
    <summary>Another abstract.</summary>
    <author><name>C. Author</name></author>
    <category term="cs.AI"/>
  </entry>
</feed>"""
papers = briefing_mod.parse_feed(CANNED)
check("two entries parsed", len(papers) == 2, str(len(papers)))
check("whitespace normalized", papers[0]["title"] == "Quantum Fisher Information Bounds",
      papers[0]["title"])
check("summary normalized", papers[0]["summary"] == "We derive new bounds. Across two lines.",
      papers[0]["summary"])
check("authors collected", papers[0]["authors"] == ["A. Researcher", "B. Scientist"])
check("category read", papers[1]["category"] == "cs.AI")

# --- briefing pipeline (fetch + LLM faked, full notify path) --------------------
print("briefing pipeline:")
real_fetch, real_oneshot = briefing_mod.fetch_papers, llm.oneshot
briefing_mod.fetch_papers = lambda *a, **k: papers
llm.oneshot = lambda system, user: "Fake briefing summary." if "Second Paper" in user else ""
notifications.clear()
briefing_mod.run_briefing()
check("briefing spoken via notify", notifications == ["Fake briefing summary."], str(notifications))

briefing_mod.fetch_papers = lambda *a, **k: (_ for _ in ()).throw(OSError("no network"))
notifications.clear()
briefing_mod.run_briefing()
check("fetch failure announced, not raised",
      len(notifications) == 1 and "couldn't reach arXiv" in notifications[0], str(notifications))
briefing_mod.fetch_papers, llm.oneshot = real_fetch, real_oneshot

# --- tool surface ----------------------------------------------------------------
print("tool:")
out = dispatch("arxiv_briefing", {"action": "schedule", "time": "07:45"})
check("schedule via tool", out == "Daily arXiv briefing scheduled for 07:45.", out)
out = dispatch("arxiv_briefing", {"action": "status"})
check("status via tool", "07:45" in out and "topics" in out.lower(), out)
out = dispatch("arxiv_briefing", {"action": "schedule", "time": "13:99"})
check("bad time rejected", out.startswith("Tool error:"), out)
check("bad time kept old schedule", "07:45" in dispatch("arxiv_briefing", {"action": "status"}))
out = dispatch("arxiv_briefing", {"action": "cancel"})
check("cancel via tool", out == "Daily arXiv briefing cancelled.", out)
check("cancel when idle", "wasn't scheduled" in dispatch("arxiv_briefing", {"action": "cancel"}))

# --- live fetch (informational; needs internet) ----------------------------------
print("live arXiv fetch:")
try:
    live = briefing_mod.fetch_papers(scope="all")
    check("live fetch returns papers", len(live) > 0, str(len(live)))
    print(f"      newest: [{live[0]['category']}] {live[0]['title'][:70]}")
except Exception as e:
    print(f"  skip live fetch ({e})")

# ----------------------------------------------------------------------------------
print(f"\n{PASS} passed, {len(FAIL)} failed" + (f": {FAIL}" if FAIL else ""))
sys.exit(1 if FAIL else 0)
