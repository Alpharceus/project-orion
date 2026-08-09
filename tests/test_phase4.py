r"""Unit + integration tests for Phase 4 (state machine, event hub, HUD bridge,
amplitude tap, wake fallback) — no LLM or real audio needed.

Run from the project root:  orion_env\Scripts\python.exe tests\test_phase4.py
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np
import websockets

import config
import events
import hud_server
import state

PASS, FAIL = 0, []


def check(name: str, condition: bool, detail: str = ""):
    global PASS
    if condition:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL {name}  {detail}")


# --- event hub ----------------------------------------------------------------
print("event hub:")
seen = []
sub = seen.append
events.subscribe(sub)
events.publish({"type": "test", "n": 1})
check("subscriber receives event", seen == [{"type": "test", "n": 1}], str(seen))
events.unsubscribe(sub)
events.publish({"type": "test", "n": 2})
check("unsubscribe stops delivery", len(seen) == 1, str(seen))


def _boom(_):
    raise RuntimeError("broken subscriber")


events.subscribe(_boom)
ok_seen = []
events.subscribe(ok_seen.append)
events.publish({"type": "test", "n": 3})
check("broken subscriber doesn't break producer", ok_seen == [{"type": "test", "n": 3}])
events.unsubscribe(_boom)
events.unsubscribe(ok_seen.append) if ok_seen.append in [] else None  # no-op guard

# --- state machine ------------------------------------------------------------
print("state machine:")
state_events = []
events.subscribe(lambda e: state_events.append(e) if e.get("type") == "state" else None)
state.set(state.IDLE)  # already idle at import
check("starts idle", state.get() == "idle")
check("no-op transition emits nothing", state_events == [], str(state_events))
state.set(state.LISTENING)
check("transition updates get()", state.get() == "listening")
check("transition emits event", state_events[-1] == {"type": "state", "value": "listening"})
state.set(state.LISTENING)
check("repeat transition is a no-op", len(state_events) == 1, str(state_events))
state.set(state.THINKING)
state.set(state.SPEAKING)
state.set(state.IDLE)
check("full cycle emits 4 events",
      [e["value"] for e in state_events] == ["listening", "thinking", "speaking", "idle"],
      str([e["value"] for e in state_events]))

# --- amplitude tap (no real TTS) ----------------------------------------------
print("amplitude tap:")
import speech


class _FakeTTS:
    sample_rate = 24000


player = speech.SpeechPlayer.__new__(speech.SpeechPlayer)  # skip __init__/thread
player.tts = _FakeTTS()
player._amp = 0.0
amps = []
events.subscribe(lambda e: amps.append(e["value"]) if e.get("type") == "amplitude" else None)
player._emit_amplitude(np.full(480, 0.18, dtype=np.float32))  # ~reference RMS over one 20ms window
check("amplitude event emitted", len(amps) >= 1, str(amps))
check("amplitude in 0..1", all(0.0 <= a <= 1.0 for a in amps), str(amps))
check("loud input pushes envelope up", amps[-1] > 0.0, str(amps))
loud = []
events.subscribe(lambda e: loud.append(e["value"]) if e.get("type") == "amplitude" else None)
for _ in range(40):  # sustained loud input should approach 1.0 as it eases up
    player._emit_amplitude(np.full(480, 0.18, dtype=np.float32))
check("sustained input eases toward 1.0", loud[-1] > 0.6, str(loud[-1]))

# --- wake word fallback -------------------------------------------------------
print("wake word:")
import wakeword

orig_model = config.WAKE_MODEL
config.WAKE_MODEL = "this_model_does_not_exist_xyz"
try:
    wakeword.WakeWord()
    check("bogus model raises WakeWordUnavailable", False)
except wakeword.WakeWordUnavailable:
    check("bogus model raises WakeWordUnavailable", True)
except Exception as e:
    check("bogus model raises WakeWordUnavailable", False, f"got {type(e).__name__}: {e}")
finally:
    config.WAKE_MODEL = orig_model
check("config has wake knobs",
      all(hasattr(config, k) for k in ("WAKE_ENABLED", "WAKE_WORD", "WAKE_THRESHOLD")))

# --- HUD WebSocket bridge (real client) ---------------------------------------
print("HUD bridge:")
state.set(state.IDLE)
hud_server.start()
URI = f"ws://{config.HUD_HOST}:{config.HUD_PORT}"


async def recv_json(ws, timeout=2.0):
    import json
    raw = await asyncio.wait_for(ws.recv(), timeout)
    return json.loads(raw)


async def ws_tests():
    import json
    # wait for the server to bind
    for _ in range(50):
        try:
            async with websockets.connect(URI):
                break
        except OSError:
            await asyncio.sleep(0.1)

    # 1) snapshot on connect = current state (idle)
    async with websockets.connect(URI) as ws:
        snap = await recv_json(ws)
        check("connect snapshot is state idle", snap == {"type": "state", "value": "idle"}, str(snap))

        # 2) a state transition is broadcast live
        state.set(state.LISTENING)
        evt = await recv_json(ws)
        check("live state broadcast", evt == {"type": "state", "value": "listening"}, str(evt))

        # 3) an inbound command is republished onto the hub
        cmds = []
        events.subscribe(lambda e: cmds.append(e) if e.get("type") == "command" else None)
        await ws.send(json.dumps({"type": "command", "name": "dismiss"}))
        await asyncio.sleep(0.2)
        check("inbound command reaches hub", {"type": "command", "name": "dismiss"} in cmds, str(cmds))

    # 4) agent events are cached and appear in a later client's snapshot
    events.publish({"type": "agent", "id": "pomodoro", "status": "active", "meta": "25:00", "progress": 0.0})
    await asyncio.sleep(0.2)
    async with websockets.connect(URI) as ws:
        msgs = [await recv_json(ws)]
        msgs.append(await recv_json(ws))
        has_state = any(m.get("type") == "state" for m in msgs)
        has_agent = any(m.get("type") == "agent" and m.get("id") == "pomodoro" for m in msgs)
        check("snapshot includes cached active agent", has_state and has_agent, str(msgs))

    # 5) an idle agent persists as a (dim) node — status changes, not eviction
    events.publish({"type": "agent", "id": "pomodoro", "status": "idle"})
    await asyncio.sleep(0.2)
    async with websockets.connect(URI) as ws:
        msgs = [await recv_json(ws), await recv_json(ws)]
        agent_msg = next((m for m in msgs if m.get("type") == "agent" and m.get("id") == "pomodoro"), None)
        check("idle agent persists in snapshot with idle status",
              agent_msg is not None and agent_msg.get("status") == "idle", str(msgs))


asyncio.run(ws_tests())

# ------------------------------------------------------------------------------
print(f"\n{PASS} passed, {len(FAIL)} failed" + (f": {FAIL}" if FAIL else ""))
sys.exit(1 if FAIL else 0)
