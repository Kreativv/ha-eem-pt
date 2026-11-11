"""Tests for turning cumulative meter registers into daily consumption."""

from datetime import date

import pytest

from custom_components.eem_online.coordinator.readings import daily_consumption, normalize_register

# Anonymized live `leituras` rows, newest first as EEM returns them.
LIVE_READINGS = [
    {"data": "2026-11-10T00:00:00", "totalRegistadores": 36965.748, "totalRegistador1": 19145.323},
    {"data": "2026-11-09T00:00:00", "totalRegistadores": 36941.498, "totalRegistador1": 19137.534},
    {"data": "2026-11-08T00:00:00", "totalRegistadores": 36916.104, "totalRegistador1": 19112.14},
    {"data": "2026-11-07T00:00:00", "totalRegistadores": 36885.632, "totalRegistador1": 19091.8},
    {"data": "2026-11-06T00:00:00", "totalRegistadores": 36859.462, "totalRegistador1": 19085.731},
    {"data": "2026-11-05T00:00:00", "totalRegistadores": 36828.264, "totalRegistador1": 19077.437},
    {"data": "2026-11-04T00:00:00", "totalRegistadores": 36801.035, "totalRegistador1": 19069.734},
]


def test_reading_differences_match_the_portal_daily_totals() -> None:
    """A reading dated D is the register at the start of D, so D+1 minus D is the consumption of D."""
    totals = daily_consumption(normalize_register(LIVE_READINGS, "totalRegistadores", date(2026, 11, 10)))

    assert [day for day, _ in totals] == [date(2026, 11, day) for day in range(4, 10)]
    # The portal's complete daily summaries for 4-7 November: 27.229, 31.198, 26.170 and 30.472 kWh.
    assert [value for _, value in totals] == pytest.approx([27.229, 31.198, 26.170, 30.472, 25.394, 24.25])


def test_register_fields_are_independent() -> None:
    """Each register produces its own series from the same rows."""
    vazio = daily_consumption(normalize_register(LIVE_READINGS, "totalRegistador1", date(2026, 11, 10)))

    assert vazio[0] == (date(2026, 11, 4), pytest.approx(7.703))


def test_missing_days_share_the_next_difference() -> None:
    """A gap in the readings is spread evenly instead of dropping or doubling days."""
    cumulative = {date(2026, 1, 1): 100.0, date(2026, 1, 4): 106.0, date(2026, 1, 5): 107.5}

    assert daily_consumption(cumulative) == [
        (date(2026, 1, 1), 2.0),
        (date(2026, 1, 2), 2.0),
        (date(2026, 1, 3), 2.0),
        (date(2026, 1, 4), 1.5),
    ]


def test_decreasing_register_counts_as_zero() -> None:
    """A replaced meter must not produce negative consumption."""
    cumulative = {date(2026, 1, 1): 500.0, date(2026, 1, 2): 3.0, date(2026, 1, 3): 5.0}

    assert daily_consumption(cumulative) == [(date(2026, 1, 1), 0.0), (date(2026, 1, 2), 2.0)]


def test_normalize_register_rejects_invalid_and_future_records() -> None:
    """Missing, non-numeric, non-positive and future values are ignored; the last same-day record wins."""
    readings = [
        {"data": "2026-01-01T00:00:00", "totalRegistador2": 10.0},
        {"data": "2026-01-01T12:00:00", "totalRegistador2": 11.0},
        {"data": "2026-01-02T00:00:00", "totalRegistador2": 0.0},
        {"data": "2026-01-03T00:00:00", "totalRegistador2": None},
        {"data": "2026-01-04T00:00:00", "totalRegistador2": True},
        {"data": "invalid", "totalRegistador2": 12.0},
        {"data": "2026-01-06T00:00:00", "totalRegistador2": 13.0},
    ]

    assert normalize_register(readings, "totalRegistador2", date(2026, 1, 5)) == {date(2026, 1, 1): 11.0}
    assert daily_consumption({date(2026, 1, 1): 11.0}) == []
