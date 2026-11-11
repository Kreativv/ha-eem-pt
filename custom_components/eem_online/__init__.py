"""Home Assistant integration for EEM Online."""

from typing import TYPE_CHECKING

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .api import EemOnlineApiClient
from .const import CONF_CONTRACT, DOMAIN
from .coordinator import EemOnlineDataUpdateCoordinator
from .data import EemOnlineData
from .service_actions import async_setup_services

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

    from .data import EemOnlineConfigEntry

PLATFORMS: list[Platform] = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's service actions."""
    await async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: EemOnlineConfigEntry) -> bool:
    """Set up EEM Online from a config entry."""
    client = EemOnlineApiClient(
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        session=async_get_clientsession(hass),
    )
    coordinator = EemOnlineDataUpdateCoordinator(hass, entry, client, entry.data[CONF_CONTRACT])
    entry.runtime_data = EemOnlineData(client=client, coordinator=coordinator)

    await coordinator.async_config_entry_first_refresh()
    entry.async_on_unload(coordinator.async_add_listener(lambda: None))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EemOnlineConfigEntry) -> bool:
    """Unload an EEM Online config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
