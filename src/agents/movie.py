"""Movie mode — ambient idle animations (ported from Project Umbra).

Orion overlays a slow, see-through procedural animation on the portrait monitor,
below the HUD. The user picks one of ten by number ("animation 3") or toggles the
whole thing on/off ("movie mode", "stop the animation"). State is published to the
HUD as a `movie` event and persisted so it survives a restart.

This module owns no rendering — that lives in the HUD (static/umbra + MovieMode.svelte).
Here we just track which animation is active and tell the HUD.
"""

import json
import threading

import config
import events

from . import tool

STORE = config.DATA_DIR / "movie.json"
_lock = threading.Lock()

# The ten animations, in the order the HUD's loader exposes them. Index 0-based
# internally; the user refers to them 1-based ("animation 1" -> ANIMATIONS[0]).
ANIMATIONS = [
    "Cosmic Drift", "Dust Motes", "Abyssal Fluid", "Volumetric Smoke",
    "Glacial Nebula", "Macro Rain", "Digital Rainfall", "The Slow Matrix",
    "Strata Shift", "Solar Corona",
]

# index is 0-based; screens is "others" (every monitor except the main one) or
# "all" (every monitor, including the main) — the HUD applies it.
_state = {"on": False, "index": 0, "screens": "others"}


def _load() -> None:
    if STORE.exists():
        try:
            data = json.loads(STORE.read_text(encoding="utf-8"))
            _state["on"] = bool(data.get("on", False))
            _state["index"] = max(0, min(len(ANIMATIONS) - 1, int(data.get("index", 0))))
            _state["screens"] = "all" if data.get("screens") == "all" else "others"
        except Exception as e:
            print(f"[movie] could not load store: {e}")


def _save() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_state, indent=2), encoding="utf-8")
    tmp.replace(STORE)


def _emit_hud() -> None:
    name = ANIMATIONS[_state["index"]]
    # Drive the blackout animation (the HUD opens a window per target monitor).
    events.publish({
        "type": "movie",
        "on": _state["on"],
        "index": _state["index"],
        "name": name,
        "screens": _state["screens"],
    })
    # And light the movie node in the HUD agent row (active=blue when running).
    events.publish({
        "type": "agent",
        "id": "movie",
        "status": "active" if _state["on"] else "idle",
        "meta": name if _state["on"] else None,
    })


def start() -> None:
    """Load persisted state and re-emit it so the HUD restores on connect."""
    _load()
    _emit_hud()


def set_animation(index: int, screens: str | None = None) -> str:
    """Select an animation by 0-based index; turns movie mode on."""
    with _lock:
        _state["index"] = max(0, min(len(ANIMATIONS) - 1, index))
        _state["on"] = True
        if screens in ("others", "all"):
            _state["screens"] = screens
    _save()
    _emit_hud()
    return ANIMATIONS[_state["index"]]


def set_on(on: bool, screens: str | None = None) -> None:
    with _lock:
        _state["on"] = bool(on)
        if screens in ("others", "all"):
            _state["screens"] = screens
    _save()
    _emit_hud()


@tool(
    "movie_mode",
    "Control 'movie mode' — a blackout screensaver that fills the user's other "
    "monitors with black and a slow ambient animation, so they don't throw light "
    "while watching something on the main screen. Actions: 'on' starts it "
    "(resumes the last animation), 'off' stops it, 'set' switches animation. For "
    "'set', pass `number` 1-10: 1 Cosmic Drift (drifting starfield), 2 Dust "
    "Motes, 3 Abyssal Fluid (slow swirling fluid), 4 Volumetric Smoke, 5 Glacial "
    "Nebula, 6 Macro Rain, 7 Digital Rainfall (falling glyphs), 8 The Slow Matrix "
    "(data grid), 9 Strata Shift (sliding bands), 10 Solar Corona (warm edge "
    "glow). Use 'set' for 'movie mode animation 3' or 'change the animation to 1'. "
    "By default it blacks out every monitor EXCEPT the main one; pass "
    "screens='all' to include the main monitor too ('black out all my screens'), "
    "or screens='others' for the default.",
    {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["on", "off", "set"]},
            "number": {"type": "integer", "description": "Animation 1-10 (for 'set')."},
            "screens": {
                "type": "string", "enum": ["others", "all"],
                "description": "'others' (default) = every monitor except the main; 'all' = every monitor.",
            },
        },
        "required": ["action"],
    },
)
def movie_mode(action, number=None, screens=None):
    if action == "off":
        set_on(False)
        return "Movie mode off."
    if action == "on":
        set_on(True, screens=screens)
        where = "all your screens" if _state["screens"] == "all" else "your other screens"
        return f"Movie mode on across {where} — {ANIMATIONS[_state['index']]}."
    if action == "set":
        if number is None:
            return "Which animation? Say a number from 1 to 10."
        if not (1 <= int(number) <= len(ANIMATIONS)):
            return f"Pick an animation between 1 and {len(ANIMATIONS)}."
        name = set_animation(int(number) - 1, screens=screens)
        return f"Switched to animation {int(number)}, {name}."
    return f"Unknown action: {action}"
