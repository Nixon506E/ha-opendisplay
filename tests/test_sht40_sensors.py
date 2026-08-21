"""Unit tests for the SHT40 ambient temperature/humidity sensors.

These avoid the full Home Assistant test harness: the entity descriptions are
built directly from a SensorData packet and their ``value_fn`` is applied to a
hand-built coordinator update, which is the whole of the decode path.
"""

from unittest.mock import MagicMock

from opendisplay.models.advertisement import parse_advertisement
from opendisplay.models.config import SensorData
from opendisplay.models.enums import SensorType

from custom_components.opendisplay.coordinator import OpenDisplayUpdate
from custom_components.opendisplay.sensor import (
    _TEMPERATURE_DESCRIPTION,
    _sht40_descriptions,
)

ADDRESS = "AA:BB:CC:DD:EE:FF"
READING = bytes.fromhex("7ca20a")  # 28.0 C / 63.6 %RH


def _sensor(msd_data_start_byte: int = 7) -> SensorData:
    return SensorData(
        instance_number=0,
        sensor_type=SensorType.SHT40,
        bus_id=0,
        i2c_addr_7bit=0x44,
        msd_data_start_byte=msd_data_start_byte,
    )


def _update(block: bytes = READING, start_byte: int = 7) -> OpenDisplayUpdate:
    """A coordinator update whose advertisement carries an SHT40 reading."""
    dynamic = bytearray(11)
    dynamic[start_byte : start_byte + 3] = block
    advertisement = parse_advertisement(bytes(dynamic) + bytes([124, 139, 0]))
    return OpenDisplayUpdate(address=ADDRESS, advertisement=advertisement)


def _values(sensor: SensorData, update: OpenDisplayUpdate) -> dict[str, float | None]:
    return {d.key: d.value_fn(update) for d in _sht40_descriptions(sensor)}


def test_reads_temperature_and_humidity():
    values = _values(_sensor(), _update())

    assert values["sht40_0_temperature"] == 28.0
    assert values["sht40_0_humidity"] == 63.6


def test_reads_from_the_configured_offset():
    """E1001/E1002/E1004 place the block at 1, not the firmware default of 7."""
    values = _values(_sensor(msd_data_start_byte=1), _update(start_byte=1))

    assert values["sht40_0_temperature"] == 28.0


def test_offset_zero_resolves_to_the_default_slot():
    """0 means "use the default", not byte 0 -- so the reading is still found."""
    values = _values(_sensor(msd_data_start_byte=0), _update(start_byte=7))

    assert values["sht40_0_temperature"] == 28.0


def test_failed_read_reports_unknown():
    """FF FF FF is the firmware's read-failure sentinel, not a measurement."""
    values = _values(_sensor(), _update(block=b"\xff\xff\xff"))

    assert values["sht40_0_temperature"] is None
    assert values["sht40_0_humidity"] is None


def test_unwritten_slot_reports_unknown():
    """An all-zero slot decodes to -40 C / 0 %RH but means "never written"."""
    values = _values(_sensor(), _update(block=b"\x00\x00\x00"))

    assert values["sht40_0_temperature"] is None
    assert values["sht40_0_humidity"] is None


def test_entities_are_primary_not_diagnostic():
    """Ambient readings are what the device is for; the chip temperature is not."""
    for description in _sht40_descriptions(_sensor()):
        assert description.entity_category is None
        assert description.entity_registry_enabled_default is True


def test_chip_temperature_stays_diagnostic_and_disabled():
    assert _TEMPERATURE_DESCRIPTION.entity_category is not None
    assert _TEMPERATURE_DESCRIPTION.entity_registry_enabled_default is False


def test_chip_temperature_keeps_its_unique_id_key():
    """Renaming is display-only: changing the key would orphan existing entities."""
    assert _TEMPERATURE_DESCRIPTION.key == "temperature"
    assert _TEMPERATURE_DESCRIPTION.translation_key == "chip_temperature"


def test_keys_are_distinct_per_instance():
    """A second SHT40 must not collide with the first one's unique_id."""
    first = {d.key for d in _sht40_descriptions(_sensor())}
    second_sensor = _sensor()
    second_sensor.instance_number = 1

    assert first.isdisjoint({d.key for d in _sht40_descriptions(second_sensor)})


def test_value_is_none_before_any_advertisement():
    """native_value guards on coordinator.data being None."""
    from custom_components.opendisplay.sensor import OpenDisplaySensorEntity

    coordinator = MagicMock()
    coordinator.data = None
    entity = OpenDisplaySensorEntity(coordinator, _sht40_descriptions(_sensor())[0])

    assert entity.native_value is None
