# iCloud Find My — Home Assistant custom integration

A custom Home Assistant integration for Apple's Find My, written from scratch
to avoid `pyicloud` (which has been broken by Apple's auth changes).

## Why not pyicloud?

Apple now requires **SRP-6a** authentication and **anisette** device-attestation
headers for unofficial iCloud clients. `pyicloud` predates these requirements
and breaks every time Apple tightens enforcement. This integration uses the
modern `findmy` Python library (which implements SRP + anisette) so the auth
layer is maintained outside this repo.

The auth layer is fully isolated in `api.py` — if `findmy` ever breaks, only
that one file needs to change. Entities, the coordinator, services, and the
config flow all talk to a small `FindMyClient` adapter and a stable
`FindMyDevice` dataclass.

## What you get

- **device_tracker** entities with GPS coordinates and accuracy for every
  location-capable Apple device on your iCloud account.
- **Sensor** entities for battery level (%), last-seen timestamp, and battery
  charging status.
- **Binary sensor** entities for online status, low-power mode, and
  locating-in-progress.
- **Services** to play a sound or enable Lost Mode on any device, plus a
  manual refresh.
- **Config flow UI** — Apple ID + password + 2FA code, all in the UI. The
  trust token is persisted so you don't have to re-enter 2FA after a restart.
- Sessions are stored in the config entry; cookies are auto-rotated and saved
  back so you stay logged in.
- Re-auth flow triggers automatically if Apple invalidates the session.

## Install

1. Copy the `custom_components/icloud_findmy/` folder into your HA config
   directory: `/config/custom_components/icloud_findmy/`.
2. Restart Home Assistant.
3. Settings → Devices & Services → Add Integration → "iCloud Find My".
4. Enter your Apple ID, password, and (when prompted) the 6-digit 2FA code
   that Apple sends to your trusted devices.

The default Anisette server is the community-hosted SideStore one
(`https://ani.sidestore.io`). For more privacy, self-host with
[Dadoum/anisette-v3-server](https://github.com/Dadoum/anisette-v3-server) and
paste your URL during setup.

## Services

```yaml
service: icloud_findmy.play_sound
data:
  device_id: "Maksym's iPhone"

service: icloud_findmy.lost_mode
data:
  device_id: "Maksym's iPhone"
  message: "If found, please call."
  phone_number: "+1 555 123 4567"

service: icloud_findmy.refresh
```

`device_id` accepts either the Find My device id or the device name shown in
the Find My app.

## Options

- **Polling interval** (seconds, default 300): how often to refresh device
  state. Don't set this too low — Apple rate-limits aggressively. 60–300s is
  reasonable.

## Surviving Apple changes

When Apple changes something:

1. `findmy` typically ships an update within days. Bump the version in
   `manifest.json` (`requirements: ["findmy>=X.Y.Z"]`) and restart.
2. If something deeper breaks, the only file you need to touch is `api.py` —
   everything else is plain Home Assistant code with no Apple-specific logic.
3. Anisette servers occasionally rotate. If yours stops responding, swap the
   URL in the integration options or self-host.

## Caveats

- **Advanced Data Protection**: if you have ADP enabled, Find My data is
  end-to-end encrypted with keys Apple cannot decrypt server-side. This
  integration relies on Apple's web Find My API, which only works for
  non-ADP-protected devices. (You said you don't have ADP on, so you're
  fine.)
- This is an unofficial use of Apple's API. It can stop working at any time.
  Don't depend on it for anything safety-critical.
- Keep your polling interval reasonable. Excessive requests can get the
  account flagged.

## File layout

```
custom_components/icloud_findmy/
├── __init__.py            # entry setup, services
├── manifest.json          # integration metadata + findmy dep
├── const.py               # constants
├── api.py                 # the only file that imports findmy
├── coordinator.py         # DataUpdateCoordinator
├── config_flow.py         # UI setup + 2FA + reauth + options
├── device_tracker.py      # GPS entities
├── sensor.py              # battery / last-seen / battery status
├── binary_sensor.py       # online / low-power / locating
├── services.yaml          # service descriptors
├── strings.json           # UI strings
└── translations/
    └── en.json
```
