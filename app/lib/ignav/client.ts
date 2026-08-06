import {
  BodyTooLargeError,
  readBoundedJson,
} from "../http/bounded-json.ts";

const ORIGIN = "https://ignav.com";
const DEFAULT_TIMEOUT_MS = 30_000;
const MAX_TIMEOUT_MS = 45_000;
const MAX_RESPONSE_BYTES = 2_000_000;
const ALLOWED_PATHS = new Set([
  "/api/fares/one-way",
  "/api/fares/round-trip",
  "/api/fares/booking-links",
]);

type FetchLike = (
  input: string | URL | Request,
  init?: RequestInit,
) => Promise<Response>;

type IgnavClientConfig = {
  apiKey: string;
};

type IgnavClientOptions = {
  getConfig?: () => IgnavClientConfig | null;
  fetchImpl?: FetchLike;
  timeoutMs?: number;
};

export type IgnavResult<T> = {
  data: T;
  mode: "live";
  providerStatus: number;
  requestId: string | null;
};

export type IgnavProviderErrorCode =
  | "not_configured"
  | "invalid_configuration"
  | "invalid_request"
  | "timeout"
  | "unavailable"
  | "authentication_failed"
  | "allowance_exhausted"
  | "spend_limit_reached"
  | "provider_rejected"
  | "invalid_response";

export class IgnavProviderError extends Error {
  readonly code: IgnavProviderErrorCode;
  readonly status: number;
  readonly providerStatus: number | null;
  readonly requestId: string | null;
  readonly retryable: boolean;

  constructor(options: {
    code: IgnavProviderErrorCode;
    message: string;
    status: number;
    providerStatus?: number | null;
    requestId?: string | null;
    retryable?: boolean;
  }) {
    super(options.message);
    this.name = "IgnavProviderError";
    this.code = options.code;
    this.status = options.status;
    this.providerStatus = options.providerStatus ?? null;
    this.requestId = options.requestId ?? null;
    this.retryable = options.retryable ?? false;
  }
}

function ensureServerRuntime(): void {
  if (typeof window !== "undefined") {
    throw new IgnavProviderError({
      code: "invalid_configuration",
      message: "The flight provider can only be used on the server.",
      status: 500,
    });
  }
}

function environmentConfig(): IgnavClientConfig | null {
  ensureServerRuntime();
  const apiKey = process.env.IGNAV_API_KEY?.trim();
  return apiKey ? { apiKey } : null;
}

function validatedConfig(
  getConfig: () => IgnavClientConfig | null,
): IgnavClientConfig {
  ensureServerRuntime();
  const config = getConfig();
  if (!config) {
    throw new IgnavProviderError({
      code: "not_configured",
      message: "Live flight search is not configured.",
      status: 503,
    });
  }
  const apiKey = config.apiKey.trim();
  if (!apiKey || apiKey.length > 500) {
    throw new IgnavProviderError({
      code: "invalid_configuration",
      message: "The flight provider configuration is invalid.",
      status: 503,
    });
  }
  return { apiKey };
}

function boundedTimeout(value: number): number {
  if (!Number.isFinite(value) || value < 1 || value > MAX_TIMEOUT_MS) {
    throw new IgnavProviderError({
      code: "invalid_request",
      message: "The flight provider timeout is invalid.",
      status: 500,
    });
  }
  return Math.floor(value);
}

function requestUrl(path: string): URL {
  if (!ALLOWED_PATHS.has(path)) {
    throw new IgnavProviderError({
      code: "invalid_request",
      message: "The flight provider request path is invalid.",
      status: 500,
    });
  }
  return new URL(path, ORIGIN);
}

function providerRequestId(response: Response): string | null {
  const value =
    response.headers.get("x-request-id") ??
    response.headers.get("trace-id") ??
    response.headers.get("cf-ray");
  return value && value.length <= 200 ? value : null;
}

function mappedProviderError(status: number) {
  if (status === 401 || status === 403) {
    return {
      code: "authentication_failed" as const,
      status: 503,
      message: "Flight search authentication is unavailable.",
      retryable: false,
    };
  }
  if (status === 402) {
    return {
      code: "allowance_exhausted" as const,
      status: 503,
      message: "The live fare allowance is currently unavailable.",
      retryable: false,
    };
  }
  if (status === 429) {
    return {
      code: "spend_limit_reached" as const,
      status: 503,
      message: "Live fare search has reached its configured usage limit.",
      retryable: false,
    };
  }
  if (status === 424 || status >= 500) {
    return {
      code: "unavailable" as const,
      status: 502,
      message: "The flight provider is temporarily unavailable.",
      retryable: true,
    };
  }
  return {
    code: "provider_rejected" as const,
    status: 422,
    message: "The flight provider could not complete this request.",
    retryable: false,
  };
}

