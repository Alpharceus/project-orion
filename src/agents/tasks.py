"""Task manager — a persisted to-do list with optional due dates + priorities.

Add / list / complete / remove tasks by voice. A task with a due time gets an
automatic reminder (via the reminder engine) so Orion speaks up when it's due;
completing or removing the task clears that reminder. Persisted to JSON so tasks
survive restarts.
"""

import json
import threading
import uuid

import config
import events

from . import reminders, tool

STORE = config.DATA_DIR / "tasks.json"
_lock = threading.Lock()
_tasks: dict = {}  # id -> task dict

_PRIORITY_RANK = {"high": 0, "normal": 1, "low": 2}


def _load() -> None:
    if STORE.exists():
        try:
            _tasks.update(json.loads(STORE.read_text(encoding="utf-8")).get("tasks", {}))
        except Exception as e:
            print(f"[tasks] could not load store: {e}")


def _save() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"tasks": _tasks}, indent=2), encoding="utf-8")
    tmp.replace(STORE)


def open_tasks() -> list:
    with _lock:
        items = [t for t in _tasks.values() if not t["done"]]
    return sorted(items, key=lambda t: (_PRIORITY_RANK.get(t["priority"], 1), t.get("due") or "9999"))


def add(title, due_time=None, due_date=None, priority="normal") -> dict:
    tid = uuid.uuid4().hex[:8]
    task = {"id": tid, "title": title.strip(), "priority": priority,
            "due": None, "reminder_id": None, "done": False}
    if due_time:
        rem = reminders.add(f"Task due: {title.strip()}", time=due_time, date=due_date)
        task["due"] = rem["next_fire"]
        task["reminder_id"] = rem["id"]
    with _lock:
        _tasks[tid] = task
    _save()
    _emit_hud()
    return task


def _clear_reminder(task: dict) -> None:
    if task.get("reminder_id"):
        reminders.cancel_id(task["reminder_id"])


def complete(which: str) -> int:
    return _resolve(which, done=True)


def remove(which: str) -> int:
    return _resolve(which, done=None)


def _resolve(which: str, done) -> int:
    """Complete (done=True) or remove (done=None) tasks matching `which`."""
    q = (which or "").strip().lower()
    n = 0
    with _lock:
        matches = [t for t in _tasks.values()
                   if not t["done"] and q and (q == "all" or q in t["title"].lower())]
        for t in matches:
            _clear_reminder(t)
            if done is None:
                _tasks.pop(t["id"], None)
            else:
                t["done"] = True
            n += 1
    if n:
        _save()
        _emit_hud()
    return n


def _due_label(t: dict) -> str:
    if not t.get("due"):
        return ""
    from datetime import datetime
    try:
        return datetime.fromisoformat(t["due"]).strftime("%a %I:%M %p").replace(" 0", " ").strip()
    except ValueError:
        return ""


def _emit_hud() -> None:
    """Publish the open-tasks list (priority-sorted) for the HUD panel."""
    items = [{"title": t["title"], "priority": t["priority"], "due": _due_label(t)}
             for t in open_tasks()]
    events.publish({"type": "tasks_list", "items": items})


def start() -> None:
    _load()
    _emit_hud()


def _format(t: dict) -> str:
    tag = "" if t["priority"] == "normal" else f" [{t['priority']}]"
    due = ""
    if t.get("due"):
        from datetime import datetime
        try:
            due = " (due " + datetime.fromisoformat(t["due"]).strftime("%a %I:%M %p").replace(" 0", " ") + ")"
        except ValueError:
            due = ""
    return f"{t['title']}{tag}{due}"


@tool(
    "task",
    "Manage the user's to-do list. Actions: 'add' a task (optionally with a due "
    "time as 24-hour HH:MM and date YYYY-MM-DD — a due time auto-creates a "
    "reminder — and priority low/normal/high), 'list' open tasks, 'complete' a "
    "task, 'remove' a task. Match tasks by a word from their title (or 'all').",
    {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["add", "list", "complete", "remove"]},
            "title": {"type": "string", "description": "The task text (for 'add')."},
            "due_time": {"type": "string", "description": "24-hour HH:MM the task is due."},
            "due_date": {"type": "string", "description": "YYYY-MM-DD the task is due."},
            "priority": {"type": "string", "enum": ["low", "normal", "high"]},
            "which": {"type": "string", "description": "For complete/remove: a word from the title, or 'all'."},
        },
        "required": ["action"],
    },
)
def task(action, title=None, due_time=None, due_date=None, priority="normal", which=None):
    if action == "add":
        if not title:
            return "What's the task?"
        t = add(title, due_time=due_time, due_date=due_date, priority=priority)
        return f"Added: {_format(t)}."
    if action == "list":
        tasks = open_tasks()
        if not tasks:
            return "Your task list is empty."
        return "Tasks: " + "; ".join(_format(t) for t in tasks)
    if action == "complete":
        n = _resolve(which or "", done=True)
        return f"Marked {n} task{'s' if n != 1 else ''} done." if n else "No matching open task."
    if action == "remove":
        n = _resolve(which or "", done=None)
        return f"Removed {n} task{'s' if n != 1 else ''}." if n else "No matching task to remove."
    return f"Unknown action: {action}"
