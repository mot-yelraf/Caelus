# Third-Party and Binary Notices

Caelus source code is distributed under the BSD 2-Clause License in `LICENSE`.

## Python Dependencies

Caelus installs pinned third-party Python packages from `requirements.txt`,
including FastAPI, Uvicorn, Jinja, Pydantic, Requests, python-multipart,
Astral, Skyfield, and skyfield-data. Each package remains governed by its own
license and distribution terms. Installing or redistributing Caelus does not
replace those terms with the Caelus license.

## JPL DE421 Ephemeris

The pinned `skyfield-data` package supplies the JPL DE421 planetary ephemeris
used by Skyfield for offline astronomical calculations. The ephemeris is
installed as dependency data; it is not tracked as a binary file in this
repository.

The authoritative JPL Solar System Dynamics download is:

`https://ssd.jpl.nasa.gov/ftp/eph/planets/bsp/de421.bsp`

Preserve the notices and license information supplied with Skyfield,
skyfield-data, and the ephemeris when redistributing an installed Caelus
runtime. Skyfield is MIT-licensed; other installed dependencies and data remain
subject to their respective distributions.

## Remote Weather Services

Caelus can display or normalize data from Ecowitt gateways, Windy, MET Norway,
Open-Meteo, the US National Weather Service, `ipapi.co`, and `ipwho.is`. Caelus
does not redistribute those services or their software. Access to their data
and endpoints remains subject to each provider's terms, attribution
requirements, availability, and privacy policy.

## Project Visual Assets

The dashboard backgrounds, Caelus compass mark, and lunar surface texture under
`static/` are distributed as part of Caelus. Preserve this notice and any
asset-specific provenance or license information added alongside those files
when redistributing them.
