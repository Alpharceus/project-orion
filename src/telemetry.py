"""System-stats + weather telemetry for the HUD strip.

A background provider that samples CPU/RAM (psutil) and GPU VRAM/utilization
(NVML) every config.TELEMETRY_INTERVAL seconds, folds in the latest weather
(Open-Meteo, refreshed every config.WEATHER_REFRESH_MIN minutes), and publishes
one combined `telemetry` event per tick:

    {"type":"telemetry","weather":{"temp":62,"code":"clear"},
     "cpu":23,"ram":41,"gpu_gb":9.7,"gpu_pct":41}

CPU-only and cheap, so it never contends with the audio path. Resilient: a
missing GPU or a failed weather fetch just omits those fields. Dropped silently
when no HUD is connected — like every other bridge event.
"""

import json
import threading
import urllib.request

import psutil

import config
import events

_weather = {}   # {"temp": int, "code": str} or {} until first fetch
_nvml = None    # (pynvml_module, handle) or None if unavailable


def weather_label(code: int) -> str:
    """Map a WMO weather code (Open-Meteo `weather_code`) to a short label."""
    if code == 0:
        return "clear"
    if code in (1, 2):
        return "fair"
    if code == 3:
        return "cloudy"
    if code in (45, 48):
        return "fog"
    if code in (51, 53, 55, 56, 57):
        return "drizzle"
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return "rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code in (95, 96, 99):
        return "storm"
    return "—"


def fetch_weather() -> dict:
    """Current temperature + condition from Open-Meteo (no API key)."""
    url = (
        "https://api.open-meteo.com/v1/forecast?"
        f"latitude={config.WEATHER_LAT}&longitude={config.WEATHER_LON}"
        f"&current=temperature_2m,weather_code&temperature_unit={config.WEATHER_UNITS}"
    )
    with urllib.request.urlopen(url, timeout=15) as response:
        current = json.loads(response.read())["current"]
    return {"temp": round(current["temperature_2m"]), "code": weather_label(int(current["weather_code"]))}


def _init_nvml() -> None:
    global _nvml
    try:
        import pynvml
        pynvml.nvmlInit()
        _nvml = (pynvml, pynvml.nvmlDeviceGetHandleByIndex(0))
    except Exception:
        _nvml = None  # no NVIDIA GPU / driver — GPU cells stay empty


def _gpu() -> dict:
    if _nvml is None:
        return {}
    pynvml, handle = _nvml
    try:
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        return {"gpu_gb": round(mem.used / 1024 ** 3, 1), "gpu_pct": int(util.gpu)}
    except Exception:
        return {}


def _weather_loop(stop: threading.Event) -> None:
    global _weather
    while not stop.is_set():
        try:
            _weather = fetch_weather()
        except Exception:
            pass  # keep the last good reading
        stop.wait(config.WEATHER_REFRESH_MIN * 60)


def _stats_loop(stop: threading.Event) -> None:
    psutil.cpu_percent(interval=None)  # prime the rolling counter
    while not stop.wait(config.TELEMETRY_INTERVAL):
        event = {
            "type": "telemetry",
            "cpu": int(psutil.cpu_percent(interval=None)),
            "ram": int(psutil.virtual_memory().percent),
        }
        event.update(_gpu())
        if _weather:
            event["weather"] = _weather
        events.publish(event)


def start() -> threading.Event:
    """Launch the weather + stats threads. Returns a stop Event."""
    _init_nvml()
    stop = threading.Event()
    threading.Thread(target=_weather_loop, args=(stop,), daemon=True).start()
    threading.Thread(target=_stats_loop, args=(stop,), daemon=True).start()
    return stop
