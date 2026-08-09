import type { FlightSegment } from "../../types/flight-booking";

const IATA_CODE = /^[A-Z]{3}$/;
const OFFSET_TIMESTAMP = /(?:Z|[+-]\d{2}:?\d{2})$/i;

export type ScheduleOccurrence = {
  kind: "departure" | "arrival";
  at: string;
  segmentId: string;
};

export type ForecastCoverage = {
  total: number;
  comparable: number;
  covered: number;
  uncomparable: number;
  validityAvailable: boolean;
};

export function selectLiveContextAirports(
  segments: FlightSegment[],
  maximum = 4,
): { codes: string[]; limited: boolean; totalUnique: number } {
  const codes: string[] = [];
  const seen = new Set<string>();
  const add = (candidate: string | undefined) => {
    if (!candidate || !IATA_CODE.test(candidate) || seen.has(candidate)) return;
    seen.add(candidate);
    codes.push(candidate);
  };

  // Preserve the two endpoints a traveller is most likely to care about,
  // even when a long connecting itinerary exceeds the server's four-airport
  // request ceiling. Fill the remaining places in journey order.
  add(segments[0]?.origin.iataCode);
  add(segments.at(-1)?.destination.iataCode);
  for (const segment of segments) {
    add(segment.origin.iataCode);
    add(segment.destination.iataCode);
  }

  return {
    codes: codes.slice(0, Math.max(1, maximum)),
    limited: codes.length > maximum,
    totalUnique: codes.length,
  };
}

export function scheduledOccurrences(
  segments: FlightSegment[],
  iata: string,
): ScheduleOccurrence[] {
  const occurrences: ScheduleOccurrence[] = [];
  for (const segment of segments) {
    if (segment.origin.iataCode === iata) {
      occurrences.push({
        kind: "departure",
        at: segment.departingAt,
        segmentId: segment.id,
      });
    }
    if (segment.destination.iataCode === iata) {
      occurrences.push({
        kind: "arrival",
        at: segment.arrivingAt,
        segmentId: segment.id,
      });
    }
  }
  return occurrences;
}

export function assessForecastCoverage(
  validFrom: string | null,
  validTo: string | null,
  occurrences: ScheduleOccurrence[],
): ForecastCoverage {
  const start = validFrom ? Date.parse(validFrom) : Number.NaN;
  const end = validTo ? Date.parse(validTo) : Number.NaN;
  const validityAvailable =
    Number.isFinite(start) && Number.isFinite(end) && end >= start;
  let comparable = 0;
  let covered = 0;

  if (validityAvailable) {
    for (const occurrence of occurrences) {
      if (!OFFSET_TIMESTAMP.test(occurrence.at)) continue;
      const timestamp = Date.parse(occurrence.at);
      if (!Number.isFinite(timestamp)) continue;
      comparable += 1;
      if (timestamp >= start && timestamp <= end) covered += 1;
    }
  }

  return {
    total: occurrences.length,
    comparable,
    covered,
    uncomparable: occurrences.length - comparable,
    validityAvailable,
  };
}

export function forecastCoverageCopy(coverage: ForecastCoverage): string {
  if (coverage.total === 0) {
    return "No scheduled occurrence is available for comparison.";
  }
  if (!coverage.validityAvailable) {
    return "This forecast has no machine-readable validity window, so SkyETA cannot compare it with the itinerary.";
  }
  if (coverage.comparable === 0) {
    return `None of the ${coverage.total} scheduled occurrences includes a reliable timezone offset, so SkyETA will not guess the comparison.`;
  }

  const comparableNoun =
    coverage.comparable === 1 ? "scheduled occurrence" : "scheduled occurrences";
  let result: string;
  if (coverage.covered === coverage.comparable) {
    result =
      coverage.uncomparable === 0
        ? `It covers all ${coverage.comparable} ${comparableNoun}.`
        : `It covers all ${coverage.comparable} comparable ${comparableNoun}.`;
  } else if (coverage.covered === 0) {
    result = `It does not cover any of the ${coverage.comparable} comparable ${comparableNoun}.`;
  } else {
    result = `It covers ${coverage.covered} of ${coverage.comparable} comparable ${comparableNoun}.`;
  }

  if (coverage.uncomparable > 0) {
    const otherNoun =
      coverage.uncomparable === 1 ? "scheduled time" : "scheduled times";
    result += ` ${coverage.uncomparable} other ${otherNoun} could not be compared safely because the timezone offset is missing.`;
  }
  return result;
}

