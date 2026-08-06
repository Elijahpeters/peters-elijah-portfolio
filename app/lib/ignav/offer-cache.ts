import type { D1DatabaseLike } from "../booking/d1.ts";
import { d1Changes, initializeBookingStorage } from "../booking/d1.ts";
import type { IgnavTripExpectation } from "./normalize.ts";

const CACHE_ID = /^ign_[a-f0-9]{32}$/;
const MAX_PAYLOAD_BYTES = 96_000;

type PassengerCounts = {
  adults: number;
  children: number;
  infantsWithoutSeat: number;
};

type CachePayload = {
  itinerary: unknown;
  ignavId: string;
  passengers: PassengerCounts;
  expected: IgnavTripExpectation;
  identity: string;
};

type CacheRow = {
  cache_id: string;
  provider_environment: "live";
  provider_payload_json: string;
  created_at: number;
  expires_at: number;
};

export function isIgnavProviderId(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length >= 8 &&
    value.length <= 500 &&
    /^[\x21-\x7E]+$/.test(value)
  );
}

export type CachedIgnavOffer = CachePayload & {
  id: string;
  mode: "live";
  createdAt: number;
  expiresAt: number;
};

export class IgnavOfferTooLargeError extends Error {
  constructor() {
    super("The flight offer is too large to store safely.");
    this.name = "IgnavOfferTooLargeError";
  }
}

function createCacheId(): string {
  return `ign_${crypto.randomUUID().replaceAll("-", "")}`;
}

function validPassengers(value: unknown): value is PassengerCounts {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const current = value as Partial<PassengerCounts>;
  const adults = current.adults;
  const children = current.children;
  const infants = current.infantsWithoutSeat;
  return (
    typeof adults === "number" &&
    Number.isInteger(adults) &&
    adults >= 1 &&
    adults <= 9 &&
    typeof children === "number" &&
    Number.isInteger(children) &&
    children >= 0 &&
    children <= 8 &&
    typeof infants === "number" &&
    Number.isInteger(infants) &&
    infants >= 0 &&
    infants <= adults &&
    adults + children + infants <= 9
  );
}

function validExpectation(value: unknown): value is IgnavTripExpectation {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const current = value as Partial<IgnavTripExpectation>;
  return (
    typeof current.origin === "string" &&
    /^[A-Z]{3}$/.test(current.origin) &&
    typeof current.destination === "string" &&
    /^[A-Z]{3}$/.test(current.destination) &&
    current.origin !== current.destination &&
    typeof current.departureDate === "string" &&
    /^\d{4}-\d{2}-\d{2}$/.test(current.departureDate) &&
    (current.returnDate === null ||
      (typeof current.returnDate === "string" &&
        /^\d{4}-\d{2}-\d{2}$/.test(current.returnDate))) &&
    typeof current.cabinClass === "string" &&
    ["economy", "premium_economy", "business", "first"].includes(
      current.cabinClass,
    )
  );
}

function decodePayload(value: string): CachePayload {
  try {
    const parsed: unknown = JSON.parse(value);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      throw new Error("invalid");
    }
    const candidate = parsed as Partial<CachePayload>;
    if (
      !("itinerary" in candidate) ||
      !isIgnavProviderId(candidate.ignavId) ||
      !validPassengers(candidate.passengers) ||
      !validExpectation(candidate.expected) ||
      typeof candidate.identity !== "string" ||
      candidate.identity.length === 0 ||
      candidate.identity.length > 5_000
    ) {
      throw new Error("invalid");
    }
    return candidate as CachePayload;
  } catch {
    throw new Error("The stored flight offer is invalid.");
  }
}

export class IgnavOfferCache {
  private readonly db: D1DatabaseLike;

  constructor(db: D1DatabaseLike) {
    this.db = db;
  }

  private async ready(): Promise<void> {
    await initializeBookingStorage(this.db);
  }

  async save(options: {
    id?: string;
    itinerary: unknown;
    ignavId: string;
    passengers: PassengerCounts;
    expected: IgnavTripExpectation;
    identity: string;
    now: number;
    expiresAt: number;
  }): Promise<string> {
    await this.ready();
    const id = options.id ?? createCacheId();
    if (
      !CACHE_ID.test(id) ||
      !isIgnavProviderId(options.ignavId) ||
      !validPassengers(options.passengers) ||
      !validExpectation(options.expected) ||
      options.identity.length === 0 ||
      options.identity.length > 5_000 ||
      options.expiresAt <= options.now
    ) {
      throw new TypeError("The flight offer cache entry is invalid.");
    }
    const payload = JSON.stringify({
      itinerary: options.itinerary,
      ignavId: options.ignavId,
      passengers: options.passengers,
      expected: options.expected,
      identity: options.identity,
    });
    if (new TextEncoder().encode(payload).byteLength > MAX_PAYLOAD_BYTES) {
      throw new IgnavOfferTooLargeError();
    }
    const row = await this.db
      .prepare(
        `INSERT INTO provider_offer_cache (
          cache_id, provider, provider_environment, provider_payload_json,
          created_at, expires_at
        ) VALUES (?, 'ignav', 'live', ?, ?, ?)
        ON CONFLICT(cache_id) DO UPDATE SET
          provider_environment = excluded.provider_environment,
          provider_payload_json = excluded.provider_payload_json,
          created_at = provider_offer_cache.created_at,
          expires_at = excluded.expires_at
        RETURNING cache_id`,
      )
      .bind(id, payload, options.now, options.expiresAt)
      .first<{ cache_id: string }>();
    if (!row || row.cache_id !== id) {
      throw new Error("The flight offer could not be stored.");
    }
    return id;
  }

  async get(id: string, now: number): Promise<CachedIgnavOffer | null> {
    await this.ready();
    if (!CACHE_ID.test(id)) return null;
    const row = await this.db
      .prepare(
        `SELECT cache_id, provider_environment, provider_payload_json,
          created_at, expires_at
        FROM provider_offer_cache
        WHERE cache_id = ? AND provider = 'ignav' AND expires_at > ?`,
      )
      .bind(id, now)
      .first<CacheRow>();
    if (!row || row.provider_environment !== "live") return null;
    return {
      id: row.cache_id,
      mode: "live",
      ...decodePayload(row.provider_payload_json),
      createdAt: row.created_at,
      expiresAt: row.expires_at,
    };
  }

  async deleteExpired(now: number, limit = 500): Promise<number> {
    await this.ready();
    const boundedLimit = Math.max(1, Math.min(500, Math.trunc(limit)));
    const result = await this.db
      .prepare(
        `DELETE FROM provider_offer_cache
        WHERE cache_id IN (
          SELECT cache_id FROM provider_offer_cache
          WHERE expires_at <= ?
          ORDER BY expires_at ASC
          LIMIT ?
        )`,
      )
      .bind(now, boundedLimit)
      .run();
    return d1Changes(result);
  }
}

export function isIgnavCacheId(value: string): boolean {
  return CACHE_ID.test(value);
}
