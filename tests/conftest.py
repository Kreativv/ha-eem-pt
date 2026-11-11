"""Shared fixtures for EEM Online tests."""

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eem_online.const import CONF_CONTRACT, DOMAIN
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom integrations in every test."""


@pytest.fixture
def mock_recorder_before_hass(recorder_db_url: str) -> None:
    """Prepare the recorder database URL before Home Assistant starts."""


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return a configured EEM contract."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="EEM Online 123456",
        unique_id="123456",
        data={CONF_USERNAME: "123", CONF_PASSWORD: "secret", CONF_CONTRACT: "123456"},
    )


@pytest.fixture
def mock_api_client() -> Generator[AsyncMock]:
    """Replace the EEM client used during config-entry setup."""
    with patch("custom_components.eem_online.EemOnlineApiClient", autospec=True) as client_class:
        client = client_class.return_value
        client.async_get_weekly_summary.return_value = {
            "consumos": [
                {
                    "data": "2026-09-12",
                    "consumoCheias": 1.0,
                    "consumoVazio": 2.0,
                    "consumoPonta": 0.5,
                },
            ],
        }
        client.async_get_meter_readings.return_value = [
            {
                "data": "2026-09-12T00:00:00",
                "totalRegistadores": 10182.0,
            },
        ]
        yield client


@pytest.fixture
def mock_statistics() -> Generator[AsyncMock]:
    """Avoid the recorder in tests unrelated to statistic persistence."""
    with (
        patch(
            "custom_components.eem_online.coordinator.base.async_last_imported_day",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "custom_components.eem_online.coordinator.base.async_import_readings",
            new_callable=AsyncMock,
            return_value={},
        ) as import_readings,
    ):
        yield import_readings


@pytest.fixture
async def init_integration(
    recorder_mock: object,
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_api_client: AsyncMock,
    mock_statistics: AsyncMock,
) -> MockConfigEntry:
    """Load the integration and return its config entry."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
