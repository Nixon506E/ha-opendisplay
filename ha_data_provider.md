# HADataProvider — wiring drawcustom `plot` into services.py

## What this is

`HADataProvider` is the HA-side implementation of drawcustom's `DataProvider` protocol.
It wraps the HA recorder and normalizes its output so `draw_plot` in drawcustom never imports anything from `homeassistant`.

Add it to `services.py` — it's small enough to live there.

---

## Imports to add at the top of `services.py`

```python
from datetime import datetime
```

---

## Class to add after `_LOGGER`

```python
class HADataProvider:
    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def get_history(
        self, entity_ids: list[str], start: datetime, end: datetime
    ) -> dict[str, list[dict]]:
        from functools import partial
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.history import get_significant_states

        raw = await get_instance(self._hass).async_add_executor_job(
            partial(
                get_significant_states,
                self._hass, start, end, entity_ids,
                significant_changes_only=False,
                minimal_response=True,
                no_attributes=False,
            )
        )
        # minimal_response=True: first item per entity is a LazyState object,
        # subsequent items are already {"state", "last_changed"} dicts.
        # Normalize the first item so callers get a uniform list of dicts.
        result = {}
        for entity_id, states in raw.items():
            if not states:
                result[entity_id] = []
                continue
            first = states[0]
            result[entity_id] = [
                {"state": first.state, "last_changed": str(first.last_changed)},
                *states[1:],
            ]
        return result
```

> **Why lazy imports?** The recorder component may not be initialized when `services.py`
> is first imported. Deferring imports to call time guarantees the recorder is ready.

---

## How to pass it into drawcustom

When you eventually replace `imagegen/` with a direct drawcustom call:

```python
from drawcustom import generate_image

image = await generate_image(
    payload,
    width,
    height,
    data_provider=HADataProvider(hass),
    session=session,
)
```

---

## DataProvider contract (from drawcustom)

`get_history` must return:
```python
dict[str, list[dict]]
# {
#   "sensor.temperature": [
#     {"state": "21.5", "last_changed": "2024-01-01T06:00:00+00:00"},
#     ...
#   ]
# }
```

- Items ordered **oldest-first**
- Each dict has `"state"` (str) and `"last_changed"` (ISO 8601 str)
- Missing entities can be absent or map to `[]`
