import type {
  PaystackApiEnvelope,
  PaystackChannel,
  PaystackEnvironment,
  PaystackInitializeTransactionInput,
  PaystackInitializeTransactionResult,
  PaystackVerifyTransactionResult,
} from "./contracts";

const PAYSTACK_API_ORIGIN = "https://api.paystack.co";
const INITIALIZE_PATH = "/transaction/initialize";
const VERIFY_PATH_PREFIX = "/transaction/verify/";
const CHECKOUT_HOSTS = new Set([
  "checkout.paystack.com",
  "standard.paystack.co",
]);
const PAYSTACK_REFERENCE = /^[A-Za-z0-9.=-]{1,100}$/;
const DEFAULT_TIMEOUT_MS = 15_000;
const MAX_TIMEOUT_MS = 30_000;
const MAX_REQUEST_BODY_BYTES = 64 * 1024;

const PAYSTACK_CHANNELS = new Set<PaystackChannel>([
  "card",
  "bank",
  "apple_pay",
  "ussd",
  "qr",
  "mobile_money",
  "bank_transfer",
  "eft",
  "capitec_pay",
  "payattitude",
]);

type FetchLike = (
  input: string | URL | Request,
  init?: RequestInit,
) => Promise<Response>;

export type PaystackRequestOptions = {
  signal?: AbortSignal;
  timeoutMs?: number;
};

export type PaystackClientOptions = {
  getSecretKey?: () => string | null | undefined;
  fetchImpl?: FetchLike;
  timeoutMs?: number;
  subtleCrypto?: SubtleCrypto;
};

export type PaystackProviderErrorCode =
  | "not_configured"
  | "invalid_configuration"
  | "invalid_request"
  | "cancelled"
  | "timeout"
  | "unavailable"
  | "authentication_failed"
  | "rate_limited"
  | "provider_rejected"
  | "invalid_response";

export class PaystackProviderError extends Error {
  readonly code: PaystackProviderErrorCode;
  readonly status: number;
  readonly providerStatus: number | null;
  readonly requestId: string | null;
  readonly retryable: boolean;

  constructor(options: {
    code: PaystackProviderErrorCode;
    message: string;
    status: number;
    providerStatus?: number | null;
    requestId?: string | null;
    retryable?: boolean;
  }) {
    super(options.message);
    this.name = "PaystackProviderError";
    this.code = options.code;
    this.status = options.status;
    this.providerStatus = options.providerStatus ?? null;
    this.requestId = options.requestId ?? null;
    this.retryable = options.retryable ?? false;
  }
}

function configurationError(
  code: "not_configured" | "invalid_configuration",
): PaystackProviderError {
  return new PaystackProviderError({
    code,
    message:
      code === "not_configured"
        ? "Secure payment is not configured."
        : "The payment provider configuration is invalid.",
    status: 503,
  });
}

function invalidRequest(message: string): PaystackProviderError {
  return new PaystackProviderError({
    code: "invalid_request",
    message,
    status: 400,
  });
}

function invalidResponse(
  providerStatus: number,
  requestId: string | null,
): PaystackProviderError {
  return new PaystackProviderError({
    code: "invalid_response",
    message: "The payment provider returned an invalid response.",
    status: 502,
    providerStatus,
    requestId,
    retryable: true,
  });
}

function ensureServerRuntime(): void {
  if (typeof window !== "undefined") {
    throw configurationError("invalid_configuration");
  }
}

function environmentSecretKey(): string | null {
  ensureServerRuntime();
  const secretKey = process.env.PAYSTACK_SECRET_KEY?.trim();
  return secretKey || null;
}

function validatedSecretKey(
  value: string | null | undefined,
): { secretKey: string; environment: PaystackEnvironment } {
  ensureServerRuntime();
  if (value === null || value === undefined || value.trim() === "") {
    throw configurationError("not_configured");
  }

  const secretKey = value.trim();
  const match = /^sk_(test|live)_[A-Za-z0-9_-]+$/.exec(secretKey);
  if (!match || secretKey.length > 512) {
    throw configurationError("invalid_configuration");
  }

  return {
    secretKey,
    environment: match[1] as PaystackEnvironment,
  };
}

