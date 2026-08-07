import { readFile, writeFile } from "node:fs/promises";

const SOURCE_URL =
  "https://raw.githubusercontent.com/mborsetti/airportsdata/main/airportsdata/airports.csv";
const OUTPUT_PATH = new URL(
  "../app/lib/skyeta/global-airports.json",
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

let csvText;
if (process.env.AIRPORTS_CSV_PATH) {
  csvText = await readFile(process.env.AIRPORTS_CSV_PATH, "utf8");
} else {
  const response = await fetch(SOURCE_URL, { redirect: "error" });
  if (!response.ok) {
    throw new Error(`Airport source returned ${response.status}.`);
  }
  csvText = await response.text();
}

const rows = parseCsv(csvText);
const headers = rows.shift();
if (!headers) throw new Error("Airport source has no header row.");

const column = Object.fromEntries(headers.map((name, index) => [name, index]));
for (const required of ["iata", "name", "city", "country", "tz"]) {
  if (!Number.isInteger(column[required])) {
    throw new Error(`Airport source is missing the ${required} column.`);
  }
}

const airports = new Map();
for (const row of rows) {
  const code = compactText(row[column.iata]).toUpperCase();
  const name = compactText(row[column.name]);
  const city = compactText(row[column.city]);
  const countryCode = compactText(row[column.country]).toUpperCase();
  const timeZone = compactText(row[column.tz]);

  if (!/^[A-Z]{3}$/.test(code) || !name) continue;
  if (countryCode && !/^[A-Z]{2}$/.test(countryCode)) continue;

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

await writeFile(OUTPUT_PATH, `${JSON.stringify(compact)}\n`, "utf8");
console.log(`Wrote ${compact.length} searchable global airport records.`);
