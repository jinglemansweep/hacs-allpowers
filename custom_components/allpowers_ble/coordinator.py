import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from .allpowers import AllpowersBLE, AllpowersState
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class AllpowersBLECoordinator(DataUpdateCoordinator[None]):
    """Data coordinator for receiving updates from Allpowers BLE battery"""

    def __init__(self, hass: HomeAssistant, allpowers_ble: AllpowersBLE) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
        )
        self._allpowers_ble = allpowers_ble
        allpowers_ble.register_callback(self._async_handle_update)
        allpowers_ble.register_disconnected_callback(self._async_handle_disconnect)
        self.connected = True

    @callback
    def _async_handle_update(self, state: AllpowersState) -> None:
        """Just trigger the callbacks."""
        _LOGGER.warning("_async_handle_update")
        self.connected = True
        # _LOGGER.info("state", state)
        self.async_set_updated_data(None)

    @callback
    def _async_handle_disconnect(self) -> None:
        """Trigger the callbacks for disconnected."""
        _LOGGER.warning("_async_handle_disconnect")
        self.connected = False
        self.async_update_listeners()
