import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { gunzipSync } from "node:zlib";

const AIRPORTS_SOURCE_PIN = Object.freeze({
  name: "mborsetti/airportsdata airports.csv",
  commit: "671fa36e373faa3068e15bb453dac96a41087e19",
  url: "https://raw.githubusercontent.com/mborsetti/airportsdata/671fa36e373faa3068e15bb453dac96a41087e19/airportsdata/airports.csv",
  bytes: 3_076_463,
  sha256: "fca6a89a336c154e86174ba933372de118d15e09a1cfa01559e0b9fd2b1e7fe0",
});
const AWC_STATIONS_SOURCE_URL =
  "https://www.connect.aviationweather.gov/data/cache/stations.cache.json.gz";
const AWC_STATIONS_PIN = Object.freeze({
  catalogueVersion: "2026-08-09",
  compressedBytes: 355_855,
  compressedSha256:
    "bac107a0b678647efd8591d594ed1eb1de817d185365d0f0b8fe1f38a59a1723",
  uncompressedBytes: 1_939_590,
  sourceRecords: 9_873,
});

const OUTPUT_PATH = new URL(
  "../app/lib/skyeta/global-airports.json",
  import.meta.url,
);
const WEATHER_OUTPUT_PATH = new URL(
  "../app/lib/skyeta/aviation-weather-airports.json",
  import.meta.url,
);

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;

  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (quoted) {
      if (character === '"' && text[index + 1] === '"') {
        field += '"';
        index += 1;
      } else if (character === '"') {
        quoted = false;
      } else {
        field += character;
      }
    } else if (character === '"') {
      quoted = true;
    } else if (character === ",") {
      row.push(field);
      field = "";
    } else if (character === "\n") {
      row.push(field.replace(/\r$/, ""));
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += character;
    }
  }

  if (field || row.length > 0) {
    row.push(field.replace(/\r$/, ""));
    rows.push(row);
  }

  return rows;
}

function compactText(value) {
  return String(value ?? "").trim().replace(/\s+/g, " ");
}

async function downloadBytes(url) {
  const response = await fetch(url, {
    redirect: "error",
    headers: {
      "User-Agent": "SkyETA airport catalogue builder",
    },
  });
  if (!response.ok) throw new Error(`Source returned ${response.status}: ${url}`);
  return Buffer.from(await response.arrayBuffer());
}

async function pinnedAirportsCsvBytes() {
  const bytes = process.env.AIRPORTS_CSV_PATH
    ? await readFile(process.env.AIRPORTS_CSV_PATH)
    : await downloadBytes(AIRPORTS_SOURCE_PIN.url);
  const sha256 = createHash("sha256").update(bytes).digest("hex");
  if (
    bytes.byteLength !== AIRPORTS_SOURCE_PIN.bytes ||
    sha256 !== AIRPORTS_SOURCE_PIN.sha256
  ) {
    throw new Error(
      "The airportsdata CSV does not match the reviewed commit, size and SHA-256 pin. Review and update the pin before regenerating mappings.",
    );
  }
  return bytes;
}

async function pinnedAwcStationBytes() {
  const bytes = process.env.AWC_STATIONS_PATH
    ? await readFile(process.env.AWC_STATIONS_PATH)
    : await downloadBytes(AWC_STATIONS_SOURCE_URL);
  const sha256 = createHash("sha256").update(bytes).digest("hex");
  if (
    bytes.byteLength !== AWC_STATIONS_PIN.compressedBytes ||
    sha256 !== AWC_STATIONS_PIN.compressedSha256
  ) {
    throw new Error(
      "The AWC station catalogue does not match the reviewed size and SHA-256 pin. Review and update the pin before regenerating mappings.",
    );
  }
  return bytes;
}

const rows = parseCsv((await pinnedAirportsCsvBytes()).toString("utf8"));
const headers = rows.shift();
if (!headers) throw new Error("Airport source has no header row.");

const column = Object.fromEntries(headers.map((name, index) => [name, index]));
for (const required of ["icao", "iata", "name", "city", "country", "tz"]) {
  if (!Number.isInteger(column[required])) {
    throw new Error(`Airport source is missing the ${required} column.`);
  }
}

const airports = new Map();
const airportIcaos = new Map();
for (const row of rows) {
  const code = compactText(row[column.iata]).toUpperCase();
  const icao = compactText(row[column.icao]).toUpperCase();
  const name = compactText(row[column.name]);
  const city = compactText(row[column.city]);
  const countryCode = compactText(row[column.country]).toUpperCase();
  const timeZone = compactText(row[column.tz]);

  if (!/^[A-Z]{3}$/.test(code) || !name) continue;
  if (countryCode && !/^[A-Z]{2}$/.test(countryCode)) continue;

  if (/^[A-Z0-9]{4}$/.test(icao)) {
    const candidates = airportIcaos.get(code) ?? new Set();
    candidates.add(icao);
    airportIcaos.set(code, candidates);
  }

  const candidate = [code, name, city, countryCode];
  const current = airports.get(code);
  if (!current || (!current.timeZone && timeZone)) {
    airports.set(code, { tuple: candidate, timeZone });
  }
}

