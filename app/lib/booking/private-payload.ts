export type EncryptedPrivateBookingPayload = {
  ciphertext: string;
  iv: string;
};

export class PrivateBookingPayloadError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PrivateBookingPayloadError";
  }
}

const BASE64URL_PATTERN = /^[A-Za-z0-9_-]+$/u;
const AES_KEY_BYTES = 32;
const AES_GCM_IV_BYTES = 12;
const AES_GCM_TAG_BYTES = 16;
const textEncoder = new TextEncoder();
const textDecoder = new TextDecoder("utf-8", { fatal: true });

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

function arrayBufferBytes(
  value: Uint8Array<ArrayBufferLike>,
): Uint8Array<ArrayBuffer> {
  const copy = new Uint8Array(value.byteLength);
  copy.set(value);
  return copy;
}

function base64UrlToBytes(value: string): Uint8Array<ArrayBuffer> {
  if (
    value.length === 0 ||
    value.length % 4 === 1 ||
    !BASE64URL_PATTERN.test(value)
  ) {
    throw new TypeError("Invalid base64url data.");
  }

  const base64 = value.replaceAll("-", "+").replaceAll("_", "/");
  const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), "=");
  let binary: string;
  try {
    binary = atob(padded);
  } catch {
    throw new TypeError("Invalid base64url data.");
  }

  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  if (bytesToBase64Url(bytes) !== value) {
    throw new TypeError("Invalid base64url data.");
  }
  return arrayBufferBytes(bytes);
}

function configuredKey(explicitKey: string | undefined): string {
  const value = explicitKey ?? process.env.BOOKING_DATA_ENCRYPTION_KEY;
  if (typeof value !== "string") {
    throw new TypeError("The private booking encryption key is unavailable.");
  }
  return value.trim();
}

async function importEncryptionKey(
  explicitKey: string | undefined,
): Promise<CryptoKey> {
  const keyBytes = base64UrlToBytes(configuredKey(explicitKey));
  if (keyBytes.byteLength !== AES_KEY_BYTES) {
    throw new TypeError("The private booking encryption key is invalid.");
  }
  return crypto.subtle.importKey(
    "raw",
    keyBytes,
    { name: "AES-GCM" },
    false,
    ["encrypt", "decrypt"],
  );
}

function additionalData(bookingAttemptId: string): Uint8Array<ArrayBuffer> {
  if (typeof bookingAttemptId !== "string" || bookingAttemptId.length === 0) {
    throw new TypeError("A booking attempt identifier is required.");
  }
  return arrayBufferBytes(textEncoder.encode(bookingAttemptId));
}

/** Encrypts JSON without retaining or emitting its plaintext representation. */
export async function encryptPrivateBookingPayload(
  value: unknown,
  bookingAttemptId: string,
  key?: string,
): Promise<EncryptedPrivateBookingPayload> {
  try {
    const serialized = JSON.stringify(value);
    if (serialized === undefined) {
      throw new TypeError("The value is not JSON serializable.");
    }
    const ivBytes = arrayBufferBytes(
      crypto.getRandomValues(new Uint8Array(AES_GCM_IV_BYTES)),
    );
    const cryptoKey = await importEncryptionKey(key);
    const encrypted = await crypto.subtle.encrypt(
      {
        name: "AES-GCM",
        iv: ivBytes,
        additionalData: additionalData(bookingAttemptId),
        tagLength: AES_GCM_TAG_BYTES * 8,
      },
      cryptoKey,
      arrayBufferBytes(textEncoder.encode(serialized)),
    );
    return {
      ciphertext: bytesToBase64Url(new Uint8Array(encrypted)),
      iv: bytesToBase64Url(ivBytes),
    };
  } catch {
    throw new PrivateBookingPayloadError(
      "The private booking payload could not be encrypted.",
    );
  }
}

/** Decrypts only when the key, IV, authentication tag, and attempt-bound AAD match. */
export async function decryptPrivateBookingPayload<T = unknown>(
  record: EncryptedPrivateBookingPayload,
  bookingAttemptId: string,
  key?: string,
): Promise<T> {
  try {
    if (typeof record !== "object" || record === null) {
      throw new TypeError("The encrypted payload is invalid.");
    }
    const ivBytes = base64UrlToBytes(record.iv);
    const ciphertextBytes = base64UrlToBytes(record.ciphertext);
    if (
      ivBytes.byteLength !== AES_GCM_IV_BYTES ||
      ciphertextBytes.byteLength < AES_GCM_TAG_BYTES
    ) {
      throw new TypeError("The encrypted payload is invalid.");
    }
    const cryptoKey = await importEncryptionKey(key);
    const decrypted = await crypto.subtle.decrypt(
      {
        name: "AES-GCM",
        iv: ivBytes,
        additionalData: additionalData(bookingAttemptId),
        tagLength: AES_GCM_TAG_BYTES * 8,
      },
      cryptoKey,
      ciphertextBytes,
    );
    return JSON.parse(textDecoder.decode(decrypted)) as T;
  } catch {
    throw new PrivateBookingPayloadError(
      "The private booking payload could not be decrypted.",
    );
  }
}
