"""Active persona state: which character Orion is currently playing.

Top-level state module (like memory.py). The system prompt (llm.py / orion.py)
and the TTS voice (speech.py) both read from here; the switch_persona tool
(agents/persona_switch.py) writes to it.
"""

import config
import events

_current = config.DEFAULT_PERSONA


def current() -> str:
    return _current


def names() -> list[str]:
    return list(config.PERSONAS)


def set_persona(name: str) -> bool:
    """Switch persona. False for unknown names; publishes an event on change."""
    global _current
    if name not in config.PERSONAS:
        return False
    if name != _current:
        _current = name
        events.publish({"type": "persona", "name": name})
    return True


def system_prompt() -> str:
    return config.PERSONAS[_current]["prompt"]
