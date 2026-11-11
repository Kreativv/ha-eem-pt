"""Service actions for EEM Online."""

import voluptuous as vol

from custom_components.eem_online.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_CONFIG_ENTRY_ID
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
import homeassistant.helpers.config_validation as cv

from .import_history import ATTR_START_DATE, async_handle_import_history

SERVICE_IMPORT_HISTORY = "import_history"

IMPORT_HISTORY_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_START_DATE): cv.date,
    }
)


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's service actions."""

    async def handle_import_history(call: ServiceCall) -> ServiceResponse:
        entry = hass.config_entries.async_get_entry(call.data[ATTR_CONFIG_ENTRY_ID])
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="entry_not_found",
            )
        if entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="entry_not_loaded",
            )
        return await async_handle_import_history(hass, entry, call)

    if not hass.services.has_service(DOMAIN, SERVICE_IMPORT_HISTORY):
        hass.services.async_register(
            DOMAIN,
            SERVICE_IMPORT_HISTORY,
            handle_import_history,
            schema=IMPORT_HISTORY_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
