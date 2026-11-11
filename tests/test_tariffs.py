"""Tests for the EEM price table and the daily cost calculation."""

from datetime import date

import pytest

from custom_components.eem_online.coordinator.tariffs import energy_costs, fixed_costs, prices_for


def test_prices_change_on_their_valid_from_day() -> None:
    """Each price set applies from its first day until the next one."""
    assert prices_for(date(2025, 11, 30)) is None
    assert prices_for(date(2025, 12, 31)).vazio == 0.1082
    assert prices_for(date(2026, 1, 1)).vazio == 0.1075
    assert prices_for(date(2026, 9, 30)).ponta == 0.2531
    assert prices_for(date(2026, 10, 1)).cheias == 0.1707


def test_energy_costs_match_the_invoice() -> None:
    """15 to 31 December 2025 on the January 2026 invoice: 128 / 60 / 151 kWh, 17 days.

    Invoice lines: energy 55.04 EUR, VAT 4 % on 18.58 EUR, VAT 22 % on 36.47 EUR, IEC 0.34 EUR plus 22 %.
    """
    days = 17
    daily = {"vazio": 128 / days, "ponta": 60 / days, "cheias": 151 / days}
    totals = {"vazio": 0.0, "ponta": 0.0, "cheias": 0.0}
    for offset in range(days):
        costs = energy_costs(date(2025, 12, 15 + offset), daily)
        assert costs is not None
        for tariff, cost in costs.items():
            totals[tariff] += cost

    invoice_total = 55.04 + 18.58 * 0.04 + 36.47 * 0.22 + 0.339 * 1.22
    assert sum(totals.values()) == pytest.approx(invoice_total, abs=0.10)


def test_low_consumption_stays_at_the_reduced_rate() -> None:
    """Below 200 kWh per 30 days only the reduced VAT rate applies to the energy."""
    costs = energy_costs(date(2026, 3, 1), {"vazio": 3.0, "ponta": 1.0, "cheias": 2.0})

    assert costs == pytest.approx(
        {
            "vazio": 3.0 * 0.1075 * 1.04 + 3.0 * 0.001 * 1.22,
            "ponta": 1.0 * 0.2531 * 1.04 + 1.0 * 0.001 * 1.22,
            "cheias": 2.0 * 0.1650 * 1.04 + 2.0 * 0.001 * 1.22,
        }
    )


def test_fixed_costs_spread_the_monthly_fees_over_the_month() -> None:
    """Contracted power per day, plus the monthly fees divided by the days of the month."""
    assert fixed_costs(date(2026, 2, 10)) == pytest.approx(0.3648 * 1.22 + (0.08 * 1.22 + 2.85 * 1.04) / 28)
    assert fixed_costs(date(2025, 11, 1)) is None
