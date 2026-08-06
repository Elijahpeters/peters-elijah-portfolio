import { readFile, writeFile } from "node:fs/promises";

const SOURCE_URL =
  "https://raw.githubusercontent.com/mborsetti/airportsdata/main/airportsdata/airports.csv";
const MODEL_PATH = new URL("../public/assets/skyeta-model.json", import.meta.url);
const OUTPUT_PATH = new URL("../app/lib/skyeta/us-airports.json", import.meta.url);

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (quoted) {
      if (char === '"' && text[index + 1] === '"') {
        field += '"';
        index += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        field += char;
      }
    } else if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      row.push(field);
      field = "";
    } else if (char === "\n") {
      row.push(field.replace(/\r$/, ""));
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += char;
    }
  }
  if (field || row.length) {
    row.push(field.replace(/\r$/, ""));
    rows.push(row);
  }
  return rows;
}

const model = JSON.parse(await readFile(MODEL_PATH, "utf8"));
const coveredCodes = new Set([
  ...Object.keys(model.rates.origin),
  ...Object.keys(model.rates.destination),
]);
let csvText;
if (process.env.AIRPORTS_CSV_PATH) {
  csvText = await readFile(process.env.AIRPORTS_CSV_PATH, "utf8");
} else {
  const response = await fetch(SOURCE_URL);
  if (!response.ok) throw new Error(`Airport source returned ${response.status}.`);
  csvText = await response.text();
}
const rows = parseCsv(csvText);
const headers = rows.shift();
const column = Object.fromEntries(headers.map((name, index) => [name, index]));
const airportsDataFormat = Number.isInteger(column.iata);
const airports = {};

for (const row of rows) {
  const code = row[airportsDataFormat ? column.iata : column.iata_code];
  if (!coveredCodes.has(code)) continue;
  const latitude = Number(
    row[airportsDataFormat ? column.lat : column.latitude_deg],
  );
  const longitude = Number(
    row[airportsDataFormat ? column.lon : column.longitude_deg],
  );
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) continue;
  airports[code] = {
    name: row[column.name] || null,
    cityName: row[airportsDataFormat ? column.city : column.municipality] || null,
    countryCode:
      row[airportsDataFormat ? column.country : column.iso_country] || null,
    regionCode:
      row[airportsDataFormat ? column.subd : column.iso_region] || null,
    timeZone: airportsDataFormat ? row[column.tz] || null : null,
    latitude,
    longitude,
  };
}

const missing = [...coveredCodes].filter((code) => !airports[code]).sort();
if (missing.length > 0) {
  throw new Error(`Airport coordinates missing for: ${missing.join(", ")}`);
}

const sorted = Object.fromEntries(
  Object.entries(airports).sort(([left], [right]) => left.localeCompare(right)),
);
await writeFile(OUTPUT_PATH, `${JSON.stringify(sorted)}\n`, "utf8");
console.log(`Wrote ${Object.keys(sorted).length} SkyETA airport records.`);
