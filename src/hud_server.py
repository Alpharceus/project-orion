"""Local WebSocket bridge between the Python brain and the (future) Tauri HUD.

Runs an asyncio websockets server on 127.0.0.1 in a background thread. It
subscribes to the event hub and broadcasts outbound events (state, transcript,
agent, telemetry, amplitude) to every connected client as compact JSON. The HUD
is a pure client: if none is connected, events are dropped silently and the
assistant is unaffected. Inbound messages (commands) are republished onto the
hub so the rest of the app can react.

Threading model: the server owns its own event loop on a dedicated thread. All
client/cache mutation happens on that loop thread. Producers on other threads
never touch shared state directly — _on_event() only schedules work onto the
loop via call_soon_threadsafe, so there are no locks and no races.
"""

import asyncio
import json
import threading

import config
import events

# Outbound event types we relay to clients. Inbound "command" messages and any
# unknown types are ignored by the broadcaster.
_RELAY_TYPES = {"state", "transcript", "agent", "telemetry", "amplitude",
                "ticker", "reminders_list", "tasks_list", "movie", "persona"}

_loop: asyncio.AbstractEventLoop | None = None
_clients: set = set()          # touched only on the loop thread
_state_event = {"type": "state", "value": "idle"}  # last state, for snapshots
_agents: dict = {}             # agent id -> last agent event, for snapshots
_ticker = None                 # last ticker event, for snapshots
_reminders_list = None         # last reminders_list event, for snapshots
_tasks_list = None             # last tasks_list event, for snapshots
_movie = None                  # last movie event, for snapshots
_persona = {"type": "persona", "name": "orion"}  # last persona event, for snapshots


def start() -> None:
    """Launch the bridge in a daemon thread. Safe to call once at startup.

    Blocks until the event loop is live so events published right after start()
    (e.g. the agent baseline) reach the broadcaster instead of being dropped.
    """
    events.subscribe(_on_event)
    ready = threading.Event()
    threading.Thread(target=lambda: asyncio.run(_serve(ready)), daemon=True).start()
    ready.wait(timeout=5)


async def _serve(ready: threading.Event) -> None:
    global _loop
    import websockets  # imported here so a missing dep can't break import-time

    _loop = asyncio.get_running_loop()
    ready.set()
    async with websockets.serve(_handler, config.HUD_HOST, config.HUD_PORT):
        print(f"🛰️  [Orion] HUD bridge on ws://{config.HUD_HOST}:{config.HUD_PORT}")
        await asyncio.Future()  # run forever


def _snapshot() -> list[dict]:
    """Events a freshly connected client needs to render the current session."""
    events_out = [_state_event, *_agents.values()]
    for cached in (_ticker, _reminders_list, _tasks_list, _movie, _persona):
        if cached is not None:
            events_out.append(cached)
    return events_out


async def _handler(ws) -> None:
    """Serve one client: send a snapshot, then relay inbound commands to the hub."""
    _clients.add(ws)
    try:
        for event in _snapshot():
            await ws.send(json.dumps(event, separators=(",", ":")))
        async for raw in ws:
            try:
                message = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(message, dict) and message.get("type") == "command":
                events.publish(message)  # let orion.py / others react
    except Exception:
        pass  # client dropped mid-stream; cleanup happens in finally
    finally:
        _clients.discard(ws)


def _on_event(event: dict) -> None:
    """Hub subscriber (any thread): hand the event to the loop thread to relay."""
    if event.get("type") not in _RELAY_TYPES:
        return
    loop = _loop
    if loop is None:
        return  # bridge not up yet; nothing connected anyway
    loop.call_soon_threadsafe(_relay, event)


def _relay(event: dict) -> None:
    """Update snapshot caches and fan the event out. Runs on the loop thread."""
    if event["type"] == "state":
        global _state_event
        _state_event = event
    elif event["type"] == "agent":
        # Agents stay in the snapshot as persistent (dim) HUD nodes; status just
        # changes their appearance, so idle no longer evicts.
        agent_id = event.get("id")
        if agent_id is not None:
            _agents[agent_id] = event
    elif event["type"] == "ticker":
        global _ticker
        _ticker = event
    elif event["type"] == "reminders_list":
        global _reminders_list
        _reminders_list = event
    elif event["type"] == "tasks_list":
        global _tasks_list
        _tasks_list = event
    elif event["type"] == "movie":
        global _movie
        _movie = event
    elif event["type"] == "persona":
        global _persona
        _persona = event

    if not _clients:
        return
    message = json.dumps(event, separators=(",", ":"))
    for ws in list(_clients):
        asyncio.create_task(_safe_send(ws, message))


async def _safe_send(ws, message: str) -> None:
    try:
        await ws.send(message)
    except Exception:
        _clients.discard(ws)
