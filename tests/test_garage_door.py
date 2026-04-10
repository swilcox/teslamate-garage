"""Tests for garage door automation logic."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from garage_door import (
    HOME_GEOFENCE,
    HOME_LAT,
    HOME_LON,
    CarState,
    GarageDoorService,
    haversine_m,
)


# --- haversine_m ---


def test_haversine_same_point():
    assert haversine_m(35.78, -86.92, 35.78, -86.92) == 0.0


def test_haversine_known_distance():
    # Nashville to Memphis is roughly 316km
    dist = haversine_m(36.1627, -86.7816, 35.1496, -90.0490)
    assert 310_000 < dist < 325_000


def test_haversine_short_distance():
    # ~111m per 0.001 degree latitude at this latitude
    dist = haversine_m(35.781, -86.917, 35.782, -86.917)
    assert 100 < dist < 120


# --- CarState ---


def test_car_state_is_home():
    car = CarState(car_id=1, geofence=HOME_GEOFENCE)
    assert car.is_home is True


def test_car_state_not_home():
    car = CarState(car_id=1, geofence="Work")
    assert car.is_home is False


def test_car_state_not_home_empty():
    car = CarState(car_id=1, geofence="")
    assert car.is_home is False


def test_car_state_is_driving():
    assert CarState(car_id=1, shift_state="D").is_driving is True
    assert CarState(car_id=1, shift_state="R").is_driving is True
    assert CarState(car_id=1, shift_state="P").is_driving is False
    assert CarState(car_id=1, shift_state="").is_driving is False


def test_car_state_is_parked():
    assert CarState(car_id=1, shift_state="P").is_parked is True
    assert CarState(car_id=1, shift_state="D").is_parked is False


def test_car_state_just_left_home():
    car = CarState(car_id=1, geofence="", prev_geofence=HOME_GEOFENCE)
    assert car.just_left_home is True


def test_car_state_just_left_home_false_when_still_home():
    car = CarState(car_id=1, geofence=HOME_GEOFENCE, prev_geofence=HOME_GEOFENCE)
    assert car.just_left_home is False


def test_car_state_just_left_home_false_when_never_home():
    car = CarState(car_id=1, geofence="", prev_geofence="Work")
    assert car.just_left_home is False


def test_distance_from_home_at_home():
    car = CarState(car_id=1, latitude=str(HOME_LAT), longitude=str(HOME_LON))
    assert car.distance_from_home() == 0.0


def test_distance_from_home_no_position():
    car = CarState(car_id=1)
    assert car.distance_from_home() is None


def test_distance_from_home_invalid():
    car = CarState(car_id=1, latitude="bad", longitude="-86.9")
    assert car.distance_from_home() is None


# --- GarageDoorService.handle_update (open logic) ---


class TestHandleUpdateOpen:
    def setup_method(self):
        self.service = GarageDoorService()
        self.service.initialized = True
        self.service.loop = MagicMock()
        # Prevent actual coroutine scheduling
        self.mock_future = MagicMock()
        self.run_patcher = patch(
            "garage_door.asyncio.run_coroutine_threadsafe",
            return_value=self.mock_future,
        )
        self.mock_run = self.run_patcher.start()

    def teardown_method(self):
        self.run_patcher.stop()

    def _place_car_far_away(self, car_id: int):
        """Put a car far from home so it can 'approach'."""
        car = self.service.cars[car_id]
        car.latitude = "36.0"
        car.longitude = "-87.0"
        car.was_near_home = False
        car.shift_state = "D"

    def test_approaching_home_triggers_open(self):
        self._place_car_far_away(1)
        # Simulate position update to within range
        self.service.handle_update(1, "latitude", str(HOME_LAT))
        self.service.handle_update(1, "longitude", str(HOME_LON))

        assert self.mock_run.called
        # The coroutine passed should be open_door
        call_args = self.mock_run.call_args
        coro = call_args[0][0]
        assert "open_door" in str(coro)

    def test_already_near_home_does_not_trigger(self):
        car = self.service.cars[1]
        car.latitude = str(HOME_LAT)
        car.longitude = str(HOME_LON)
        car.was_near_home = True
        car.shift_state = "D"

        self.service.handle_update(1, "latitude", str(HOME_LAT + 0.0001))
        assert not self.mock_run.called

    def test_not_driving_does_not_trigger(self):
        self._place_car_far_away(1)
        self.service.cars[1].shift_state = "P"  # Parked, not driving

        self.service.handle_update(1, "latitude", str(HOME_LAT))
        self.service.handle_update(1, "longitude", str(HOME_LON))
        assert not self.mock_run.called

    def test_not_initialized_does_not_trigger(self):
        self.service.initialized = False
        self._place_car_far_away(1)

        self.service.handle_update(1, "latitude", str(HOME_LAT))
        assert not self.mock_run.called


# --- GarageDoorService.handle_update (close logic) ---


class TestHandleUpdateClose:
    def setup_method(self):
        self.service = GarageDoorService()
        self.service.initialized = True
        self.service.loop = MagicMock()
        self.run_patcher = patch(
            "garage_door.asyncio.run_coroutine_threadsafe",
            return_value=MagicMock(),
        )
        self.mock_run = self.run_patcher.start()

    def teardown_method(self):
        self.run_patcher.stop()

    def test_leaving_home_triggers_close(self):
        car = self.service.cars[1]
        car.geofence = HOME_GEOFENCE

        self.service.handle_update(1, "geofence", "")

        assert self.mock_run.called
        coro = self.mock_run.call_args[0][0]
        assert "close_door" in str(coro)

    def test_arriving_home_does_not_trigger_close(self):
        car = self.service.cars[1]
        car.geofence = ""

        self.service.handle_update(1, "geofence", HOME_GEOFENCE)
        # Should not have called close (might have called open via distance,
        # but the geofence path shouldn't trigger close)
        for call in self.mock_run.call_args_list:
            coro = call[0][0]
            assert "close_door" not in str(coro)


# --- GarageDoorService.open_door cooldowns ---


class TestOpenDoorCooldowns:
    @pytest.fixture
    def service(self):
        svc = GarageDoorService()
        svc.garage_device = MagicMock()
        svc.garage_device.async_update = AsyncMock()
        svc.garage_device.get_is_open = MagicMock(return_value=False)
        svc.garage_device.async_open = AsyncMock()
        return svc

    @pytest.mark.asyncio
    async def test_open_cooldown_blocks(self, service):
        service.last_open_time = time.time()
        await service.open_door("test")
        service.garage_device.async_open.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_cooldown_blocks_open(self, service):
        service.last_close_time = time.time()
        await service.open_door("test")
        service.garage_device.async_open.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_cooldown_opens(self, service):
        service.last_open_time = 0
        service.last_close_time = 0
        await service.open_door("test")
        service.garage_device.async_open.assert_called_once_with(channel=0)

    @pytest.mark.asyncio
    async def test_already_open_skips(self, service):
        service.garage_device.get_is_open = MagicMock(return_value=True)
        await service.open_door("test")
        service.garage_device.async_open.assert_not_called()


# --- GarageDoorService.close_door safety ---


class TestCloseDoorSafety:
    @pytest.fixture
    def service(self):
        svc = GarageDoorService()
        svc.garage_device = MagicMock()
        svc.garage_device.async_update = AsyncMock()
        svc.garage_device.get_is_open = MagicMock(return_value=True)
        svc.garage_device.async_close = AsyncMock()
        return svc

    @pytest.mark.asyncio
    async def test_close_when_safe(self, service):
        # No cars driving at home
        await service.close_door("test")
        service.garage_device.async_close.assert_called_once_with(channel=0)

    @pytest.mark.asyncio
    async def test_close_refused_car_driving_at_home(self, service):
        car = service.cars[1]
        car.geofence = HOME_GEOFENCE
        car.shift_state = "D"
        await service.close_door("test")
        service.garage_device.async_close.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_refused_car_reversing_at_home(self, service):
        car = service.cars[2]
        car.geofence = HOME_GEOFENCE
        car.shift_state = "R"
        await service.close_door("test")
        service.garage_device.async_close.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_ok_car_driving_not_home(self, service):
        car = service.cars[1]
        car.geofence = ""
        car.shift_state = "D"
        await service.close_door("test")
        service.garage_device.async_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_already_closed_skips(self, service):
        service.garage_device.get_is_open = MagicMock(return_value=False)
        await service.close_door("test")
        service.garage_device.async_close.assert_not_called()
