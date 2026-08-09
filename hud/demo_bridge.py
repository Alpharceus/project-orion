r"""Drive the Orion HUD without the full assistant.

Runs the real Phase 4 WebSocket bridge (src/hud_server.py) and emits a looping
demo sequence of state / agent / transcript / amplitude events, so the HUD can
be developed and demoed without llama-server or a microphone. Launch the HUD
(`npm run tauri dev` from hud/, or the built exe) while this is running.

  orion_env\Scripts\python.exe hud\demo_bridge.py
"""

import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import events
import hud_server
import state
import telemetry
from agents import publish_agents_baseline

# Print anything the HUD sends back (e.g. set_interactive) — confirms the
# bidirectional link is live.
events.subscribe(lambda e: print("HUD ->", e) if e.get("type") == "command" else None)

hud_server.start()
telemetry.start()  # live CPU/GPU/RAM + weather into the telemetry strip
events.publish({"type": "ticker", "titles": [
    "GKP codes  arXiv:2606.xxxxx", "CV-MBQC fault-tolerance threshold",
    "SiN photonics heterogeneous integration", "single-photon source g2(0) record",
]})
print("bridge up on ws://127.0.0.1:8765 — launch the HUD now. Ctrl+C to stop.")

# Populate the full agent row (all dim), then light a couple up.
publish_agents_baseline()
events.publish({"type": "agent", "id": "pomodoro", "status": "active", "meta": "24:13", "progress": 0.62})
events.publish({"type": "agent", "id": "eye_care", "status": "active", "meta": "14:02", "progress": 0.30})
events.publish({"type": "transcript", "role": "user", "text": "hey orion, what's on my plate?"})

try:
    while True:
        state.set(state.LISTENING)
        time.sleep(2.5)
        state.set(state.THINKING)
        time.sleep(2.0)
        events.publish({"type": "transcript", "role": "orion",
                        "text": "Two focus blocks queued, and your briefing lands at nine."})
        state.set(state.SPEAKING)
        for i in range(70):  # fake speech envelope: bursts + gaps, eased
            v = max(0.0, math.sin(i * 0.5) ** 2 * (0.6 + 0.4 * math.sin(i * 0.13)))
            events.publish({"type": "amplitude", "value": round(v, 3)})
            time.sleep(0.05)
        events.publish({"type": "amplitude", "value": 0.0})
        state.set(state.IDLE)
        time.sleep(3.0)
except KeyboardInterrupt:
    print("\nbye")
