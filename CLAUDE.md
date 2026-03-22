# CLAUDE.md

## Project overview

teslamate-garage is a Python service that automatically opens/closes a Meross MSG100 garage door based on Tesla vehicle proximity using TeslaMate MQTT data.

## Architecture

- `garage_door.py` — Main service. Connects to Meross cloud and MQTT broker, monitors vehicle positions, triggers door open/close.
- `diag_meross.py` — CLI utility for testing Meross device connectivity (discover/status/open/close).
- `diag_mqtt.py` — CLI utility for monitoring raw TeslaMate MQTT data.
- `Dockerfile` — Container image for running alongside TeslaMate on a Docker host.

## Key design decisions

- **Distance-based open trigger** (not geofence): TeslaMate geofence detection lags 20-30s behind real-time position. We use haversine distance from lat/lon MQTT updates instead, triggering at 200m.
- **Geofence-based close trigger**: Close fires when the car leaves the "Home" geofence. The lag is acceptable for closing since the car is driving away.
- **Cooldowns**: 2-minute open cooldown, 5-minute close cooldown (prevents reopening after leaving if the car lingers nearby).
- **Safety**: Close is refused if any tracked car is in Drive or Reverse at the Home geofence.

## Development

```bash
uv sync --group dev    # Install with dev dependencies
uv run pytest          # Run tests
```

## Tech stack

- Python 3.12, managed with uv
- `meross-iot` — Meross cloud API (async)
- `paho-mqtt` — MQTT client for TeslaMate data
- `structlog` — Structured logging
- `pytest` / `pytest-asyncio` — Testing
