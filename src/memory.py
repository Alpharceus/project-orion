"""Orion's persistent, local memory (data/memory.json). Fully on-device.

Three sections:
  - facts:        durable things Orion knows about the user. Loaded into the
                  system prompt at startup (preamble) and editable as model tools.
                  This is where a pasted "LLM memory" lives — one fact per item.
  - seen_arxiv:   arXiv ids already surfaced in a briefing, so the same paper is
                  never read out twice (dedup ledger, capped).
  - last_briefing: the most recent briefing's papers (id/title/pdf), so the user
                  can say "download the GKP one" and it resolves to a real id.
"""

import json
import threading
import uuid
from datetime import datetime

import config
import events

STORE = config.DATA_DIR / "memory.json"
_lock = threading.Lock()
_data = {"facts": {}, "seen_arxiv": [], "last_briefing": []}


# --- persistence --------------------------------------------------------------
def _load() -> None:
    if STORE.exists():
        try:
            loaded = json.loads(STORE.read_text(encoding="utf-8"))
            _data["facts"] = loaded.get("facts", {})
            _data["seen_arxiv"] = loaded.get("seen_arxiv", [])
            _data["last_briefing"] = loaded.get("last_briefing", [])
        except Exception as e:
            print(f"[memory] could not load store: {e}")


def _save() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_data, indent=2), encoding="utf-8")
    tmp.replace(STORE)


def start() -> None:
    _load()
    emit_node()


def emit_node() -> None:
    """Publish the HUD memory node with the current fact count."""
    n = len(all_facts())
    events.publish({"type": "agent", "id": "memory",
                    "status": "active" if n else "idle",
                    "meta": f"{n} facts" if n else None})


# --- facts (long-term memory) -------------------------------------------------
def remember(text: str) -> dict:
    text = text.strip()
    fact = {"id": uuid.uuid4().hex[:8], "text": text, "created": datetime.now().isoformat(timespec="seconds")}
    with _lock:
        _data["facts"][fact["id"]] = fact
        # enforce the cap, dropping the oldest
        if len(_data["facts"]) > config.MEMORY_MAX_FACTS:
            oldest = sorted(_data["facts"].values(), key=lambda f: f.get("created", ""))[0]
            _data["facts"].pop(oldest["id"], None)
    _save()
    return fact


def remember_many(texts: list) -> int:
    """Bulk-add facts (e.g. a pasted memory). Skips exact duplicates."""
    existing = {f["text"].strip().lower() for f in all_facts()}
    n = 0
    for t in texts:
        t = (t or "").strip()
        if t and t.lower() not in existing:
            remember(t)
            existing.add(t.lower())
            n += 1
    return n


def all_facts() -> list:
    with _lock:
        return sorted(_data["facts"].values(), key=lambda f: f.get("created", ""))


def recall(query: str) -> list:
    """Return facts whose text contains any word of the query (case-insensitive)."""
    words = [w for w in (query or "").lower().split() if len(w) > 2]
    if not words:
        return all_facts()
    return [f for f in all_facts() if any(w in f["text"].lower() for w in words)]


def forget(query: str) -> int:
    q = (query or "").strip().lower()
    with _lock:
        hits = [f["id"] for f in _data["facts"].values()
                if q and (q == "all" or q in f["text"].lower())]
        for fid in hits:
            _data["facts"].pop(fid, None)
    if hits:
        _save()
    return len(hits)


def preamble() -> str:
    """The facts formatted for the system prompt (empty string if none)."""
    facts = all_facts()
    if not facts:
        return ""
    lines = "\n".join(f"- {f['text']}" for f in facts)
    return f"\n\nWhat you remember about the user (use it naturally; don't recite it):\n{lines}"


# --- arXiv dedup ledger -------------------------------------------------------
def is_seen(arxiv_id: str) -> bool:
    with _lock:
        return arxiv_id in _data["seen_arxiv"]


def mark_seen(arxiv_ids: list) -> None:
    with _lock:
        seen = _data["seen_arxiv"]
        for aid in arxiv_ids:
            if aid not in seen:
                seen.append(aid)
        if len(seen) > config.SEEN_ARXIV_CAP:
            _data["seen_arxiv"] = seen[-config.SEEN_ARXIV_CAP:]
    _save()


def set_last_briefing(papers: list) -> None:
    """Store [{id, title, pdf}, ...] from the latest briefing for downloads."""
    with _lock:
        _data["last_briefing"] = [{"id": p["id"], "title": p["title"], "pdf": p.get("pdf", "")} for p in papers]
    _save()


def last_briefing() -> list:
    with _lock:
        return list(_data["last_briefing"])
