"""Pomodoro timer agent: work/break cycles announced out loud via notify()."""

import threading
import time

import events

from . import notify, tool


def _emit(status: str, phase: str = "", minutes: float = 0.0) -> None:
    """Publish a HUD agent event for the pomodoro node."""
    event = {"type": "agent", "id": "pomodoro", "status": status}
    if status == "active":
        event["meta"] = f"{int(minutes)}:{int(minutes % 1 * 60):02d}"
        event["progress"] = 0.0
        event["phase"] = phase
    events.publish(event)

_lock = threading.Lock()
_stop_event: threading.Event | None = None
_state = {"phase": None, "phase_ends": 0.0, "work": 25.0, "break": 5.0}


def _run_cycles(stop: threading.Event, work_min: float, break_min: float):
    while not stop.is_set():
        for phase, minutes, message in (
            ("work", work_min, f"Break's over. Starting a {work_min:g} minute focus block."),
            ("break", break_min, f"Time's up. Take a {break_min:g} minute break."),
        ):
            with _lock:
                _state["phase"] = phase
                _state["phase_ends"] = time.monotonic() + minutes * 60
            _emit("active", phase, minutes)
            if phase == "break":  # the work block just ended
                notify(message)
            if stop.wait(minutes * 60):
                return


@tool(
    "pomodoro",
    "Manage the pomodoro focus timer. Actions: 'start' begins repeating "
    "work/break cycles and announces each transition aloud, 'stop' cancels it, "
    "'status' reports the current phase and time remaining.",
    {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["start", "stop", "status"]},
            "work_minutes": {"type": "number", "description": "Work block length, default 25."},
            "break_minutes": {"type": "number", "description": "Break length, default 5."},
        },
        "required": ["action"],
    },
)
def pomodoro(action: str, work_minutes: float = 25, break_minutes: float = 5) -> str:
    global _stop_event
    if action == "start":
        if _stop_event is not None and not _stop_event.is_set():
            return "A pomodoro is already running. Stop it first to change settings."
        _stop_event = threading.Event()
        with _lock:
            _state.update({"work": work_minutes, "break": break_minutes})
        threading.Thread(
            target=_run_cycles, args=(_stop_event, work_minutes, break_minutes), daemon=True
        ).start()
        return f"Pomodoro started: {work_minutes:g} minutes work, {break_minutes:g} minutes break, repeating."
    if action == "stop":
        if _stop_event is None or _stop_event.is_set():
            return "No pomodoro is running."
        _stop_event.set()
        with _lock:
            _state["phase"] = None
        _emit("idle")
        return "Pomodoro stopped."
    if action == "status":
        with _lock:
            phase, ends = _state["phase"], _state["phase_ends"]
        if _stop_event is None or _stop_event.is_set() or phase is None:
            return "No pomodoro is running."
        remaining = max(0, ends - time.monotonic())
        return f"In a {phase} block with {remaining / 60:.1f} minutes left."
    return f"Unknown action: {action}"
