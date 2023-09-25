from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Callable
from typing import Any, TypeVar

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakDBusError, BleakError
from bleak_retry_connector import BLEAK_RETRY_EXCEPTIONS as BLEAK_EXCEPTIONS
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    BleakNotFoundError,
    establish_connection,
    retry_bluetooth_connection_error,
)
from const import CHARACTERISTIC_NOTIFY, CHARACTERISTIC_WRITE
from models import AllpowersState

BLEAK_BACKOFF_TIME = 0.25

__version__ = "0.0.0"


WrapFuncType = TypeVar("WrapFuncType", bound=Callable[..., Any])

RETRY_BACKOFF_EXCEPTIONS = (BleakDBusError,)

_LOGGER = logging.getLogger(__name__)

DEFAULT_ATTEMPTS = sys.maxsize


class CharacteristicMissingError(Exception):
    """Raised when a characteristic is missing."""


class AllpowersBLE:
    """Allpowers BLE interface."""

    def __init__(
        self,
        ble_device: BLEDevice,
        advertisement_data: AdvertisementData | None = None,
    ) -> None:
        """Init the Allpowers BLE."""
        self._ble_device = ble_device
        self._advertisement_data = advertisement_data
        self._operation_lock = asyncio.Lock()
        self._state = AllpowersState()
        self._connect_lock: asyncio.Lock = asyncio.Lock()
        self._client: BleakClientWithServiceCache | None = None
        self._expected_disconnect = False
        self.loop = asyncio.get_running_loop()
        self._callbacks: list[Callable[[AllpowersState], None]] = []
        self._disconnected_callbacks: list[Callable[[], None]] = []
        self._buf = b""

    def set_ble_device_and_advertisement_data(
        self, ble_device: BLEDevice, advertisement_data: AdvertisementData
    ) -> None:
        """Set the ble device."""
        self._ble_device = ble_device
        self._advertisement_data = advertisement_data

    @property
    def address(self) -> str:
        """Return the address."""
        return self._ble_device.address

    @property
    def _address(self) -> str:
        """Return the address."""
        return self._ble_device.address

    @property
    def name(self) -> str:
        """Get the name of the device."""
        return self._ble_device.name or self._ble_device.address

    @property
    def rssi(self) -> int | None:
        """Get the rssi of the device."""
        if self._advertisement_data:
            return self._advertisement_data.rssi
        return None

    @property
    def state(self) -> AllpowersState:
        """Return the state."""
        return self._state

    @property
    def ac_on(self) -> bool:
        """Return the state of AC."""
        return self._state.ac_on

    @property
    def dc_on(self) -> bool:
        """Return the state of DC."""
        return self._state.dc_on

    @property
    def light_on(self) -> bool:
        """Return the state of Light."""
        return self._state.light_on

    @property
    def percent_remain(self) -> int:
        """Return percentage battery remaining."""
        return self._state.percent_remain

    @property
    def minutes_remain(self) -> int:
        """Return minutes of battery remaining."""
        return self._state.minutes_remain

    @property
    def watts_import(self) -> int:
        """Return incoming power in watts."""
        return self._state.watts_import

    @property
    def watts_export(self) -> int:
        """Return outgoing power in watts."""
        return self._state.watts_export

    async def _change_status_to_device(self) -> None:
        """Send the current state back to the device."""
        full = bytes.fromhex("a56500b10101000071")
        s = bytearray(9)
        for x in range(9):
            s[x] = full[x]

        s[7] = 0

        s[7] = s[7] ^ (1 << 5) if self.light_on else s[7] & ~(1 << 5)
        s[7] = s[7] ^ (1 << 0) if self.dc_on else s[7] & ~(1 << 0)
        s[7] = s[7] ^ (1 << 1) if self.ac_on else s[7] & ~(1 << 1)

        # I'm sure this checksum algo isn't complete/correct,
        # but it certainly works for all the scenarios we care about
        s[8] = 113 - s[7]
        if self.ac_on:
            s[8] = s[8] + 4

        if self._client is not None:
            await self._client.write_gatt_char(CHARACTERISTIC_WRITE, s)

    async def set_torch(self, enabled: bool) -> None:
        """Set the current value of the light."""
        self._state.light_on = enabled
        await self._change_status_to_device()

    async def set_ac(self, enabled: bool) -> None:
        """Set the current value of the AC."""
        self._state.ac_on = enabled
        await self._change_status_to_device()

    async def set_dc(self, enabled: bool) -> None:
        """Set the current value of the DC."""
        self._state.dc_on = enabled
        await self._change_status_to_device()

    async def stop(self) -> None:
        """Stop the Allpowers BLE."""
        _LOGGER.debug("%s: Stop", self.name)
        await self._execute_disconnect()

    def _fire_callbacks(self) -> None:
        """Fire the callbacks."""
        for callback in self._callbacks:
            callback(self._state)

    def register_callback(
        self, callback: Callable[[AllpowersState], None]
    ) -> Callable[[], None]:
        """Register a callback to be called when the state changes."""

        def unregister_callback() -> None:
            self._callbacks.remove(callback)

        self._callbacks.append(callback)
        return unregister_callback

    def _fire_disconnected_callbacks(self) -> None:
        """Fire the callbacks."""
        for callback in self._disconnected_callbacks:
            callback()

    def register_disconnected_callback(
        self, callback: Callable[[], None]
    ) -> Callable[[], None]:
        """Register a callback to be called when the state changes."""

        def unregister_callback() -> None:
            self._disconnected_callbacks.remove(callback)

        self._disconnected_callbacks.append(callback)
        return unregister_callback

    async def initialise(self) -> None:
        """Initialize the device."""
        _LOGGER.debug("%s: Sending configuration commands", self.name)
        await self._ensure_connected()

        _LOGGER.debug("%s: Subscribe to notifications; RSSI: %s", self.name, self.rssi)
        if self._client is not None:
            await self._client.start_notify(
                CHARACTERISTIC_NOTIFY, self._notification_handler
            )

    async def _ensure_connected(self) -> None:
        """Ensure connection to device is established."""
        if self._connect_lock.locked():
            _LOGGER.debug(
                "%s: Connection already in progress, "
                + "waiting for it to complete; RSSI: %s",
                self.name,
                self.rssi,
            )
        if self._client and self._client.is_connected:
            return
        async with self._connect_lock:
            # Check again while holding the lock
            if self._client and self._client.is_connected:
                return
            _LOGGER.debug("%s: Connecting; RSSI: %s", self.name, self.rssi)
            client = await establish_connection(
                BleakClientWithServiceCache,
                self._ble_device,
                self.name,
                self._disconnected,
                use_services_cache=True,
                ble_device_callback=lambda: self._ble_device,
            )
            _LOGGER.debug("%s: Connected; RSSI: %s", self.name, self.rssi)

            self._client = client

    async def _reconnect(self) -> None:
        """Attempt a reconnect."""
        _LOGGER.debug("ensuring connection")
        try:
            await self._ensure_connected()
            _LOGGER.debug("ensured connection - initialising")
            await self.initialise()
        except BleakNotFoundError:
            _LOGGER.debug("failed to ensure connection - backing off")
            await asyncio.sleep(BLEAK_BACKOFF_TIME)
            _LOGGER.debug("reconnecting again")
            _dummy = asyncio.create_task(self._reconnect())

    def _notification_handler(self, _sender: int, data: bytearray) -> None:
        """Handle notification responses."""
        _LOGGER.debug("%s: Notification received: %s", self.name, data.hex())

        self._buf += data

        battery_percentage = data[8]
        dc_on = data[7] >> 0 & 1 == 1
        ac_on = data[7] >> 1 & 1 == 1
        torch_on = data[7] >> 4 & 1 == 1
        output_power = (256 * data[11]) + data[12]
        input_power = (256 * data[9]) + data[10]
        minutes_remaining = (256 * data[13]) + data[14]

        self._state = AllpowersState(
            ac_on=ac_on,
            dc_on=dc_on,
            light_on=torch_on,
            percent_remain=battery_percentage,
            minutes_remain=minutes_remaining,
            watts_export=output_power,
            watts_import=input_power,
        )

        self._fire_callbacks()

        _LOGGER.debug(
            "%s: Notification received; RSSI: %s: %s %s",
            self.name,
            self.rssi,
            data.hex(),
            self._state,
        )

    def _disconnected(self, client: BleakClientWithServiceCache) -> None:
        """Disconnected callback."""
        self._fire_disconnected_callbacks()
        if self._expected_disconnect:
            _LOGGER.debug(
                "%s: Disconnected from device; RSSI: %s", self.name, self.rssi
            )
            return
        _LOGGER.warning(
            "%s: Device unexpectedly disconnected; RSSI: %s",
            self.name,
            self.rssi,
        )
        _dummy = asyncio.create_task(self._reconnect())

    def _disconnect(self) -> None:
        """Disconnect from device."""
        _dummy = asyncio.create_task(self._execute_timed_disconnect())

    async def _execute_timed_disconnect(self) -> None:
        """Execute timed disconnection."""
        _LOGGER.debug(
            "%s: Disconnecting",
            self.name,
        )
        await self._execute_disconnect()

    async def _execute_disconnect(self) -> None:
        """Execute disconnection."""
        async with self._connect_lock:
            client = self._client
            self._expected_disconnect = True
            self._client = None
            if client and client.is_connected:
                await client.stop_notify(CHARACTERISTIC_NOTIFY)
                await client.disconnect()

    @retry_bluetooth_connection_error(DEFAULT_ATTEMPTS)
    async def _send_command_locked(self, commands: list[bytes]) -> None:
        """Send command to device and read response."""
        try:
            await self._execute_command_locked(commands)
        except BleakDBusError as ex:
            # Disconnect so we can reset state and try again
            await asyncio.sleep(BLEAK_BACKOFF_TIME)
            _LOGGER.debug(
                "%s: RSSI: %s; Backing off %ss; Disconnecting due to error: %s",
                self.name,
                self.rssi,
                BLEAK_BACKOFF_TIME,
                ex,
            )
            await self._execute_disconnect()
            raise
        except BleakError as ex:
            # Disconnect so we can reset state and try again
            _LOGGER.debug(
                "%s: RSSI: %s; Disconnecting due to error: %s", self.name, self.rssi, ex
            )
            await self._execute_disconnect()
            raise

    async def _send_command(
        self, commands: list[bytes] | bytes, retry: int | None = None
    ) -> None:
        """Send command to device and read response."""
        await self._ensure_connected()
        if not isinstance(commands, list):
            commands = [commands]
        await self._send_command_while_connected(commands, retry)

    async def _send_command_while_connected(
        self, commands: list[bytes], retry: int | None = None
    ) -> None:
        """Send command to device and read response."""
        _LOGGER.debug(
            "%s: Sending commands %s",
            self.name,
            [command.hex() for command in commands],
        )
        if self._operation_lock.locked():
            _LOGGER.debug(
                "%s: Operation already in progress,"
                + "waiting for it to complete; RSSI: %s",
                self.name,
                self.rssi,
            )
        async with self._operation_lock:
            try:
                await self._send_command_locked(commands)
                return
            except BleakNotFoundError:
                _LOGGER.error(
                    "%s: device not found, no longer in range," + "or poor RSSI: %s",
                    self.name,
                    self.rssi,
                    exc_info=True,
                )
                raise
            except CharacteristicMissingError as ex:
                _LOGGER.debug(
                    "%s: characteristic missing: %s; RSSI: %s",
                    self.name,
                    ex,
                    self.rssi,
                    exc_info=True,
                )
                raise
            except BLEAK_EXCEPTIONS:
                _LOGGER.debug("%s: communication failed", self.name, exc_info=True)
                raise

        raise RuntimeError("Unreachable")

    async def _execute_command_locked(self, commands: list[bytes]) -> None:
        """Execute command and read response."""
        if self._client is not None:
            for command in commands:
                await self._client.write_gatt_char(CHARACTERISTIC_WRITE, command, False)