const compact = [...airports.values()]
  .map(({ tuple }) => tuple)
  .sort(([left], [right]) => left.localeCompare(right));

if (compact.length < 5_000) {
  throw new Error(`Expected a global catalogue; found only ${compact.length} airports.`);
}

const compressedStations = await pinnedAwcStationBytes();
const stationJson = gunzipSync(compressedStations);
if (stationJson.byteLength !== AWC_STATIONS_PIN.uncompressedBytes) {
  throw new Error("The reviewed AWC station catalogue has an unexpected expanded size.");
}

let stationRows;
try {
  stationRows = JSON.parse(stationJson.toString("utf8"));
} catch {
  throw new Error("The reviewed AWC station catalogue is not valid UTF-8 JSON.");
}
if (
  !Array.isArray(stationRows) ||
  stationRows.length !== AWC_STATIONS_PIN.sourceRecords
) {
  throw new Error("The reviewed AWC station catalogue record count changed.");
}

const officialStations = new Map();
const ambiguousOfficialIata = new Set();
for (const row of stationRows) {
  if (!row || typeof row !== "object" || Array.isArray(row)) continue;
  const iata = compactText(row.iataId).toUpperCase();
  const icao = compactText(row.icaoId).toUpperCase();
  const siteTypes = Array.isArray(row.siteType) ? row.siteType : [];
  const supportsMetar = siteTypes.includes("METAR");
  const supportsTaf = siteTypes.includes("TAF");
  if (
    !/^[A-Z]{3}$/.test(iata) ||
    !/^[A-Z0-9]{4}$/.test(icao) ||
    (!supportsMetar && !supportsTaf)
  ) {
    continue;
  }
  const current = officialStations.get(iata);
  if (current && current.icao !== icao) {
    ambiguousOfficialIata.add(iata);
    officialStations.delete(iata);
    continue;
  }
  if (!ambiguousOfficialIata.has(iata)) {
    officialStations.set(iata, { icao, supportsMetar, supportsTaf });
  }
}

// Every exported pair must be unambiguous in airportsdata and independently
// confirmed by the pinned AWC station catalogue. Missing or conflicting pairs
// are omitted instead of being guessed.
const aviationWeatherAirports = [];
for (const [iata, official] of officialStations) {
  const candidates = airportIcaos.get(iata);
  if (
    candidates?.size !== 1 ||
    !candidates.has(official.icao) ||
    ambiguousOfficialIata.has(iata)
  ) {
    continue;
  }
  aviationWeatherAirports.push([
    iata,
    official.icao,
    official.supportsMetar,
    official.supportsTaf,
  ]);
}
aviationWeatherAirports.sort(([left], [right]) => left.localeCompare(right));

if (aviationWeatherAirports.length < 4_000) {
  throw new Error(
    `Expected a reviewed global AWC catalogue; found only ${aviationWeatherAirports.length} mappings.`,
  );
}

const weatherOutput = {
  schemaVersion: 1,
  provenance: {
    sourceName: "NOAA Aviation Weather Center station catalogue",
    sourceUrl: AWC_STATIONS_SOURCE_URL,
    catalogueVersion: AWC_STATIONS_PIN.catalogueVersion,
    compressedBytes: AWC_STATIONS_PIN.compressedBytes,
    compressedSha256: AWC_STATIONS_PIN.compressedSha256,
    uncompressedBytes: AWC_STATIONS_PIN.uncompressedBytes,
    sourceRecords: AWC_STATIONS_PIN.sourceRecords,
    airportIdentitySource: {
      name: AIRPORTS_SOURCE_PIN.name,
      url: AIRPORTS_SOURCE_PIN.url,
      commit: AIRPORTS_SOURCE_PIN.commit,
      bytes: AIRPORTS_SOURCE_PIN.bytes,
      sha256: AIRPORTS_SOURCE_PIN.sha256,
    },
    validatedMappings: aviationWeatherAirports.length,
    validation:
      "Exact unambiguous IATA/ICAO pair in airportsdata and the pinned AWC catalogue; METAR/TAF capability copied from AWC siteType.",
  },
  airports: aviationWeatherAirports,
};

await writeFile(OUTPUT_PATH, `${JSON.stringify(compact)}\n`, "utf8");
await writeFile(WEATHER_OUTPUT_PATH, `${JSON.stringify(weatherOutput)}\n`, "utf8");
console.log(`Wrote ${compact.length} searchable global airport records.`);
console.log(
  `Wrote ${aviationWeatherAirports.length} AWC-validated aviation-weather station mappings.`,
);
