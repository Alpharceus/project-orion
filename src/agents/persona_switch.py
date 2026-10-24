"""Model tool for switching Orion's persona (system prompt + TTS voice).

The state module is the top-level src/persona.py (imported late inside the
function, because the tool parameter is also named `persona`).
"""

from . import tool

_ALIASES = {"jarvis": "orion"}


@tool(
    "switch_persona",
    "Switch which character you are. Use 'ultron' when the user asks for Ultron "
    "or Ultron mode; use 'orion' when they ask for Orion or Jarvis back.",
    {"type": "object",
     "properties": {"persona": {"type": "string", "enum": ["orion", "ultron"],
                                "description": "The persona to become."}},
     "required": ["persona"]},
)
def switch_persona(persona: str) -> str:
    # The parameter name is fixed by the tool schema, so reach the module via alias.
    import persona as persona_state
    name = str(persona).strip().lower()
    name = _ALIASES.get(name, name)
    if name not in persona_state.names():
        return f"Unknown persona '{persona}'. Available: {', '.join(persona_state.names())}."
    if name == persona_state.current():
        return f"Already {name}; carry on in character."
    persona_state.set_persona(name)
    return f"Switched to {name}. Reply now in the character of {name}."
