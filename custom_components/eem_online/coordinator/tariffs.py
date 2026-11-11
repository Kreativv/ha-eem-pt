"""EEM prices for Madeira and the cost of one day, itemized as on the EEM invoice."""

from calendar import monthrange
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class EemOnlinePrices:
    """Regulated prices without VAT, valid from a day until the next entry."""

    valid_from: date
    vazio: float
    ponta: float
    cheias: float
    power_per_day: float


# RAM, BTN <= 20.7 kVA, tri-horária, 6.9 kVA contracted power, EUR without VAT.
# December 2025 and January 2026: EEM invoice. October 2026: ERSE Diretiva 4/2026.
PRICES: tuple[EemOnlinePrices, ...] = (
    EemOnlinePrices(date(2025, 12, 1), vazio=0.1082, ponta=0.2484, cheias=0.1741, power_per_day=0.3386),
    EemOnlinePrices(date(2026, 1, 1), vazio=0.1075, ponta=0.2531, cheias=0.1650, power_per_day=0.3648),
    EemOnlinePrices(date(2026, 10, 1), vazio=0.1131, ponta=0.2589, cheias=0.1707, power_per_day=0.3648),
)
TARIFFS: tuple[str, ...] = ("vazio", "ponta", "cheias")

VAT_REDUCED = 0.04
VAT_NORMAL = 0.22
REDUCED_VAT_KWH_PER_DAY = 200 / 30
IEC_PER_KWH = 0.001
OPERATION_FEE_PER_MONTH = 0.08
AUDIOVISUAL_FEE_PER_MONTH = 2.85


def prices_for(day: date) -> EemOnlinePrices | None:
    """Return the prices valid on a day, or None before the first known prices."""
    current: EemOnlinePrices | None = None
    for prices in PRICES:
        if prices.valid_from <= day:
            current = prices
    return current


def energy_costs(day: date, consumption: Mapping[str, float]) -> dict[str, float] | None:
    """Return each tariff's cost of one day including VAT and IEC.

    The reduced VAT rate covers 200 kWh per 30 days, shared by the tariffs in proportion
    to their consumption; the rest, and IEC, carry the normal rate.
    """
    prices = prices_for(day)
    if prices is None:
        return None
    unit_prices = {"vazio": prices.vazio, "ponta": prices.ponta, "cheias": prices.cheias}
    total = sum(consumption.values())
    reduced_share = min(1.0, REDUCED_VAT_KWH_PER_DAY / total) if total > 0 else 1.0
    vat_factor = 1 + reduced_share * VAT_REDUCED + (1 - reduced_share) * VAT_NORMAL
    return {
        tariff: round(kwh * unit_prices[tariff] * vat_factor + kwh * IEC_PER_KWH * (1 + VAT_NORMAL), 6)
        for tariff, kwh in consumption.items()
    }


def fixed_costs(day: date) -> float | None:
    """Return one day's contracted power, operation fee and audiovisual contribution including VAT."""
    prices = prices_for(day)
    if prices is None:
        return None
    days_in_month = monthrange(day.year, day.month)[1]
    monthly = OPERATION_FEE_PER_MONTH * (1 + VAT_NORMAL) + AUDIOVISUAL_FEE_PER_MONTH * (1 + VAT_REDUCED)
    return round(prices.power_per_day * (1 + VAT_NORMAL) + monthly / days_in_month, 6)
