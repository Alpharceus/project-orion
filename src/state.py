"""Orion's formal runtime state machine.

Four explicit states drive both the assistant's behavior and the HUD visuals:

    idle ──wake──▶ listening ──speech ends──▶ thinking ──reply starts──▶ speaking
     ▲                                                                       │
     └───────────────────────────── reply done ─────────────────────────────┘

Modules set state at their natural boundaries (listening.py on record start,
llm.py on request start, speech.py on first audio chunk / on drain, orion.py
back to idle). Every transition publishes a {"type":"state","value":...} event
so the HUD bridge can broadcast it. Reading/writing state is thread-safe.
"""

import threading

import events

IDLE = "idle"
LISTENING = "listening"
THINKING = "thinking"
SPEAKING = "speaking"

_state = IDLE
_lock = threading.Lock()

# Set by the go_to_sleep tool when the user asks to end the conversation; the
# main loop checks it after a turn to drop the follow-up window immediately.
_sleep_requested = threading.Event()

# True while a conversation is in progress (from wake until the follow-up window
# closes). The speech player uses it so that draining mid-conversation flows
# straight into the next listen instead of flashing back to idle — only proactive
# announcements (fired while dormant) return to idle on their own.
_in_conversation = threading.Event()


def begin_conversation() -> None:
    _in_conversation.set()


def end_conversation() -> None:
    _in_conversation.clear()


def in_conversation() -> bool:
    return _in_conversation.is_set()


def request_sleep() -> None:
    _sleep_requested.set()


def sleep_requested() -> bool:
    return _sleep_requested.is_set()


def clear_sleep() -> None:
    _sleep_requested.clear()


def get() -> str:
    with _lock:
        return _state


def set(value: str) -> None:
    """Transition to a new state and emit a state event (no-op if unchanged)."""
    global _state
    with _lock:
        if value == _state:
            return
        _state = value
    events.publish({"type": "state", "value": value})
