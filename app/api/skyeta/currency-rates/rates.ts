import {
  BodyTooLargeError,
  readBoundedJson,
} from "../../../lib/http/bounded-json.ts";

const FRANKFURTER_URL =
  "https://api.frankfurter.dev/v2/rates?base=EUR&quotes=NGN,USD,GBP&providers=CBN";
const MAX_RESPONSE_BYTES = 32_000;
const DEFAULT_TIMEOUT_MS = 8_000;
const FRESH_TTL_MS = 12 * 60 * 60 * 1_000;
const STALE_TTL_MS = 48 * 60 * 60 * 1_000;

export const CONVERSION_CURRENCIES = ["USD", "GBP", "EUR"] as const;
export type ConversionCurrency = (typeof CONVERSION_CURRENCIES)[number];

type FetchLike = (
  input: string | URL | Request,
  init?: RequestInit,
) => Promise<Response>;

type RateSnapshot = {
  base: "NGN";
  rates: Record<ConversionCurrency, number>;
  asOf: string;
  fetchedAt: string;
  source: {
    name: "Central Bank of Nigeria via Frankfurter";
    url: "https://frankfurter.dev/providers/cbn/";
  };
};

type CacheEntry = {
  snapshot: RateSnapshot;
  fetchedAtMs: number;
};

type HandlerOptions = {
  fetchImpl?: FetchLike;
  now?: () => number;
  timeoutMs?: number;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function validDate(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    !Number.isNaN(Date.parse(`${value}T00:00:00.000Z`))
  );
}

function normalizeSnapshot(value: unknown, fetchedAtMs: number): RateSnapshot | null {
  if (!Array.isArray(value)) return null;

  const rows = new Map<string, { rate: number; date: string }>();
  for (const candidate of value) {
    if (
      !isRecord(candidate) ||
      candidate.base !== "EUR" ||
      typeof candidate.quote !== "string" ||
      !["NGN", "USD", "GBP"].includes(candidate.quote) ||
      typeof candidate.rate !== "number" ||
      !Number.isFinite(candidate.rate) ||
      candidate.rate <= 0 ||
      !validDate(candidate.date) ||
      rows.has(candidate.quote)
    ) {
      return null;
    }
    rows.set(candidate.quote, { rate: candidate.rate, date: candidate.date });
  }

  const ngn = rows.get("NGN");
  const usd = rows.get("USD");
  const gbp = rows.get("GBP");
  if (!ngn || !usd || !gbp) return null;
  if (ngn.date !== usd.date || usd.date !== gbp.date) return null;

  const rates = {
    USD: usd.rate / ngn.rate,
    GBP: gbp.rate / ngn.rate,
    EUR: 1 / ngn.rate,
  } satisfies Record<ConversionCurrency, number>;
  if (Object.values(rates).some((rate) => !Number.isFinite(rate) || rate <= 0)) {
    return null;
  }

  return {
    base: "NGN",
    rates,
    asOf: ngn.date,
    fetchedAt: new Date(fetchedAtMs).toISOString(),
    source: {
      name: "Central Bank of Nigeria via Frankfurter",
      url: "https://frankfurter.dev/providers/cbn/",
    },
  };
}

function json(body: unknown, status: number, cacheControl: string): Response {
  return Response.json(body, {
    status,
    headers: {
      "Cache-Control": cacheControl,
      "Content-Type": "application/json; charset=utf-8",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

async function fetchSnapshot(
  fetchImpl: FetchLike,
  fetchedAtMs: number,
  timeoutMs: number,
): Promise<RateSnapshot> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchImpl(FRANKFURTER_URL, {
      method: "GET",
      headers: { Accept: "application/json" },
      redirect: "manual",
      signal: controller.signal,
    });
    if (!response.ok) throw new Error("rate_provider_rejected");

    const snapshot = normalizeSnapshot(
      await readBoundedJson(response, MAX_RESPONSE_BYTES),
      fetchedAtMs,
    );
    if (!snapshot) throw new Error("invalid_rate_response");
    return snapshot;
  } catch (error) {
    if (error instanceof BodyTooLargeError) {
      throw new Error("invalid_rate_response");
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export function createCurrencyRatesHandler(options: HandlerOptions = {}) {
  const fetchImpl =
    options.fetchImpl ??
    ((input: string | URL | Request, init?: RequestInit) =>
      globalThis.fetch(input, init));
  const now = options.now ?? Date.now;
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  let cached: CacheEntry | null = null;
  let inFlight: Promise<RateSnapshot> | null = null;

  return async function GET(): Promise<Response> {
    const current = now();
    if (cached && current - cached.fetchedAtMs < FRESH_TTL_MS) {
      return json(
        { ok: true, ...cached.snapshot, stale: false },
        200,
        "public, max-age=3600, s-maxage=43200, stale-while-revalidate=86400",
      );
    }

    try {
      inFlight ??= fetchSnapshot(fetchImpl, current, timeoutMs);
      const snapshot = await inFlight;
      cached = { snapshot, fetchedAtMs: current };
      return json(
        { ok: true, ...snapshot, stale: false },
        200,
        "public, max-age=3600, s-maxage=43200, stale-while-revalidate=86400",
      );
    } catch {
      if (cached && current - cached.fetchedAtMs < STALE_TTL_MS) {
        return json(
          { ok: true, ...cached.snapshot, stale: true },
          200,
          "public, max-age=300, s-maxage=300",
        );
      }
      return json(
        {
          ok: false,
          error: {
            code: "rates_unavailable",
            message: "Currency equivalents are unavailable right now.",
          },
        },
        502,
        "public, max-age=60",
      );
    } finally {
      inFlight = null;
    }
  };
}
