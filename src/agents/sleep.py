"""Let the user dismiss Orion mid-conversation, back to wake-word-only idle."""

import state

from . import tool


@tool(
    "go_to_sleep",
    "Call this when the user wants to end the conversation and send you back to "
    "sleep / idle — e.g. 'go to sleep', 'go idle', 'that's all', 'never mind', "
    "'dismiss', 'goodbye', 'nothing else' (including 'go to sleep but keep the "
    "movie on'). After this, the user must say the wake word again to talk. This "
    "does NOT stop movie mode / the screensaver — leave that running; only the "
    "movie_mode tool turns it off. Give a brief sign-off in your spoken reply.",
    {"type": "object", "properties": {}},
)
def go_to_sleep() -> str:
    state.request_sleep()
    return "Going idle. Say the wake word when you need me."
