"""Tests for EEM Online data normalization."""

from datetime import date, timedelta
from typing import cast
from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eem_online.api import (
    EemOnlineApiClient,
    EemOnlineApiClientAuthenticationError,
    EemOnlineApiClientCommunicationError,
)
from custom_components.eem_online.const import MADEIRA_TIME_ZONE, MAX_GAP_FILL_DAYS, METER_READING_WINDOW_DAYS
from custom_components.eem_online.coordinator.base import (
    EemOnlineDataUpdateCoordinator,
    _normalize_consumption,
    _normalize_meter_reading,
)
from custom_components.eem_online.data import EemOnlineConfigEntry, EemOnlineCoordinatorData
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util


def test_normalize_uses_last_duplicate_and_rejects_incomplete_days() -> None:
    """Keep the last duplicate while excluding zero and structurally incomplete days."""
    payload = {
        "consumos": [
            {"data": "2026-09-10", "consumoCheias": 1, "consumoVazio": 0, "consumoPonta": 0},
            {"data": "2026-09-10", "consumoCheias": 2, "consumoVazio": 0, "consumoPonta": 0},
            {"data": "2026-09-11", "consumoCheias": 0, "consumoVazio": 0, "consumoPonta": 0},
            {"data": "2026-09-12", "consumoCheias": 3, "consumoVazio": 0},
        ],
    }

    result = _normalize_consumption(payload, date(2026, 9, 9), date(2026, 9, 13))

    assert [(item.day, item.value) for item in result] == [(date(2026, 9, 10), 2)]


def test_normalize_meter_reading_uses_latest_day_and_last_duplicate() -> None:
    """Response order does not matter except that the last same-day record wins."""
    readings = [
        {"data": "2026-09-12T00:00:00", "totalRegistadores": 20.0},
        {"data": "2026-09-11T00:00:00", "totalRegistadores": 10.0},
        {"data": "2026-09-12T12:00:00", "totalRegistadores": 21.0},
    ]

    assert _normalize_meter_reading(readings, date(2026, 9, 1), date(2026, 9, 12)) == (
        date(2026, 9, 12),
        21.0,
    )


def test_normalize_meter_reading_rejects_missing_and_nonpositive_values() -> None:
    """Missing, null, invalid, zero, and out-of-range records do not create a value."""
    readings = [
        {"data": "2026-09-12T00:00:00"},
        {"data": "2026-09-12T00:00:00", "totalRegistadores": None},
        {"data": "invalid", "totalRegistadores": 12.0},
        {"data": "2026-09-12T00:00:00", "totalRegistadores": -1.0},
        {"data": "2026-09-12T00:00:00", "totalRegistadores": 0.0},
        {"data": "2026-08-31T00:00:00", "totalRegistadores": 12.0},
    ]

    assert _normalize_meter_reading(readings, date(2026, 9, 1), date(2026, 9, 12)) is None


def _coordinator(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    client: AsyncMock,
) -> EemOnlineDataUpdateCoordinator:
    return EemOnlineDataUpdateCoordinator(
        hass,
        cast(EemOnlineConfigEntry, config_entry),
        cast(EemOnlineApiClient, client),
        "456",
    )


async def _refresh(coordinator: EemOnlineDataUpdateCoordinator) -> EemOnlineCoordinatorData:
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    return coordinator.data


async def test_summary_succeeds_when_meter_readings_fail(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api_client: AsyncMock,
    mock_statistics: AsyncMock,
) -> None:
    """A readings error leaves the daily summary available but imports no statistics."""
    yesterday = dt_util.now(MADEIRA_TIME_ZONE).date() - timedelta(days=1)
    mock_api_client.async_get_weekly_summary.return_value = {
        "consumos": [
            {"data": yesterday.isoformat(), "consumoCheias": 1.0, "consumoVazio": 2.0, "consumoPonta": 0.5},
        ],
    }
    mock_api_client.async_get_meter_readings.side_effect = EemOnlineApiClientCommunicationError("offline")

    data = await _refresh(_coordinator(hass, config_entry, mock_api_client))

    assert data.summary_available
    assert not data.meter_readings_available
    assert data.latest_day == yesterday
    assert data.latest_consumption == 3.5
    assert data.latest_meter_reading is None
    mock_statistics.assert_not_awaited()


