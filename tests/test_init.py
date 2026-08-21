"""Test the OpenDisplay integration setup and unload."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from opendisplay import (
    AuthenticationFailedError,
    AuthenticationRequiredError,
    BLEConnectionError,
    BLETimeoutError,
    OpenDisplayError,
)
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.opendisplay.const import CONF_ENCRYPTION_KEY, DOMAIN

from . import ENCRYPTION_KEY, LANDING_URL


async def test_setup_and_unload(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test setting up and unloading a config entry."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_encrypted_device(
    hass: HomeAssistant,
    mock_encrypted_config_entry: MockConfigEntry,
    mock_opendisplay_device: MagicMock,
    mock_opendisplay_device_class: MagicMock,
) -> None:
    """Test setup passes the encryption key to OpenDisplayDevice."""
    mock_opendisplay_device.is_flex = False
    mock_encrypted_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_encrypted_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_encrypted_config_entry.state is ConfigEntryState.LOADED
    assert mock_opendisplay_device_class.call_args.kwargs[
        "encryption_key"
    ] == bytes.fromhex(ENCRYPTION_KEY)


async def test_setup_device_not_found(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test setup retries when device is not visible."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.opendisplay.async_ble_device_from_address",
        return_value=None,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.parametrize(
    "exception",
    [
        BLEConnectionError("connection failed"),
        BLETimeoutError("timeout"),
        OpenDisplayError("device error"),
    ],
)
async def test_setup_connection_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    exception: Exception,
) -> None:
    """Test setup retries on BLE connection errors."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.opendisplay.OpenDisplayDevice",
        return_value=AsyncMock(__aenter__=AsyncMock(side_effect=exception)),
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_device_registered(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Test that a device is registered in the device registry after setup."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    devices = dr.async_entries_for_config_entry(
        device_registry, mock_config_entry.entry_id
    )
    assert len(devices) == 1


@pytest.mark.parametrize(
    ("is_flex", "expect_hw_version"),
    [
        (True, True),
        (False, False),
    ],
)
async def test_setup_device_registry_fields(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_opendisplay_device: MagicMock,
    device_registry: dr.DeviceRegistry,
    is_flex: bool,
    expect_hw_version: bool,
) -> None:
    """Test that hw_version is Flex-only but configuration_url is always set.

    configuration_url is a per-device deep link from ``landing_url()``, which is
    just as useful on a non-Flex tag, so unlike hw_version it is not gated.
    """
    mock_opendisplay_device.is_flex = is_flex
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    devices = dr.async_entries_for_config_entry(
        device_registry, mock_config_entry.entry_id
    )
    assert len(devices) == 1
    device = devices[0]
    assert device.sw_version == "1.2.3"
    assert (device.hw_version is not None) == expect_hw_version
    assert device.configuration_url == LANDING_URL


async def test_unload_cancels_active_upload_task(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Test that unloading the entry cancels an in-progress upload task."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    task = hass.async_create_task(asyncio.sleep(3600))
    mock_config_entry.runtime_data.upload_task = task

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert task.cancelled()


@pytest.mark.parametrize(
    "exception",
    [
        AuthenticationFailedError("wrong key"),
        AuthenticationRequiredError("auth required"),
    ],
)
async def test_setup_authentication_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    exception: Exception,
) -> None:
    """Test that auth errors result in SETUP_ERROR and trigger reauth."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.opendisplay.OpenDisplayDevice",
        return_value=AsyncMock(__aenter__=AsyncMock(side_effect=exception)),
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_setup_invalid_encryption_key_format(
    hass: HomeAssistant,
) -> None:
    """Test that a malformed stored encryption key triggers reauth."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="AA:BB:CC:DD:EE:FF",
        title="OpenDisplay 1234",
        data={CONF_ENCRYPTION_KEY: "not-valid-hex!"},
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
