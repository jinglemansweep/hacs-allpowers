DOMAIN = "allpowers_ble"
LOCAL_NAMES = {"Allpowers"}

CHARACTERISTIC_NOTIFY = "0000FFF1-0000-1000-8000-00805F9B34FB"
CHARACTERISTIC_WRITE = "0000FFF2-0000-1000-8000-00805F9B34FB"


class CharacteristicMissingError(Exception):
    """Raised when a characteristic is missing."""
