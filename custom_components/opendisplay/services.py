"""Service registration for the OpenDisplay integration."""

import asyncio
from collections.abc import Callable
import contextlib
from datetime import timedelta
from enum import IntEnum
import io
import logging
import os
from typing import TYPE_CHECKING, Any

import aiohttp
from epaper_dithering import ColorScheme
from odl_renderer import generate_image
from opendisplay import (
    AuthenticationFailedError,
    AuthenticationRequiredError,
    DitherMode,
    FitMode,
    OpenDisplayDevice,
    OpenDisplayError,
    RefreshMode,
    Rotation,
)
from PIL import Image as PILImage, ImageOps
import voluptuous as vol

from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.components.http.auth import async_sign_path
from homeassistant.components.media_source import async_resolve_media
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH
from homeassistant.helpers.network import get_url
from homeassistant.helpers.selector import MediaSelector, MediaSelectorConfig

if TYPE_CHECKING:
    from . import OpenDisplayConfigEntry

from .const import CONF_ENCRYPTION_KEY, DOMAIN

ATTR_IMAGE = "image"
ATTR_ROTATION = "rotation"
ATTR_DITHER_MODE = "dither_mode"
ATTR_REFRESH_MODE = "refresh_mode"
ATTR_FIT_MODE = "fit_mode"
ATTR_TONE_COMPRESSION = "tone_compression"


def _str_to_int_enum(enum_class: type[IntEnum]) -> Callable[[str], Any]:
    """Convert a lowercase enum name string to an enum member."""
    members = {m.name.lower(): m for m in enum_class}

    def validate(value: str) -> IntEnum:
        if (result := members.get(value)) is None:
            raise vol.Invalid(f"Invalid value: {value}")
        return result

    return validate


SCHEMA_UPLOAD_IMAGE = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_IMAGE): MediaSelector(
            MediaSelectorConfig(accept=["image/*"])
        ),
        vol.Optional(ATTR_ROTATION, default=Rotation.ROTATE_0): vol.All(
            vol.Coerce(int), vol.Coerce(Rotation)
        ),
        vol.Optional(ATTR_DITHER_MODE, default="burkes"): _str_to_int_enum(DitherMode),
        vol.Optional(ATTR_REFRESH_MODE, default="full"): _str_to_int_enum(RefreshMode),
        vol.Optional(ATTR_FIT_MODE, default="contain"): _str_to_int_enum(FitMode),
        vol.Optional(ATTR_TONE_COMPRESSION): vol.All(
            vol.Coerce(float), vol.Range(min=0.0, max=100.0)
        ),
    }
)


def _get_entry_for_device(call: ServiceCall) -> OpenDisplayConfigEntry:
    """Return the config entry for the device targeted by a service call."""
    device_id: str = call.data[ATTR_DEVICE_ID]
    device_registry = dr.async_get(call.hass)

    if (device := device_registry.async_get(device_id)) is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_device_id",
            translation_placeholders={"device_id": device_id},
        )

    mac_address = next(
        (conn[1] for conn in device.connections if conn[0] == CONNECTION_BLUETOOTH),
        None,
    )
    if mac_address is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_device_id",
            translation_placeholders={"device_id": device_id},
        )

    entry = call.hass.config_entries.async_entry_for_domain_unique_id(
        DOMAIN, mac_address
    )
    if entry is None or entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="device_not_found",
            translation_placeholders={"address": mac_address},
        )

    return entry


def _load_image(path: str) -> PILImage.Image:
    """Load an image from disk and apply EXIF orientation."""
    image = PILImage.open(path)
    image.load()
    return ImageOps.exif_transpose(image)


def _load_image_from_bytes(data: bytes) -> PILImage.Image:
    """Load an image from bytes and apply EXIF orientation."""
    image = PILImage.open(io.BytesIO(data))
    image.load()
    return ImageOps.exif_transpose(image)


async def _async_download_image(hass: HomeAssistant, url: str) -> PILImage.Image:
    """Download an image from a URL and return a PIL Image."""
    if not url.startswith(("http://", "https://")):
        url = get_url(hass) + async_sign_path(
            hass, url, timedelta(minutes=5), use_content_user=True
        )
    session = async_get_clientsession(hass)
    try:
        async with session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.read()
    except aiohttp.ClientError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="media_download_error",
            translation_placeholders={"error": str(err)},
        ) from err

    return await hass.async_add_executor_job(_load_image_from_bytes, data)


