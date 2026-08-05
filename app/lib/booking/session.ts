import { createOpaqueToken, sha256Base64Url } from "./idempotency.ts";
import type { BookingSessionRecord } from "./types";

export const BOOKING_SESSION_COOKIE = "skyeta_booking_session";
export const DEFAULT_BOOKING_SESSION_TTL_MS = 24 * 60 * 60 * 1_000;

const SESSION_TOKEN_PATTERN = /^[A-Za-z0-9_-]{43}$/;

export type NewBookingSession = {
  token: string;
  record: BookingSessionRecord;
};

export async function createBookingSession(
  now = Date.now(),
  ttlMs = DEFAULT_BOOKING_SESSION_TTL_MS,
): Promise<NewBookingSession> {
  if (!Number.isSafeInteger(now) || now < 0) {
    throw new RangeError("Session time must be a non-negative integer.");
  }
  if (!Number.isSafeInteger(ttlMs) || ttlMs < 60_000) {
    throw new RangeError("Booking sessions must last at least one minute.");
  }
  if (!Number.isSafeInteger(now + ttlMs)) {
    throw new RangeError("The booking session expiry is outside the safe range.");
  }

  const token = createOpaqueToken(32);
  const sessionHash = await hashBookingSessionToken(token);
  return {
    token,
    record: {
      sessionHash,
      status: "active",
      createdAt: now,
      lastSeenAt: now,
      expiresAt: now + ttlMs,
    },
  };
}

export function isValidBookingSessionToken(value: string): boolean {
  return SESSION_TOKEN_PATTERN.test(value);
}

export async function hashBookingSessionToken(token: string): Promise<string> {
  if (!isValidBookingSessionToken(token)) {
    throw new TypeError("The booking session token has an invalid format.");
  }
  return sha256Base64Url(token);
}

export function readBookingSessionCookie(
  cookieHeader: string | null,
): string | null {
  if (!cookieHeader) return null;

  for (const part of cookieHeader.split(";")) {
    const separator = part.indexOf("=");
    if (separator < 0) continue;
    const name = part.slice(0, separator).trim();
    if (name !== BOOKING_SESSION_COOKIE) continue;
    const token = part.slice(separator + 1).trim();
    return isValidBookingSessionToken(token) ? token : null;
  }
  return null;
}

export function serializeBookingSessionCookie(
  token: string,
  expiresAt: number,
  options: { secure?: boolean; now?: number } = {},
): string {
  if (!isValidBookingSessionToken(token)) {
    throw new TypeError("The booking session token has an invalid format.");
  }
  const now = options.now ?? Date.now();
  if (
    !Number.isSafeInteger(now) ||
    !Number.isSafeInteger(expiresAt) ||
    expiresAt < 0
  ) {
    throw new RangeError("The booking session expiry is invalid.");
  }
  const maxAge = Math.max(0, Math.floor((expiresAt - now) / 1_000));
  const attributes = [
    `${BOOKING_SESSION_COOKIE}=${token}`,
    "Path=/",
    "HttpOnly",
    "SameSite=Lax",
    `Max-Age=${maxAge}`,
    `Expires=${new Date(expiresAt).toUTCString()}`,
  ];
  if (options.secure ?? true) attributes.push("Secure");
  return attributes.join("; ");
}

export function clearBookingSessionCookie(options: {
  secure?: boolean;
} = {}): string {
  const attributes = [
    `${BOOKING_SESSION_COOKIE}=`,
    "Path=/",
    "HttpOnly",
    "SameSite=Lax",
    "Max-Age=0",
    "Expires=Thu, 01 Jan 1970 00:00:00 GMT",
  ];
  if (options.secure ?? true) attributes.push("Secure");
  return attributes.join("; ");
}
