"""Model tools for Orion's long-term memory. Wraps the src/memory.py store.

Note: `import memory` here resolves to the top-level src/memory.py (the store),
not this package module — they share a short name but live in different packages.
"""

import memory as mem

from . import tool


@tool(
    "memory_store",
    "Save a durable fact or preference about the user to long-term memory (it "
    "persists across sessions and loads at startup). Use when the user shares "
    "something worth remembering — 'remember that ...', 'my X is Y', a routine, a "
    "preference. Keep each fact a single self-contained sentence.",
    {"type": "object", "properties": {"text": {"type": "string", "description": "The fact to remember."}},
     "required": ["text"]},
)
def memory_store(text: str) -> str:
    mem.remember(text)
    mem.emit_node()
    return f"Saved to memory: {text}"


@tool(
    "memory_recall",
    "Look up what you remember about the user from long-term memory. Optional "
    "query to filter to relevant facts; omit it to list everything.",
    {"type": "object", "properties": {"query": {"type": "string", "description": "Words to filter by."}}},
)
def memory_recall(query: str = "") -> str:
    facts = mem.recall(query) if query else mem.all_facts()
    if not facts:
        return "I don't have anything in memory about that."
    return "I remember: " + "; ".join(f["text"] for f in facts[:10])


@tool(
    "memory_forget",
    "Forget stored memory items matching a phrase (or 'all'). Only call this when "
    "the user explicitly asks you to forget something.",
    {"type": "object", "properties": {"query": {"type": "string", "description": "Phrase to match, or 'all'."}},
     "required": ["query"]},
)
def memory_forget(query: str) -> str:
    n = mem.forget(query)
    mem.emit_node()
    return f"Forgot {n} item{'s' if n != 1 else ''}." if n else "Nothing in memory matched that."
