"""Orion's tool registry.

Each agent module registers its functions with the @tool decorator; orion.py
exposes them to the model via tool_specs() and routes calls through dispatch().
Agents that fire on timers (pomodoro, eye care) announce themselves through
notify(), which orion.py wires to the speaker at startup.
"""

import config
import events

REGISTRY = {}  # name -> {"spec": OpenAI tool spec, "func": callable}

_notifier = print  # replaced by orion.py with a print-and-speak callback

# Agents shown as nodes in the HUD's bottom row (reminders + tasks have their own
# panels, so they're not here). The HUD also hardcodes this set for guaranteed
# visibility; these baseline events just set initial idle status.
HUD_AGENT_IDS = ["pomodoro", "eye_care", "terminal", "arxiv_briefing", "memory", "movie"]
if not config.ENABLE_TERMINAL:
    HUD_AGENT_IDS.remove("terminal")


def publish_agents_baseline() -> None:
    """Emit an idle node for each HUD agent so the row is always populated."""
    for agent_id in HUD_AGENT_IDS:
        events.publish({"type": "agent", "id": agent_id, "status": "idle"})


def tool(name: str, description: str, parameters: dict | None = None):
    """Register the decorated function as a model-callable tool."""
    def decorator(fn):
        REGISTRY[name] = {
            "spec": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters or {"type": "object", "properties": {}},
                },
            },
            "func": fn,
        }
        return fn
    return decorator


def tool_specs() -> list:
    return [entry["spec"] for entry in REGISTRY.values()]


def dispatch(name: str, args: dict) -> str:
    if name not in REGISTRY:
        return f"Unknown tool: {name}"
    try:
        return str(REGISTRY[name]["func"](**args))
    except Exception as e:
        return f"Tool error: {e}"


def set_notifier(fn) -> None:
    global _notifier
    _notifier = fn


def notify(text: str) -> None:
    _notifier(text)


from . import pomodoro, eye_care, arxiv_briefing, sleep, reminders, tasks, memory, movie, persona_switch  # noqa: E402,F401  (importing registers their tools)
if config.ENABLE_TERMINAL:  # off by default: unbounded shell access (see config.py)
    from . import terminal  # noqa: E402,F401
