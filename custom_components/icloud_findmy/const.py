"""Constants for the iCloud Find My integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "icloud_findmy"

# Config / options keys
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_ANISETTE_URL = "anisette_url"
CONF_2FA_CODE = "code"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_SESSION = "session"  # base64-encoded findmy account export
CONF_TRACKED_DEVICES = "tracked_devices"

# Defaults.
# The default Anisette server is the SideStore community-hosted one. Users
# concerned about data sovereignty can self-host (https://github.com/Dadoum/anisette-v3-server)
# and point the integration at their own URL.
DEFAULT_ANISETTE_URL = "https://ani.sidestore.io"
DEFAULT_SCAN_INTERVAL = timedelta(minutes=5)
MIN_SCAN_INTERVAL = timedelta(seconds=30)

# Service names
SERVICE_PLAY_SOUND = "play_sound"
SERVICE_LOST_MODE = "lost_mode"
SERVICE_REFRESH = "refresh"

# Service attributes
ATTR_DEVICE_ID = "device_id"
ATTR_MESSAGE = "message"
ATTR_PHONE_NUMBER = "phone_number"

# Coordinator data keys
DATA_DEVICES = "devices"
DATA_ACCOUNT = "account"
DATA_COORDINATOR = "coordinator"

# Manufacturer string for the device registry
MANUFACTURER = "Apple"

# Logger name
LOGGER_NAME = "custom_components.icloud_findmy"
