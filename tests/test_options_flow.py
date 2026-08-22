"""Test the OpenDisplay options flow.

Kept out of test_config_flow.py because that module stubs async_setup_entry
for every test, and the options flow's reload needs a really-set-up entry.
"""

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.opendisplay.const import (
    CONF_BLOCKS_PER_ACK,
    CONF_MAX_QUEUE_SIZE,
    CONF_MISSED_CYCLES,
    CONF_PROBE_BEFORE_QUEUE,
    CONF_QUEUE_TIMEOUT_HOURS,
    CONF_SLEEP_MODE,
)


async def test_options_flow_persists_and_reloads(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Submitting the options form stores the values and reloads the entry.

    The reload matters: SleepProfile is built at setup, so without it a changed
    sleep mode would not take effect until Home Assistant restarted.
    """
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_SLEEP_MODE: "on",
            CONF_MISSED_CYCLES: 5,
            CONF_QUEUE_TIMEOUT_HOURS: 12,
            CONF_PROBE_BEFORE_QUEUE: False,
            CONF_BLOCKS_PER_ACK: 8,
            CONF_MAX_QUEUE_SIZE: 4,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_SLEEP_MODE] == "on"
    assert mock_config_entry.options[CONF_MISSED_CYCLES] == 5
    # Reloaded, so the new sleep mode is live on the profile.
    assert mock_config_entry.runtime_data.sleep_profile.is_sleepy is True
