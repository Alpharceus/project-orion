"""In-process daily scheduler: run a function every day at a wall-clock time.

Used for proactive agents (arXiv morning briefing). Jobs only fire while
orion.py is running — Orion is meant to be left on. Waits are chopped into
short slices against the wall clock, so a job still fires (late, not skipped)
if the PC was asleep at the scheduled moment.
"""

import threading
from datetime import datetime, timedelta

_lock = threading.Lock()
_jobs = {}  # name -> {"time": "HH:MM[:SS]", "stop": threading.Event}

_WAIT_SLICE_SECONDS = 30.0


def parse_time(spec: str) -> tuple[int, int, int]:
    """Validate "HH:MM" (or "HH:MM:SS", used by tests) -> (h, m, s)."""
    parts = spec.split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"bad time {spec!r}, expected HH:MM")
    h, m = int(parts[0]), int(parts[1])
    s = int(parts[2]) if len(parts) == 3 else 0
    if not (0 <= h < 24 and 0 <= m < 60 and 0 <= s < 60):
        raise ValueError(f"bad time {spec!r}, expected HH:MM")
    return h, m, s


def _next_run(spec: str) -> datetime:
    h, m, s = parse_time(spec)
    now = datetime.now()
    target = now.replace(hour=h, minute=m, second=s, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def _worker(name: str, spec: str, fn, stop: threading.Event):
    while not stop.is_set():
        target = _next_run(spec)
        while not stop.is_set():
            remaining = (target - datetime.now()).total_seconds()
            if remaining <= 0:
                break
            stop.wait(min(remaining, _WAIT_SLICE_SECONDS))
        if stop.is_set():
            return
        try:
            fn()
        except Exception as e:
            print(f"\n[scheduler] daily job '{name}' failed: {e}")


def schedule_daily(name: str, spec: str, fn) -> None:
    """(Re)schedule fn to run every day at spec ("HH:MM"). Replaces same-name job."""
    parse_time(spec)  # validate before touching the existing job
    with _lock:
        old = _jobs.pop(name, None)
        if old:
            old["stop"].set()
        stop = threading.Event()
        _jobs[name] = {"time": spec, "stop": stop}
        threading.Thread(target=_worker, args=(name, spec, fn, stop), daemon=True).start()


def cancel(name: str) -> bool:
    """Cancel a job; returns False if it wasn't scheduled."""
    with _lock:
        job = _jobs.pop(name, None)
    if job is None:
        return False
    job["stop"].set()
    return True


def scheduled_time(name: str) -> str | None:
    """The job's "HH:MM" if scheduled, else None."""
    with _lock:
        job = _jobs.get(name)
    return job["time"] if job else None
