# teslamate-garage

[![CI](https://github.com/swilcox/teslamate-garage/actions/workflows/ci.yml/badge.svg)](https://github.com/swilcox/teslamate-garage/actions/workflows/ci.yml)
[![Docker](https://github.com/swilcox/teslamate-garage/actions/workflows/docker.yml/badge.svg)](https://github.com/swilcox/teslamate-garage/actions/workflows/docker.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

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

Copy `.env.example` to `.env`, then set the required values and optionally override the defaults:

```
MEROSS_EMAIL=your_email@example.com
MEROSS_PASSWORD=your_password
MQTT_HOST=your_mqtt_broker_host
MQTT_PORT=1883
```

Supported `.env` settings:

| Variable | Default | Description |
|---|---|---|
| `MEROSS_EMAIL` | — | Required. Meross cloud account email. |
| `MEROSS_PASSWORD` | — | Required. Meross cloud account password. |
| `MQTT_HOST` | `localhost` | MQTT broker hostname used for TeslaMate topics. |
| `MQTT_PORT` | `1883` | MQTT broker port. |
| `LOG_LEVEL` | `INFO` | Application log level such as `DEBUG`, `INFO`, `WARNING`, or `ERROR`. |
| `CAR_IDS` | `1,2` | Comma-separated TeslaMate car IDs to monitor. |
| `HOME_GEOFENCE` | `Home` | TeslaMate geofence name that represents home. |
| `HOME_LAT` | `37.3944` | Home latitude used for proximity-based open detection. |
| `HOME_LON` | `-122.1501` | Home longitude used for proximity-based open detection. |
| `OPEN_DISTANCE_M` | `200` | Distance in meters from home that triggers an open while driving. |
| `OPEN_COOLDOWN` | `120` | Minimum seconds between open actions. |
| `CLOSE_COOLDOWN` | `300` | Minimum seconds after a close before opening is allowed again. |
| `HEARTBEAT_INTERVAL` | `300` | Seconds between heartbeat status logs and MQTT staleness checks. |

## Usage

```bash
# Run the service
uv run python garage_door.py
```

## Docker Compose

```bash
# Local development: build from the checked-out source
docker compose up --build -d

# Deployment: pull the published GHCR image
docker compose -f docker-compose.deploy.yml up -d
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
uv run ruff check .
uv run pytest --cov=garage_door --cov-report=term-missing
```
