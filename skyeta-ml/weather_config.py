"""Configuration shared by the reproducible SkyETA weather pipeline.

The airport set is the 50 busiest endpoints in a January 2025 BTS audit of the
same Reporting Carrier On-Time Performance data used by ``train.py``.  Keeping
the list explicit makes station and timezone choices reviewable.  GHCNh station
identifiers are resolved from NOAA's station list by the ICAO code below.
"""

from __future__ import annotations

from dataclasses import dataclass


GHCNH_STATION_LIST_URL = (
    "https://www.ncei.noaa.gov/oa/global-historical-climatology-network/"
    "hourly/doc/ghcnh-station-list.csv"
)
GHCNH_YEAR_PARQUET_URL = (
    "https://www.ncei.noaa.gov/oa/global-historical-climatology-network/"
    "hourly/access/by-year/{year}/parquet/GHCNh_{station}_{year}.parquet"
)
GHCNH_DOCUMENTATION_URL = (
    "https://www.ncei.noaa.gov/oa/global-historical-climatology-network/"
    "hourly/doc/ghcnh_DOCUMENTATION.pdf"
)

DEFAULT_WEATHER_YEAR = 2025
DEFAULT_CUTOFF_HOURS = 3.0
DEFAULT_MAX_OBSERVATION_AGE_HOURS = 3.0


@dataclass(frozen=True)
class AirportWeatherStation:
    iata: str
    icao: str
    timezone: str


def _airport(iata: str, timezone: str, icao: str | None = None) -> AirportWeatherStation:
    return AirportWeatherStation(iata, icao or f"K{iata}", timezone)


# IANA zones are deliberate: ``zoneinfo`` applies the historical 2025 DST rules
# instead of treating BTS local clock times as a fixed UTC offset.
AIRPORTS = {
    item.iata: item
    for item in (
        _airport("DFW", "America/Chicago"),
        _airport("DEN", "America/Denver"),
        _airport("ATL", "America/New_York"),
        _airport("ORD", "America/Chicago"),
        _airport("CLT", "America/New_York"),
        _airport("PHX", "America/Phoenix"),
        _airport("LAX", "America/Los_Angeles"),
        _airport("LAS", "America/Los_Angeles"),
        _airport("MCO", "America/New_York"),
        _airport("SEA", "America/Los_Angeles"),
        _airport("DCA", "America/New_York"),
        _airport("LGA", "America/New_York"),
        _airport("SFO", "America/Los_Angeles"),
        _airport("BOS", "America/New_York"),
        _airport("MIA", "America/New_York"),
        _airport("EWR", "America/New_York"),
        _airport("SLC", "America/Denver"),
        _airport("IAH", "America/Chicago"),
        _airport("DTW", "America/Detroit"),
        _airport("MSP", "America/Chicago"),
        _airport("JFK", "America/New_York"),
        _airport("FLL", "America/New_York"),
        _airport("BNA", "America/Chicago"),
        _airport("SAN", "America/Los_Angeles"),
        _airport("BWI", "America/New_York"),
        _airport("PHL", "America/New_York"),
        _airport("TPA", "America/New_York"),
        _airport("AUS", "America/Chicago"),
        _airport("DAL", "America/Chicago"),
        _airport("MDW", "America/Chicago"),
        _airport("HNL", "Pacific/Honolulu", "PHNL"),
        _airport("STL", "America/Chicago"),
        _airport("PDX", "America/Los_Angeles"),
        _airport("MSY", "America/Chicago"),
        _airport("RDU", "America/New_York"),
        _airport("SMF", "America/Los_Angeles"),
        _airport("HOU", "America/Chicago"),
        _airport("IAD", "America/New_York"),
        _airport("SJC", "America/Los_Angeles"),
        _airport("RSW", "America/New_York"),
        _airport("IND", "America/Indiana/Indianapolis"),
        _airport("MCI", "America/Chicago"),
        _airport("SNA", "America/Los_Angeles"),
        _airport("CMH", "America/New_York"),
        _airport("SJU", "America/Puerto_Rico", "TJSJ"),
        _airport("SAT", "America/Chicago"),
        _airport("PIT", "America/New_York"),
        _airport("PBI", "America/New_York"),
        _airport("CLE", "America/New_York"),
        _airport("OAK", "America/Los_Angeles"),
    )
}


RAW_WEATHER_VARIABLES = {
    "temperature": (-90.0, 60.0),
    "dew_point_temperature": (-100.0, 60.0),
    "relative_humidity": (0.0, 100.0),
    "sea_level_pressure": (870.0, 1085.0),
    "wind_speed": (0.0, 120.0),
    "wind_gust": (0.0, 150.0),
    "precipitation": (0.0, 1000.0),
    "visibility": (0.0, 200.0),
    "ceiling_height": (0.0, 30_000.0),
}


def endpoint_weather_feature_names(prefix: str) -> list[str]:
    return [
        f"{prefix}_temperature_c",
        f"{prefix}_dew_point_c",
        f"{prefix}_relative_humidity_pct",
        f"{prefix}_sea_level_pressure_hpa",
        f"{prefix}_wind_speed_mps",
        f"{prefix}_wind_gust_mps",
        f"{prefix}_precipitation_mm",
        f"{prefix}_visibility_km",
        f"{prefix}_ceiling_m",
        f"{prefix}_adverse_weather",
        f"{prefix}_weather_max_age_hours",
        f"{prefix}_weather_missing_fraction",
    ]


WEATHER_FEATURE_NAMES = endpoint_weather_feature_names(
    "origin"
) + endpoint_weather_feature_names("destination")
