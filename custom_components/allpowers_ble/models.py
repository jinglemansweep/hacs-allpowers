from __future__ import annotations
from dataclasses import dataclass

# from sonicare_bletb import SonicareBLETB
from .coordinator import AllpowersBLECoordinator


@dataclass
class AllpowersBLEData:
    """Data for Allpowers BLE battery integration."""

    title: str
    # device: SonicareBLETB
    coordinator: AllpowersBLECoordinator