async def _async_upload_image(call: ServiceCall) -> None:
    """Handle the upload_image service call."""
    entry = _get_entry_for_device(call)
    address = entry.unique_id
    assert address is not None

    image_data: dict[str, Any] = call.data[ATTR_IMAGE]
    rotation: Rotation = call.data[ATTR_ROTATION]
    dither_mode: DitherMode = call.data[ATTR_DITHER_MODE]
    refresh_mode: RefreshMode = call.data[ATTR_REFRESH_MODE]
    fit_mode: FitMode = call.data[ATTR_FIT_MODE]
    tone_compression_pct: float | None = call.data.get(ATTR_TONE_COMPRESSION)
    tone_compression: float | str = (
        tone_compression_pct / 100.0 if tone_compression_pct is not None else "auto"
    )

    ble_device = async_ble_device_from_address(call.hass, address, connectable=True)
    if ble_device is None:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="device_not_found",
            translation_placeholders={"address": address},
        )

    current = asyncio.current_task()
    if (prev := entry.runtime_data.upload_task) is not None and not prev.done():
        prev.cancel()
        # pylint: disable-next=home-assistant-action-swallowed-exception
        with contextlib.suppress(asyncio.CancelledError):
            await prev
    entry.runtime_data.upload_task = current

    try:
        media = await async_resolve_media(
            call.hass, image_data["media_content_id"], None
        )

        if media.path is not None:
            pil_image = await call.hass.async_add_executor_job(
                _load_image, str(media.path)
            )
        else:
            pil_image = await _async_download_image(call.hass, media.url)

        raw_key = entry.data.get(CONF_ENCRYPTION_KEY)
        if raw_key is not None and len(raw_key) != 32:
            entry.async_start_reauth(call.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="authentication_error"
            )
        try:
            encryption_key = bytes.fromhex(raw_key) if raw_key is not None else None
        except ValueError as err:
            entry.async_start_reauth(call.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="authentication_error"
            ) from err

        async with OpenDisplayDevice(
            mac_address=address,
            ble_device=ble_device,
            config=entry.runtime_data.device_config,
            encryption_key=encryption_key,
        ) as device:
            await device.upload_image(
                pil_image,
                refresh_mode=refresh_mode,
                dither_mode=dither_mode,
                tone=tone_compression,
                fit=fit_mode,
                rotate=rotation,
            )
    except asyncio.CancelledError:
        return
    except (AuthenticationFailedError, AuthenticationRequiredError) as err:
        entry.async_start_reauth(call.hass)
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="authentication_error"
        ) from err
    except OpenDisplayError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="upload_error"
        ) from err
    finally:
        if entry.runtime_data.upload_task is current:
            entry.runtime_data.upload_task = None


_LOGGER = logging.getLogger(__name__)


