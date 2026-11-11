"""Tests for the meter-reading Energy statistics."""

from collections.abc import Mapping
from datetime import UTC, date, timedelta
from typing import Any

import pytest

from custom_components.eem_online.coordinator.statistics import (
    async_import_readings,
    async_last_imported_day,
    cost_statistic_id,
    fixed_charges_statistic_id,
    period_start,
    statistic_id,
)
from custom_components.eem_online.coordinator.tariffs import energy_costs, fixed_costs
from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.core import HomeAssistant
from homeassistant.helpers.recorder import get_instance

CONTRACT = "456"


def _readings(start: date, values: list[float], field: str = "totalRegistadores") -> list[Mapping[str, Any]]:
    return [
        {"data": f"{(start + timedelta(days=offset)).isoformat()}T00:00:00", field: value}
        for offset, value in enumerate(values)
    ]


async def _wait(hass: HomeAssistant, recorder: Recorder) -> None:
    await hass.async_block_till_done()
    await hass.async_add_executor_job(recorder.block_till_done)


async def _rows(hass: HomeAssistant, key: str = "", stat_id: str | None = None) -> list[dict[str, Any]]:
    stat_id = stat_id or statistic_id(CONTRACT, key)
    result = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        period_start(date(2025, 1, 1)),
        None,
        {stat_id},
        "hour",
        None,
        {"state", "sum"},
    )
    return [dict(row) for row in sorted(result.get(stat_id, []), key=lambda row: row["start"])]


async def test_import_is_idempotent_and_reports_the_imported_range(
    recorder_mock: Recorder, hass: HomeAssistant
) -> None:
    """Importing the same readings twice gives the same rows and sums."""
    readings = _readings(date(2026, 1, 1), [100.0, 101.0, 103.0, 106.0])

    for _ in range(2):
        summary = await async_import_readings(hass, CONTRACT, readings, date(2026, 1, 4))
        await _wait(hass, recorder_mock)

    rows = await _rows(hass)
    assert [row["start"] for row in rows] == [period_start(date(2026, 1, day)).timestamp() for day in (1, 2, 3)]
    assert [row["state"] for row in rows] == pytest.approx([1, 2, 3])
    assert [row["sum"] for row in rows] == pytest.approx([1, 3, 6])
    total = summary.registers["total"]
    assert (total.first_day, total.last_day, total.days) == (date(2026, 1, 1), date(2026, 1, 3), 3)
    assert (total.first_reading, total.last_reading) == (100.0, 106.0)
    assert await async_last_imported_day(hass, CONTRACT) == date(2026, 1, 3)


async def test_reimport_continues_from_the_row_before_it(recorder_mock: Recorder, hass: HomeAssistant) -> None:
    """A later window rewrites its days on top of the sum stored before them, without a jump."""
    await async_import_readings(
        hass, CONTRACT, _readings(date(2026, 1, 1), [100.0, 110.0, 120.0, 130.0]), date(2026, 2, 1)
    )
    await _wait(hass, recorder_mock)

    await async_import_readings(hass, CONTRACT, _readings(date(2026, 1, 3), [120.0, 125.0, 131.0]), date(2026, 2, 1))
    await _wait(hass, recorder_mock)

    rows = await _rows(hass)
    assert [row["state"] for row in rows] == pytest.approx([10, 10, 5, 6])
    assert [row["sum"] for row in rows] == pytest.approx([10, 20, 25, 31])


async def test_backfill_replaces_older_rows_and_keeps_sums_monotonic(
    recorder_mock: Recorder,
    hass: HomeAssistant,
) -> None:
    """Importing history before existing rows rewrites them so the cumulative sum never drops."""
    await async_import_readings(hass, CONTRACT, _readings(date(2026, 3, 10), [500.0, 505.0, 512.0]), date(2026, 4, 1))
    await _wait(hass, recorder_mock)

    history = _readings(date(2026, 3, 7), [480.0, 490.0, 495.0, 500.0, 505.0, 512.0])
    await async_import_readings(hass, CONTRACT, history, date(2026, 4, 1))
    await _wait(hass, recorder_mock)

    rows = await _rows(hass)
    assert [row["state"] for row in rows] == pytest.approx([10, 5, 5, 5, 7])
    assert [row["sum"] for row in rows] == pytest.approx([10, 15, 20, 25, 32])


