r"""Unit tests for Phase 6.5 (reminders + tasks) — no LLM, isolated temp stores.

Run from the project root:  orion_env\Scripts\python.exe tests\test_phase65.py
"""

import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config
import events
from agents import dispatch, reminders, set_notifier, tasks

# Isolate the JSON stores so tests don't touch the real data dir.
_tmp = Path(tempfile.mkdtemp())
config.DATA_DIR = _tmp
reminders.STORE = _tmp / "reminders.json"
tasks.STORE = _tmp / "tasks.json"
reminders._reminders.clear()
tasks._tasks.clear()

notes = []
set_notifier(notes.append)

PASS, FAIL = 0, []


def check(name, condition, detail=""):
    global PASS
    if condition:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL {name}  {detail}")


# --- next-fire math -----------------------------------------------------------
print("scheduling math:")
now = datetime(2026, 6, 14, 12, 0, 0)
check("relative offset", reminders._compute_next(now, delay_seconds=1200) == now + timedelta(minutes=20))
check("absolute later today",
      reminders._compute_next(now, time_hm="15:00", allowed=list(range(7))) == now.replace(hour=15, minute=0))
check("absolute past -> tomorrow",
      reminders._compute_next(now, time_hm="09:00", allowed=list(range(7))) == (now + timedelta(days=1)).replace(hour=9, minute=0))
wk = reminders._compute_next(now, time_hm="09:00", allowed=[0, 1, 2, 3, 4])
check("weekdays-only lands on a weekday", wk.weekday() in (0, 1, 2, 3, 4) and wk.hour == 9 and wk > now, str(wk))

# --- one-off fire + removal ---------------------------------------------------
print("one-off reminder:")
notes.clear()
reminders.add("stretch", in_minutes=0.01)  # ~0.6 s from now
fired = reminders.fire_due(datetime.now() + timedelta(seconds=2))
check("one-off fired", fired >= 1 and any("stretch" in n for n in notes), str(notes))
check("one-off removed after firing", not any(r["message"] == "stretch" for r in reminders.active_reminders()))

# --- recurring advance --------------------------------------------------------
print("recurring reminder:")
rem = reminders.add("standup", time="09:00", repeat="daily")
first = rem["next_fire"]
reminders.fire_due(datetime.fromisoformat(first) + timedelta(seconds=1))
again = next(r for r in reminders.active_reminders() if r["message"] == "standup")
check("recurring stays active", again is not None)
check("recurring advanced to a future time", again["next_fire"] > first, again["next_fire"])

# --- persistence round-trip ---------------------------------------------------
print("persistence:")
reminders._save()
reminders._reminders.clear()
reminders._load()
check("reminders reload from disk", any(r["message"] == "standup" for r in reminders.active_reminders()))

# --- cancel -------------------------------------------------------------------
print("cancel:")
reminders.add("call mom", time="18:00")
check("cancel by substring", reminders.cancel("call mom") == 1)
check("cancel no match", reminders.cancel("nonexistent") == 0)

# --- tasks --------------------------------------------------------------------
print("tasks:")
tasks._tasks.clear()
tasks.add("write report", priority="high")
before = len(reminders.active_reminders())
milk = tasks.add("buy milk", due_time="17:00")
check("due task creates a reminder", len(reminders.active_reminders()) == before + 1 and milk["reminder_id"], str(milk))
ordered = tasks.open_tasks()
check("high priority sorts first", ordered[0]["title"] == "write report", str([t["title"] for t in ordered]))
check("complete by word", tasks.complete("report") == 1 and not any(t["title"] == "write report" for t in tasks.open_tasks()))
before = len(reminders.active_reminders())
tasks.complete("milk")
check("completing a due task clears its reminder", len(reminders.active_reminders()) == before - 1)

# --- tool surfaces ------------------------------------------------------------
print("tools:")
check("reminder add", "Reminder set" in dispatch("reminder", {"action": "add", "message": "water plants", "time": "08:00", "repeat": "daily"}))
check("reminder list", "water plants" in dispatch("reminder", {"action": "list"}))
check("reminder cancel", "Cancelled 1" in dispatch("reminder", {"action": "cancel", "which": "water"}))
check("task add", "Added" in dispatch("task", {"action": "add", "title": "finish slides", "priority": "high"}))
check("task list", "finish slides" in dispatch("task", {"action": "list"}))
check("task complete", "1 task" in dispatch("task", {"action": "complete", "which": "slides"}))

# --- HUD events ---------------------------------------------------------------
# Reminders + tasks each have their own HUD panel now (not agent nodes), so they
# publish a full list snapshot whenever the set changes.
print("HUD events:")
seen = []
events.subscribe(lambda e: seen.append(e) if e.get("type") in ("reminders_list", "tasks_list") else None)
reminders.add("ping", in_minutes=5)
rem_evt = next((e for e in reversed(seen) if e["type"] == "reminders_list"), None)
check("reminders_list published with the new item",
      rem_evt is not None and any(i["text"] == "ping" for i in rem_evt["items"]), str(rem_evt))
tasks.add("demo task")
task_evt = next((e for e in reversed(seen) if e["type"] == "tasks_list"), None)
check("tasks_list published with the new item",
      task_evt is not None and any(i["title"] == "demo task" for i in task_evt["items"]), str(task_evt))

print(f"\n{PASS} passed, {len(FAIL)} failed" + (f": {FAIL}" if FAIL else ""))
sys.exit(1 if FAIL else 0)
