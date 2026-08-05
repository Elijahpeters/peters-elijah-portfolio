import assert from "node:assert/strict";
import test from "node:test";

import {
  bookingCallbackUrl,
  bookingReadiness,
  isPaystackBookingCurrency,
} from "../app/lib/booking/config.ts";

const live = {
  SKYETA_BOOKING_ENABLED: "true",
  DUFFEL_MODE: "live",
  DUFFEL_ACCESS_TOKEN: "duffel_live_example",
  SKYETA_PAYMENT_PROVIDER: "paystack",
  PAYSTACK_SECRET_KEY: "sk_live_example",
  PAYSTACK_ALLOWED_CURRENCIES: "NGN,USD",
  BOOKING_DATA_ENCRYPTION_KEY: "A".repeat(43),
  NEXT_PUBLIC_SITE_URL: "https://peterselijah.name.ng",
};

test("checkout is ready only when every live safeguard is configured", () => {
  assert.deepEqual(bookingReadiness(live), { ready: true, code: "ready" });
  assert.equal(bookingReadiness({ ...live, DUFFEL_MODE: "test" }).code, "provider_not_live");
  assert.equal(
    bookingReadiness({ ...live, PAYSTACK_SECRET_KEY: "sk_test_example" }).code,
    "payment_not_live",
  );
  assert.equal(
    bookingReadiness({ ...live, BOOKING_DATA_ENCRYPTION_KEY: "bad" }).code,
    "encryption_not_configured",
  );
});

test("the callback is resolved only from the configured HTTPS origin", () => {
  assert.equal(
    bookingCallbackUrl(live),
    "https://peterselijah.name.ng/skyeta/payment/return",
  );
  assert.throws(
    () => bookingCallbackUrl({ ...live, NEXT_PUBLIC_SITE_URL: "http://example.com" }),
    /origin/i,
  );
});

test("Paystack checkout refuses currencies without an implemented settlement path", () => {
  assert.equal(isPaystackBookingCurrency("NGN", live), true);
  assert.equal(isPaystackBookingCurrency("usd", live), true);
  assert.equal(isPaystackBookingCurrency("GBP", live), false);
  assert.equal(isPaystackBookingCurrency("USD", {}), false);
});
