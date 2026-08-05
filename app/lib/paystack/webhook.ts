export type PaystackChargeSuccessEvent = {
  eventType: "charge.success";
  providerEventId: string;
  reference: string;
};

const PAYMENT_REFERENCE = /^[A-Za-z0-9.=-]{1,100}$/;
const EVENT_ID = /^[1-9]\d{0,30}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function normalizedEventId(value: unknown): string | null {
  if (typeof value === "number") {
    return Number.isSafeInteger(value) && value > 0 ? String(value) : null;
  }
  return typeof value === "string" && EVENT_ID.test(value) ? value : null;
}

/**
 * Parses only the routing fields from a signed webhook. Payment truth still
 * comes from Paystack's server-side transaction verification endpoint.
 */
export function parsePaystackChargeSuccessEvent(
  value: unknown,
): PaystackChargeSuccessEvent | null {
  if (!isRecord(value) || value.event !== "charge.success" || !isRecord(value.data)) {
    return null;
  }
  const id = normalizedEventId(value.data.id);
  const reference = value.data.reference;
  if (!id || typeof reference !== "string" || !PAYMENT_REFERENCE.test(reference)) {
    return null;
  }
  return {
    eventType: "charge.success",
    providerEventId: `charge.success:${id}`,
    reference,
  };
}
