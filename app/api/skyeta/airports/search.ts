import airportSource from "../../../lib/skyeta/global-airports.json" with {
  type: "json",
};

const MAX_QUERY_LENGTH = 64;
const MAX_RESULTS = 8;

type AirportTuple = readonly [
  code: string,
  name: string,
  city: string,
  countryCode: string,
];

export type AirportSearchResult = {
  code: string;
  name: string;
  city: string;
  countryCode: string;
  label: string;
};

type SearchableAirport = AirportSearchResult & {
  normalizedCode: string;
  normalizedName: string;
  normalizedCity: string;
  normalizedCountry: string;
};

function normalizedText(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLocaleLowerCase("en")
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .replace(/\s+/g, " ");
}

function isAirportTuple(value: unknown): value is AirportTuple {
  return (
    Array.isArray(value) &&
    value.length === 4 &&
    typeof value[0] === "string" &&
    /^[A-Z]{3}$/.test(value[0]) &&
    typeof value[1] === "string" &&
    value[1].length > 0 &&
    value[1].length <= 180 &&
    typeof value[2] === "string" &&
    value[2].length <= 100 &&
    typeof value[3] === "string" &&
    (value[3] === "" || /^[A-Z]{2}$/.test(value[3]))
  );
}

function resultLabel(
  code: string,
  name: string,
  city: string,
  countryCode: string,
): string {
  const location = [city, countryCode].filter(Boolean).join(", ");
  return `${code} — ${name}${location ? ` · ${location}` : ""}`;
}

const AIRPORTS: SearchableAirport[] = (airportSource as unknown[])
  .filter(isAirportTuple)
  .map(([code, name, city, countryCode]) => ({
    code,
    name,
    city,
    countryCode,
    label: resultLabel(code, name, city, countryCode),
    normalizedCode: code.toLocaleLowerCase("en"),
    normalizedName: normalizedText(name),
    normalizedCity: normalizedText(city),
    normalizedCountry: normalizedText(countryCode),
  }));

function matchScore(airport: SearchableAirport, query: string): number | null {
  const compactQuery = query.replace(/\s/g, "");
  const tokens = query.split(" ").filter(Boolean);
  const searchable = `${airport.normalizedCode} ${airport.normalizedCity} ${airport.normalizedName} ${airport.normalizedCountry}`;

  if (airport.normalizedCode === compactQuery) return 0;
  if (airport.normalizedCity === query) return 10;
  if (airport.normalizedName === query) return 12;
  if (airport.normalizedCode.startsWith(compactQuery)) return 18;
  if (airport.normalizedCity.startsWith(query)) return 20;
  if (airport.normalizedName.startsWith(query)) return 24;
  if (!tokens.every((token) => searchable.includes(token))) return null;

  const cityIndex = airport.normalizedCity.indexOf(query);
  const nameIndex = airport.normalizedName.indexOf(query);
  const firstIndex = Math.min(
    cityIndex < 0 ? Number.POSITIVE_INFINITY : cityIndex,
    nameIndex < 0 ? Number.POSITIVE_INFINITY : nameIndex,
  );
  return 40 + (Number.isFinite(firstIndex) ? firstIndex : 20);
}

export function searchAirports(
  rawQuery: string,
  limit = MAX_RESULTS,
): AirportSearchResult[] {
  const query = normalizedText(rawQuery.slice(0, MAX_QUERY_LENGTH));
  if (query.length < 2) return [];

  const safeLimit = Math.max(1, Math.min(MAX_RESULTS, Math.trunc(limit) || 1));
  return AIRPORTS.map((airport) => ({
    airport,
    score: matchScore(airport, query),
  }))
    .filter(
      (candidate): candidate is { airport: SearchableAirport; score: number } =>
        candidate.score !== null,
    )
    .sort(
      (left, right) =>
        left.score - right.score ||
        left.airport.name.localeCompare(right.airport.name) ||
        left.airport.code.localeCompare(right.airport.code),
    )
    .slice(0, safeLimit)
    .map(({ airport }) => ({
      code: airport.code,
      name: airport.name,
      city: airport.city,
      countryCode: airport.countryCode,
      label: airport.label,
    }));
}

function json(body: unknown, status = 200): Response {
  return Response.json(body, {
    status,
    headers: {
      "Cache-Control":
        status === 200
          ? "public, max-age=86400, s-maxage=604800, stale-while-revalidate=2592000"
          : "no-store",
      "Content-Type": "application/json; charset=utf-8",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

export function createAirportSearchHandler() {
  return async function GET(request: Request): Promise<Response> {
    const requestUrl = new URL(request.url);
    const queries = requestUrl.searchParams.getAll("q");
    if (queries.length > 1) {
      return json(
        {
          ok: false,
          error: {
            code: "invalid_airport_query",
            message: "Enter one city, airport name or airport code.",
          },
        },
        400,
      );
    }

    const query = queries[0]?.trim() ?? "";
    if (query.length > MAX_QUERY_LENGTH) {
      return json(
        {
          ok: false,
          error: {
            code: "invalid_airport_query",
            message: "Airport search is too long.",
          },
        },
        400,
      );
    }

    return json({
      ok: true,
      query,
      airports: searchAirports(query),
    });
  };
}
