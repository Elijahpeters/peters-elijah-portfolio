export type BookingReadinessCode =
  | "ready"
  | "disabled"
  | "provider_not_live"
  | "payment_not_live"
  | "encryption_not_configured"
  | "site_origin_not_configured";

export type BookingReadiness = {
  ready: boolean;
  code: BookingReadinessCode;
};

type EnvironmentLike = Record<string, string | undefined>;

const BASE64URL_KEY = /^[A-Za-z0-9_-]{43}$/;
const PAYSTACK_LIVE_KEY = /^sk_live_[A-Za-z0-9_-]+$/;

function canonicalHttpsOrigin(value: string | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value.trim());
    if (
      url.protocol !== "https:" ||
      url.username !== "" ||
      url.password !== "" ||
      url.pathname !== "/" ||
      url.search !== "" ||
      url.hash !== ""
    ) {
      return null;
    }
    return url.origin;
  } catch {
    return null;
  }
}

export function bookingReadiness(
  environment: EnvironmentLike = process.env,
): BookingReadiness {
  if (environment.SKYETA_BOOKING_ENABLED?.trim().toLowerCase() !== "true") {
    return { ready: false, code: "disabled" };
  }
  const duffelToken = environment.DUFFEL_ACCESS_TOKEN?.trim() ?? "";
  if (
    environment.DUFFEL_MODE?.trim().toLowerCase() !== "live" ||
    !duffelToken ||
    duffelToken.startsWith("duffel_test_")
  ) {
    return { ready: false, code: "provider_not_live" };
  }
  if (
    environment.SKYETA_PAYMENT_PROVIDER?.trim().toLowerCase() !== "paystack" ||
    !PAYSTACK_LIVE_KEY.test(environment.PAYSTACK_SECRET_KEY?.trim() ?? "")
  ) {
    return { ready: false, code: "payment_not_live" };
  }
  if (!BASE64URL_KEY.test(environment.BOOKING_DATA_ENCRYPTION_KEY?.trim() ?? "")) {
    return { ready: false, code: "encryption_not_configured" };
  }
  if (!canonicalHttpsOrigin(environment.NEXT_PUBLIC_SITE_URL)) {
    return { ready: false, code: "site_origin_not_configured" };
  }
  return { ready: true, code: "ready" };
}

export function isLiveBookingConfigured(
  environment: EnvironmentLike = process.env,
): boolean {
  return bookingReadiness(environment).ready;
}

export function bookingCallbackUrl(
  environment: EnvironmentLike = process.env,
): string {
  const origin = canonicalHttpsOrigin(environment.NEXT_PUBLIC_SITE_URL);
  if (!origin) {
    throw new TypeError("The public booking origin is not configured.");
  }
  return new URL("/skyeta/payment/return", origin).toString();
}

export function isPaystackBookingCurrency(
  currency: string,
  environment: EnvironmentLike = process.env,
): boolean {
  const code = currency.trim().toUpperCase();
  const configured = (environment.PAYSTACK_ALLOWED_CURRENCIES ?? "NGN")
    .split(",")
    .map((value) => value.trim().toUpperCase())
    .filter((value) => /^[A-Z]{3}$/.test(value));
  return new Set(configured).has(code);
}
