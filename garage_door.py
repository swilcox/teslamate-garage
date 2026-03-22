"""
Garage door automation service.

Subscribes to TeslaMate MQTT for vehicle state and automatically
opens/closes the garage door via Meross when a car approaches home.

Uses distance-based triggering (lat/lon) for opening so we don't have to
wait for TeslaMate's geofence detection, which can lag behind by 20-30s.
Still uses geofence for close (leaving Home).

Usage:
    1. Ensure .env has MEROSS_EMAIL, MEROSS_PASSWORD, MQTT_HOST, MQTT_PORT
    2. uv run python garage_door.py
"""

import asyncio
import logging
import math
import os
import sys
import time
from dataclasses import dataclass

import paho.mqtt.client as mqtt
import structlog
from meross_iot.http_api import MerossHttpClient
from meross_iot.manager import MerossManager

# Configure structlog
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="%H:%M:%S", utc=False),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

# Quiet down noisy libraries
logging.getLogger("meross_iot").setLevel(logging.WARNING)
logging.getLogger("paho").setLevel(logging.WARNING)

log = structlog.get_logger()

CAR_IDS = [int(x) for x in os.environ.get("CAR_IDS", "1,2").split(",")]
HOME_GEOFENCE = os.environ.get("HOME_GEOFENCE", "Home")
HOME_LAT = float(os.environ.get("HOME_LAT", "37.3944"))  # Default: Tesla HQ
HOME_LON = float(os.environ.get("HOME_LON", "-122.1501"))
OPEN_DISTANCE_M = float(os.environ.get("OPEN_DISTANCE_M", "200"))
OPEN_COOLDOWN = int(os.environ.get("OPEN_COOLDOWN", "120"))
CLOSE_COOLDOWN = int(os.environ.get("CLOSE_COOLDOWN", "300"))


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in meters between two lat/lon points."""
    R = 6_371_000  # Earth radius in meters
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def load_env():
    """Load .env file if present; otherwise rely on environment variables."""
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip())


@dataclass
class CarState:
    car_id: int
    latitude: str = ""
    longitude: str = ""
    speed: str = ""
    geofence: str = ""
    state: str = ""
    shift_state: str = ""
    heading: str = ""
    prev_geofence: str = ""
    was_near_home: bool = False

    @property
    def is_home(self) -> bool:
        return self.geofence == HOME_GEOFENCE

    @property
    def is_driving(self) -> bool:
        return self.shift_state in ("D", "R")

    @property
    def is_parked(self) -> bool:
        return self.shift_state == "P"

    @property
    def just_left_home(self) -> bool:
        return not self.is_home and self.prev_geofence == HOME_GEOFENCE

    def distance_from_home(self) -> float | None:
        """Returns distance from home in meters, or None if no position."""
        try:
            lat = float(self.latitude)
            lon = float(self.longitude)
        except (ValueError, TypeError):
            return None
        return haversine_m(lat, lon, HOME_LAT, HOME_LON)


class GarageDoorService:
    def __init__(self):
        self.cars: dict[int, CarState] = {cid: CarState(car_id=cid) for cid in CAR_IDS}
        self.meross_manager: MerossManager | None = None
        self.meross_http: MerossHttpClient | None = None
        self.garage_device = None
        self.loop: asyncio.AbstractEventLoop | None = None

        # Cooldowns: prevent re-triggering after open or close
        self.last_open_time: float = 0
        self.last_close_time: float = 0
        self.open_cooldown = OPEN_COOLDOWN
        self.close_cooldown = CLOSE_COOLDOWN

        # Track if initial retained messages have been processed
        self.initialized = False
        self.init_timer: asyncio.TimerHandle | None = None

    async def connect_meross(self):
        email = os.environ.get("MEROSS_EMAIL")
        password = os.environ.get("MEROSS_PASSWORD")
        if not email or not password:
            log.error("meross_config_missing")
            sys.exit(1)

        log.info("meross_connecting")
        self.meross_http = await MerossHttpClient.async_from_user_password(
            api_base_url="https://iot.meross.com",
            email=email,
            password=password,
        )
        self.meross_manager = MerossManager(http_client=self.meross_http)
        await self.meross_manager.async_init()
        await self.meross_manager.async_device_discovery()

        openers = self.meross_manager.find_devices(device_type="msg100")
        if not openers:
            log.error("meross_no_opener")
            sys.exit(1)

        self.garage_device = openers[0]
        await self.garage_device.async_update()
        is_open = self.garage_device.get_is_open()
        log.info("meross_connected",
                 device=self.garage_device.name,
                 status="open" if is_open else "closed")

    async def open_door(self, reason: str):
        now = time.time()
        if now - self.last_open_time < self.open_cooldown:
            log.info("open_skipped", reason="open_cooldown_active", trigger=reason)
            return
        if now - self.last_close_time < self.close_cooldown:
            log.info("open_skipped", reason="close_cooldown_active", trigger=reason)
            return

        await self.garage_device.async_update()
        if self.garage_device.get_is_open():
            log.info("open_skipped", reason="already_open", trigger=reason)
            return

        log.info("door_opening", reason=reason)
        await self.garage_device.async_open(channel=0)
        self.last_open_time = now

    async def close_door(self, reason: str):
        await self.garage_device.async_update()
        if not self.garage_device.get_is_open():
            log.info("close_skipped", reason="already_closed", trigger=reason)
            return

        # Safety check: don't close if ANY car is in drive/reverse at home
        for car in self.cars.values():
            if car.is_home and car.is_driving:
                log.warning("close_refused",
                            car=car.car_id,
                            shift_state=car.shift_state,
                            geofence=HOME_GEOFENCE)
                return

        log.info("door_closing", reason=reason)
        await self.garage_device.async_close(channel=0)
        self.last_close_time = time.time()

    def handle_update(self, car_id: int, metric: str, value: str):
        car = self.cars[car_id]

        if metric == "geofence":
            car.prev_geofence = car.geofence

        setattr(car, metric, value)

        # Don't act on the initial batch of retained messages
        if not self.initialized:
            return

        # --- OPEN LOGIC ---
        # Trigger: position update shows car approaching home
        if metric in ("latitude", "longitude"):
            dist = car.distance_from_home()
            if dist is not None:
                near_home = dist <= OPEN_DISTANCE_M
                if near_home and not car.was_near_home and car.is_driving:
                    log.info("car_approaching",
                             car=car_id,
                             distance_m=round(dist),
                             shift_state=car.shift_state)
                    asyncio.run_coroutine_threadsafe(
                        self.open_door(f"Car {car_id} within {dist:.0f}m of home"),
                        self.loop,
                    )
                car.was_near_home = near_home

        # --- CLOSE LOGIC ---
        # Trigger: geofence just changed away from Home (car leaving)
        if metric == "geofence" and car.just_left_home:
            log.info("car_leaving_home", car=car_id, new_geofence=car.geofence)
            asyncio.run_coroutine_threadsafe(
                self.close_door(f"Car {car_id} left {HOME_GEOFENCE}"),
                self.loop,
            )

    def mark_initialized(self):
        """Called after a short delay to mark retained messages as processed."""
        self.initialized = True
        for cid, car in self.cars.items():
            dist = car.distance_from_home()
            # Set initial near-home state so we don't false-trigger
            if dist is not None:
                car.was_near_home = dist <= OPEN_DISTANCE_M
            log.info("car_state",
                     car=cid,
                     geofence=car.geofence or None,
                     state=car.state or None,
                     shift_state=car.shift_state or None,
                     distance_m=round(dist) if dist is not None else None,
                     near_home=car.was_near_home)
        log.info("initialized")

    def start_mqtt(self):
        topics = [
            "latitude", "longitude", "speed",
            "geofence", "state", "shift_state", "heading",
        ]

        def on_connect(client, userdata, flags, reason_code, properties):
            if reason_code != 0:
                log.error("mqtt_connect_failed", reason_code=reason_code)
                return
            mqtt_host = os.environ.get("MQTT_HOST", "localhost")
            log.info("mqtt_connected", host=mqtt_host)
            for car_id in CAR_IDS:
                for topic in topics:
                    client.subscribe(f"teslamate/cars/{car_id}/{topic}")
            # After retained messages arrive (give it 3 seconds), mark as initialized
            self.init_timer = self.loop.call_later(3.0, self.mark_initialized)

        def on_message(client, userdata, msg):
            parts = msg.topic.split("/")
            if len(parts) != 4:
                return
            car_id = int(parts[2])
            metric = parts[3]
            value = msg.payload.decode("utf-8", errors="replace")
            self.handle_update(car_id, metric, value)

        mqtt_host = os.environ.get("MQTT_HOST", "localhost")
        mqtt_port = int(os.environ.get("MQTT_PORT", "1883"))

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.on_connect = on_connect
        client.on_message = on_message

        log.info("mqtt_connecting", host=mqtt_host, port=mqtt_port)
        client.connect(mqtt_host, mqtt_port, keepalive=60)
        client.loop_start()
        return client

    async def run(self):
        self.loop = asyncio.get_event_loop()
        await self.connect_meross()
        mqtt_client = self.start_mqtt()

        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            log.info("shutting_down")
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
            if self.meross_manager:
                self.meross_manager.close()
            if self.meross_http:
                await self.meross_http.async_logout()
            log.info("shutdown_complete")


def main():
    load_env()
    service = GarageDoorService()
    try:
        asyncio.run(service.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
