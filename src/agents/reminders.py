"""Reminders & scheduled events — one-off and recurring, persisted to disk.

A single tick thread checks the wall clock every config.REMINDER_TICK_SECONDS
and fires anything due through notify() (Orion speaks it). Reminders survive
restarts (JSON store); an overdue one fires on the next tick after startup, so a
reminder that came due while Orion was off isn't silently lost. The model drives
everything through the `reminder` tool; relative times ("in 20 minutes") are
resolved here so the model never needs to know the current clock.
"""

import json
import threading
import uuid
from datetime import date, datetime, timedelta

import config
import events

from . import notify, tool

STORE = config.DATA_DIR / "reminders.json"
_lock = threading.Lock()
_reminders: dict = {}  # id -> reminder dict

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


# --- persistence --------------------------------------------------------------
def _load() -> None:
    if STORE.exists():
        try:
            _reminders.update(json.loads(STORE.read_text(encoding="utf-8")).get("reminders", {}))
        except Exception as e:
            print(f"[reminders] could not load store: {e}")


def _save() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"reminders": _reminders}, indent=2), encoding="utf-8")
    tmp.replace(STORE)


# --- scheduling math ----------------------------------------------------------
def _allowed_weekdays(repeat: str, weekdays) -> list | None:
    if repeat == "daily":
        return list(range(7))
    if repeat == "weekdays":
        return [0, 1, 2, 3, 4]
    if repeat == "weekly":
        return _to_indices(weekdays) or list(range(7))
    return None  # one-off


def _to_indices(weekdays) -> list:
    out = []
    for w in weekdays or []:
        if isinstance(w, int) and 0 <= w <= 6:
            out.append(w)
        elif isinstance(w, str) and w.strip().lower() in _WEEKDAYS:
            out.append(_WEEKDAYS.index(w.strip().lower()))
    return sorted(set(out))


def _compute_next(now: datetime, time_hm=None, allowed=None, on_date=None, delay_seconds=None) -> datetime:
    if delay_seconds is not None:
        return now + timedelta(seconds=delay_seconds)
    h, m = (int(x) for x in time_hm.split(":"))
    if on_date:
        d = date.fromisoformat(on_date)
        return datetime(d.year, d.month, d.day, h, m)
    allowed = allowed if allowed else list(range(7))
    for i in range(8):
        cand = (now + timedelta(days=i)).replace(hour=h, minute=m, second=0, microsecond=0)
        if cand > now and cand.weekday() in allowed:
            return cand
    return now + timedelta(days=1)


def _describe(rem: dict) -> str:
    when = datetime.fromisoformat(rem["next_fire"])
    try:
        clock = when.strftime("%I:%M %p").lstrip("0")
    except ValueError:
        clock = when.strftime("%H:%M")
    if rem["repeat"] == "daily":
        return f"every day at {clock}"
    if rem["repeat"] == "weekdays":
        return f"every weekday at {clock}"
    if rem["repeat"] == "weekly":
        days = ", ".join(_WEEKDAYS[i].capitalize() for i in _to_indices(rem.get("weekdays")))
        return f"every {days} at {clock}"
    day = when.strftime("%a %b %d")
    return f"{day} at {clock}"


# --- core ---------------------------------------------------------------------
def add(message, time=None, in_minutes=None, in_hours=None, date=None,
        repeat="none", weekdays=None) -> dict:
    now = datetime.now()
    delay = None
    if in_minutes or in_hours:
        delay = (in_minutes or 0) * 60 + (in_hours or 0) * 3600
    allowed = _allowed_weekdays(repeat, weekdays)
    if delay is not None:
        nxt, time_hm = _compute_next(now, delay_seconds=delay), None
    else:
        if not time:
            raise ValueError("need a time, or an in_minutes/in_hours offset")
        time_hm = _norm_time(time)
        nxt = _compute_next(now, time_hm=time_hm, allowed=allowed, on_date=date)
    rid = uuid.uuid4().hex[:8]
    rem = {"id": rid, "message": message.strip(), "time_hm": time_hm,
           "weekdays": _to_indices(weekdays) if repeat == "weekly" else None,
           "repeat": repeat, "next_fire": nxt.isoformat(), "active": True}
    with _lock:
        _reminders[rid] = rem
    _save()
    _emit_hud()
    return rem


def _norm_time(t: str) -> str:
    parts = str(t).strip().split(":")
    h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(f"bad time {t!r}, expected 24-hour HH:MM")
    return f"{h:02d}:{m:02d}"


def active_reminders() -> list:
    with _lock:
        return [r for r in _reminders.values() if r["active"]]


