"""Unit tests for the write_nfc service.

Mirrors the test_services.py approach: no Home Assistant test harness; the
service module's touchpoints (``_get_entry_for_device``,
``_async_connect_and_run``) are patched in the services module namespace so
the schema validation, capability gating, content transforms, size checks
and error translation can be exercised directly.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from opendisplay import NfcNotSupportedError, NfcWriteError
import pytest
import voluptuous as vol

from custom_components.opendisplay import services as services_mod
from custom_components.opendisplay.services import (
    ATTR_CONTENT,
    ATTR_MIME_TYPE,
    ATTR_RECORD_TYPE,
    HA_TAG_URL_PREFIX,
    NFC_MAX_PAYLOAD,
    SCHEMA_WRITE_NFC,
    _async_write_nfc,
)
from custom_components.opendisplay.sleep import SleepProfile

DEVICE_ID = "device-1"


def _profile(**overrides):
    params = {
        "sleep_mode": "off",
        "power_mode": 1,
        "sleep_timeout_ms": 0,
        "deep_sleep_time_seconds": 300,
        "missed_cycles": 3,
        "queue_timeout_hours": 24,
    }
    params.update(overrides)
    return SleepProfile.create(**params)


def _make_entry(*, nfc_configs="default", sleepy=False, last_seen=None):
    """Return a fake config entry with the runtime_data shape services.py reads."""
    if nfc_configs == "default":
        device_config = SimpleNamespace(nfc_configs=[SimpleNamespace(enabled=True)])
    elif nfc_configs is None:
        device_config = None
    else:
        device_config = SimpleNamespace(nfc_configs=nfc_configs)

    coordinator = MagicMock()
    coordinator.data = SimpleNamespace(last_seen=last_seen)
    runtime = SimpleNamespace(
        device_config=device_config,
        sleep_profile=_profile(sleep_mode="on" if sleepy else "off"),
        coordinator=coordinator,
    )
    entry = MagicMock()
    entry.runtime_data = runtime
    return entry


def _call(*, record_type="url", content="value", mime_type=None):
    """Build a fake ServiceCall with already-schema-shaped data."""
    data = {
        "device_id": DEVICE_ID,
        ATTR_RECORD_TYPE: record_type,
        ATTR_CONTENT: content,
    }
    if mime_type is not None:
        data[ATTR_MIME_TYPE] = mime_type
    return SimpleNamespace(hass=MagicMock(), data=data)


def _patches(entry, device):
    """Patch _get_entry_for_device and _async_connect_and_run to drive `device`."""

    async def _fake_connect_and_run(hass, passed_entry, action):
        await action(device)

    return (
        patch.object(services_mod, "_get_entry_for_device", return_value=entry),
        patch.object(
            services_mod,
            "_async_connect_and_run",
            AsyncMock(side_effect=_fake_connect_and_run),
        ),
    )


# --- schema ---


def test_schema_default_record_type_is_url():
    result = SCHEMA_WRITE_NFC({"device_id": DEVICE_ID, "content": "http://example.com"})
    assert result["record_type"] == "url"


def test_schema_rejects_unknown_record_type():
    with pytest.raises(vol.Invalid):
        SCHEMA_WRITE_NFC(
            {"device_id": DEVICE_ID, "content": "x", "record_type": "bogus"}
        )


# --- capability gate ---


@pytest.mark.asyncio
async def test_no_nfc_configs_raises():
    entry = _make_entry(nfc_configs=[])
    device = MagicMock()
    p1, p2 = _patches(entry, device)
    with p1, p2, pytest.raises(ServiceValidationError) as exc_info:
        await _async_write_nfc(_call())
    assert exc_info.value.translation_key == "no_nfc"


@pytest.mark.asyncio
async def test_nfc_configs_present_but_none_enabled_raises():
    entry = _make_entry(nfc_configs=[SimpleNamespace(enabled=False)])
    device = MagicMock()
    p1, p2 = _patches(entry, device)
    with p1, p2, pytest.raises(ServiceValidationError) as exc_info:
        await _async_write_nfc(_call())
    assert exc_info.value.translation_key == "no_nfc"


@pytest.mark.asyncio
async def test_device_config_none_raises():
    entry = _make_entry(nfc_configs=None)
    device = MagicMock()
    p1, p2 = _patches(entry, device)
    with p1, p2, pytest.raises(ServiceValidationError) as exc_info:
        await _async_write_nfc(_call())
    assert exc_info.value.translation_key == "no_nfc"


# --- sleeping device ---


@pytest.mark.asyncio
async def test_sleeping_device_raises():
    entry = _make_entry(sleepy=True, last_seen=None)
    device = MagicMock()
    p1, p2 = _patches(entry, device)
    with p1, p2, pytest.raises(HomeAssistantError) as exc_info:
        await _async_write_nfc(_call())
    assert exc_info.value.translation_key == "device_sleeping"


# --- record_type -> device method mapping ---


@pytest.mark.asyncio
async def test_url_calls_write_nfc_url():
    entry = _make_entry()
    device = MagicMock()
    device.write_nfc_url = AsyncMock()
    p1, p2 = _patches(entry, device)
    with p1, p2:
        await _async_write_nfc(_call(record_type="url", content="http://example.com"))
    device.write_nfc_url.assert_awaited_once_with("http://example.com")


@pytest.mark.asyncio
async def test_text_calls_write_nfc_text():
    entry = _make_entry()
    device = MagicMock()
    device.write_nfc_text = AsyncMock()
    p1, p2 = _patches(entry, device)
    with p1, p2:
        await _async_write_nfc(_call(record_type="text", content="hello"))
    device.write_nfc_text.assert_awaited_once_with("hello")


@pytest.mark.asyncio
async def test_mime_default_mime_type_is_text_vcard():
    entry = _make_entry()
    device = MagicMock()
    device.write_nfc_mime = AsyncMock()
    p1, p2 = _patches(entry, device)
    with p1, p2:
        await _async_write_nfc(_call(record_type="mime", content="BEGIN:VCARD"))
    device.write_nfc_mime.assert_awaited_once_with("text/vcard", "BEGIN:VCARD")


@pytest.mark.asyncio
async def test_mime_explicit_mime_type_honored():
    entry = _make_entry()
    device = MagicMock()
    device.write_nfc_mime = AsyncMock()
    p1, p2 = _patches(entry, device)
    with p1, p2:
        await _async_write_nfc(
            _call(record_type="mime", content="{}", mime_type="application/json")
        )
    device.write_nfc_mime.assert_awaited_once_with("application/json", "{}")


@pytest.mark.asyncio
async def test_ha_tag_composes_url_and_quotes_special_characters():
    entry = _make_entry()
    device = MagicMock()
    device.write_nfc_url = AsyncMock()
    p1, p2 = _patches(entry, device)
    with p1, p2:
        await _async_write_nfc(_call(record_type="ha_tag", content="ifa booth 3"))
    device.write_nfc_url.assert_awaited_once_with(HA_TAG_URL_PREFIX + "ifa%20booth%203")


@pytest.mark.asyncio
async def test_ha_tag_simple_id():
    entry = _make_entry()
    device = MagicMock()
    device.write_nfc_url = AsyncMock()
    p1, p2 = _patches(entry, device)
    with p1, p2:
        await _async_write_nfc(_call(record_type="ha_tag", content="ifa-booth-3"))
    device.write_nfc_url.assert_awaited_once_with(
        "https://www.home-assistant.io/tag/ifa-booth-3"
    )


# --- validation errors ---


@pytest.mark.asyncio
async def test_mime_type_with_url_record_type_rejected():
    entry = _make_entry()
    device = MagicMock()
    p1, p2 = _patches(entry, device)
    with p1, p2, pytest.raises(ServiceValidationError) as exc_info:
        await _async_write_nfc(
            _call(
                record_type="url",
                content="http://example.com",
                mime_type="text/plain",
            )
        )
    assert exc_info.value.translation_key == "mime_type_not_applicable"


@pytest.mark.asyncio
async def test_empty_content_rejected():
    entry = _make_entry()
    device = MagicMock()
    p1, p2 = _patches(entry, device)
    with p1, p2, pytest.raises(ServiceValidationError) as exc_info:
        await _async_write_nfc(_call(record_type="text", content="   "))
    assert exc_info.value.translation_key == "nfc_content_empty"


@pytest.mark.asyncio
async def test_ha_tag_empty_content_rejected():
    entry = _make_entry()
    device = MagicMock()
    p1, p2 = _patches(entry, device)
    with p1, p2, pytest.raises(ServiceValidationError) as exc_info:
        await _async_write_nfc(_call(record_type="ha_tag", content="   "))
    assert exc_info.value.translation_key == "nfc_content_empty"


@pytest.mark.asyncio
async def test_oversized_content_rejected():
    entry = _make_entry()
    device = MagicMock()
    p1, p2 = _patches(entry, device)
    with p1, p2, pytest.raises(ServiceValidationError) as exc_info:
        await _async_write_nfc(
            _call(record_type="text", content="a" * (NFC_MAX_PAYLOAD + 1))
        )
    assert exc_info.value.translation_key == "nfc_content_too_long"


@pytest.mark.asyncio
async def test_content_at_exact_byte_limit_accepted():
    entry = _make_entry()
    device = MagicMock()
    device.write_nfc_text = AsyncMock()
    p1, p2 = _patches(entry, device)
    content = "a" * NFC_MAX_PAYLOAD
    with p1, p2:
        await _async_write_nfc(_call(record_type="text", content=content))
    device.write_nfc_text.assert_awaited_once_with(content)


@pytest.mark.asyncio
async def test_multibyte_utf8_content_measured_in_bytes_not_chars():
    entry = _make_entry()
    device = MagicMock()
    p1, p2 = _patches(entry, device)
    # 200 four-byte-UTF-8 emoji: 200 chars but 800 bytes, over the 512 limit.
    content = "\U0001f600" * 200
    with p1, p2, pytest.raises(ServiceValidationError) as exc_info:
        await _async_write_nfc(_call(record_type="text", content=content))
    assert exc_info.value.translation_key == "nfc_content_too_long"


@pytest.mark.asyncio
async def test_mime_header_pushes_body_over_limit_rejected():
    entry = _make_entry()
    device = MagicMock()
    p1, p2 = _patches(entry, device)
    # default mime type "text/vcard" (10 bytes) + 1 length byte + 510-byte
    # body = 521 > 512
    with p1, p2, pytest.raises(ServiceValidationError) as exc_info:
        await _async_write_nfc(_call(record_type="mime", content="a" * 510))
    assert exc_info.value.translation_key == "nfc_content_too_long"


# --- device-raised errors ---


@pytest.mark.asyncio
async def test_nfc_not_supported_error_translated():
    entry = _make_entry()
    device = MagicMock()
    device.write_nfc_url = AsyncMock(side_effect=NfcNotSupportedError())
    p1, p2 = _patches(entry, device)
    with p1, p2, pytest.raises(HomeAssistantError) as exc_info:
        await _async_write_nfc(_call(record_type="url", content="http://example.com"))
    assert exc_info.value.translation_key == "nfc_not_supported"


@pytest.mark.asyncio
async def test_nfc_write_error_translated():
    entry = _make_entry()
    device = MagicMock()
    device.write_nfc_url = AsyncMock(side_effect=NfcWriteError("bad", error_code=3))
    p1, p2 = _patches(entry, device)
    with p1, p2, pytest.raises(HomeAssistantError) as exc_info:
        await _async_write_nfc(_call(record_type="url", content="http://example.com"))
    assert exc_info.value.translation_key == "nfc_write_failed"
