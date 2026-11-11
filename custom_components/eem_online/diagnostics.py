"""Diagnostics for EEM Online."""

import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse

import aiohttp

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.redact import async_redact_data

from .const import BASE_URL, CONF_CONTRACT

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import EemOnlineConfigEntry

TO_REDACT = {CONF_USERNAME, CONF_PASSWORD, CONF_CONTRACT}
SCRIPT_SRC = re.compile(r"""<script[^>]+src=["']([^"']+)["']""", re.IGNORECASE)
LINK_HREF = re.compile(r"""href=["']([^"'#?]+)["']""", re.IGNORECASE)
API_CONTEXT = re.compile(r".{0,100}(?:api/sm|WS3BaseURL|leituras|diagrama|carga|consumo).{0,140}", re.IGNORECASE)
MAX_PAGES = 25
MAX_MATCHES = 300


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: EemOnlineConfigEntry,
) -> dict[str, Any]:
    """Return redacted configuration and normalized coordinator data."""
    coordinator = entry.runtime_data.coordinator
    data = coordinator.data
    return {
        "entry": {
            "version": entry.version,
            "state": str(entry.state),
            "data": async_redact_data(entry.data, TO_REDACT),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval": str(coordinator.update_interval),
            "latest_day": str(data.latest_day) if data and data.latest_day else None,
            "latest_consumption": data.latest_consumption if data else None,
            "latest_meter_day": str(data.latest_meter_day) if data and data.latest_meter_day else None,
            "latest_meter_reading": data.latest_meter_reading if data else None,
            "summary_available": data.summary_available if data else None,
            "meter_readings_available": data.meter_readings_available if data else None,
        },
        "portal_endpoints": await _async_portal_endpoints(hass),
    }


async def _async_portal_endpoints(hass: HomeAssistant) -> dict[str, Any]:
    """Temporary fork-only probe: list API references found in the public portal pages and scripts."""
    session = async_get_clientsession(hass)
    host = urlparse(BASE_URL).netloc
    pages = [BASE_URL + "/"]
    scripts: list[str] = []
    seen: set[str] = set()
    matches: list[str] = []
    errors: list[str] = []

    async def fetch(url: str) -> str | None:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as response:
                if response.status != 200:
                    errors.append(f"{url}: HTTP {response.status}")
                    return None
                return await response.text(errors="replace")
        except Exception as err:  # noqa: BLE001 - debugging probe, report and continue
            errors.append(f"{url}: {type(err).__name__}")
            return None

    def collect(text: str, source: str) -> None:
        for match in API_CONTEXT.finditer(text):
            snippet = " ".join(match.group(0).split())
            if snippet not in seen and len(matches) < MAX_MATCHES:
                seen.add(snippet)
                matches.append(f"{source}: {snippet}")

    visited: set[str] = set()
    while pages and len(visited) < MAX_PAGES:
        page = pages.pop(0)
        if page in visited:
            continue
        visited.add(page)
        html = await fetch(page)
        if html is None:
            continue
        collect(html, urlparse(page).path or "/")
        for src in SCRIPT_SRC.findall(html):
            url = urljoin(page, src)
            if urlparse(url).netloc == host and url not in scripts:
                scripts.append(url)
        for href in LINK_HREF.findall(html):
            url = urljoin(page, href)
            if (
                urlparse(url).netloc == host
                and url not in visited
                and not url.endswith((".css", ".png", ".jpg", ".svg", ".pdf", ".ico"))
            ):
                pages.append(url)

    for script in scripts:
        text = await fetch(script)
        if text is not None:
            collect(text, urlparse(script).path)

    return {"pages": sorted(visited), "scripts": scripts, "matches": matches, "errors": errors[:50]}
