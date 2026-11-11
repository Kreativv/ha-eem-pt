"""Tests for the import_history service action."""

from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eem_online.api import EemOnlineApiClientAuthenticationError, EemOnlineApiClientCommunicationError
from custom_components.eem_online.const import DOMAIN, MADEIRA_TIME_ZONE, MAX_HISTORY_DAYS
from custom_components.eem_online.coordinator.statistics import EemOnlineImportResult
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

IMPORT_PATH = "custom_components.eem_online.service_actions.import_history.async_import_readings"


def _today() -> date:
    return dt_util.now(MADEIRA_TIME_ZONE).date()


async def _call(hass: HomeAssistant, entry_id: str, start: date) -> dict:
    return await hass.services.async_call(
        DOMAIN,
        "import_history",
        {"config_entry_id": entry_id, "start_date": start.isoformat()},
        blocking=True,
        return_response=True,
    )


async def test_action_exists_without_a_loaded_entry(recorder_mock: object, hass: HomeAssistant) -> None:
    """The action is registered in async_setup and rejects an unknown entry."""
    assert await async_setup_component(hass, DOMAIN, {})
    assert hass.services.has_service(DOMAIN, "import_history")

    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, "missing", _today() - timedelta(days=10))
    assert err.value.translation_key == "entry_not_found"


async def test_action_rejects_an_unloaded_entry(
    recorder_mock: object,
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """An entry that is not loaded has no client to fetch with."""
    assert await async_setup_component(hass, DOMAIN, {})
    config_entry.add_to_hass(hass)

    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, config_entry.entry_id, _today() - timedelta(days=10))
    assert err.value.translation_key == "entry_not_loaded"


@pytest.mark.parametrize("days_ago", [0, 1, MAX_HISTORY_DAYS + 1])
async def test_action_rejects_start_dates_outside_the_history(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    days_ago: int,
) -> None:
    """Only dates with at least one complete day after them, inside EEM's history, are accepted."""
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, init_integration.entry_id, _today() - timedelta(days=days_ago))
    assert err.value.translation_key == "invalid_start_date"


async def test_action_imports_and_reports_each_register(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api_client: AsyncMock,
) -> None:
    """The whole range is fetched once and the response describes what was written."""
    start = _today() - timedelta(days=30)
    result = EemOnlineImportResult(start, _today() - timedelta(days=1), 30, 100.0, 400.0)

    with patch(IMPORT_PATH, new_callable=AsyncMock, return_value={"total": result}) as import_readings:
        response = await _call(hass, init_integration.entry_id, start)

    _, fetch_start, fetch_end = mock_api_client.async_get_meter_readings.await_args.args
    assert (fetch_start, fetch_end) == (start, _today())
    import_readings.assert_awaited_once()
    assert response == {
        "total": {
            "first_day": start.isoformat(),
            "last_day": (_today() - timedelta(days=1)).isoformat(),
            "days": 30,
            "first_reading": 100.0,
            "last_reading": 400.0,
        }
    }


async def test_action_without_readings_fails(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    """An empty answer is reported instead of silently importing nothing."""
    with (
        patch(IMPORT_PATH, new_callable=AsyncMock, return_value={}),
        pytest.raises(HomeAssistantError) as err,
    ):
        await _call(hass, init_integration.entry_id, _today() - timedelta(days=30))
    assert err.value.translation_key == "import_history_empty"


async def test_action_communication_error(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api_client: AsyncMock,
) -> None:
    """A failed fetch surfaces as a translated error."""
    mock_api_client.async_get_meter_readings.side_effect = EemOnlineApiClientCommunicationError("offline")

    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, init_integration.entry_id, _today() - timedelta(days=30))
    assert err.value.translation_key == "import_history_failed"


async def test_action_authentication_error_starts_reauth(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_api_client: AsyncMock,
) -> None:
    """Rejected credentials start the reauthentication flow."""
    mock_api_client.async_get_meter_readings.side_effect = EemOnlineApiClientAuthenticationError("rejected")

    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, init_integration.entry_id, _today() - timedelta(days=30))
    assert err.value.translation_key == "authentication_failed"
    assert init_integration.async_get_active_flows(hass, {SOURCE_REAUTH})
