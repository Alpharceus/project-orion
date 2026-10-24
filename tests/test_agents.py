r"""Unit tests for the Phase 2 agent framework — no LLM or audio needed.

Run from the project root:  orion_env\Scripts\python.exe tests\test_agents.py
"""

import builtins
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import agents
import config
import events
import persona
from agents import dispatch, set_notifier, tool_specs
from agents import eye_care as eye_care_mod

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

# --- registry ---------------------------------------------------------------
print("registry:")
specs = tool_specs()
names = {s["function"]["name"] for s in specs}
check("all tools registered",
      names == {"pomodoro", "eye_care", "arxiv_briefing", "download_paper",
                "open_papers_folder", "go_to_sleep", "reminder", "task",
                "memory_store", "memory_recall", "memory_forget", "movie_mode",
                "switch_persona"} | ({"run_terminal_command"} if config.ENABLE_TERMINAL else set()),
      str(names))
check("terminal disabled by default",
      config.ENABLE_TERMINAL or ("run_terminal_command" not in names
                                 and "terminal" not in agents.HUD_AGENT_IDS))
check("specs are well-formed", all(s["type"] == "function" and "parameters" in s["function"] for s in specs))
check("unknown tool handled", dispatch("nope", {}) == "Unknown tool: nope")
check("bad args become tool error", dispatch("pomodoro", {"bogus": 1}).startswith("Tool error:"))

# --- terminal guardrails -----------------------------------------------------
if config.ENABLE_TERMINAL:
    print("terminal:")
    out = dispatch("run_terminal_command", {"command": "hostname"})
    check("safe command runs without prompt", out.strip() != "" and "Denied" not in out, out)

    out = dispatch("run_terminal_command", {"command": "shutdown /s /t 0"})
    check("blocked command denied", out.startswith("Denied:"), out)

    real_input = builtins.input
    builtins.input = lambda *a: "n"
    out = dispatch("run_terminal_command", {"command": "git --version"})
    check("declined confirmation respected", out == "The user declined to run this command.", out)

    builtins.input = lambda *a: "y"
    out = dispatch("run_terminal_command", {"command": "git --version"})
    check("approved command runs", "git version" in out, out)
    builtins.input = real_input
else:
    print("terminal: skipped (config.ENABLE_TERMINAL is False)")

# --- pomodoro ----------------------------------------------------------------
print("pomodoro:")
check("status when idle", dispatch("pomodoro", {"action": "status"}) == "No pomodoro is running.")
out = dispatch("pomodoro", {"action": "start", "work_minutes": 0.03, "break_minutes": 0.02})
check("start", out.startswith("Pomodoro started"), out)
check("double start rejected", "already running" in dispatch("pomodoro", {"action": "start"}))
check("status reports work block", "work block" in dispatch("pomodoro", {"action": "status"}))
time.sleep(2.5)  # work block is 1.8s; the work->break transition should announce
check("work-end announced", any("break" in n.lower() for n in notifications), str(notifications))
check("stop", dispatch("pomodoro", {"action": "stop"}) == "Pomodoro stopped.")
check("status after stop", dispatch("pomodoro", {"action": "status"}) == "No pomodoro is running.")

# --- eye care ----------------------------------------------------------------
print("eye_care:")
check("status when idle", "not running" in dispatch("eye_care", {"action": "status"}))
eye_care_mod.INTERVAL_MINUTES = 0.02  # 1.2s for the test
eye_care_mod.LOOK_AWAY_SECONDS = 0.5
notifications.clear()
out = dispatch("eye_care", {"action": "start"})
check("start", out.startswith("Eye-care reminders started"), out)
check("double start rejected", "already running" in dispatch("eye_care", {"action": "start"}))
check("status while running", dispatch("eye_care", {"action": "status"}) == "Eye-care reminders are running.")
time.sleep(2.5)
check("reminder announced", any("Eye care time" in n for n in notifications), str(notifications))
check("look-away end announced", any("Back to it" in n for n in notifications), str(notifications))
check("stop", dispatch("eye_care", {"action": "stop"}) == "Eye-care reminders stopped.")
check("status after stop", "not running" in dispatch("eye_care", {"action": "status"}))

# --- go to sleep -------------------------------------------------------------
print("go_to_sleep:")
import state
state.clear_sleep()
out = dispatch("go_to_sleep", {})
check("returns a sign-off", "idle" in out.lower(), out)
check("sets the sleep flag", state.sleep_requested())
state.clear_sleep()
check("flag clears", not state.sleep_requested())

# --- personas ----------------------------------------------------------------
print("personas:")
persona_events = []
events.subscribe(persona_events.append)
check("starts as default", persona.current() == config.DEFAULT_PERSONA)
out = dispatch("switch_persona", {"persona": "ultron"})
check("switch to ultron", persona.current() == "ultron" and out.startswith("Switched"), out)
check("ultron prompt active", persona.system_prompt() == config.ULTRON_SYSTEM_PROMPT)
check("persona event published", {"type": "persona", "name": "ultron"} in persona_events, str(persona_events))
dispatch("switch_persona", {"persona": "Jarvis"})
check("jarvis maps to orion", persona.current() == "orion")
out = dispatch("switch_persona", {"persona": "hal9000"})
check("unknown persona rejected", persona.current() == "orion" and "Unknown" in out, out)
events.unsubscribe(persona_events.append)
persona.set_persona("orion")

# --- download_paper id validation ---------------------------------------------
print("download_paper:")
import urllib.request
real_urlopen = urllib.request.urlopen


def _no_network(*a, **k):
    raise AssertionError("network touched")


urllib.request.urlopen = _no_network
for bad in ("..\\..\\evil", "../x", "2506.12345/../../x"):
    out = dispatch("download_paper", {"arxiv_id": bad})
    check(f"rejects {bad!r}", "valid arXiv id" in out, out)
urllib.request.urlopen = real_urlopen

# --- chat_turn refreshes the system prompt after a persona switch --------------
print("chat_turn persona refresh:")
import llm
real_stream = llm.stream_reply
replies = iter([
    ("", [{"id": "1", "name": "switch_persona", "arguments": '{"persona": "ultron"}'}]),
    ("Ah, a new age.", []),
])
llm.stream_reply = lambda messages, speaker: next(replies)
msgs = [{"role": "system", "content": config.SYSTEM_PROMPT}, {"role": "user", "content": "Ultron"}]
try:
    llm.chat_turn(msgs)
finally:
    llm.stream_reply = real_stream
    persona.set_persona("orion")
check("system prompt swapped", msgs[0]["content"].startswith(config.ULTRON_SYSTEM_PROMPT))

# ------------------------------------------------------------------------------
print(f"\n{PASS} passed, {len(FAIL)} failed" + (f": {FAIL}" if FAIL else ""))
sys.exit(1 if FAIL else 0)