async def test_meter_reading_succeeds_when_summary_fails(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api_client: AsyncMock,
    mock_statistics: AsyncMock,
) -> None:
    """A summary error does not hide a valid latest meter reading."""
    today = dt_util.now(MADEIRA_TIME_ZONE).date()
    reading_day = today - timedelta(days=1)
    mock_api_client.async_get_weekly_summary.side_effect = EemOnlineApiClientCommunicationError("offline")
    mock_api_client.async_get_meter_readings.return_value = [
        {"data": f"{reading_day.isoformat()}T00:00:00", "totalRegistadores": 123.0},
    ]

    data = await _refresh(_coordinator(hass, config_entry, mock_api_client))

    assert not data.summary_available
    assert data.meter_readings_available
    assert data.latest_consumption is None
    assert data.latest_meter_reading == 123.0
    assert data.latest_meter_day == reading_day
    _, start, end = mock_api_client.async_get_meter_readings.await_args.args
    assert end == today
    assert start == today - timedelta(days=METER_READING_WINDOW_DAYS)
    mock_statistics.assert_awaited_once()


async def test_empty_meter_response_preserves_previous_reading(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api_client: AsyncMock,
    mock_statistics: AsyncMock,
) -> None:
    """A valid empty response is available and does not erase prior data."""
    coordinator = _coordinator(hass, config_entry, mock_api_client)
    first = await _refresh(coordinator)
    mock_api_client.async_get_meter_readings.return_value = []

    second = await _refresh(coordinator)

    assert second.meter_readings_available
    assert second.latest_meter_reading == first.latest_meter_reading
    assert second.latest_meter_day == first.latest_meter_day


async def test_both_sources_failing_raises_update_failed(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api_client: AsyncMock,
    mock_statistics: AsyncMock,
) -> None:
    """The coordinator fails only when neither source updates."""
    mock_api_client.async_get_weekly_summary.side_effect = EemOnlineApiClientCommunicationError("summary offline")
    mock_api_client.async_get_meter_readings.side_effect = EemOnlineApiClientCommunicationError("readings offline")

    coordinator = _coordinator(hass, config_entry, mock_api_client)
    await coordinator.async_refresh()

    assert not coordinator.last_update_success
    assert isinstance(coordinator.last_exception, UpdateFailed)


async def test_authentication_failure_starts_reauthentication(
    recorder_mock: object,
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api_client: AsyncMock,
) -> None:
    """Authentication failure from either source is not treated as partial data."""
    mock_api_client.async_get_weekly_summary.side_effect = EemOnlineApiClientAuthenticationError("rejected")

    config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    [flow] = config_entry.async_get_active_flows(hass, {SOURCE_REAUTH})
    result = await hass.config_entries.flow.async_configure(flow["flow_id"])
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {}


async def test_meter_reading_authentication_failure_starts_reauthentication(
    recorder_mock: object,
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api_client: AsyncMock,
    mock_statistics: AsyncMock,
) -> None:
    """Readings authentication failure also invalidates the whole entry."""
    mock_api_client.async_get_meter_readings.side_effect = EemOnlineApiClientAuthenticationError("rejected")

    config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    [flow] = config_entry.async_get_active_flows(hass, {SOURCE_REAUTH})
    result = await hass.config_entries.flow.async_configure(flow["flow_id"])
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {}


async def test_long_outage_reaches_back_to_the_last_imported_day(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api_client: AsyncMock,
    mock_statistics: AsyncMock,
) -> None:
    """After more than a month without updates the fetch starts at the newest imported day."""
    today = dt_util.now(MADEIRA_TIME_ZONE).date()
    last_imported = today - timedelta(days=100)

    with patch(
        "custom_components.eem_online.coordinator.base.async_last_imported_day",
        new_callable=AsyncMock,
        return_value=last_imported,
    ):
        await _refresh(_coordinator(hass, config_entry, mock_api_client))

    _, start, end = mock_api_client.async_get_meter_readings.await_args.args
    assert (start, end) == (last_imported, today)


async def test_gap_fill_is_bounded(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api_client: AsyncMock,
    mock_statistics: AsyncMock,
) -> None:
    """A very old last import does not trigger an unbounded automatic download."""
    today = dt_util.now(MADEIRA_TIME_ZONE).date()

    with patch(
        "custom_components.eem_online.coordinator.base.async_last_imported_day",
        new_callable=AsyncMock,
        return_value=today - timedelta(days=MAX_GAP_FILL_DAYS + 50),
    ):
        await _refresh(_coordinator(hass, config_entry, mock_api_client))

    _, start, _ = mock_api_client.async_get_meter_readings.await_args.args
    assert start == today - timedelta(days=MAX_GAP_FILL_DAYS)
