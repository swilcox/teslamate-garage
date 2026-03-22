"""
Proof-of-concept: connect to Meross cloud and interact with garage door opener.

Usage:
    1. Copy .env.example to .env and fill in your Meross credentials
    2. Run: uv run python diag_meross.py discover
       → Lists all Meross devices on your account
    3. Run: uv run python diag_meross.py status
       → Shows garage door open/closed state
    4. Run: uv run python diag_meross.py open
       → Opens the garage door
    5. Run: uv run python diag_meross.py close
       → Closes the garage door
"""

import asyncio
import os
import sys

from meross_iot.http_api import MerossHttpClient
from meross_iot.manager import MerossManager


def load_env():
    """Load .env file manually (no extra dependency needed)."""
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        print("ERROR: .env file not found. Copy .env.example to .env and fill in credentials.")
        sys.exit(1)
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


async def get_manager() -> tuple[MerossManager, MerossHttpClient]:
    email = os.environ.get("MEROSS_EMAIL")
    password = os.environ.get("MEROSS_PASSWORD")
    if not email or not password:
        print("ERROR: MEROSS_EMAIL and MEROSS_PASSWORD must be set in .env")
        sys.exit(1)

    http_client = await MerossHttpClient.async_from_user_password(
        api_base_url="https://iot.meross.com",
        email=email,
        password=password,
    )
    manager = MerossManager(http_client=http_client)
    await manager.async_init()
    await manager.async_device_discovery()
    return manager, http_client


async def cleanup(manager: MerossManager, http_client: MerossHttpClient):
    manager.close()
    await http_client.async_logout()


async def cmd_discover():
    """List all Meross devices on the account."""
    manager, http_client = await get_manager()
    try:
        devices = manager.find_devices()
        if not devices:
            print("No Meross devices found on this account.")
            return
        print(f"Found {len(devices)} device(s):\n")
        for dev in devices:
            print(f"  Name:    {dev.name}")
            print(f"  Type:    {dev.type}")
            print(f"  Model:   {dev.hardware.get('type', 'unknown') if hasattr(dev, 'hardware') else 'unknown'}")
            print(f"  Online:  {dev.online_status}")
            print(f"  UUID:    {dev.uuid}")
            print()
    finally:
        await cleanup(manager, http_client)


async def find_garage_opener(manager: MerossManager):
    """Find a garage door opener (MSG100 or MSG200)."""
    for device_type in ("msg100", "msg200"):
        openers = manager.find_devices(device_type=device_type)
        if openers:
            dev = openers[0]
            await dev.async_update()
            return dev
    return None


async def cmd_status():
    """Show garage door status."""
    manager, http_client = await get_manager()
    try:
        dev = await find_garage_opener(manager)
        if not dev:
            print("No garage door opener (MSG100/MSG200) found.")
            print("Run 'discover' to see all devices and their types.")
            return
        is_open = dev.get_is_open()
        print(f"Device: {dev.name}")
        print(f"Status: {'OPEN' if is_open else 'CLOSED'}")
    finally:
        await cleanup(manager, http_client)


async def cmd_open():
    """Open the garage door."""
    manager, http_client = await get_manager()
    try:
        dev = await find_garage_opener(manager)
        if not dev:
            print("No garage door opener found.")
            return
        is_open = dev.get_is_open()
        if is_open:
            print(f"{dev.name} is already OPEN.")
            return
        print(f"Opening {dev.name}...")
        await dev.async_open(channel=0)
        print("Open command sent.")
    finally:
        await cleanup(manager, http_client)


async def cmd_close():
    """Close the garage door."""
    manager, http_client = await get_manager()
    try:
        dev = await find_garage_opener(manager)
        if not dev:
            print("No garage door opener found.")
            return
        is_open = dev.get_is_open()
        if not is_open:
            print(f"{dev.name} is already CLOSED.")
            return
        print(f"Closing {dev.name}...")
        await dev.async_close(channel=0)
        print("Close command sent.")
    finally:
        await cleanup(manager, http_client)


COMMANDS = {
    "discover": cmd_discover,
    "status": cmd_status,
    "open": cmd_open,
    "close": cmd_close,
}


def main():
    load_env()

    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"Usage: uv run python {sys.argv[0]} <command>")
        print(f"Commands: {', '.join(COMMANDS)}")
        sys.exit(1)

    command = sys.argv[1]
    asyncio.run(COMMANDS[command]())


if __name__ == "__main__":
    main()
