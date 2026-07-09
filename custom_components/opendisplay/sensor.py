"""Sensor platform for OpenDisplay devices."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import time

from opendisplay import voltage_to_percent
from opendisplay.models.enums import CapacityEstimator, PowerMode

from homeassistant.components.bluetooth import async_last_service_info
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OpenDisplayConfigEntry
from .coordinator import OpenDisplayUpdate
from .entity import OpenDisplayEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class OpenDisplaySensorEntityDescription(SensorEntityDescription):
    """Describes an OpenDisplay sensor entity."""

    value_fn: Callable[[OpenDisplayUpdate], float | int | str | datetime | None]


_TEMPERATURE_DESCRIPTION = OpenDisplaySensorEntityDescription(
    key="temperature",
    device_class=SensorDeviceClass.TEMPERATURE,
    native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    state_class=SensorStateClass.MEASUREMENT,
    entity_category=EntityCategory.DIAGNOSTIC,
    entity_registry_enabled_default=False,
    value_fn=lambda upd: upd.advertisement.temperature_c,
)

_BATTERY_POWER_MODES = {PowerMode.BATTERY, PowerMode.SOLAR}

_BATTERY_VOLTAGE_DESCRIPTION = OpenDisplaySensorEntityDescription(
    key="battery_voltage",
    translation_key="battery_voltage",
    device_class=SensorDeviceClass.VOLTAGE,
    native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
    state_class=SensorStateClass.MEASUREMENT,
    entity_category=EntityCategory.DIAGNOSTIC,
    entity_registry_enabled_default=False,
    value_fn=lambda upd: upd.advertisement.battery_mv,
)

_RSSI_DESCRIPTION = OpenDisplaySensorEntityDescription(
    key="rssi",
    translation_key="rssi",
    device_class=SensorDeviceClass.SIGNAL_STRENGTH,
    native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    state_class=SensorStateClass.MEASUREMENT,
    entity_category=EntityCategory.DIAGNOSTIC,
    entity_registry_enabled_default=False,
    value_fn=lambda upd: upd.rssi,
)

_LAST_SEEN_DESCRIPTION = OpenDisplaySensorEntityDescription(
    key="last_seen",
    translation_key="last_seen",
    device_class=SensorDeviceClass.TIMESTAMP,
    entity_category=EntityCategory.DIAGNOSTIC,
    entity_registry_enabled_default=False,
    # native_value is overridden by OpenDisplayLastSeenSensor, so this value_fn
    # is dead code; value_fn is a required field, hence the no-op.
    value_fn=lambda _upd: None,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OpenDisplayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up OpenDisplay sensor entities."""
    coordinator = entry.runtime_data.coordinator
    power_config = entry.runtime_data.device_config.power
    descriptions: list[OpenDisplaySensorEntityDescription] = [
        _TEMPERATURE_DESCRIPTION,
        _RSSI_DESCRIPTION,
        _LAST_SEEN_DESCRIPTION,
    ]

    if power_config.power_mode_enum in _BATTERY_POWER_MODES:
        capacity_estimator = power_config.capacity_estimator or CapacityEstimator.LI_ION
        descriptions += [
            _BATTERY_VOLTAGE_DESCRIPTION,
            OpenDisplaySensorEntityDescription(
                key="battery",
                device_class=SensorDeviceClass.BATTERY,
                native_unit_of_measurement=PERCENTAGE,
                state_class=SensorStateClass.MEASUREMENT,
                entity_category=EntityCategory.DIAGNOSTIC,
                value_fn=lambda upd: voltage_to_percent(
                    upd.advertisement.battery_mv, capacity_estimator
                ),
            ),
        ]

    async_add_entities(
        (
            OpenDisplayLastSeenSensor(coordinator, description)
            if description.key == "last_seen"
            else OpenDisplaySensorEntity(coordinator, description)
        )
        for description in descriptions
    )


class OpenDisplaySensorEntity(OpenDisplayEntity, SensorEntity):
    """A sensor entity for an OpenDisplay device."""

    entity_description: OpenDisplaySensorEntityDescription

    @property
    def native_value(self) -> float | int | str | datetime | None:
        """Return the sensor value."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)


class OpenDisplayLastSeenSensor(OpenDisplaySensorEntity):
    """last_seen sourced from the bluetooth stack, not the gated callback."""

    @property
    def native_value(self) -> datetime | None:
        # connectable=False matches the Bluetooth advertisement monitor's
        # "updated" field: _all_history, refreshed on every received advert
        # before core's connectable/de-dup gates.
        info = async_last_service_info(
            self.hass, self.coordinator.address, connectable=False
        )
        if info is None:
            return None
        # info.time is a monotonic clock (monotonic_time_coarse); convert to
        # wall time with the same offset the advertisement monitor uses.
        wall = info.time + (time.time() - time.monotonic())
        return datetime.fromtimestamp(wall, tz=timezone.utc)
