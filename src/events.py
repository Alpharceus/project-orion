"""Tiny thread-safe pub/sub hub decoupling event producers from the HUD bridge.

Producers (state machine, agents, speech amplitude, telemetry) call publish();
consumers (hud_server, and anything else) subscribe() a callback. Subscribers
run synchronously in the caller's thread, so they must be cheap and non-blocking
— hud_server hops to its asyncio loop via call_soon_threadsafe rather than doing
work here. The assistant has no hard dependency on any subscriber: with the HUD
closed there are simply no consumers and publish() is nearly free.
"""

import threading

_subscribers: list = []
_lock = threading.Lock()


def subscribe(fn) -> None:
    """Register fn(event: dict) to receive every published event."""
    with _lock:
        _subscribers.append(fn)


def unsubscribe(fn) -> None:
    with _lock:
        if fn in _subscribers:
            _subscribers.remove(fn)


def publish(event: dict) -> None:
    """Fan an event out to all subscribers. Safe to call from any thread."""
    with _lock:
        subscribers = list(_subscribers)
    for fn in subscribers:
        try:
            fn(event)
        except Exception as e:  # a broken subscriber must never break a producer
            print(f"[events] subscriber error: {e}")