function boundedTimeout(value: number): number {
  if (!Number.isFinite(value) || value < 1 || value > MAX_TIMEOUT_MS) {
    throw invalidRequest("The payment provider timeout is invalid.");
  }
  return Math.floor(value);
}

function validatedReference(value: unknown): string {
  if (typeof value !== "string" || !PAYSTACK_REFERENCE.test(value)) {
    throw invalidRequest("The payment reference is invalid.");
  }
  return value;
}

function transactionUrl(
  operation: "initialize" | "verify",
  reference?: string,
): URL {
  const expectedPath =
    operation === "initialize"
      ? INITIALIZE_PATH
      : `${VERIFY_PATH_PREFIX}${encodeURIComponent(
          validatedReference(reference),
        )}`;
  const url = new URL(expectedPath, PAYSTACK_API_ORIGIN);

  const allowlisted =
    url.origin === PAYSTACK_API_ORIGIN &&
    url.username === "" &&
    url.password === "" &&
    url.search === "" &&
    url.hash === "" &&
    (url.pathname === INITIALIZE_PATH ||
      (operation === "verify" && url.pathname === expectedPath));
  if (!allowlisted) {
    throw invalidRequest("The payment provider request path is invalid.");
  }

  return url;
}

function amountInSubunits(value: number | string): string {
  const normalized = typeof value === "number" ? String(value) : value;
  if (!/^[1-9][0-9]*$/.test(normalized)) {
    throw invalidRequest("The payment amount is invalid.");
  }
  const amount = Number(normalized);
  if (!Number.isSafeInteger(amount) || amount < 1) {
    throw invalidRequest("The payment amount is invalid.");
  }
  return normalized;
}

function validatedCallbackUrl(value: string): string {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw invalidRequest("The payment callback URL is invalid.");
  }
  if (
    url.protocol !== "https:" ||
    url.username !== "" ||
    url.password !== "" ||
    value.length > 2_048
  ) {
    throw invalidRequest("The payment callback URL is invalid.");
  }
  return url.toString();
}

