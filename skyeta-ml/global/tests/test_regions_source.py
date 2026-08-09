"""Synthetic checks for the saved UN M49 overview loader."""

from __future__ import annotations

import hashlib
import html
import importlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
features = importlib.import_module("global.features")
regions = importlib.import_module("global.sources.regions")


HEADERS = [
    "Global Code",
    "Global Name",
    "Region Code",
    "Region Name",
    "Sub-region Code",
    "Sub-region Name",
    "Intermediate Region Code",
    "Intermediate Region Name",
    "Country or Area",
    "M49 Code",
    "ISO-alpha2 Code",
    "ISO-alpha3 Code",
    "Least Developed Countries (LDC)",
    "Land Locked Developing Countries (LLDC)",
    "Small Island Developing States (SIDS)",
]
RETRIEVED = datetime(2026, 8, 9, 2, 30, tzinfo=timezone(timedelta(hours=1)))


def row(**overrides: str) -> dict[str, str]:
    values = {
        "Global Code": "001",
        "Global Name": "World",
        "Region Code": "002",
        "Region Name": "Africa",
        "Sub-region Code": "015",
        "Sub-region Name": "Northern Africa",
        "Intermediate Region Code": "",
        "Intermediate Region Name": "",
        "Country or Area": "Algeria",
        "M49 Code": "012",
        "ISO-alpha2 Code": "DZ",
        "ISO-alpha3 Code": "DZA",
        "Least Developed Countries (LDC)": "",
        "Land Locked Developing Countries (LLDC)": "",
        "Small Island Developing States (SIDS)": "",
    }
    values.update(overrides)
    return values


def table(
    *rows: dict[str, str],
    headers: list[str] | None = None,
    table_id: str = "downloadTableEN",
) -> str:
    active_headers = headers or HEADERS
    header_cells = "".join(f"<td>{html.escape(name)}</td>" for name in active_headers)
    body_rows = []
    for values in rows:
        cells = "".join(
            f"<td>{html.escape(values.get(name, ''))}</td>" for name in active_headers
        )
        body_rows.append(f"<tr>{cells}</tr>")
    return (
        f'<table id="{html.escape(table_id)}"><thead><tr>{header_cells}</tr></thead>'
        f"<tbody>{''.join(body_rows)}</tbody></table>"
    )


def page(*rows: dict[str, str], headers: list[str] | None = None) -> bytes:
    # A preceding layout/decoy table and a later translated table ensure the
    # parser selects only the first official English table by identity.
    markup = (
        "<!doctype html><html><body>"
        "<table><tr><td>not the M49 data</td></tr></table>"
        + table(*rows, headers=headers)
        + table(
            row(**{"Country or Area": "Wrong later table"}),
            table_id="downloadTableZH",
        )
        + "</body></html>"
    )
    return markup.encode("utf-8-sig")


def complete_rows() -> tuple[dict[str, str], ...]:
    return (
        row(),
        row(
            **{
                "Country or Area": "Egypt",
                "M49 Code": "818",
                "ISO-alpha2 Code": "EG",
                "ISO-alpha3 Code": "EGY",
            }
        ),
        row(
            **{
                "Region Code": "019",
                "Region Name": "Americas",
                "Sub-region Code": "021",
                "Sub-region Name": "Northern America",
                "Country or Area": "United States of America",
                "M49 Code": "840",
                "ISO-alpha2 Code": "US",
                "ISO-alpha3 Code": "USA",
            }
        ),
        row(
            **{
                "Region Code": "019",
                "Region Name": "Americas",
                "Sub-region Code": "419",
                "Sub-region Name": "Latin America and the Caribbean",
                "Intermediate Region Code": "005",
                "Intermediate Region Name": "South America",
                "Country or Area": "Brazil",
                "M49 Code": "076",
                "ISO-alpha2 Code": "BR",
                "ISO-alpha3 Code": "BRA",
            }
        ),
        row(
            **{
                "Region Code": "142",
                "Region Name": "Asia",
                "Sub-region Code": "030",
                "Sub-region Name": "Eastern Asia",
                "Country or Area": "Japan",
                "M49 Code": "392",
                "ISO-alpha2 Code": "JP",
                "ISO-alpha3 Code": "JPN",
            }
        ),
        row(
            **{
                "Region Code": "142",
                "Region Name": "Asia",
                "Sub-region Code": "034",
                "Sub-region Name": "Southern Asia",
                "Country or Area": "Iran (Islamic Republic of)",
                "M49 Code": "364",
                "ISO-alpha2 Code": "IR",
                "ISO-alpha3 Code": "IRN",
            }
        ),
        row(
            **{
                "Region Code": "142",
                "Region Name": "Asia",
                "Sub-region Code": "145",
                "Sub-region Name": "Western Asia",
                "Country or Area": "United Arab Emirates",
                "M49 Code": "784",
                "ISO-alpha2 Code": "AE",
                "ISO-alpha3 Code": "ARE",
            }
        ),
        row(
            **{
                "Region Code": "150",
                "Region Name": "Europe",
                "Sub-region Code": "154",
                "Sub-region Name": "Northern Europe",
                "Country or Area": "United Kingdom of Great Britain and Northern Ireland",
                "M49 Code": "826",
                "ISO-alpha2 Code": "GB",
                "ISO-alpha3 Code": "GBR",
            }
        ),
        row(
            **{
                "Region Code": "009",
                "Region Name": "Oceania",
                "Sub-region Code": "053",
                "Sub-region Name": "Australia and New Zealand",
                "Country or Area": "Australia",
                "M49 Code": "036",
                "ISO-alpha2 Code": "AU",
                "ISO-alpha3 Code": "AUS",
            }
        ),
        row(
            **{
                "Region Code": "",
                "Region Name": "",
                "Sub-region Code": "",
                "Sub-region Name": "",
                "Country or Area": "Antarctica",
                "M49 Code": "010",
                "ISO-alpha2 Code": "AQ",
                "ISO-alpha3 Code": "ATA",
            }
        ),
        row(
            **{
                "Sub-region Code": "018",
                "Sub-region Name": "Southern Africa",
                "Country or Area": "Namibia",
                "M49 Code": "516",
                "ISO-alpha2 Code": "NA",
                "ISO-alpha3 Code": "NAM",
            }
        ),
    )


