from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AllpowersBLE, AllpowersBLECoordinator
from .const import DOMAIN
from .models import AllpowersBLEData

BATTERY_LEVEL_DESCRIPTION = SensorEntityDescription(
    key="percent_remain",
    device_class=SensorDeviceClass.BATTERY,
    entity_registry_enabled_default=True,
    entity_registry_visible_default=True,
    has_entity_name=True,
    name="Battery Percentage Remaining",
    native_unit_of_measurement=PERCENTAGE,
    state_class=SensorStateClass.MEASUREMENT,
)

SENSOR_DESCRIPTIONS = [
    BATTERY_LEVEL_DESCRIPTION,
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the platform for Allpowers BLE"""
    data: AllpowersBLEData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        AllpowersBLESensor(
            data.coordinator,
            data.device,
            entry.title,
            description,
        )
        for description in SENSOR_DESCRIPTIONS
    )


class AllpowersBLESensor(
    CoordinatorEntity[AllpowersBLECoordinator], SensorEntity, RestoreEntity
):
    """Generic sensor for Allpowers BLE"""

    def __init__(
        self,
        coordinator: AllpowersBLECoordinator,
        device: AllpowersBLE,
        name: str,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._device = device
        self._key = description.key
        self.entity_description = description
        self._attr_unique_id = f"{device.address}_{self._key}"
        self._attr_device_info = DeviceInfo(
            name=name,
            connections={(dr.CONNECTION_BLUETOOTH, device.address)},
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if not (last_state := await self.async_get_last_state()):
            return
        self._attr_native_value = last_state.state

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator"""
        self._attr_native_value = getattr(self._device, self._key)
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Unavailable if coordinator isn't connected"""
        return True

    @property
    def assumed_state(self) -> bool:
        return not self._coordinator.connected

    @property
    def native_value(self) -> str | int | None:
        return getattr(self._device, self._key)