async function safeJson(response: Response): Promise<unknown> {
  try {
    return await readBoundedJson(response, MAX_RESPONSE_BYTES);
  } catch (error) {
    if (!(error instanceof BodyTooLargeError)) return null;
    throw new IgnavProviderError({
      code: "invalid_response",
      message: "The flight provider response is too large.",
      status: 502,
      providerStatus: response.status,
      requestId: providerRequestId(response),
      retryable: true,
    });
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function transportDiagnostic(error: unknown, apiKey: string) {
  const redact = (value: string) =>
    value.replaceAll(apiKey, "[redacted]").slice(0, 500);
  const cause =
    error instanceof Error && error.cause instanceof Error
      ? {
          name: error.cause.name,
          message: redact(error.cause.message),
        }
      : null;

  return error instanceof Error
    ? { name: error.name, message: redact(error.message), cause }
    : { name: "UnknownError", message: "Unknown provider transport failure.", cause };
}

export function createIgnavClient(options: IgnavClientOptions = {}) {
  const getConfig = options.getConfig ?? environmentConfig;
  const fetchImpl = options.fetchImpl ?? fetch;
  const defaultTimeoutMs = boundedTimeout(
    options.timeoutMs ?? DEFAULT_TIMEOUT_MS,
  );

  return {
    getMode(): "live" | null {
      return getConfig() ? "live" : null;
    },

    async request<T>(
      path: string,
      body: unknown,
      requestOptions: { signal?: AbortSignal; timeoutMs?: number } = {},
    ): Promise<IgnavResult<T>> {
      const config = validatedConfig(getConfig);
      const url = requestUrl(path);
      const timeoutMs = boundedTimeout(
        requestOptions.timeoutMs ?? defaultTimeoutMs,
      );
      let serialized: string;
      try {
        serialized = JSON.stringify(body);
      } catch {
        throw new IgnavProviderError({
          code: "invalid_request",
          message: "The flight provider request body is invalid.",
          status: 500,
        });
      }

      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort("timeout"), timeoutMs);
      const abortFromCaller = () => controller.abort("caller");
      requestOptions.signal?.addEventListener("abort", abortFromCaller, {
        once: true,
      });
      if (requestOptions.signal?.aborted) abortFromCaller();

      let response!: Response;
      let payload: unknown;
      try {
        response = await fetchImpl(url, {
          method: "POST",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
            "User-Agent": "SkyETA/1.0",
            "X-Api-Key": config.apiKey,
          },
          body: serialized,
          signal: controller.signal,
          redirect: "manual",
        });
        payload = await safeJson(response);
        if (controller.signal.aborted) throw new Error("request_aborted");
      } catch (error) {
        if (error instanceof IgnavProviderError) throw error;
        console.error(
          "Ignav provider transport failure",
          transportDiagnostic(error, config.apiKey),
        );
        const timedOut =
          controller.signal.aborted && !requestOptions.signal?.aborted;
        throw new IgnavProviderError({
          code: timedOut ? "timeout" : "unavailable",
          message: timedOut
            ? "The flight provider timed out."
            : "The flight provider is unavailable.",
          status: timedOut ? 504 : 502,
          retryable: true,
        });
      } finally {
        clearTimeout(timeout);
        requestOptions.signal?.removeEventListener("abort", abortFromCaller);
      }

      if (!response.ok) {
        const mapped = mappedProviderError(response.status);
        throw new IgnavProviderError({
          ...mapped,
          providerStatus: response.status,
          requestId: providerRequestId(response),
        });
      }
      if (!isRecord(payload)) {
        throw new IgnavProviderError({
          code: "invalid_response",
          message: "The flight provider returned an invalid response.",
          status: 502,
          providerStatus: response.status,
          requestId: providerRequestId(response),
          retryable: true,
        });
      }
      return {
        data: payload as T,
        mode: "live",
        providerStatus: response.status,
        requestId: providerRequestId(response),
      };
    },
  };
}