function serializedInitializeBody(
  input: PaystackInitializeTransactionInput,
): string {
  const email = input.email?.trim();
  if (
    !email ||
    email.length > 254 ||
    !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
  ) {
    throw invalidRequest("The payment email address is invalid.");
  }

  const body: Record<string, unknown> = {
    email,
    amount: amountInSubunits(input.amount),
  };
  if (input.currency !== undefined) {
    const currency = input.currency.trim().toUpperCase();
    if (!/^[A-Z]{3}$/.test(currency)) {
      throw invalidRequest("The payment currency is invalid.");
    }
    body.currency = currency;
  }
  if (input.reference !== undefined) {
    body.reference = validatedReference(input.reference);
  }
  if (input.callbackUrl !== undefined) {
    body.callback_url = validatedCallbackUrl(input.callbackUrl);
  }
  if (input.metadata !== undefined) {
    body.metadata = input.metadata;
  }
  if (input.channels !== undefined) {
    if (
      input.channels.length < 1 ||
      input.channels.length > PAYSTACK_CHANNELS.size ||
      new Set(input.channels).size !== input.channels.length ||
      input.channels.some((channel) => !PAYSTACK_CHANNELS.has(channel))
    ) {
      throw invalidRequest("The payment channels are invalid.");
    }
    body.channels = [...input.channels];
  }

  let serialized: string;
  try {
    serialized = JSON.stringify(body);
  } catch {
    throw invalidRequest("The payment request body is invalid.");
  }
  if (new TextEncoder().encode(serialized).byteLength > MAX_REQUEST_BODY_BYTES) {
    throw invalidRequest("The payment request body is too large.");
  }
  return serialized;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function apiEnvelope(value: unknown): PaystackApiEnvelope | null {
  return isRecord(value) ? (value as PaystackApiEnvelope) : null;
}

function providerRequestId(response: Response): string | null {
  const value =
    response.headers.get("x-request-id") ??
    response.headers.get("x-paystack-request-id");
  return value && /^[\x20-\x7e]{1,200}$/.test(value) ? value : null;
}

function mappedProviderError(status: number): {
  code: PaystackProviderErrorCode;
  message: string;
  status: number;
  retryable: boolean;
} {
  if (status === 401 || status === 403) {
    return {
      code: "authentication_failed",
      message: "Payment authentication is unavailable.",
      status: 503,
      retryable: false,
    };
  }
  if (status === 408) {
    return {
      code: "timeout",
      message: "The payment provider timed out.",
      status: 504,
      retryable: true,
    };
  }
  if (status === 429) {
    return {
      code: "rate_limited",
      message: "Payments are temporarily busy. Please try again shortly.",
      status: 503,
      retryable: true,
    };
  }
  if (status >= 500) {
    return {
      code: "unavailable",
      message: "The payment provider is temporarily unavailable.",
      status: 502,
      retryable: true,
    };
  }
  return {
    code: "provider_rejected",
    message: "The payment provider could not complete this request.",
    status: 422,
    retryable: false,
  };
}

function checkoutUrl(value: unknown): string | null {
  if (typeof value !== "string" || value.length > 2_048) return null;
  try {
    const url = new URL(value);
    if (
      url.protocol !== "https:" ||
      url.username !== "" ||
      url.password !== "" ||
      url.port !== "" ||
      !CHECKOUT_HOSTS.has(url.hostname.toLowerCase())
    ) {
      return null;
    }
    return url.toString();
  } catch {
    return null;
  }
}

function boundedString(
  value: unknown,
  maximumLength: number,
): string | null {
  return typeof value === "string" &&
    value.length > 0 &&
    value.length <= maximumLength
    ? value
    : null;
}

function verifiedAmount(value: unknown): number | null {
  if (typeof value === "number") {
    return Number.isSafeInteger(value) && value >= 0 ? value : null;
  }
  if (typeof value === "string" && /^(0|[1-9][0-9]*)$/.test(value)) {
    const number = Number(value);
    return Number.isSafeInteger(number) ? number : null;
  }
  return null;
}

function verifiedCustomerEmail(value: unknown): string | null {
  if (!isRecord(value) || typeof value.email !== "string") return null;
  const email = value.email.trim().toLowerCase();
  return email.length <= 254 && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
    ? email
    : null;
}

function verifiedMetadata(
  value: unknown,
): { bookingAttemptId: string } | null {
  let metadata: unknown = value;
  if (typeof metadata === "string") {
    if (metadata.length < 2 || metadata.length > MAX_REQUEST_BODY_BYTES) {
      return null;
    }
    try {
      metadata = JSON.parse(metadata);
    } catch {
      return null;
    }
  }
  if (!isRecord(metadata)) return null;

  const bookingAttemptId = boundedString(metadata.bookingAttemptId, 128);
  return bookingAttemptId && /^[A-Za-z0-9._:-]+$/.test(bookingAttemptId)
    ? { bookingAttemptId }
    : null;
}

function rawBodyBytes(
  value: ArrayBuffer | ArrayBufferView,
): Uint8Array<ArrayBuffer> | null {
  if (value instanceof ArrayBuffer) return new Uint8Array(value.slice(0));
  if (!ArrayBuffer.isView(value)) return null;
  const copy = new Uint8Array(value.byteLength);
  copy.set(new Uint8Array(value.buffer, value.byteOffset, value.byteLength));
  return copy;
}

function signatureBytes(
  value: string | null | undefined,
): Uint8Array<ArrayBuffer> | null {
  if (typeof value !== "string" || !/^[A-Fa-f0-9]{128}$/.test(value)) {
    return null;
  }
  const result = new Uint8Array(64);
  for (let index = 0; index < result.length; index += 1) {
    result[index] = Number.parseInt(value.slice(index * 2, index * 2 + 2), 16);
  }
  return result;
}

async function verifyWebhookHmac(options: {
  rawBody: ArrayBuffer | ArrayBufferView;
  signature: string | null | undefined;
  secretKey: string;
  subtleCrypto?: SubtleCrypto;
}): Promise<boolean> {
  const body = rawBodyBytes(options.rawBody);
  const signature = signatureBytes(options.signature);
  if (!body || !signature) return false;

  const subtleCrypto = options.subtleCrypto ?? globalThis.crypto?.subtle;
  if (!subtleCrypto) throw configurationError("invalid_configuration");

  try {
    const key = await subtleCrypto.importKey(
      "raw",
      new TextEncoder().encode(options.secretKey),
      { name: "HMAC", hash: "SHA-512" },
      false,
      ["verify"],
    );
    // Web Crypto performs the HMAC comparison without a data-dependent JS loop.
    return await subtleCrypto.verify("HMAC", key, signature, body);
  } catch {
    throw configurationError("invalid_configuration");
  }
}

export function createPaystackClient(options: PaystackClientOptions = {}) {
  const getSecretKey = options.getSecretKey ?? environmentSecretKey;
  const fetchImpl = options.fetchImpl ?? fetch;
  const defaultTimeoutMs = boundedTimeout(
    options.timeoutMs ?? DEFAULT_TIMEOUT_MS,
  );

  async function request(
    url: URL,
    method: "GET" | "POST",
    body: string | undefined,
    requestOptions: PaystackRequestOptions,
  ): Promise<{
    payload: unknown;
    response: Response;
    requestId: string | null;
    environment: PaystackEnvironment;
  }> {
    const config = validatedSecretKey(getSecretKey());
    const timeoutMs = boundedTimeout(
      requestOptions.timeoutMs ?? defaultTimeoutMs,
    );
    if (requestOptions.signal?.aborted) {
      throw new PaystackProviderError({
        code: "cancelled",
        message: "The payment provider request was cancelled.",
        status: 499,
        retryable: true,
      });
    }

    const controller = new AbortController();
    let abortSource: "timeout" | "caller" | null = null;
    const timeout = setTimeout(() => {
      abortSource = "timeout";
      controller.abort();
    }, timeoutMs);
    const abortFromCaller = () => {
      if (!abortSource) abortSource = "caller";
      controller.abort();
    };
    requestOptions.signal?.addEventListener("abort", abortFromCaller, {
      once: true,
    });

    let response: Response;
    let payload: unknown = null;
    try {
      response = await fetchImpl(url, {
        method,
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${config.secretKey}`,
          ...(body === undefined
            ? {}
            : { "Content-Type": "application/json" }),
        },
        body,
        signal: controller.signal,
        redirect: "error",
        cache: "no-store",
      });
      try {
        payload = await response.json();
      } catch (error) {
        if (abortSource) throw error;
        // Provider responses must be JSON. Raw response text is never exposed.
      }
    } catch {
      const cancelled = abortSource === "caller";
      const timedOut = abortSource === "timeout";
      throw new PaystackProviderError({
        code: cancelled ? "cancelled" : timedOut ? "timeout" : "unavailable",
        message: cancelled
          ? "The payment provider request was cancelled."
          : timedOut
            ? "The payment provider timed out."
            : "The payment provider is unavailable.",
        status: cancelled ? 499 : timedOut ? 504 : 502,
        retryable: true,
      });
    } finally {
      clearTimeout(timeout);
      requestOptions.signal?.removeEventListener("abort", abortFromCaller);
    }

    const requestId = providerRequestId(response);
    if (!response.ok) {
      throw new PaystackProviderError({
        ...mappedProviderError(response.status),
        providerStatus: response.status,
        requestId,
      });
    }

    const envelope = apiEnvelope(payload);
    if (envelope?.status === false) {
      throw new PaystackProviderError({
        ...mappedProviderError(400),
        providerStatus: response.status,
        requestId,
      });
    }
    if (envelope?.status !== true || !isRecord(envelope.data)) {
      throw invalidResponse(response.status, requestId);
    }

    return {
      payload: envelope.data,
      response,
      requestId,
      environment: config.environment,
    };
  }

  return {
    isConfigured(): boolean {
      try {
        validatedSecretKey(getSecretKey());
        return true;
      } catch (error) {
        if (
          error instanceof PaystackProviderError &&
          (error.code === "not_configured" ||
            error.code === "invalid_configuration")
        ) {
          return false;
        }
        throw error;
      }
    },

    getEnvironment(): PaystackEnvironment | null {
      try {
        return validatedSecretKey(getSecretKey()).environment;
      } catch (error) {
        if (
          error instanceof PaystackProviderError &&
          error.code === "not_configured"
        ) {
          return null;
        }
        throw error;
      }
    },

    async initializeTransaction(
      input: PaystackInitializeTransactionInput,
      requestOptions: PaystackRequestOptions = {},
    ): Promise<PaystackInitializeTransactionResult> {
      const body = serializedInitializeBody(input);
      const result = await request(
        transactionUrl("initialize"),
        "POST",
        body,
        requestOptions,
      );
      const data = result.payload as Record<string, unknown>;
      const authorizationUrl = checkoutUrl(data.authorization_url);
      const accessCode = boundedString(data.access_code, 512);
      const reference = boundedString(data.reference, 100);
      if (
        !authorizationUrl ||
        !accessCode ||
        !reference ||
        !PAYSTACK_REFERENCE.test(reference) ||
        (input.reference !== undefined && reference !== input.reference)
      ) {
        throw invalidResponse(result.response.status, result.requestId);
      }

      return {
        authorizationUrl,
        accessCode,
        reference,
        environment: result.environment,
        requestId: result.requestId,
      };
    },

    async verifyTransaction(
      referenceValue: string,
      requestOptions: PaystackRequestOptions = {},
    ): Promise<PaystackVerifyTransactionResult> {
      const reference = validatedReference(referenceValue);
      const result = await request(
        transactionUrl("verify", reference),
        "GET",
        undefined,
        requestOptions,
      );
      const data = result.payload as Record<string, unknown>;
      const responseReference = boundedString(data.reference, 100);
      const status = boundedString(data.status, 64);
      const amount = verifiedAmount(data.amount);
      const currency = boundedString(data.currency, 3);
      const domain = boundedString(data.domain, 4);
      const channel =
        data.channel === null || data.channel === undefined
          ? null
          : boundedString(data.channel, 64);
      const paidAt =
        data.paid_at === null || data.paid_at === undefined
          ? null
          : boundedString(data.paid_at, 100);
      const customerEmail = verifiedCustomerEmail(data.customer);
      const metadata = verifiedMetadata(data.metadata);
      if (
        responseReference !== reference ||
        !status ||
        !/^[A-Za-z_]+$/.test(status) ||
        amount === null ||
        !currency ||
        !/^[A-Z]{3}$/.test(currency) ||
        domain !== result.environment ||
        (data.channel !== null && data.channel !== undefined && !channel) ||
        (data.paid_at !== null && data.paid_at !== undefined && !paidAt)
      ) {
        throw invalidResponse(result.response.status, result.requestId);
      }

      return {
        status,
        reference: responseReference,
        amount,
        currency,
        environment: result.environment,
        paidAt,
        channel,
        customerEmail,
        metadata,
        requestId: result.requestId,
      };
    },

    async verifyWebhookSignature(
      rawBody: ArrayBuffer | ArrayBufferView,
      signature: string | null | undefined,
    ): Promise<boolean> {
      const signatureValue = signatureBytes(signature);
      const body = rawBodyBytes(rawBody);
      if (!signatureValue || !body) return false;
      const config = validatedSecretKey(getSecretKey());
      return verifyWebhookHmac({
        rawBody: body,
        signature,
        secretKey: config.secretKey,
        subtleCrypto: options.subtleCrypto,
      });
    },
  };
}

export async function verifyPaystackWebhookSignature(
  rawBody: ArrayBuffer | ArrayBufferView,
  signature: string | null | undefined,
  secretKey?: string,
): Promise<boolean> {
  const client = createPaystackClient({
    getSecretKey: secretKey === undefined ? environmentSecretKey : () => secretKey,
  });
  return client.verifyWebhookSignature(rawBody, signature);
}

export const paystackClient = createPaystackClient();

export function isPaystackConfigured(): boolean {
  return paystackClient.isConfigured();
}

export { PaystackProviderError as PaystackError };
export type {
  PaystackEnvironment,
  PaystackInitializeTransactionInput,
  PaystackInitializeTransactionResult,
  PaystackVerifyTransactionResult,
} from "./contracts";
