"""Unit tests for the firmware update entity's version formatting.

``_format_firmware_version`` used to divide two-digit minors by 10, on the
theory that the firmware byte stored minor*10. That's not true: both
Firmware_NRF52840_ESP32/src/communication.cpp and Firmware_NRF52/EPD/EPD_service.c
parse BUILD_VERSION with a plain int conversion on the substring after the dot,
so the minor byte always equals the literal tag digits (2.20 -> 20, 1.71 -> 71,
1.6 -> 6). See issue #62: a device on 2.20 was displayed as 2.2.
"""

from awesomeversion import AwesomeVersion
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


@pytest.mark.parametrize(
    ("major", "minor", "patch", "expected"),
    [
        # patch available (py-opendisplay parses the trailing patch byte):
        # three-part form so a device on 2.25.1 matches its release tag.
        (2, 25, 1, "2.25.1"),
        (2, 25, 0, "2.25.0"),
        # patch unavailable (cached firmware dict written before the patch byte
        # was parsed): fall back to the two-part form. This is transient — it
        # still compares older than a patch release, so the device shows a
        # pending update until it is next interrogated. `.0` would not help
        # either, since 2.25.0 < 2.25.1 too.
        (2, 25, None, "2.25"),
    ],
)
def test_format_firmware_version_with_patch(major, minor, patch, expected):
    assert _format_firmware_version(major, minor, patch) == expected


@pytest.mark.parametrize(
    ("installed", "latest_tag", "expect_update"),
    [
        # The regression this exists for (issue #62): newest firmware against
        # the newest release must report no update.
        ((2, 25, 1), "2.25.1", False),
        ((3, 0, 0), "3.0.0", False),
        # A genuinely newer release is still offered.
        ((2, 25, 0), "2.25.1", True),
        ((2, 23, 0), "2.25.1", True),
        # Legacy two-part release tags: firmware reporting patch 0 formats as
        # x.y.0, which AwesomeVersion ranks equal to the bare "x.y" tag, so
        # devices on pre-SemVer releases do not gain a phantom update.
        ((2, 23, 0), "2.23", False),
        ((1, 71, 0), "1.71", False),
    ],
)
def test_update_offered_only_when_genuinely_newer(installed, latest_tag, expect_update):
    """installed_version and latest_version must be comparable like-for-like.

    ``latest_version`` is the GitHub tag verbatim, so a two-part installed
    string ranks below a patch release of the same minor — which is what made
    an update look permanently pending.
    """
    formatted = _format_firmware_version(*installed)
    assert (AwesomeVersion(latest_tag) > AwesomeVersion(formatted)) is expect_update
