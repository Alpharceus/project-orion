r"""Phase 4 acceptance — needs llama-server running (.\start-orion-server.ps1).

Drives one real turn (text in -> Gemma -> PocketTTS) through the real
SpeechPlayer while a real WebSocket client records what the HUD bridge emits,
then asserts the Phase 4 acceptance sequence: idle -> listening -> thinking ->
speaking -> idle, with live amplitude during speech and an Orion transcript.
The actual acoustic wake word / mic VAD can't run headless; those are covered
by the unit suite (model load + fallback) — here we simulate wake by setting
LISTENING, exactly the boundary listening.py crosses on a real utterance.
"""

import asyncio
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config
import hud_server
import state
from llm import chat_turn, server_ready
from speech import SpeechPlayer, load_tts

if not server_ready():
    print("llama-server not running — start .\\start-orion-server.ps1 first.")
    sys.exit(2)

URI = f"ws://{config.HUD_HOST}:{config.HUD_PORT}"
collected = []
stop = threading.Event()


def client_thread():
    async def run():
        async with websockets_connect() as ws:
            while not stop.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), 0.3)
                    collected.append(json.loads(raw))
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break

    def websockets_connect():
        import websockets
        return websockets.connect(URI)

    asyncio.run(run())


print("starting HUD bridge + client...")
hud_server.start()
state.set(state.IDLE)
threading.Thread(target=client_thread, daemon=True).start()
time.sleep(0.6)  # connect + receive snapshot

print("loading TTS...")
speaker = SpeechPlayer(*load_tts())

print("driving one turn (text in -> Gemma -> speech)...")
state.set(state.LISTENING)            # what listening.py does on a real utterance
time.sleep(0.1)
messages = [
    {"role": "system", "content": config.SYSTEM_PROMPT},
    {"role": "user", "content": "Say exactly: Phase four is online. Nothing else."},
]
chat_turn(messages, speaker)
speaker.wait_until_done()
state.set(state.IDLE)
time.sleep(0.4)
stop.set()
time.sleep(0.4)

# --- analyze ------------------------------------------------------------------
PASS, FAIL = 0, []


def check(name, condition, detail=""):
    global PASS
    if condition:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL {name}  {detail}")


states = [e["value"] for e in collected if e.get("type") == "state"]
amps = [e["value"] for e in collected if e.get("type") == "amplitude"]
transcripts = [e for e in collected if e.get("type") == "transcript" and e.get("role") == "orion"]


def is_subsequence(sub, seq):
    it = iter(seq)
    return all(item in it for item in sub)


print("\nbridge events:")
print(f"  states seen: {states}")
check("idle->listening->thinking->speaking->idle in order",
      is_subsequence(["idle", "listening", "thinking", "speaking", "idle"], states), str(states))
check("amplitude emitted during speech", len(amps) > 5, f"{len(amps)} amplitude events")
check("amplitude rose above zero", any(a > 0.05 for a in amps), f"max={max(amps) if amps else 0}")
check("amplitude returned to zero at end", amps[-1] == 0.0 if amps else False, str(amps[-3:]))
check("orion transcript broadcast", len(transcripts) >= 1, str(transcripts))
if transcripts:
    print(f"  orion said: {transcripts[-1]['text']!r}")

print(f"\n{PASS} passed, {len(FAIL)} failed" + (f": {FAIL}" if FAIL else ""))
sys.exit(1 if FAIL else 0)
