const IDEMPOTENCY_KEY_PATTERN = /^[A-Za-z0-9._:-]{16,128}$/;

function bytesToBase64Url(bytes: Uint8Array): string {
  let binary = "";
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index]);
  }
  return btoa(binary)
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replace(/=+$/u, "");
}

export function createOpaqueToken(byteLength = 32): string {
  if (!Number.isInteger(byteLength) || byteLength < 16 || byteLength > 64) {
    throw new RangeError("Opaque tokens must contain between 16 and 64 bytes.");
  }
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return bytesToBase64Url(bytes);
}

export async function sha256Base64Url(
  value: string | Uint8Array,
): Promise<string> {
  const bytes =
    typeof value === "string" ? new TextEncoder().encode(value) : value;
  const digestInput = new Uint8Array(bytes).buffer;
  const digest = await crypto.subtle.digest("SHA-256", digestInput);
  return bytesToBase64Url(new Uint8Array(digest));
}

export function createIdempotencyKey(): string {
  return `skyeta_${createOpaqueToken(32)}`;
}

export function isValidIdempotencyKey(value: string): boolean {
  return IDEMPOTENCY_KEY_PATTERN.test(value);
}

export async function hashIdempotencyKey(value: string): Promise<string> {
  if (!isValidIdempotencyKey(value)) {
    throw new TypeError("The idempotency key has an invalid format.");
  }
  return sha256Base64Url(value);
}

export type BookingRequestFingerprintInput = {
  sessionHash: string;
  offerSelectionId: string;
  currency: string;
  totalAmountMinor: number;
  passengerCounts: {
    adults: number;
    children: number;
    infantsWithoutSeat: number;
  };
};

/**
 * Detects reuse of an idempotency key for a different booking request without
 * retaining passenger identity or contact fields.
 */
export async function fingerprintBookingRequest(
  input: BookingRequestFingerprintInput,
): Promise<string> {
  const canonical = [
    "skyeta-booking-v1",
    input.sessionHash,
    input.offerSelectionId,
    input.currency.toUpperCase(),
    String(input.totalAmountMinor),
    String(input.passengerCounts.adults),
    String(input.passengerCounts.children),
    String(input.passengerCounts.infantsWithoutSeat),
  ].join("\n");
  return sha256Base64Url(canonical);
}