export function retryCountdownLabel(seconds: number): string {
  const bounded = Number.isFinite(seconds)
    ? Math.max(0, Math.min(3_600, Math.ceil(seconds)))
    : 0;
  if (bounded === 0) return "A fresh live-data check is available now.";
  const minutes = Math.floor(bounded / 60);
  const remainingSeconds = bounded % 60;
  const parts: string[] = [];
  if (minutes > 0) parts.push(`${minutes} minute${minutes === 1 ? "" : "s"}`);
  if (remainingSeconds > 0) {
    parts.push(
      `${remainingSeconds} second${remainingSeconds === 1 ? "" : "s"}`,
    );
  }
  return `A fresh live-data check will be available in ${parts.join(" ")}.`;
}

type FetchLike = (
  input: string | URL | Request,
  init?: RequestInit,
) => Promise<Response>;

type RequestCacheOptions<T> = {
  parse: (value: unknown) => T | null;
  fetchImpl?: FetchLike;
  now?: () => number;
  timeoutMs?: number;
  ttlMs?: number;
  maxEntries?: number;
};

type RequestEntry<T> = {
  id: symbol;
  expiresAt: number;
  promise: Promise<T>;
};

export function createLiveContextRequestCache<T>(
  options: RequestCacheOptions<T>,
) {
  const fetchImpl = options.fetchImpl ?? globalThis.fetch;
  const now = options.now ?? Date.now;
  const timeoutMs = options.timeoutMs ?? 8_000;
  const ttlMs = options.ttlMs ?? 60_000;
  const maxEntries = Math.max(1, options.maxEntries ?? 40);
  const entries = new Map<string, RequestEntry<T>>();

  function prune(current: number) {
    for (const [key, entry] of entries) {
      if (entry.expiresAt <= current) entries.delete(key);
    }
    while (entries.size >= maxEntries) {
      const oldest = entries.keys().next().value;
      if (oldest === undefined) break;
      entries.delete(oldest);
    }
  }

  function load(
    codes: string[],
    loadOptions: { force?: boolean } = {},
  ): Promise<T> {
    const key = codes.join(",");
    const current = now();
    if (loadOptions.force) entries.delete(key);
    const cached = entries.get(key);
    if (cached && cached.expiresAt > current) return cached.promise;
    if (cached) entries.delete(key);
    prune(current);

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    const id = Symbol(key);
    const promise = (async () => {
      try {
        const response = await fetchImpl(
          `/api/skyeta/live-context?airports=${encodeURIComponent(key)}`,
          {
            headers: { Accept: "application/json" },
            signal: controller.signal,
          },
        );
        const value: unknown = await response.json();
        const parsed = options.parse(value);
        if (!response.ok || !parsed) throw new Error("live_context_unavailable");
        return parsed;
      } finally {
        clearTimeout(timeout);
      }
    })().catch((error) => {
      const active = entries.get(key);
      if (active?.id === id) entries.delete(key);
      throw error;
    });
    entries.set(key, { id, expiresAt: current + ttlMs, promise });
    return promise;
  }

  return {
    load,
    invalidate: (codes: string[]) => entries.delete(codes.join(",")),
    size: () => entries.size,
    has: (codes: string[]) => entries.has(codes.join(",")),
    clear: () => entries.clear(),
  };
}
