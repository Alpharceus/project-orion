r"""End-to-end Phase 2 test: text prompts -> Gemma (llama-server) -> tool calls.

Uses orion.py's real chat_turn dispatch loop, just with text instead of mic
audio and no TTS. Requires llama-server running on :8080.

Run:  orion_env\Scripts\python.exe tests\test_e2e.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config
import llm
from agents import dispatch as real_dispatch

PASS, FAIL = 0, []
calls = []  # (tool_name, args) actually dispatched


def spy_dispatch(name, args):
    calls.append((name, args))
    return real_dispatch(name, args)


llm.dispatch = spy_dispatch


def check(name, condition, detail=""):
    global PASS
    if condition:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL {name}  {detail}")


messages = [{"role": "system", "content": config.SYSTEM_PROMPT}]


def turn(user_text):
    calls.clear()
    print(f"\n>>> {user_text}")
    messages.append({"role": "user", "content": user_text})
    reply = llm.chat_turn(messages, speaker=None)
    print()  # chat_turn streams without trailing newline
    return reply


# 1. plain chat — no tool should fire
reply = turn("Hey Orion, how's it going?")
check("chat turn produces a reply", bool(reply.strip()))
check("chat turn uses no tools", not calls, str(calls))

# 2. pomodoro with custom durations
reply = turn("Start a pomodoro with 30 minute work blocks and 10 minute breaks.")
pomo = [c for c in calls if c[0] == "pomodoro"]
check("pomodoro tool called", bool(pomo), str(calls))
if pomo:
    args = pomo[0][1]
    check("action=start", args.get("action") == "start", str(args))
    check("custom durations passed", args.get("work_minutes") == 30 and args.get("break_minutes") == 10, str(args))

reply = turn("How much time is left on my pomodoro?")
check("status call", ("pomodoro" in [c[0] for c in calls]
                      and any(c[1].get("action") == "status" for c in calls if c[0] == "pomodoro")), str(calls))
check("reply mentions time", any(w in reply.lower() for w in ("minute", "min")), reply)

reply = turn("Stop the pomodoro.")
check("stop call", any(c[0] == "pomodoro" and c[1].get("action") == "stop" for c in calls), str(calls))

# 3. eye care
reply = turn("Turn on the twenty twenty twenty eye reminders.")
check("eye_care start", any(c[0] == "eye_care" and c[1].get("action") == "start" for c in calls), str(calls))
reply = turn("Actually turn the eye reminders off.")
check("eye_care stop", any(c[0] == "eye_care" and c[1].get("action") == "stop" for c in calls), str(calls))

# 4. terminal (safe command, result must flow back into the answer)
if config.ENABLE_TERMINAL:
    reply = turn("What's my computer's hostname? Check it in the terminal.")
    term = [c for c in calls if c[0] == "run_terminal_command"]
    check("terminal tool called", bool(term), str(calls))
    import socket
    check("real hostname in spoken reply", socket.gethostname().lower() in reply.lower(), reply)
else:
    print("terminal e2e skipped (config.ENABLE_TERMINAL is False)")

print(f"\n{PASS} passed, {len(FAIL)} failed" + (f": {FAIL}" if FAIL else ""))
sys.exit(1 if FAIL else 0)
