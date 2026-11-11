"""Rebuild the Energy statistics from EEM meter readings."""

from datetime import date, timedelta
from typing import TYPE_CHECKING

from custom_components.eem_online.api import EemOnlineApiClientAuthenticationError, EemOnlineApiClientError
from custom_components.eem_online.const import CONF_CONTRACT, DOMAIN, MADEIRA_TIME_ZONE, MAX_HISTORY_DAYS
from custom_components.eem_online.coordinator.statistics import async_import_readings
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from custom_components.eem_online.data import EemOnlineConfigEntry

ATTR_START_DATE = "start_date"


async def async_handle_import_history(
    hass: HomeAssistant,
    entry: EemOnlineConfigEntry,
    call: ServiceCall,
) -> ServiceResponse:
    """Fetch every meter reading since the start date and rewrite the statistics from there."""
    start: date = call.data[ATTR_START_DATE]
    today = dt_util.now(MADEIRA_TIME_ZONE).date()
    oldest = today - timedelta(days=MAX_HISTORY_DAYS)
    if not oldest <= start < today - timedelta(days=1):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_start_date",
            translation_placeholders={"oldest": oldest.isoformat(), "latest": (today - timedelta(days=2)).isoformat()},
        )

    contract: str = entry.data[CONF_CONTRACT]
    try:
        readings = await entry.runtime_data.client.async_get_meter_readings(contract, start, today)
    except EemOnlineApiClientAuthenticationError as err:
        entry.async_start_reauth(hass)
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="authentication_failed",
        ) from err
    except EemOnlineApiClientError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="import_history_failed",
            translation_placeholders={"error": str(err)},
        ) from err

    results = await async_import_readings(hass, contract, readings, today)
    if not results:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="import_history_empty",
            translation_placeholders={"start": start.isoformat()},
        )
    return {
        key: {
            "first_day": result.first_day.isoformat(),
            "last_day": result.last_day.isoformat(),
            "days": result.days,
            "first_reading": result.first_reading,
            "last_reading": result.last_reading,
        }
        for key, result in results.items()
    }
