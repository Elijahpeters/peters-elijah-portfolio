import assert from "node:assert/strict";
import test from "node:test";

import {
  decryptPrivateBookingPayload,
  encryptPrivateBookingPayload,
  PrivateBookingPayloadError,
} from "../app/lib/booking/private-payload.ts";

const KEY = Buffer.alloc(32, 0x42).toString("base64url");
const OTHER_KEY = Buffer.alloc(32, 0x24).toString("base64url");
const ATTEMPT_ID = "booking-attempt-01";
const PAYLOAD = {
  contact: { email: "traveller@example.com", phone: "+2348012345678" },
  passengers: [{ givenName: "Ada", familyName: "Lovelace" }],
};

test("private booking JSON round-trips through authenticated encryption", async () => {
  const encrypted = await encryptPrivateBookingPayload(PAYLOAD, ATTEMPT_ID, KEY);

  assert.match(encrypted.ciphertext, /^[A-Za-z0-9_-]+$/u);
  assert.match(encrypted.iv, /^[A-Za-z0-9_-]{16}$/u);
  assert.equal(Buffer.from(encrypted.iv, "base64url").byteLength, 12);
  assert.ok(Buffer.from(encrypted.ciphertext, "base64url").byteLength > 16);
  assert.doesNotMatch(encrypted.ciphertext, /Ada|Lovelace|traveller/u);
  assert.deepEqual(
    await decryptPrivateBookingPayload(encrypted, ATTEMPT_ID, KEY),
    PAYLOAD,
  );
});

test("encryption uses a fresh 96-bit IV for every payload", async () => {
  const first = await encryptPrivateBookingPayload(PAYLOAD, ATTEMPT_ID, KEY);
  const second = await encryptPrivateBookingPayload(PAYLOAD, ATTEMPT_ID, KEY);

  assert.notEqual(first.iv, second.iv);
  assert.notEqual(first.ciphertext, second.ciphertext);
});

test("decryption fails closed for the wrong attempt, key, or ciphertext", async () => {
  const encrypted = await encryptPrivateBookingPayload(PAYLOAD, ATTEMPT_ID, KEY);
  const ciphertext = Buffer.from(encrypted.ciphertext, "base64url");
  ciphertext[0] ^= 1;
  const tampered = {
    ...encrypted,
    ciphertext: ciphertext.toString("base64url"),
  };

  for (const operation of [
    decryptPrivateBookingPayload(encrypted, "booking-attempt-02", KEY),
    decryptPrivateBookingPayload(encrypted, ATTEMPT_ID, OTHER_KEY),
    decryptPrivateBookingPayload(tampered, ATTEMPT_ID, KEY),
  ]) {
    await assert.rejects(operation, PrivateBookingPayloadError);
  }
});

test("keys and encrypted fields must be canonical unpadded base64url", async () => {
  await assert.rejects(
    encryptPrivateBookingPayload(PAYLOAD, ATTEMPT_ID, "A".repeat(42)),
    PrivateBookingPayloadError,
  );
  await assert.rejects(
    encryptPrivateBookingPayload(PAYLOAD, ATTEMPT_ID, `${KEY}=`),
    PrivateBookingPayloadError,
  );

  const encrypted = await encryptPrivateBookingPayload(PAYLOAD, ATTEMPT_ID, KEY);
  await assert.rejects(
    decryptPrivateBookingPayload({ ...encrypted, iv: `${encrypted.iv}=` }, ATTEMPT_ID, KEY),
    PrivateBookingPayloadError,
  );
});

test("values without a JSON representation are rejected", async () => {
  await assert.rejects(
    encryptPrivateBookingPayload(undefined, ATTEMPT_ID, KEY),
    PrivateBookingPayloadError,
  );
});
