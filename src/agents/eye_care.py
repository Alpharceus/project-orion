"""20/20/20 eye-care agent: every 20 minutes, look 20 feet away for 20 seconds."""

import threading

import events

from . import notify, tool

INTERVAL_MINUTES = 20
LOOK_AWAY_SECONDS = 20

_stop_event: threading.Event | None = None


def _emit(status: str) -> None:
    """Publish a HUD agent event for the eye-care node."""
    event = {"type": "agent", "id": "eye_care", "status": status}
    if status == "active":
        event["meta"] = f"{int(INTERVAL_MINUTES)}:00"
        event["progress"] = 0.0
    events.publish(event)


def _reminder_loop(stop: threading.Event):
    while True:
        if stop.wait(INTERVAL_MINUTES * 60):
            return
        notify("Eye care time. Look at something twenty feet away for twenty seconds.")
        if stop.wait(LOOK_AWAY_SECONDS):
            return
        notify("Twenty seconds done. Back to it.")


@tool(
    "eye_care",
    "Manage the 20/20/20 eye-strain reminder: every 20 minutes, a spoken prompt "
    "to look at something 20 feet away for 20 seconds. Actions: 'start', 'stop', 'status'.",
    {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["start", "stop", "status"]},
        },
        "required": ["action"],
    },
)
def eye_care(action: str) -> str:
    global _stop_event
    if action == "start":
        if _stop_event is not None and not _stop_event.is_set():
            return "Eye-care reminders are already running."
        _stop_event = threading.Event()
        threading.Thread(target=_reminder_loop, args=(_stop_event,), daemon=True).start()
        _emit("active")
        return "Eye-care reminders started. First one in twenty minutes."
    if action == "stop":
        if _stop_event is None or _stop_event.is_set():
            return "Eye-care reminders are not running."
        _stop_event.set()
        _emit("idle")
        return "Eye-care reminders stopped."
    if action == "status":
        running = _stop_event is not None and not _stop_event.is_set()
        return "Eye-care reminders are running." if running else "Eye-care reminders are not running."
    return f"Unknown action: {action}"
