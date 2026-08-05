import assert from "node:assert/strict";
import test from "node:test";

import { createBookingStatusHandler } from "../app/api/skyeta/bookings/status/status.ts";
import { hashBookingSessionToken } from "../app/lib/booking/session.ts";

const token = "A".repeat(43);
const now = new Date("2026-08-05T12:00:00Z");

async function requestFor(reference = "skyeta-payment-123") {
  return new Request(
    `https://peterselijah.name.ng/api/skyeta/bookings/status?reference=${reference}`,
    { headers: { cookie: `skyeta_booking_session=${token}` } },
  );
}

async function handlerFor(state, booking = null, attemptSessionHash) {
  const sessionHash = await hashBookingSessionToken(token);
  const handler = createBookingStatusHandler({
    now: () => now,
    getDatabase: () => ({}),
    createRepository: () => ({
      getActiveSession: async () => ({ sessionHash, expiresAt: now.getTime() + 60_000 }),
      getBookingAttemptByPaymentReference: async () => ({
        id: "bat_123",
        sessionHash: attemptSessionHash ?? sessionHash,
        state,
      }),
      getBookingByAttempt: async () => booking,
    }),
  });
  return handler;
}

test("a booking reference is exposed only after a confirmed airline booking", async () => {
  const handler = await handlerFor("confirmed", {
    status: "confirmed",
    bookingReference: "ABC123",
  });
  const response = await handler(await requestFor());
  const body = await response.json();

  assert.equal(response.status, 200);
  assert.equal(body.state, "confirmed");
  assert.equal(body.bookingReference, "ABC123");
});

test("payment confirmation never invents an airline reference", async () => {
  const handler = await handlerFor("payment_authorized");
  const body = await (await handler(await requestFor())).json();

  assert.equal(body.state, "creating_booking");
  assert.equal("bookingReference" in body, false);
});

test("manual review tells the traveller not to pay twice", async () => {
  const handler = await handlerFor("manual_review");
  const body = await (await handler(await requestFor())).json();

  assert.equal(body.state, "manual_review");
  assert.match(body.message, /do not make another payment/i);
  assert.equal("bookingReference" in body, false);
});

test("booking status stays scoped to the secure browser session", async () => {
  const handler = await handlerFor("confirmed", null, "another-session-hash");
  const response = await handler(await requestFor());
  assert.equal(response.status, 404);
});

test("malformed references are rejected before storage access", async () => {
  let databaseAccessed = false;
  const handler = createBookingStatusHandler({
    getDatabase: () => {
      databaseAccessed = true;
      throw new Error("must not run");
    },
  });
  const response = await handler(await requestFor("../orders"));
  assert.equal(response.status, 404);
  assert.equal(databaseAccessed, false);
});
