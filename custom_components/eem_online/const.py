"""Constants for EEM Online."""

from datetime import timedelta
from logging import Logger, getLogger
from zoneinfo import ZoneInfo

LOGGER: Logger = getLogger(__package__)

DOMAIN = "eem_online"
CONF_CONTRACT = "contract"

BASE_URL = "https://eemonline.eem.pt"
ATTRIBUTION = "Data provided by EEM Online"
UPDATE_INTERVAL = timedelta(hours=12)
CORRECTION_WINDOW_DAYS = 7
METER_READING_WINDOW_DAYS = 30
MAX_GAP_FILL_DAYS = 366
MAX_HISTORY_DAYS = 3 * 366
MADEIRA_TIME_ZONE = ZoneInfo("Atlantic/Madeira")
