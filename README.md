# teslamate-garage

Automatically opens and closes a Meross smart garage door based on Tesla vehicle proximity, using [TeslaMate](https://github.com/teslamate-org/teslamate) MQTT data.

## How it works

- **Open**: Subscribes to TeslaMate MQTT lat/lon updates. When a vehicle in Drive enters within 200m of home, the garage door opens via the Meross cloud API.
- **Close**: When a vehicle's TeslaMate geofence changes away from "Home", the door closes (with a safety check that no other vehicle is in Drive/Reverse at home).
- **Cooldowns**: After opening, a 2-minute cooldown prevents re-triggering. After closing, a 5-minute cooldown prevents the door from reopening if the car lingers nearby.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) for dependency management
- A [TeslaMate](https://github.com/teslamate-org/teslamate) instance publishing to an MQTT broker
- A [Meross](https://www.meross.com/) MSG100 smart garage door opener
- A Meross cloud account (email/password)

## Setup

```bash
# Clone and install
cd teslamate-garage
uv sync

# Configure
cp .env.example .env
# Edit .env with your Meross credentials and MQTT broker details
```

## Configuration

Edit `.env`:

```
MEROSS_EMAIL=your_email@example.com
MEROSS_PASSWORD=your_password
MQTT_HOST=your_mqtt_broker_host
MQTT_PORT=1883
```

Constants at the top of `garage_door.py`:

| Constant | Default | Description |
|---|---|---|
| `HOME_LAT` / `HOME_LON` | — | Your home/driveway coordinates |
| `OPEN_DISTANCE_M` | 200 | Distance in meters to trigger door open |
| `CAR_IDS` | `[1, 2]` | TeslaMate car IDs to monitor |
| `HOME_GEOFENCE` | `"Home"` | TeslaMate geofence name for home |

## Usage

```bash
# Run the service
uv run python garage_door.py
```

## Utility scripts

```bash
# Test Meross connectivity and control
uv run python diag_meross.py discover   # List devices
uv run python diag_meross.py status     # Door open/closed
uv run python diag_meross.py open       # Open the door
uv run python diag_meross.py close      # Close the door

# Monitor TeslaMate MQTT data
uv run python diag_mqtt.py
```

## Running tests

```bash
uv run pytest
```
