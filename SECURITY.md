# Security Policy

## Deployment Boundary

Caelus is designed for a trusted private LAN. It does not provide user
accounts, login sessions, or a complete authentication boundary. Browser-based
settings changes use a per-process CSRF token, but CSRF protection does not
authenticate people who can reach the application.

Caelus binds HTTP to `0.0.0.0:8767` by default, making the dashboard reachable
through every network interface allowed by the host firewall. Do not expose
port 8767 directly to the Internet, configure public router port forwarding to
it, or place it behind a public reverse proxy without adding a suitable
authentication layer.

Anyone who can reach the service can read dashboard data and exports, trigger
gateway polling, and use the gateway-discovery feature to make HTTP requests to
a selected LAN host. Treat network reachability as authorization. The gateway
validation limits requests to plain HTTP base URLs and known Ecowitt endpoints,
but it is not a substitute for network isolation.

Use these controls:

- Keep the Caelus host and Ecowitt gateway on a trusted LAN or isolated IoT
  VLAN.
- Restrict inbound port 8767 with host and network firewalls.
- Set `CAELUS_HTTP_HOST=127.0.0.1` when only local access is required.
- Use a VPN or another authenticated private-access layer for remote access.
- Keep the Windy iframe sandbox and supported-host validation in place.

## External Services and Privacy

Depending on configuration, Caelus can contact IP-location and forecast
providers. IP-assisted location sends the server's public IP to `ipapi.co` or
`ipwho.is`. Forecast requests send the configured coordinates to MET Norway,
Open-Meteo, or the US National Weather Service. The embedded Windy map also
loads remote content in the browser.

Disable IP location and enter coordinates manually if public-IP lookup is not
acceptable. Review the privacy and security requirements of the selected
external services before deployment.

## Runtime Data

Do not commit `data/settings.json`, `data/forecast.json`, or `data/caelus.db`
from a live installation. These files can disclose precise coordinates,
private gateway addresses, station inventory, forecasts, and historical
weather observations. Protect the host account, filesystem, backups, and
exports accordingly.

Gateway and Windy URL validation rejects embedded credentials. Do not weaken
those restrictions or add credentials to configured URLs.

## Reporting a Vulnerability

If you discover a security issue, report it privately:

- [GitHub private vulnerability reporting](https://github.com/mot-yelraf/Caelus/security/advisories/new)
- Email: mot.yelraf@gmail.com

Please include a clear description, steps to reproduce, affected versions, and
any relevant logs or screenshots. We will acknowledge reports within seven
days and provide a remediation timeline when possible.