class HADataProvider:
    """Provides HA recorder history data to odl_renderer plot elements."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def get_history(
        self,
        entity_ids: list[str],
        start: Any,
        end: Any,
    ) -> dict[str, list[dict]]:
        from functools import partial

        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.history import get_significant_states

        raw = await get_instance(self._hass).async_add_executor_job(
            partial(
                get_significant_states,
                self._hass,
                start,
                end,
                entity_ids,
                significant_changes_only=False,
                minimal_response=True,
                no_attributes=False,
            )
        )
        result: dict[str, list[dict]] = {}
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


def _get_entry_for_device_id(
    hass: HomeAssistant, device_id: str
) -> "OpenDisplayConfigEntry":
    """Return the config entry for a raw device_id string."""
    device_registry = dr.async_get(hass)
    if (device := device_registry.async_get(device_id)) is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_device_id",
            translation_placeholders={"device_id": device_id},
        )
    mac_address = next(
        (conn[1] for conn in device.connections if conn[0] == CONNECTION_BLUETOOTH),
        None,
    )
    if mac_address is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_device_id",
            translation_placeholders={"device_id": device_id},
        )
    entry = hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, mac_address)
    if entry is None or entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="device_not_found",
            translation_placeholders={"address": mac_address},
        )
    return entry


async def _get_device_ids_from_label(hass: HomeAssistant, label_id: str) -> list[str]:
    device_registry = dr.async_get(hass)
    entry_ids = {e.entry_id for e in hass.config_entries.async_entries(DOMAIN)}
    return [
        d.id
        for d in dr.async_entries_for_label(device_registry, label_id)
        if d.config_entries & entry_ids
    ]


async def _get_device_ids_from_area(hass: HomeAssistant, area_id: str) -> list[str]:
    device_registry = dr.async_get(hass)
    entry_ids = {e.entry_id for e in hass.config_entries.async_entries(DOMAIN)}
    return [
        d.id
        for d in dr.async_entries_for_area(device_registry, area_id)
        if d.config_entries & entry_ids
    ]


async def _async_drawcustom(call: ServiceCall) -> None:
    """Handle the drawcustom service call."""
    hass = call.hass

    device_ids: list[str] = list(call.data.get("device_id", []))
    if isinstance(device_ids, str):
        device_ids = [device_ids]
    for label_id in call.data.get("label_id", []):
        device_ids.extend(await _get_device_ids_from_label(hass, label_id))
    for area_id in call.data.get("area_id", []):
        device_ids.extend(await _get_device_ids_from_area(hass, area_id))

    seen: set[str] = set()
    unique_ids = [d for d in device_ids if not (d in seen or seen.add(d))]  # type: ignore[func-returns-value]
    if not unique_ids:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="no_targets_specified",
        )

    errors: list[str] = []
    for device_id in unique_ids:
        try:
            await _drawcustom_for_device(hass, device_id, call)
        except (HomeAssistantError, ServiceValidationError) as err:
            errors.append(f"{device_id}: {err}")
    if errors:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="multiple_errors",
            translation_placeholders={"errors": "\n".join(errors)},
        )


def _font_search_dirs(hass: HomeAssistant) -> list[str]:
    """Return font search directories in priority order."""
    candidates = [
        hass.config.path("www/fonts"),
        hass.config.path("media/fonts"),
        "/media/fonts",
    ]
    return [p for p in candidates if os.path.isdir(p)]


async def _drawcustom_for_device(
    hass: HomeAssistant, device_id: str, call: ServiceCall
) -> None:
    entry = _get_entry_for_device_id(hass, device_id)
    display = entry.runtime_data.device_config.displays[0]
    cs = display.color_scheme_enum
    color_scheme = cs if isinstance(cs, ColorScheme) else ColorScheme.from_value(cs)

    img = await generate_image(
        width=display.pixel_width,
        height=display.pixel_height,
        elements=call.data.get("payload", []),
        background=call.data.get("background", "white"),
        accent_color=color_scheme.accent_color,
        session=async_get_clientsession(hass),
        data_provider=HADataProvider(hass),
        font_dirs=_font_search_dirs(hass),
    )

    rotate = call.data.get("rotate", 0)
    if rotate:
        img = img.rotate(rotate, expand=True)

    if call.data.get("dry-run", False):
        _LOGGER.info("Drawcustom dry run for device %s", device_id)
        return

    dither_mode: DitherMode = _str_to_int_enum(DitherMode)(
        call.data.get("dither", "ordered")
    )
    refresh_type = int(call.data.get("refresh_type", 0))
    refresh_mode = RefreshMode.FAST if refresh_type == 1 else RefreshMode.FULL

    address = entry.unique_id
    assert address is not None
    ble_device = async_ble_device_from_address(hass, address, connectable=True)
    if ble_device is None:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="device_not_found",
            translation_placeholders={"address": address},
        )

    raw_key = entry.data.get(CONF_ENCRYPTION_KEY)
    if raw_key is not None and len(raw_key) != 32:
        entry.async_start_reauth(hass)
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="authentication_error"
        )
    try:
        encryption_key = bytes.fromhex(raw_key) if raw_key is not None else None
    except ValueError as err:
        entry.async_start_reauth(hass)
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="authentication_error"
        ) from err

    try:
        async with OpenDisplayDevice(
            mac_address=address,
            ble_device=ble_device,
            config=entry.runtime_data.device_config,
            encryption_key=encryption_key,
        ) as device:
            await device.upload_image(img, refresh_mode=refresh_mode, dither_mode=dither_mode)
    except (AuthenticationFailedError, AuthenticationRequiredError) as err:
        entry.async_start_reauth(hass)
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="authentication_error"
        ) from err
    except OpenDisplayError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="upload_error"
        ) from err


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register OpenDisplay services."""
    hass.services.async_register(
        DOMAIN,
        "upload_image",
        _async_upload_image,
        schema=SCHEMA_UPLOAD_IMAGE,
    )
    hass.services.async_register(DOMAIN, "drawcustom", _async_drawcustom)

## TODO: piggyback off of upload image? also vol for validation in drawcustom