def cancel(which: str) -> int:
    """Cancel reminders matching `which` (substring of the message, or 'all')."""
    with _lock:
        if which and which.strip().lower() == "all":
            hits = [r["id"] for r in _reminders.values() if r["active"]]
        else:
            q = (which or "").strip().lower()
            hits = [r["id"] for r in _reminders.values()
                    if r["active"] and q and q in r["message"].lower()]
        for rid in hits:
            _reminders.pop(rid, None)
    if hits:
        _save()
        _emit_hud()
    return len(hits)


def cancel_id(rid: str) -> bool:
    """Remove a specific reminder by id (used when a task's due reminder is gone)."""
    with _lock:
        existed = _reminders.pop(rid, None) is not None
    if existed:
        _save()
        _emit_hud()
    return existed


def fire_due(now: datetime | None = None) -> int:
    """Fire every reminder due at `now`; advance recurring, drop one-offs."""
    now = now or datetime.now()
    fired = 0
    for r in active_reminders():
        if datetime.fromisoformat(r["next_fire"]) <= now:
            notify(f"Reminder: {r['message']}")
            fired += 1
            with _lock:
                if r["repeat"] == "none":
                    _reminders.pop(r["id"], None)
                else:
                    allowed = _allowed_weekdays(r["repeat"], r.get("weekdays"))
                    r["next_fire"] = _compute_next(now, time_hm=r["time_hm"], allowed=allowed).isoformat()
    if fired:
        _save()
        _emit_hud()
    return fired


def _emit_hud() -> None:
    """Publish the upcoming-reminders list (soonest first) for the HUD panel."""
    rems = sorted(active_reminders(), key=lambda r: r["next_fire"])
    items = [{"text": r["message"], "when": _describe(r)} for r in rems]
    events.publish({"type": "reminders_list", "items": items})


def _tick(stop: threading.Event) -> None:
    while not stop.wait(config.REMINDER_TICK_SECONDS):
        try:
            fire_due()
        except Exception as e:
            print(f"[reminders] tick error: {e}")


def start() -> threading.Event:
    _load()
    _emit_hud()
    stop = threading.Event()
    threading.Thread(target=_tick, args=(stop,), daemon=True).start()
    return stop


# --- tool ---------------------------------------------------------------------
@tool(
    "reminder",
    "Set, list, or cancel spoken reminders and scheduled events. Use for one-off "
    "reminders ('remind me at 3pm to call the lab' -> time='15:00'; 'in 20 minutes' "
    "-> in_minutes=20) and recurring ones ('every day at 9' -> repeat='daily', "
    "time='09:00'; 'every weekday' -> repeat='weekdays'; 'every Monday and Thursday' "
    "-> repeat='weekly', weekdays=['monday','thursday']). Convert clock times to "
    "24-hour HH:MM. Actions: 'add', 'list', 'cancel'.",
    {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["add", "list", "cancel"]},
            "message": {"type": "string", "description": "What to remind the user about."},
            "time": {"type": "string", "description": "24-hour HH:MM for the reminder."},
            "in_minutes": {"type": "number", "description": "Relative offset from now, in minutes."},
            "in_hours": {"type": "number", "description": "Relative offset from now, in hours."},
            "date": {"type": "string", "description": "YYYY-MM-DD for a one-off on a specific date."},
            "repeat": {"type": "string", "enum": ["none", "daily", "weekdays", "weekly"]},
            "weekdays": {"type": "array", "items": {"type": "string"},
                         "description": "Weekday names for repeat='weekly'."},
            "which": {"type": "string", "description": "For 'cancel': part of the message, or 'all'."},
        },
        "required": ["action"],
    },
)
def reminder(action, message=None, time=None, in_minutes=None, in_hours=None,
             date=None, repeat="none", weekdays=None, which=None):
    if action == "add":
        if not message:
            return "What should I remind you about?"
        try:
            rem = add(message, time=time, in_minutes=in_minutes, in_hours=in_hours,
                      date=date, repeat=repeat, weekdays=weekdays)
        except ValueError as e:
            return f"Tool error: {e}"
        return f"Reminder set: {message} — {_describe(rem)}."
    if action == "list":
        rems = active_reminders()
        if not rems:
            return "No reminders set."
        return "Reminders: " + "; ".join(f"{r['message']} ({_describe(r)})" for r in rems)
    if action == "cancel":
        n = cancel(which or "")
        return f"Cancelled {n} reminder{'s' if n != 1 else ''}." if n else "No matching reminder to cancel."
    return f"Unknown action: {action}"
