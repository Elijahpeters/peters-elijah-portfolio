"""Cache official NOAA GHCNh station-year Parquet files for SkyETA.

No token, paid API, or secret is required.  Downloads are atomic and restartable;
existing valid Parquet files are not fetched again.  ``--metadata-only`` resolves
and records station choices without downloading the airport-year files.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from weather_config import (
    AIRPORTS,
    DEFAULT_WEATHER_YEAR,
    GHCNH_DOCUMENTATION_URL,
    GHCNH_STATION_LIST_URL,
    GHCNH_YEAR_PARQUET_URL,
)


USER_AGENT = "SkyETA-portfolio-research/1.0 (NOAA GHCNh cache)"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=DEFAULT_WEATHER_YEAR)
    parser.add_argument(
        "--weather-dir", type=Path, default=Path("skyeta-ml/data/weather")
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--airports",
        help="Optional comma-separated IATA subset (default: configured top 50)",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Resolve NOAA station IDs and write a manifest; do not fetch Parquet",
    )
    return parser.parse_args()


def download(url: str, destination: Path, retries: int = 3) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=90) as response, temporary.open(
                "wb"
            ) as target:
                shutil.copyfileobj(response, target, length=1024 * 1024)
            os.replace(temporary, destination)
            return
        except (OSError, urllib.error.URLError) as error:
            temporary.unlink(missing_ok=True)
            if attempt == retries:
                raise RuntimeError(f"Could not download {url}: {error}") from error
            time.sleep(2**attempt)


def valid_parquet(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 12:
        return False
    with path.open("rb") as source:
        first = source.read(4)
        source.seek(-4, os.SEEK_END)
        last = source.read(4)
    return first == b"PAR1" and last == b"PAR1"


def load_station_rows(station_list: Path) -> list[dict[str, str]]:
    with station_list.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def resolve_station(rows: list[dict[str, str]], icao: str) -> dict[str, str]:
    matches = [row for row in rows if row.get("ICAO", "").strip() == icao]
    if not matches:
        raise RuntimeError(f"NOAA GHCNh station list has no station for ICAO {icao}")
    matches.sort(
        key=lambda row: (
            not row.get("GHCN_ID", "").startswith("USW"),
            "AIRPORT" not in row.get("NAME", "") and " AP" not in row.get("NAME", ""),
            row.get("GHCN_ID", ""),
        )
    )
    return matches[0]


def selected_airports(argument: str | None) -> list[str]:
    if not argument:
        return list(AIRPORTS)
    requested = [item.strip().upper() for item in argument.split(",") if item.strip()]
    unknown = sorted(set(requested) - set(AIRPORTS))
    if unknown:
        raise ValueError(f"Unsupported airport(s): {', '.join(unknown)}")
    return requested


def main() -> None:
    args = parse_args()
    if args.year < 1900 or args.year > datetime.now().year:
        raise ValueError("--year must be between 1900 and the current year")
    if args.workers < 1 or args.workers > 8:
        raise ValueError("--workers must be between 1 and 8")

    args.weather_dir.mkdir(parents=True, exist_ok=True)
    station_list = args.weather_dir / "ghcnh-station-list.csv"
    if not station_list.exists() or station_list.stat().st_size < 100_000:
        print("Downloading the NOAA GHCNh station list...", flush=True)
        download(GHCNH_STATION_LIST_URL, station_list)
    rows = load_station_rows(station_list)

    entries: list[dict] = []
    for iata in selected_airports(args.airports):
        configured = AIRPORTS[iata]
        station = resolve_station(rows, configured.icao)
        station_id = station["GHCN_ID"].strip()
        url = GHCNH_YEAR_PARQUET_URL.format(year=args.year, station=station_id)
        destination = args.weather_dir / str(args.year) / f"{iata}_{station_id}.parquet"
        entries.append(
            {
                "iata": iata,
                "icao": configured.icao,
                "timezone": configured.timezone,
                "stationId": station_id,
                "stationName": station.get("NAME", "").strip(),
                "latitude": float(station["LATITUDE"]),
                "longitude": float(station["LONGITUDE"]),
                "url": url,
                "path": str(destination.as_posix()),
                "downloaded": valid_parquet(destination),
            }
        )

    if not args.metadata_only:
        pending = [entry for entry in entries if not entry["downloaded"]]
        print(
            f"Fetching {len(pending)} NOAA station-year Parquet file(s) "
            f"with {args.workers} workers...",
            flush=True,
        )

        def fetch(entry: dict) -> tuple[str, int]:
            destination = Path(entry["path"])
            download(entry["url"], destination)
            if not valid_parquet(destination):
                destination.unlink(missing_ok=True)
                raise RuntimeError(f"Downloaded file is not valid Parquet: {destination}")
            return entry["iata"], destination.stat().st_size

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(fetch, entry): entry for entry in pending}
            for future in as_completed(futures):
                iata, size = future.result()
                print(f"  {iata}: {size / 1_000_000:.2f} MB", flush=True)

        for entry in entries:
            entry["downloaded"] = valid_parquet(Path(entry["path"]))
            if entry["downloaded"]:
                entry["bytes"] = Path(entry["path"]).stat().st_size

    manifest = {
        "formatVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "year": args.year,
        "publisher": "NOAA National Centers for Environmental Information",
        "dataset": "Global Historical Climatology Network hourly (GHCNh), Version 1",
        "stationList": GHCNH_STATION_LIST_URL,
        "documentation": GHCNH_DOCUMENTATION_URL,
        "airports": entries,
    }
    manifest_path = args.weather_dir / f"manifest-{args.year}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    resolved = sum(entry["downloaded"] for entry in entries)
    print(
        f"Wrote {manifest_path}; {len(entries)} stations resolved, "
        f"{resolved} data file(s) cached.",
        flush=True,
    )


if __name__ == "__main__":
    main()
