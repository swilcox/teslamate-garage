"""
Proof-of-concept: subscribe to TeslaMate MQTT and display vehicle state.

Usage:
    uv run python diag_mqtt.py

Connects to the MQTT broker and prints live updates for both cars:
position, speed, geofence, state, and shift state.

Press Ctrl+C to stop.
"""

import os
import signal
import sys

import paho.mqtt.client as mqtt

MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))

CAR_IDS = [1, 2]

TOPICS_OF_INTEREST = [
    "latitude",
    "longitude",
    "speed",
    "geofence",
    "state",
    "shift_state",
    "heading",
]

# Store latest state per car
car_state: dict[int, dict[str, str]] = {car_id: {} for car_id in CAR_IDS}


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print(f"Connected to MQTT broker at {MQTT_HOST}:{MQTT_PORT}")
        for car_id in CAR_IDS:
            for topic in TOPICS_OF_INTEREST:
                full_topic = f"teslamate/cars/{car_id}/{topic}"
                client.subscribe(full_topic)
        print(f"Subscribed to topics for car(s): {CAR_IDS}")
        print("Waiting for updates...\n")
    else:
        print(f"Connection failed: {reason_code}")
        sys.exit(1)


def on_message(client, userdata, msg):
    # Parse: teslamate/cars/{car_id}/{metric}
    parts = msg.topic.split("/")
    if len(parts) != 4:
        return
    car_id = int(parts[2])
    metric = parts[3]
    value = msg.payload.decode("utf-8", errors="replace")

    old_value = car_state[car_id].get(metric)
    car_state[car_id][metric] = value

    if old_value != value:
        print(f"  Car {car_id} | {metric:>12s} = {value}")

        # Print summary when we get a position update
        if metric in ("latitude", "longitude"):
            s = car_state[car_id]
            lat = s.get("latitude", "?")
            lon = s.get("longitude", "?")
            spd = s.get("speed", "?")
            geo = s.get("geofence", "")
            state = s.get("state", "?")
            shift = s.get("shift_state", "?")
            geo_str = f" [{geo}]" if geo else ""
            print(
                f"         → pos=({lat}, {lon}) speed={spd}km/h "
                f"state={state} shift={shift}{geo_str}"
            )


def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    print(f"Connecting to {MQTT_HOST}:{MQTT_PORT}...")
    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    except Exception as e:
        print(f"Failed to connect: {e}")
        sys.exit(1)

    def handle_sigint(sig, frame):
        print("\nDisconnecting...")
        client.disconnect()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sigint)
    client.loop_forever()


if __name__ == "__main__":
    main()
