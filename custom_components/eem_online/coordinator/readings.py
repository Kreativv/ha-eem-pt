"""Turn cumulative EEM meter registers into daily consumption."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise
from math import isfinite
from typing import Any


@dataclass(frozen=True, slots=True)
class EemOnlineRegister:
    """One cumulative register reported by the `leituras` endpoint."""

    key: str
    field: str
    name: str


REGISTERS: tuple[EemOnlineRegister, ...] = (
    EemOnlineRegister("", "totalRegistadores", "consumption"),
    EemOnlineRegister("vazio", "totalRegistador1", "Vazio consumption (register 1)"),
    EemOnlineRegister("ponta", "totalRegistador2", "Ponta consumption (register 2)"),
    EemOnlineRegister("cheias", "totalRegistador3", "Cheias consumption (register 3)"),
)


def normalize_register(readings: list[Mapping[str, Any]], field: str, end: date) -> dict[date, float]:
    """Return one positive cumulative value per day; the last same-day record wins."""
    values: dict[date, float] = {}
    for record in readings:
        raw_day = record.get("data")
        raw_value = record.get(field)
        if not isinstance(raw_day, str) or not isinstance(raw_value, int | float) or isinstance(raw_value, bool):
            continue
        try:
            day = date.fromisoformat(raw_day[:10])
        except ValueError:
            continue
        value = float(raw_value)
        if day > end or not isfinite(value) or value <= 0:
            continue
        values[day] = value
    return values


def daily_consumption(cumulative: Mapping[date, float]) -> list[tuple[date, float]]:
    """Return the consumption of every complete day between the first and the last reading.

    A reading dated D is the register at the start of D, so day D is the difference to the reading of D+1.
    Days without a reading share the difference to the next reading evenly, and a decreasing register
    (a replaced meter) counts as zero instead of a negative consumption.
    """
    days = sorted(cumulative)
    result: list[tuple[date, float]] = []
    for left, right in pairwise(days):
        span = (right - left).days
        step = round(max(cumulative[right] - cumulative[left], 0.0) / span, 6)
        result.extend((left + timedelta(days=offset), step) for offset in range(span))
    return result
