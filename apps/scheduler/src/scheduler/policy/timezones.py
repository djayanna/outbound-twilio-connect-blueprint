"""Resolve a reasonable local timezone for an E.164 phone number.

Perfect timezone recovery from a phone number is impossible — a US number
could be AKDT or EDT. The blueprint takes a conservative stance: use the
IANA zone the caller sets on `job.constraints.timezone` if present,
otherwise derive from the country code of the number using a bundled
primary-zone table.

This is good enough for the quickstart. For production, overlay a per-user
timezone from your system of record and set it on the Job.
"""
from __future__ import annotations

from zoneinfo import ZoneInfo

import phonenumbers

# Primary IANA zone per country code. Multi-zone countries use the biggest
# metro's zone as a safe default (US → Eastern is the latest sunset over the
# contiguous US, so quiet-hour checks lean conservative). Override with
# `job.constraints.timezone` when you can.
_COUNTRY_PRIMARY_ZONE: dict[str, str] = {
    "US": "America/New_York",
    "CA": "America/Toronto",
    "MX": "America/Mexico_City",
    "GB": "Europe/London",
    "IE": "Europe/Dublin",
    "DE": "Europe/Berlin",
    "FR": "Europe/Paris",
    "ES": "Europe/Madrid",
    "IT": "Europe/Rome",
    "NL": "Europe/Amsterdam",
    "SE": "Europe/Stockholm",
    "PL": "Europe/Warsaw",
    "AU": "Australia/Sydney",
    "NZ": "Pacific/Auckland",
    "JP": "Asia/Tokyo",
    "KR": "Asia/Seoul",
    "SG": "Asia/Singapore",
    "IN": "Asia/Kolkata",
    "BR": "America/Sao_Paulo",
    "AR": "America/Argentina/Buenos_Aires",
    "ZA": "Africa/Johannesburg",
}

_DEFAULT_ZONE = "UTC"


def resolve_zone(phone_e164: str, override: str | None = None) -> ZoneInfo:
    """Return a ZoneInfo. Falls back to UTC on unknown country."""
    if override:
        try:
            return ZoneInfo(override)
        except Exception:
            pass  # fall through to number-derived
    try:
        parsed = phonenumbers.parse(phone_e164, None)
        region = phonenumbers.region_code_for_number(parsed)
        zone_name = _COUNTRY_PRIMARY_ZONE.get(region or "", _DEFAULT_ZONE)
    except phonenumbers.NumberParseException:
        zone_name = _DEFAULT_ZONE
    return ZoneInfo(zone_name)


__all__ = ["resolve_zone"]
