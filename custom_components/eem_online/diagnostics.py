"""Diagnostics for EEM Online."""

from datetime import timedelta
import json
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urljoin, urlparse

import aiohttp
from yarl import URL

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.redact import async_redact_data
from homeassistant.util import dt as dt_util

from .const import BASE_URL, CONF_CONTRACT, MADEIRA_TIME_ZONE

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import EemOnlineConfigEntry

TO_REDACT = {CONF_USERNAME, CONF_PASSWORD, CONF_CONTRACT}
SCRIPT_SRC = re.compile(r"""<script[^>]+src=["']([^"']+)["']""", re.IGNORECASE)
LINK_HREF = re.compile(r"""href=["']([^"'#?]+)["']""", re.IGNORECASE)
API_CONTEXT = re.compile(r".{0,120}(?:api/sm|WS3BaseURL|proxy\.ashx|bundles/|/api/).{0,160}", re.IGNORECASE)
BUNDLES = ("private", "privado", "privada", "reserved", "reservada", "area", "cliente", "client", "auth", "app", "main")
PATHS = (
    "diagramacargas",
    "diagramacarga",
    "diagramadecargas",
    "diagrama",
    "diagramas",
    "cargas",
    "curvacarga",
    "curvascarga",
    "consumos",
    "resumo",
    "resumo/ultimomes",
    "resumo/diario",
    "resumo/ontem",
)
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
        "endpoint_probe": await _async_probe(hass, entry),
    }


async def _async_probe(hass: HomeAssistant, entry: EemOnlineConfigEntry) -> dict[str, Any]:
    """Temporary fork-only probe: try likely bundle names and load-profile paths with the session token."""
    session = async_get_clientsession(hass)
    client = entry.runtime_data.client
    contract = entry.data[CONF_CONTRACT]
    try:
        await client._async_login()  # noqa: SLF001 - debugging probe
    except Exception as err:  # noqa: BLE001
        return {"login_error": type(err).__name__}
    token = client._token or ""  # noqa: SLF001 - debugging probe
    headers = {"x-auth-token": token}
    day = (dt_util.now(MADEIRA_TIME_ZONE).date() - timedelta(days=2)).isoformat()
    results: dict[str, Any] = {}

    async def get(url: str, encoded: bool = False) -> dict[str, Any]:
        try:
            async with session.get(
                URL(url, encoded=encoded), headers=headers, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                text = await response.text(errors="replace")
                body: Any
                try:
                    body = _anonymize(json.loads(text))
                    body = json.dumps(body)[:600]
                except ValueError:
                    body = " ".join(text.split())[:200]
                return {"status": response.status, "type": response.content_type, "body": body}
        except Exception as err:  # noqa: BLE001
            return {"error": type(err).__name__}

    for name in BUNDLES:
        try:
            async with session.get(
                f"{BASE_URL}/bundles/js-{name}-pt", headers=headers, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                if response.status != 200:
                    continue
                text = await response.text(errors="replace")
        except Exception:  # noqa: BLE001
            continue
        snippets = [" ".join(match.group(0).split()) for match in API_CONTEXT.finditer(text)]
        results[f"bundle:{name}"] = {"length": len(text), "matches": list(dict.fromkeys(snippets))[:150]}
    for path in PATHS:
        base = f"{BASE_URL}/proxy.ashx?proxy-WS3BaseURL/api/sm/leituras/{contract}/{path}"
        results[path] = await get(base, encoded=True)
        query = quote(f"?data={day} 00:00&data2={day} 23:59", safe="")
        with_query = await get(base + query, encoded=True)
        if with_query.get("status") != results[path].get("status") or with_query.get("body") != results[path].get(
            "body"
        ):
            results[f"{path}?data"] = with_query
    return results


def _anonymize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _anonymize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_anonymize(item) for item in value[:6]]
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str) and re.match(r"\d{4}-\d{2}-\d{2}", value):
        return value
    return "***"


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
        for src in [*SCRIPT_SRC.findall(html), *re.findall(r"/bundles/[\w-]+", html)]:
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
