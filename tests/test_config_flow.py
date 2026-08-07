"""Unit tests for the options-flow schema (sliding-window transfer options).

Mirrors the other test modules: no Home Assistant test harness; the schema is
exercised directly via ``_options_schema()`` — a plain voluptuous schema — so a
round-trip through it is exactly what the options flow persists.
"""

import pytest
import voluptuous as vol

from custom_components.opendisplay.config_flow import _options_schema
from custom_components.opendisplay.const import (
    CONF_BLOCKS_PER_ACK,
    CONF_MAX_QUEUE_SIZE,
    CONF_MISSED_CYCLES,
    CONF_PROBE_BEFORE_QUEUE,
    CONF_QUEUE_TIMEOUT_HOURS,
    CONF_SLEEP_MODE,
    DEFAULT_BLOCKS_PER_ACK,
    DEFAULT_MAX_QUEUE_SIZE,
    DEFAULT_MISSED_CYCLES,
    DEFAULT_PROBE_BEFORE_QUEUE,
    DEFAULT_QUEUE_TIMEOUT_HOURS,
    DEFAULT_SLEEP_MODE,
)


def test_options_schema_defaults():
    """An empty submission resolves every option to its default."""
    result = _options_schema()({})

    assert result[CONF_SLEEP_MODE] == DEFAULT_SLEEP_MODE
    assert result[CONF_MISSED_CYCLES] == DEFAULT_MISSED_CYCLES
    assert result[CONF_QUEUE_TIMEOUT_HOURS] == DEFAULT_QUEUE_TIMEOUT_HOURS
    assert result[CONF_PROBE_BEFORE_QUEUE] == DEFAULT_PROBE_BEFORE_QUEUE
    assert result[CONF_BLOCKS_PER_ACK] == DEFAULT_BLOCKS_PER_ACK
    assert result[CONF_MAX_QUEUE_SIZE] == DEFAULT_MAX_QUEUE_SIZE


def test_options_schema_custom_values_persist():
    """Custom values round-trip, coerced to int (NumberSelector yields floats)."""
    result = _options_schema()(
        {
            CONF_SLEEP_MODE: DEFAULT_SLEEP_MODE,
            CONF_MISSED_CYCLES: DEFAULT_MISSED_CYCLES,
            CONF_QUEUE_TIMEOUT_HOURS: DEFAULT_QUEUE_TIMEOUT_HOURS,
            CONF_PROBE_BEFORE_QUEUE: DEFAULT_PROBE_BEFORE_QUEUE,
            CONF_BLOCKS_PER_ACK: 4.0,
            CONF_MAX_QUEUE_SIZE: 1,
        }
    )

    assert result[CONF_BLOCKS_PER_ACK] == 4
    assert isinstance(result[CONF_BLOCKS_PER_ACK], int)
    assert result[CONF_MAX_QUEUE_SIZE] == 1  # 1 == fast transfer disabled
    assert isinstance(result[CONF_MAX_QUEUE_SIZE], int)


@pytest.mark.parametrize("key", [CONF_BLOCKS_PER_ACK, CONF_MAX_QUEUE_SIZE])
@pytest.mark.parametrize("value", [0, 33])
def test_options_schema_rejects_out_of_range(key, value):
    """Both options are bounded to the protocol's 1..32 window range."""
    with pytest.raises(vol.Invalid):
        _options_schema()({key: value})
