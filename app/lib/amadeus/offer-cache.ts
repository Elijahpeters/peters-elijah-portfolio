import type { D1DatabaseLike } from "../booking/d1.ts";
import { d1Changes, initializeBookingStorage } from "../booking/d1.ts";
import type { AmadeusMode } from "./client.ts";

const CACHE_ID = /^ama_[a-f0-9]{32}$/;
const MAX_PAYLOAD_BYTES = 96_000;

export class AmadeusOfferTooLargeError extends Error {
  constructor() {
    super("The flight offer is too large to store safely.");
    this.name = "AmadeusOfferTooLargeError";
  }
}

type CacheRow = {
  cache_id: string;
  provider_environment: AmadeusMode;
  provider_payload_json: string;
  created_at: number;
  expires_at: number;
};

export type CachedAmadeusOffer = {
  id: string;
  mode: AmadeusMode;
  offer: unknown;
  dictionaries?: unknown;
  createdAt: number;
  expiresAt: number;
};

function createCacheId(): string {
  return `ama_${crypto.randomUUID().replaceAll("-", "")}`;
}

function decodePayload(value: string): { offer: unknown; dictionaries?: unknown } {
  try {
    const parsed: unknown = JSON.parse(value);
    if (typeof parsed !== "object" || parsed === null || !("offer" in parsed)) {
      throw new Error("invalid");
    }
    return parsed as { offer: unknown; dictionaries?: unknown };
  } catch {
    throw new Error("The stored flight offer is invalid.");
  }
}

export class AmadeusOfferCache {
  private readonly db: D1DatabaseLike;

  constructor(db: D1DatabaseLike) {
    this.db = db;
  }

  private async ready(): Promise<void> {
    await initializeBookingStorage(this.db);
  }

  async save(options: {
    id?: string;
    mode: AmadeusMode;
    offer: unknown;
    dictionaries?: unknown;
    now: number;
    expiresAt: number;
  }): Promise<string> {
    await this.ready();
    const id = options.id ?? createCacheId();
    if (!CACHE_ID.test(id) || options.expiresAt <= options.now) {
      throw new TypeError("The flight offer cache entry is invalid.");
    }
    const payload = JSON.stringify({
      offer: options.offer,
      dictionaries: options.dictionaries,
    });
    if (new TextEncoder().encode(payload).byteLength > MAX_PAYLOAD_BYTES) {
      throw new AmadeusOfferTooLargeError();
    }
    const row = await this.db
      .prepare(
        `INSERT INTO provider_offer_cache (
          cache_id, provider, provider_environment, provider_payload_json,
          created_at, expires_at
        ) VALUES (?, 'amadeus', ?, ?, ?, ?)
        ON CONFLICT(cache_id) DO UPDATE SET
          provider_environment = excluded.provider_environment,
          provider_payload_json = excluded.provider_payload_json,
          created_at = provider_offer_cache.created_at,
          expires_at = excluded.expires_at
        RETURNING cache_id`,
      )
      .bind(id, options.mode, payload, options.now, options.expiresAt)
      .first<{ cache_id: string }>();
    if (!row || row.cache_id !== id) {
      throw new Error("The flight offer could not be stored.");
    }
    return id;
  }

  async get(id: string, now: number): Promise<CachedAmadeusOffer | null> {
    await this.ready();
    if (!CACHE_ID.test(id)) return null;
    const row = await this.db
      .prepare(
        `SELECT cache_id, provider_environment, provider_payload_json,
          created_at, expires_at
        FROM provider_offer_cache
        WHERE cache_id = ? AND provider = 'amadeus' AND expires_at > ?`,
      )
      .bind(id, now)
      .first<CacheRow>();
    if (!row) return null;
    const payload = decodePayload(row.provider_payload_json);
    return {
      id: row.cache_id,
      mode: row.provider_environment,
      offer: payload.offer,
      dictionaries: payload.dictionaries,
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

export function isAmadeusCacheId(value: string): boolean {
  return CACHE_ID.test(value);
}
