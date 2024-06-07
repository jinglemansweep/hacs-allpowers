from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, PERCENTAGE, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AllpowersBLE, AllpowersBLECoordinator
from .const import DOMAIN
from .models import AllpowersBLEData

from typing import Dict, Any

AC_SWITCH_DESCRIPTION = SwitchEntityDescription(
    key="ac",
    device_class=SwitchDeviceClass.OUTLET,
    entity_registry_enabled_default=True,
    entity_registry_visible_default=True,
    has_entity_name=True,
    name="AC",
)

DC_SWITCH_DESCRIPTION = SwitchEntityDescription(
    key="dc",
    device_class=SwitchDeviceClass.OUTLET,
    entity_registry_enabled_default=True,
    entity_registry_visible_default=True,
    has_entity_name=True,
    name="DC",
)

TORCH_SWITCH_DESCRIPTION = SwitchEntityDescription(
    key="torch",
    device_class=SwitchDeviceClass.SWITCH,
    entity_registry_enabled_default=True,
    entity_registry_visible_default=True,
    has_entity_name=True,
    name="Light",
)

SWITCH_DESCRIPTIONS = [
    AC_SWITCH_DESCRIPTION,
    DC_SWITCH_DESCRIPTION,
    TORCH_SWITCH_DESCRIPTION,
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the platform for Allpowers BLE"""
    data: AllpowersBLEData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        AllpowersBLESwitch(
            data.coordinator,
            data.device,
            entry.title,
            description,
        )
        for description in SWITCH_DESCRIPTIONS
    )


class AllpowersBLESwitch(
    CoordinatorEntity[AllpowersBLECoordinator], SwitchEntity, RestoreEntity
):
    """Generic switch for Allpowers BLE"""

    def __init__(
        self,
        coordinator: AllpowersBLECoordinator,
        device: AllpowersBLE,
        name: str,
        description: SwitchEntityDescription,
    ) -> None:
        """Initialize switch"""
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._device = device
        self._attr_is_on = False
        self._last_action = None
        self._key = description.key
        self.entity_description = description
        self._attr_unique_id = f"{device.address}_{self._key}"
        self._attr_device_info = DeviceInfo(
            name=name,
            connections={(dr.CONNECTION_BLUETOOTH, device.address)},
        )
        self._icon = "mdi:light-switch"

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added."""
        await super().async_added_to_hass()
        if not (last_state := await self.async_get_last_state()):
            return
        self._attr_is_on = last_state.state == STATE_ON
        if "last_run_success" in last_state.attributes:
            self._last_run_success = last_state.attributes["last_run_success"]

    async def async_turn_off(self, **kwargs) -> None:
        """Turn entity off"""
        if self._key not in ["ac", "dc", "torch"]:
            return
        self._last_run_success = bool(
            await getattr(self._device, f"set_{self._key}")(False)
        )
        if self._last_run_success:
            self._attr_is_on = False
            self._last_action = "Off"
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        """Turn entity off"""
        if self._key not in ["ac", "dc", "torch"]:
            return
        self._last_run_success = bool(
            await getattr(self._device, f"set_{self._key}")(True)
        )
        if self._last_run_success:
            self._attr_is_on = False
            self._last_action = "On"
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator"""
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Unavailable if coordinator isn't connected"""
        return True

    @property
    def is_on(self) -> bool | None:
        """Return true if device is on"""
        if self._key == "ac":
            return self._device.ac_on
        elif self._key == "dc":
            return self._device.dc_on
        elif self._key == "torch":
            return self._device.light_on
        else:
            return False

    @property
    def assumed_state(self) -> bool:
        """Returns the last known state if unable to access real state of entity"""
        return self._last_action == "On"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return the state attributes"""
        return {"last_action": self._last_action}
