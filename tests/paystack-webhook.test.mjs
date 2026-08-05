import assert from "node:assert/strict";
import test from "node:test";

import { parsePaystackChargeSuccessEvent } from "../app/lib/paystack/webhook.ts";

test("only signed-event routing fields are accepted before transaction verification", () => {
  assert.deepEqual(
    parsePaystackChargeSuccessEvent({
      event: "charge.success",
      data: {
        id: 12345,
        reference: "skyeta-payment-123",
        amount: 1,
        metadata: { ignored: "untrusted" },
      },
    }),
    {
      eventType: "charge.success",
      providerEventId: "charge.success:12345",
      reference: "skyeta-payment-123",
    },
  );
});

test("unsupported or malformed webhooks are ignored", () => {
  assert.equal(
    parsePaystackChargeSuccessEvent({
      event: "transfer.success",
      data: { id: 1, reference: "skyeta-payment-123" },
    }),
    null,
  );
  assert.equal(
    parsePaystackChargeSuccessEvent({
      event: "charge.success",
      data: { id: 1, reference: "../orders" },
    }),
    null,
  );
});
