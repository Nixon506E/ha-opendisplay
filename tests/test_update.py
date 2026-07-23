"""Unit tests for the firmware update entity's version formatting.

``_format_firmware_version`` used to divide two-digit minors by 10, on the
theory that the firmware byte stored minor*10. That's not true: both
Firmware_NRF52840_ESP32/src/communication.cpp and Firmware_NRF52/EPD/EPD_service.c
parse BUILD_VERSION with a plain int conversion on the substring after the dot,
so the minor byte always equals the literal tag digits (2.20 -> 20, 1.71 -> 71,
1.6 -> 6). See issue #62: a device on 2.20 was displayed as 2.2.
"""

import pytest

from custom_components.opendisplay.update import _format_firmware_version


@pytest.mark.parametrize(
    ("major", "minor", "expected"),
    [
        (2, 20, "2.20"),
        (1, 71, "1.71"),
        (1, 82, "1.82"),
        (1, 6, "1.6"),
        (1, 0, "1.0"),
        (0, 68, "0.68"),
    ],
)
def test_format_firmware_version(major, minor, expected):
    assert _format_firmware_version(major, minor) == expected
