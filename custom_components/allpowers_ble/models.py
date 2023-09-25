from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from .allpowers import AllpowersBLE
    from .coordinator import AllpowersBLECoordinator


@dataclass
class AllpowersBLEData:
    """Data for Allpowers BLE battery integration."""

    title: str
    device: AllpowersBLE
    coordinator: AllpowersBLECoordinator


@dataclass(frozen=False)
class AllpowersState:
    """State model for Allpowers devices."""

    ac_on: bool = False
    dc_on: bool = False
    light_on: bool = False
    percent_remain: int = 0
    minutes_remain: int = 0
    watts_import: int = 0
    watts_export: int = 0
