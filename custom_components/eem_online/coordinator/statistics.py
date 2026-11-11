"""Import EEM meter-reading consumption into Home Assistant long-term statistics."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from custom_components.eem_online.const import DOMAIN, MADEIRA_TIME_ZONE
from homeassistant.components.recorder.models import StatisticData, StatisticMeanType, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.recorder import get_instance

from .readings import REGISTERS, EemOnlineRegister, daily_consumption, normalize_register

SUM_LOOKBACK = timedelta(days=3700)


@dataclass(frozen=True, slots=True)
class EemOnlineImportResult:
    """What one register import wrote."""

    first_day: date
    last_day: date
    days: int
    first_reading: float
    last_reading: float


def statistic_id(contract: str, key: str = "") -> str:
    """Return the stable Energy statistic ID for a contract and register."""
    suffix = f"_{key}" if key else ""
    return f"{DOMAIN}:{contract}_consumption{suffix}"


def period_start(day: date) -> datetime:
    """Convert an EEM civil day start in Madeira to UTC."""
    return datetime.combine(day, time.min, tzinfo=MADEIRA_TIME_ZONE).astimezone(UTC)


async def async_last_imported_day(hass: HomeAssistant, contract: str) -> date | None:
    """Return the newest day of the total consumption statistic."""
    stat_id = statistic_id(contract)
    result = await get_instance(hass).async_add_executor_job(
        get_last_statistics,
        hass,
        1,
        stat_id,
        False,
        {"sum"},
    )
    rows = result.get(stat_id, [])
    if not rows or (start := rows[0].get("start")) is None:
        return None
    return datetime.fromtimestamp(start, UTC).astimezone(MADEIRA_TIME_ZONE).date()


async def async_import_readings(
    hass: HomeAssistant,
    contract: str,
    readings: list[Mapping[str, Any]],
    end: date,
) -> dict[str, EemOnlineImportResult]:
    """Rewrite every register statistic from the first fetched reading onwards."""
    results: dict[str, EemOnlineImportResult] = {}
    for register in REGISTERS:
        cumulative = normalize_register(readings, register.field, end)
        days = daily_consumption(cumulative)
        if not days:
            continue
        await _async_import_register(hass, contract, register, days)
        first_day, last_day = min(cumulative), max(cumulative)
        results[register.key or "total"] = EemOnlineImportResult(
            first_day=days[0][0],
            last_day=days[-1][0],
            days=len(days),
            first_reading=cumulative[first_day],
            last_reading=cumulative[last_day],
        )
    return results


async def _async_import_register(
    hass: HomeAssistant,
    contract: str,
    register: EemOnlineRegister,
    days: list[tuple[date, float]],
) -> None:
    """Upsert daily rows whose sums continue from the last row before the first day."""
    stat_id = statistic_id(contract, register.key)
    running_sum = await _async_sum_before(hass, stat_id, days[0][0])
    statistics: list[StatisticData] = []
    for day, value in days:
        running_sum += value
        statistics.append(StatisticData(start=period_start(day), state=value, sum=running_sum))

    metadata: StatisticMetaData = {
        "mean_type": StatisticMeanType.NONE,
        "has_sum": True,
        "name": f"EEM Online {contract} {register.name}",
        "source": DOMAIN,
        "statistic_id": stat_id,
        "unit_class": "energy",
        "unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
    }
    async_add_external_statistics(hass, metadata, statistics)


async def _async_sum_before(hass: HomeAssistant, stat_id: str, day: date) -> float:
    """Return the cumulative sum of the newest row before a day, or zero for a new series."""
    end = period_start(day)
    result = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        end - SUM_LOOKBACK,
        end,
        {stat_id},
        "hour",
        None,
        {"sum"},
    )
    latest_start: float | None = None
    latest_sum = 0.0
    for row in result.get(stat_id, []):
        start = row.get("start")
        row_sum = row.get("sum")
        if start is None or row_sum is None:
            continue
        if latest_start is None or start > latest_start:
            latest_start = start
            latest_sum = float(row_sum)
    return latest_sum