async def test_registers_get_their_own_statistics(recorder_mock: Recorder, hass: HomeAssistant) -> None:
    """Every register that EEM reports becomes a separate statistic."""
    readings = [
        {"data": "2026-01-01T00:00:00", "totalRegistadores": 10.0, "totalRegistador1": 4.0, "totalRegistador3": 6.0},
        {"data": "2026-01-02T00:00:00", "totalRegistadores": 13.0, "totalRegistador1": 5.0, "totalRegistador3": 8.0},
    ]

    summary = await async_import_readings(hass, CONTRACT, readings, date(2026, 1, 2))
    await _wait(hass, recorder_mock)

    assert set(summary.registers) == {"total", "vazio", "cheias"}
    assert [row["state"] for row in await _rows(hass, "vazio")] == pytest.approx([1])
    assert [row["state"] for row in await _rows(hass, "cheias")] == pytest.approx([2])
    assert await _rows(hass, "ponta") == []


def test_statistic_ids_keep_the_existing_total_id() -> None:
    """The total keeps the ID existing Energy dashboards already use."""
    assert statistic_id("456") == "eem_online:456_consumption"
    assert statistic_id("456", "vazio") == "eem_online:456_consumption_vazio"


def test_madeira_dst_period_starts_are_hour_aligned() -> None:
    """Madeira civil midnights remain valid hourly starts across DST."""
    before = period_start(date(2026, 3, 29))
    after = period_start(date(2026, 3, 30))
    assert before.tzinfo is UTC
    assert before.minute == after.minute == 0
    assert (after - before).total_seconds() == 23 * 60 * 60


async def test_costs_follow_the_registers_and_skip_days_without_prices(
    recorder_mock: Recorder,
    hass: HomeAssistant,
) -> None:
    """Each tariff gets a cost statistic, plus fixed charges carried by a zero-energy statistic."""
    readings = [
        {
            "data": f"2025-11-{day}T00:00:00",
            "totalRegistadores": total,
            "totalRegistador1": vazio,
            "totalRegistador2": ponta,
            "totalRegistador3": cheias,
        }
        for day, total, vazio, ponta, cheias in (
            (29, 100.0, 50.0, 20.0, 30.0),
            (30, 120.0, 58.0, 24.0, 38.0),
        )
    ] + [
        {
            "data": "2025-12-01T00:00:00",
            "totalRegistadores": 145.0,
            "totalRegistador1": 68.0,
            "totalRegistador2": 29.0,
            "totalRegistador3": 48.0,
        },
        {
            "data": "2025-12-02T00:00:00",
            "totalRegistadores": 160.0,
            "totalRegistador1": 75.0,
            "totalRegistador2": 31.0,
            "totalRegistador3": 54.0,
        },
    ]

    summary = await async_import_readings(hass, CONTRACT, readings, date(2025, 12, 2))
    await _wait(hass, recorder_mock)

    expected = energy_costs(date(2025, 12, 1), {"vazio": 7.0, "ponta": 2.0, "cheias": 6.0})
    assert expected is not None
    vazio_rows = await _rows(hass, stat_id=cost_statistic_id(CONTRACT, "vazio"))
    assert [row["start"] for row in vazio_rows] == [period_start(date(2025, 12, 1)).timestamp()]
    assert [row["state"] for row in vazio_rows] == pytest.approx([expected["vazio"]])
    fixed_rows = await _rows(hass, stat_id=cost_statistic_id(CONTRACT, "fixed"))
    assert [row["state"] for row in fixed_rows] == pytest.approx([fixed_costs(date(2025, 12, 1))])
    assert [row["state"] for row in await _rows(hass, stat_id=fixed_charges_statistic_id(CONTRACT))] == [0.0]
    assert summary.costs == pytest.approx(
        {
            **{key: round(value, 2) for key, value in expected.items()},
            "fixed": round(fixed_costs(date(2025, 12, 1)) or 0, 2),
        }
    )
