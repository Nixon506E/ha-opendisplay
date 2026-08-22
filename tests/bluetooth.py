"""Bluetooth test helpers vendored from Home Assistant core.

pytest-homeassistant-custom-component ships core's *fixtures*
(``enable_bluetooth``, ``mock_bluetooth_adapters``, ``mock_bleak_scanner_start``
in ``plugins.py``) but none of the per-component test helpers, so the functions
below are copied from core's ``tests/components/bluetooth/__init__.py``.

Vendored from home-assistant/core @ 2026.9.0.dev0. Only the helpers this
integration's tests actually use are kept; refresh from upstream if a test
needs more, and keep the bodies identical so behaviour tracks core.
"""

from collections.abc import Generator
from contextlib import contextmanager
import itertools
import time as time_module
from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch

from bleak.backends.scanner import AdvertisementData, BLEDevice
from habluetooth import get_manager
from homeassistant.components.bluetooth import (
    SOURCE_LOCAL,
    BluetoothServiceInfo,
    BluetoothServiceInfoBleak,
    async_get_advertisement_callback,
)
from homeassistant.components.bluetooth.manager import HomeAssistantBluetoothManager
from homeassistant.core import HomeAssistant

__all__ = (
    "generate_advertisement_data",
    "generate_ble_device",
    "inject_advertisement",
    "inject_bluetooth_service_info",
    "inject_bluetooth_service_info_bleak",
    "patch_all_discovered_devices",
    "patch_bluetooth_time",
)

ADVERTISEMENT_DATA_DEFAULTS = {
    "local_name": "",
    "manufacturer_data": {},
    "service_data": {},
    "service_uuids": [],
    "rssi": -127,
    "platform_data": ((),),
    "tx_power": -127,
}

BLE_DEVICE_DEFAULTS = {
    "name": None,
    "details": None,
}


@contextmanager
def patch_bluetooth_time(mock_time: float) -> Generator[None]:
    """Patch the bluetooth time."""
    with (
        patch(
            "homeassistant.components.bluetooth.MONOTONIC_TIME", return_value=mock_time
        ),
        patch("habluetooth.base_scanner.monotonic_time_coarse", return_value=mock_time),
        patch("habluetooth.manager.monotonic_time_coarse", return_value=mock_time),
        patch("habluetooth.scanner.monotonic_time_coarse", return_value=mock_time),
    ):
        yield


def generate_advertisement_data(**kwargs: Any) -> AdvertisementData:
    """Generate advertisement data with defaults."""
    new = kwargs.copy()
    for key, value in ADVERTISEMENT_DATA_DEFAULTS.items():
        new.setdefault(key, value)
    return AdvertisementData(**new)


def generate_ble_device(
    address: str | None = None,
    name: str | None = None,
    details: Any | None = None,
    **kwargs: Any,
) -> BLEDevice:
    """Generate a BLEDevice with defaults."""
    new = kwargs.copy()
    if address is not None:
        new["address"] = address
    if name is not None:
        new["name"] = name
    if details is not None:
        new["details"] = details
    for key, value in BLE_DEVICE_DEFAULTS.items():
        new.setdefault(key, value)
    return BLEDevice(**new)


def _get_manager() -> HomeAssistantBluetoothManager:
    """Return the bluetooth manager."""
    manager: HomeAssistantBluetoothManager = get_manager()
    return manager


def inject_advertisement(
    hass: HomeAssistant, device: BLEDevice, adv: AdvertisementData
) -> None:
    """Inject an advertisement into the manager."""
    return _inject_advertisement_with_time_and_source_connectable(
        hass, device, adv, time_module.monotonic(), SOURCE_LOCAL, True
    )


def _inject_advertisement_with_time_and_source_connectable(
    hass: HomeAssistant,
    device: BLEDevice,
    adv: AdvertisementData,
    time: float,
    source: str,
    connectable: bool,
    raw: bytes | None = None,
) -> None:
    """Inject an advertisement at a time from a source with connectable status."""
    async_get_advertisement_callback(hass)(
        BluetoothServiceInfoBleak(
            name=adv.local_name or device.name or device.address,
            address=device.address,
            rssi=adv.rssi,
            manufacturer_data=adv.manufacturer_data,
            service_data=adv.service_data,
            service_uuids=adv.service_uuids,
            source=source,
            device=device,
            advertisement=adv,
            connectable=connectable,
            time=time,
            tx_power=adv.tx_power,
            raw=raw,
        )
    )


def inject_bluetooth_service_info_bleak(
    hass: HomeAssistant, info: BluetoothServiceInfoBleak
) -> None:
    """Inject an advertisement into the manager with connectable status."""
    advertisement_data = generate_advertisement_data(
        local_name=None if info.name == "" else info.name,
        manufacturer_data=info.manufacturer_data,
        service_data=info.service_data,
        service_uuids=info.service_uuids,
        rssi=info.rssi,
    )
    device = generate_ble_device(
        address=info.address,
        name=info.name,
        details={},
    )
    _inject_advertisement_with_time_and_source_connectable(
        hass,
        device,
        advertisement_data,
        info.time,
        SOURCE_LOCAL,
        connectable=info.connectable,
    )


def inject_bluetooth_service_info(
    hass: HomeAssistant, info: BluetoothServiceInfo
) -> None:
    """Inject a BluetoothServiceInfo into the manager."""
    advertisement_data = generate_advertisement_data(
        local_name=None if info.name == "" else info.name,
        manufacturer_data=info.manufacturer_data,
        service_data=info.service_data,
        service_uuids=info.service_uuids,
        rssi=info.rssi,
    )
    device = generate_ble_device(
        address=info.address,
        name=info.name,
        details={},
    )
    inject_advertisement(hass, device, advertisement_data)


@contextmanager
def patch_all_discovered_devices(mock_discovered: list[BLEDevice]) -> Generator[None]:
    """Mock all the discovered devices from all the scanners."""
    manager = _get_manager()
    scanners = list(
        itertools.chain(
            manager._connectable_scanners,
            manager._non_connectable_scanners,
        )
    )
    if scanners and getattr(scanners[0], "scanner", None):
        with patch.object(
            scanners[0].scanner.__class__,
            "discovered_devices_and_advertisement_data",
            new=PropertyMock(
                side_effect=[
                    {
                        device.address: (device, MagicMock())
                        for device in mock_discovered
                    },
                ]
                + [{}] * (len(scanners))
            ),
        ):
            yield
    else:
        yield
