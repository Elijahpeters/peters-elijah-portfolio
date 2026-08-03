"""Download and verify the official 2025 BTS flight archives.

The BTS endpoint is bandwidth-limited per connection, so each archive is
downloaded in four byte ranges. Three archives are processed concurrently.
"""

from __future__ import annotations

import argparse
import shutil
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


BASE_URL = "https://transtats.bts.gov/PREZIP"
FILENAME = (
    "On_Time_Reporting_Carrier_On_Time_Performance_1987_present_2025_{month}.zip"
)
EXPECTED_SIZES = {
    1: 27_108_664,
    2: 25_302_583,
    3: 30_544_825,
    4: 29_369_186,
    5: 30_830_593,
    6: 31_131_411,
    7: 32_208_704,
    8: 30_864_245,
    9: 28_151_630,
    10: 30_723_803,
    11: 28_847_755,
    12: 30_337_431,
}
USER_AGENT = "SkyETA-portfolio-model/1.0"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("skyeta-ml/data/raw"))
    parser.add_argument("--parts", type=int, default=4)
    parser.add_argument("--file-workers", type=int, default=3)
    return parser.parse_args()


def valid_archive(path: Path, expected_size: int) -> bool:
    if not path.exists() or path.stat().st_size != expected_size:
        return False
    try:
        with zipfile.ZipFile(path) as archive:
            return archive.testzip() is None
    except zipfile.BadZipFile:
        return False


def download_range(
    url: str, target: Path, start: int, end: int, total_size: int
) -> None:
    expected = end - start + 1
    if target.exists() and target.stat().st_size == expected:
        return
    headers = {
        "Range": f"bytes={start}-{end}",
        "User-Agent": USER_AGENT,
    }
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=180) as response, target.open(
                "wb"
            ) as output:
                if response.status != 206:
                    raise RuntimeError(
                        f"Expected HTTP 206 for {start}-{end}, received {response.status}"
                    )
                expected_content_range = f"bytes {start}-{end}/{total_size}"
                if response.headers.get("Content-Range") != expected_content_range:
                    raise RuntimeError(
                        "Unexpected Content-Range: "
                        f"{response.headers.get('Content-Range')!r}; "
                        f"expected {expected_content_range!r}"
                    )
                shutil.copyfileobj(response, output, length=1024 * 1024)
            if target.stat().st_size != expected:
                raise RuntimeError(
                    f"Range {start}-{end} wrote {target.stat().st_size} bytes; "
                    f"expected {expected}"
                )
            return
        except Exception as error:  # noqa: BLE001 - bounded retry with final raise
            last_error = error
            target.unlink(missing_ok=True)
            time.sleep(2**attempt)
    raise RuntimeError(f"Failed range {start}-{end} from {url}") from last_error


def download_month(data_dir: Path, month: int, parts: int) -> Path:
    filename = FILENAME.format(month=month)
    target = data_dir / filename
    expected_size = EXPECTED_SIZES[month]
    if valid_archive(target, expected_size):
        print(f"month {month:02d}: already verified", flush=True)
        return target

    url = f"{BASE_URL}/{filename}"
    chunk = (expected_size + parts - 1) // parts
    ranges = []
    for index in range(parts):
        start = index * chunk
        end = min(expected_size - 1, (index + 1) * chunk - 1)
        if start <= end:
            ranges.append((index, start, end))

    with ThreadPoolExecutor(max_workers=parts) as executor:
        futures = [
            executor.submit(
                download_range,
                url,
                target.with_suffix(target.suffix + f".part{index}"),
                start,
                end,
                expected_size,
            )
            for index, start, end in ranges
        ]
        for future in as_completed(futures):
            future.result()

    temporary = target.with_suffix(target.suffix + ".assembling")
    with temporary.open("wb") as output:
        for index, _, _ in ranges:
            part = target.with_suffix(target.suffix + f".part{index}")
            with part.open("rb") as source:
                shutil.copyfileobj(source, output, length=1024 * 1024)
    if temporary.stat().st_size != expected_size:
        raise RuntimeError(f"Assembled archive has the wrong size: {temporary}")
    temporary.replace(target)
    for index, _, _ in ranges:
        target.with_suffix(target.suffix + f".part{index}").unlink(missing_ok=True)
    if not valid_archive(target, expected_size):
        raise RuntimeError(f"Archive verification failed: {target}")
    print(f"month {month:02d}: downloaded and verified", flush=True)
    return target


def main() -> None:
    args = parse_args()
    if args.parts < 1:
        raise ValueError("--parts must be at least 1")
    if args.file_workers < 1:
        raise ValueError("--file-workers must be at least 1")
    args.data_dir.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=args.file_workers) as executor:
        futures = {
            executor.submit(download_month, args.data_dir, month, args.parts): month
            for month in range(1, 13)
        }
        for future in as_completed(futures):
            future.result()
    print("All 2025 BTS archives are present and valid.", flush=True)


if __name__ == "__main__":
    main()