def load(raw: bytes):
    temporary = tempfile.TemporaryDirectory()
    path = Path(temporary.name) / "m49-overview.html"
    path.write_bytes(raw)
    catalog = regions.load_m49_region_catalog(
        path,
        retrieved_at_utc=RETRIEVED,
    )
    return temporary, path, catalog


class M49RegionLoadTests(unittest.TestCase):
    def test_builds_mapping_preserves_un_geography_and_provenance(self) -> None:
        raw = page(*complete_rows())
        temporary, path, catalog = load(raw)
        self.addCleanup(temporary.cleanup)

        expected = {
            "DZ": "Africa",
            "EG": "Middle East",
            "US": "North America",
            "BR": "South America",
            "JP": "Asia",
            "IR": "Middle East",
            "AE": "Middle East",
            "GB": "Europe",
            "AU": "Oceania",
            "AQ": "Other",
            "NA": "Africa",
            "TW": "Asia",
            "XK": "Europe",
        }
        self.assertEqual(dict(catalog), expected)
        self.assertEqual(catalog.country_to_region, expected)
        self.assertEqual(catalog.region_for_iso2(" br "), "South America")
        self.assertEqual(catalog["NA"], "Africa")
        self.assertNotIn("TW", catalog.by_iso2)
        self.assertNotIn("XK", catalog.by_iso2)

        brazil = catalog.by_iso2["BR"]
        self.assertEqual(brazil.un_region_name, "Americas")
        self.assertEqual(brazil.un_subregion_name, "Latin America and the Caribbean")
        self.assertEqual(brazil.un_intermediate_region_name, "South America")
        self.assertEqual(brazil.skyeta_region_token, "south_america")
        egypt = catalog.by_iso2["EG"]
        self.assertEqual(egypt.un_region_name, "Africa")
        self.assertEqual(egypt.un_subregion_name, "Northern Africa")
        self.assertEqual(egypt.skyeta_region, "Middle East")

        provenance = catalog.provenance
        self.assertEqual(provenance.source_url, regions.UN_M49_OVERVIEW_URL)
        self.assertEqual(provenance.file_path, str(path.resolve()))
        self.assertEqual(
            provenance.retrieved_at_utc,
            datetime(2026, 8, 9, 1, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(provenance.raw_file_sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual(provenance.raw_bytes, len(raw))
        self.assertEqual(provenance.raw_row_count, len(complete_rows()))
        self.assertEqual(provenance.accepted_row_count, len(complete_rows()))
        self.assertEqual(provenance.rejected_row_count, 0)
        self.assertEqual(provenance.compatibility_override_count, 2)
        self.assertEqual(provenance.mapping_count, len(expected))
        self.assertTrue(catalog.audit.completed)
        self.assertEqual(catalog.audit.raw_row_count, len(complete_rows()))
        self.assertEqual(catalog.audit.accepted_row_count, len(complete_rows()))
        self.assertEqual(catalog.audit.rejected_row_count, 0)
        self.assertEqual(catalog.audit.mapping_count, len(expected))
        exported = catalog.audit.to_dict()
        self.assertEqual(exported["provenance"]["retrieved_at_utc"], "2026-08-09T01:30:00Z")
        self.assertEqual(exported["compatibility_iso2_overrides"], {"TW": "Asia", "XK": "Europe"})

    def test_region_labels_match_feature_tokens_and_policy_is_explicit(self) -> None:
        normalized = {
            "_".join(label.casefold().replace("-", " ").split())
            for label in regions.SKYETA_REGION_LABELS
        }
        self.assertEqual(normalized, set(features.REGION_TOKENS))
        self.assertEqual(
            regions.MIDDLE_EAST_ISO2_OVERRIDES,
            {
                "AE", "AM", "AZ", "BH", "CY", "EG", "GE", "IL", "IQ", "IR",
                "JO", "KW", "LB", "OM", "PS", "QA", "SA", "SY", "TR", "YE",
            },
        )
        self.assertIn("UN Western Asia plus Iran and Egypt", regions.MIDDLE_EAST_OVERRIDE_RATIONALE)

    def test_catalog_is_immutable_and_unknown_countries_fail_closed(self) -> None:
        temporary, _, catalog = load(page(row()))
        self.addCleanup(temporary.cleanup)

        with self.assertRaises(TypeError):
            catalog.regions_by_iso2["US"] = "North America"  # type: ignore[index]
        with self.assertRaises(TypeError):
            catalog.by_iso2["US"] = catalog.records[0]  # type: ignore[index]
        with self.assertRaisesRegex(regions.UnknownCountryError, "country ZZ"):
            catalog.region_for_iso2("ZZ")
        with self.assertRaisesRegex(ValueError, "exactly two ASCII letters"):
            catalog.region_for_iso2("Z")

    def test_duplicate_and_conflicting_country_identities_are_fatal(self) -> None:
        duplicate = row()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.html"
            path.write_bytes(page(duplicate, duplicate))
            with self.assertRaisesRegex(
                regions.M49RegionDuplicateError,
                "exactly duplicates row 2 for ISO-alpha2 DZ",
            ):
                regions.load_m49_region_catalog(path, retrieved_at_utc=RETRIEVED)

        conflict = row(**{"Country or Area": "Not Algeria"})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "conflict.html"
            path.write_bytes(page(row(), conflict))
            with self.assertRaisesRegex(
                regions.M49RegionConflictError,
                "conflicts with row 2 for ISO-alpha2 DZ",
            ):
                regions.load_m49_region_catalog(path, retrieved_at_utc=RETRIEVED)

        same_m49 = row(
            **{
                "Country or Area": "Other identity",
                "ISO-alpha2 Code": "ZZ",
                "ISO-alpha3 Code": "ZZZ",
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "m49-conflict.html"
            path.write_bytes(page(row(), same_m49))
            with self.assertRaisesRegex(
                regions.M49RegionConflictError,
                "for M49 012",
            ):
                regions.load_m49_region_catalog(path, retrieved_at_utc=RETRIEVED)

    def test_unknown_or_drifted_geographies_are_fatal(self) -> None:
        cases = {
            "unknown region": row(
                **{
                    "Region Code": "999",
                    "Region Name": "Atlantis",
                    "Country or Area": "Unknown",
                    "M49 Code": "999",
                    "ISO-alpha2 Code": "ZZ",
                    "ISO-alpha3 Code": "ZZZ",
                }
            ),
            "blank non-Antarctica": row(
                **{
                    "Region Code": "",
                    "Region Name": "",
                    "Sub-region Code": "",
                    "Sub-region Name": "",
                }
            ),
            "new Western Asia member": row(
                **{
                    "Region Code": "142",
                    "Region Name": "Asia",
                    "Sub-region Code": "145",
                    "Sub-region Name": "Western Asia",
                    "Country or Area": "Unknown",
                    "M49 Code": "999",
                    "ISO-alpha2 Code": "ZZ",
                    "ISO-alpha3 Code": "ZZZ",
                }
            ),
            "override classification drift": row(
                **{
                    "Region Code": "142",
                    "Region Name": "Asia",
                    "Sub-region Code": "034",
                    "Sub-region Name": "Southern Asia",
                    "Country or Area": "United Arab Emirates",
                    "M49 Code": "784",
                    "ISO-alpha2 Code": "AE",
                    "ISO-alpha3 Code": "ARE",
                }
            ),
        }
        for label, source_row in cases.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "bad-region.html"
                path.write_bytes(page(source_row))
                with self.assertRaises(regions.M49RegionError):
                    regions.load_m49_region_catalog(path, retrieved_at_utc=RETRIEVED)

    def test_bad_table_structure_encoding_and_provenance_inputs_are_fatal(self) -> None:
        missing_headers = [name for name in HEADERS if name != "ISO-alpha2 Code"]
        malformed_inputs = {
            "missing English table": table(row(), table_id="downloadTableZH").encode(),
            "missing header": page(row(), headers=missing_headers),
            "empty table": page(),
            "invalid utf8": b'<table id="downloadTableEN">\xff</table>',
        }
        for label, raw in malformed_inputs.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "bad.html"
                path.write_bytes(raw)
                with self.assertRaises(regions.M49RegionError):
                    regions.load_m49_region_catalog(path, retrieved_at_utc=RETRIEVED)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "m49.html"
            path.write_bytes(page(row()))
            with self.assertRaisesRegex(ValueError, "aware datetime"):
                regions.load_m49_region_catalog(
                    path, retrieved_at_utc=datetime(2026, 8, 9)
                )
            with self.assertRaisesRegex(ValueError, "absolute HTTPS"):
                regions.load_m49_region_catalog(
                    path,
                    retrieved_at_utc=RETRIEVED,
                    source_url="file:///m49.html",
                )


if __name__ == "__main__":
    unittest.main()
