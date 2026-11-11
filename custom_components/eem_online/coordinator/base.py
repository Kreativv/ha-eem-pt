"""Data update coordinator for EEM Online."""

from collections.abc import Mapping
from datetime import date, timedelta
from math import isfinite
from typing import TYPE_CHECKING, Any

from custom_components.eem_online.api import (
    EemOnlineApiClient,
    EemOnlineApiClientAuthenticationError,
    EemOnlineApiClientError,
)
from custom_components.eem_online.const import (
    CORRECTION_WINDOW_DAYS,
    DOMAIN,
    LOGGER,
    MADEIRA_TIME_ZONE,
    MAX_GAP_FILL_DAYS,
    METER_READING_WINDOW_DAYS,
    UPDATE_INTERVAL,
)
from custom_components.eem_online.data import EemOnlineCoordinatorData, EemOnlineDailyConsumption
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .statistics import async_import_readings, async_last_imported_day, period_start

if TYPE_CHECKING:
    from custom_components.eem_online.data import EemOnlineConfigEntry


class EemOnlineDataUpdateCoordinator(DataUpdateCoordinator[EemOnlineCoordinatorData]):
    """Fetch EEM data and keep the meter-reading Energy statistics synchronized."""

    config_entry: EemOnlineConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: EemOnlineConfigEntry,
        client: EemOnlineApiClient,
        contract: str,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
            always_update=False,
        )
        self._client = client
        self._contract = contract

    async def _async_update_data(self) -> EemOnlineCoordinatorData:
        """Fetch EEM data, normalize it, and update long-term statistics from the meter readings."""
        previous = self.data
        latest_day = previous.latest_day if previous else None
        latest_consumption = previous.latest_consumption if previous else None
        latest_meter_day = previous.latest_meter_day if previous else None
        latest_meter_reading = previous.latest_meter_reading if previous else None
        summary_error: EemOnlineApiClientError | None = None
        meter_readings_error: EemOnlineApiClientError | None = None

        today = dt_util.now(MADEIRA_TIME_ZONE).date()
        correction_window_start = today - timedelta(days=CORRECTION_WINDOW_DAYS)
        meter_readings_end = today
        meter_readings_start = await self._async_meter_readings_start(today)

        try:
            payload = await self._client.async_get_weekly_summary(self._contract)
            fresh = _normalize_consumption(payload, correction_window_start, today)
            if fresh:
                latest_day = fresh[-1].day
                latest_consumption = fresh[-1].value
            else:
                latest_day = None
                latest_consumption = None
        except EemOnlineApiClientAuthenticationError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="authentication_failed",
            ) from err
        except EemOnlineApiClientError as err:
            summary_error = err

        try:
            readings = await self._client.async_get_meter_readings(
                self._contract,
                meter_readings_start,
                meter_readings_end,
            )
            latest_reading = _normalize_meter_reading(readings, meter_readings_start, meter_readings_end)
            if latest_reading is not None:
                latest_meter_day, latest_meter_reading = latest_reading
            await async_import_readings(self.hass, self._contract, readings, meter_readings_end)
        except EemOnlineApiClientAuthenticationError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="authentication_failed",
            ) from err
        except EemOnlineApiClientError as err:
            meter_readings_error = err

        if summary_error is not None and meter_readings_error is not None:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
            ) from summary_error
        if summary_error is not None:
            LOGGER.warning("Unable to update EEM daily consumption: %s", summary_error)
        if meter_readings_error is not None:
            LOGGER.warning("Unable to update EEM meter reading: %s", meter_readings_error)

        return EemOnlineCoordinatorData(
            latest_day=latest_day,
            latest_consumption=latest_consumption,
            latest_meter_day=latest_meter_day,
            latest_meter_reading=latest_meter_reading,
            summary_available=summary_error is None,
            meter_readings_available=meter_readings_error is None,
        )

    async def _async_meter_readings_start(self, today: date) -> date:
        """Overlap the last month, or reach back to the newest imported day after a longer outage."""
        start = today - timedelta(days=METER_READING_WINDOW_DAYS)
        last_imported = await async_last_imported_day(self.hass, self._contract)
        if last_imported is None or last_imported >= start:
            return start
        return max(last_imported, today - timedelta(days=MAX_GAP_FILL_DAYS))


def _normalize_consumption(
    payload: Mapping[str, Any],
    window_start: date,
    today: date,
) -> list[EemOnlineDailyConsumption]:
    """Return valid, positive completed days from the weekly response."""
    consumptions = payload.get("consumos")
    if consumptions is None:
        return []
    if not isinstance(consumptions, list):
        raise EemOnlineApiClientError("EEM consumos is not a list")

    values: dict[date, float] = {}
    for record in consumptions:
        if not isinstance(record, Mapping):
            continue
        try:
            day = date.fromisoformat(str(record["data"])[:10])
            value = sum(float(record[key]) for key in ("consumoCheias", "consumoVazio", "consumoPonta"))
        except KeyError, TypeError, ValueError:
            continue
        if day < window_start or day >= today or not isfinite(value) or value <= 0:
            continue
        values[day] = value

    return [EemOnlineDailyConsumption(day, period_start(day), value) for day, value in sorted(values.items())]


def _normalize_meter_reading(
    readings: list[Mapping[str, Any]],
    start: date,
    end: date,
) -> tuple[date, float] | None:
    """Return the latest valid cumulative reading in the requested range."""
    values: dict[date, float] = {}
    for record in readings:
        raw_day = record.get("data")
        raw_value = record.get("totalRegistadores")
        if not isinstance(raw_day, str) or not isinstance(raw_value, int | float) or isinstance(raw_value, bool):
            continue
        try:
            day = date.fromisoformat(raw_day[:10])
        except ValueError:
            continue
        value = float(raw_value)
        if day < start or day > end or not isfinite(value) or value <= 0:
            continue
        values[day] = value

    if not values:
        return None
    latest_day = max(values)
    return latest_day, values[latest_day]
