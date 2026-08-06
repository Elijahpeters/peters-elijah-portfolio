import type { D1DatabaseLike } from "../booking/d1.ts";
import { initializeBookingStorage } from "../booking/d1.ts";

const QUOTA_KEY = /^[a-f0-9]{64}$/;
const MAX_LIMIT = 100;
const MAX_WINDOW_MS = 24 * 60 * 60 * 1_000;
const CLEANUP_INTERVAL_MS = 10 * 60 * 1_000;
let lastCleanupAt = 0;

export type RateLimitResult = {
  allowed: boolean;
  retryAfterSeconds: number;
};

type QuotaRow = {
  request_count: number;
  expires_at: number;
};

function toHex(bytes: Uint8Array): string {
  return [...bytes].map((value) => value.toString(16).padStart(2, "0")).join("");
}

export async function createQuotaKey(
  scope: string,
  identifier: string,
): Promise<string> {
  if (!scope || scope.length > 100 || !identifier || identifier.length > 300) {
    throw new TypeError("The rate-limit identifier is invalid.");
  }
  const bytes = new TextEncoder().encode(`${scope}\u0000${identifier}`);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return toHex(new Uint8Array(digest));
}

export function cloudflareClientAddress(request: Request): string | null {
  const value = request.headers.get("cf-connecting-ip")?.trim();
  return value && /^[0-9a-f:.]{3,64}$/i.test(value) ? value : null;
}

export class DurableRequestLimiter {
  private readonly db: D1DatabaseLike;

  constructor(db: D1DatabaseLike) {
    this.db = db;
  }

  async consume(options: {
    key: string;
    now: number;
    windowMs: number;
    limit: number;
  }): Promise<RateLimitResult> {
    if (
      !QUOTA_KEY.test(options.key) ||
      !Number.isSafeInteger(options.now) ||
      !Number.isSafeInteger(options.windowMs) ||
      options.windowMs < 1 ||
      options.windowMs > MAX_WINDOW_MS ||
      !Number.isSafeInteger(options.limit) ||
      options.limit < 1 ||
      options.limit > MAX_LIMIT
    ) {
      throw new TypeError("The rate-limit request is invalid.");
    }
    await initializeBookingStorage(this.db);
    const expiresAt = options.now + options.windowMs;
    const row = await this.db
      .prepare(
        `INSERT INTO provider_request_quotas (
          quota_key, window_started_at, request_count, expires_at
        ) VALUES (?, ?, 1, ?)
        ON CONFLICT(quota_key) DO UPDATE SET
          window_started_at = CASE
            WHEN provider_request_quotas.expires_at <= ?
              THEN excluded.window_started_at
            ELSE provider_request_quotas.window_started_at
          END,
          request_count = CASE
            WHEN provider_request_quotas.expires_at <= ? THEN 1
            ELSE provider_request_quotas.request_count + 1
          END,
          expires_at = CASE
            WHEN provider_request_quotas.expires_at <= ? THEN excluded.expires_at
            ELSE provider_request_quotas.expires_at
          END
        WHERE provider_request_quotas.expires_at <= ?
          OR provider_request_quotas.request_count < ?
        RETURNING request_count, expires_at`,
      )
      .bind(
        options.key,
        options.now,
        expiresAt,
        options.now,
        options.now,
        options.now,
        options.now,
        options.limit,
      )
      .first<QuotaRow>();

    if (options.now - lastCleanupAt >= CLEANUP_INTERVAL_MS) {
      lastCleanupAt = options.now;
      await this.deleteExpired(options.now, 500);
    }
    if (row) return { allowed: true, retryAfterSeconds: 0 };

    const existing = await this.db
      .prepare(
        `SELECT request_count, expires_at
        FROM provider_request_quotas
        WHERE quota_key = ?`,
      )
      .bind(options.key)
      .first<QuotaRow>();
    return {
      allowed: false,
      retryAfterSeconds: Math.max(
        1,
        Math.ceil(((existing?.expires_at ?? expiresAt) - options.now) / 1_000),
      ),
    };
  }

  async deleteExpired(now: number, limit: number): Promise<void> {
    const boundedLimit = Math.max(1, Math.min(500, Math.trunc(limit)));
    await this.db
      .prepare(
        `DELETE FROM provider_request_quotas
        WHERE quota_key IN (
          SELECT quota_key FROM provider_request_quotas
          WHERE expires_at <= ?
          ORDER BY expires_at ASC
          LIMIT ?
        )`,
      )
      .bind(now, boundedLimit)
      .run();
  }
}
