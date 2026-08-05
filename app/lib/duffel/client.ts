import type {
  DuffelApiEnvelope,
  DuffelApiErrorEnvelope,
  DuffelMode,
} from "./contracts";

const DUFFEL_API_ORIGIN = "https://api.duffel.com";
const DEFAULT_TIMEOUT_MS = 25_000;
// Duffel advises allowing at least 130 seconds when an airline order is being
// created. Search requests keep their shorter defaults; order helpers opt in.
const MAX_TIMEOUT_MS = 150_000;
const DUFFEL_PATH = /^\/air\/[A-Za-z0-9_./-]+$/;

type FetchLike = (
  input: string | URL | Request,
  init?: RequestInit,
) => Promise<Response>;

type DuffelClientConfig = {
  accessToken: string;
  mode: DuffelMode;
};

type DuffelRequestOptions = {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  query?: Record<string, string | number | boolean | null | undefined>;
  body?: unknown;
  idempotencyKey?: string;
  signal?: AbortSignal;
  timeoutMs?: number;
};

type DuffelClientOptions = {
  getConfig?: () => DuffelClientConfig | null;
  fetchImpl?: FetchLike;
  timeoutMs?: number;
};

export type DuffelResult<T> = {
  data: T;
  meta?: unknown;
  mode: DuffelMode;
  providerStatus: number;
  requestId: string | null;
};

export type DuffelProviderErrorCode =
  | "not_configured"
  | "invalid_configuration"
  | "invalid_request"
  | "timeout"
  | "unavailable"
  | "authentication_failed"
  | "rate_limited"
  | "provider_rejected"
  | "invalid_response";

export class DuffelProviderError extends Error {
  readonly code: DuffelProviderErrorCode;
  readonly status: number;
  readonly providerStatus: number | null;
  readonly requestId: string | null;
  readonly retryable: boolean;

  constructor(options: {
    code: DuffelProviderErrorCode;
    message: string;
    status: number;
    providerStatus?: number | null;
    requestId?: string | null;
    retryable?: boolean;
  }) {
    super(options.message);
    this.name = "DuffelProviderError";
    this.code = options.code;
    this.status = options.status;
    this.providerStatus = options.providerStatus ?? null;
    this.requestId = options.requestId ?? null;
    this.retryable = options.retryable ?? false;
  }
}

function ensureServerRuntime(): void {
  if (typeof window !== "undefined") {
    throw new DuffelProviderError({
      code: "invalid_configuration",
      message: "The flight provider can only be used on the server.",
      status: 500,
    });
  }
}

function environmentConfig(): DuffelClientConfig | null {
  ensureServerRuntime();
  const accessToken = process.env.DUFFEL_ACCESS_TOKEN?.trim();
  const rawMode = process.env.DUFFEL_MODE?.trim().toLowerCase();

  if (!accessToken && !rawMode) return null;
  if (!accessToken || (rawMode !== "test" && rawMode !== "live")) {
    throw new DuffelProviderError({
      code: "invalid_configuration",
      message: "The flight provider configuration is incomplete.",
      status: 503,
    });
  }

  if (
    (rawMode === "live" && accessToken.startsWith("duffel_test_")) ||
    (rawMode === "test" && accessToken.startsWith("duffel_live_"))
  ) {
    throw new DuffelProviderError({
      code: "invalid_configuration",
      message: "The flight provider mode does not match its access token.",
      status: 503,
    });
  }

  return { accessToken, mode: rawMode };
}

function validatedConfig(
  getConfig: () => DuffelClientConfig | null,
): DuffelClientConfig {
  ensureServerRuntime();
  const config = getConfig();
  if (!config) {
    throw new DuffelProviderError({
      code: "not_configured",
      message: "Live flight search is not configured.",
      status: 503,
    });
  }
  if (
    !config.accessToken.trim() ||
    (config.mode !== "test" && config.mode !== "live") ||
    (config.mode === "live" &&
      config.accessToken.startsWith("duffel_test_")) ||
    (config.mode === "test" &&
      config.accessToken.startsWith("duffel_live_"))
  ) {
    throw new DuffelProviderError({
      code: "invalid_configuration",
      message: "The flight provider configuration is invalid.",
      status: 503,
    });
  }
  return { accessToken: config.accessToken.trim(), mode: config.mode };
}

function validatedPath(path: string): string {
  if (
    !DUFFEL_PATH.test(path) ||
    path.includes("..") ||
    path.includes("//") ||
    path.includes("?") ||
    path.includes("#")
  ) {
    throw new DuffelProviderError({
      code: "invalid_request",
      message: "The flight provider request path is invalid.",
      status: 500,
    });
  }
  return path;
}

function requestUrl(
  path: string,
  query: DuffelRequestOptions["query"],
): URL {
  const url = new URL(validatedPath(path), DUFFEL_API_ORIGIN);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== null && value !== undefined) {
      url.searchParams.set(key, String(value));
    }
  }
  return url;
}

function boundedTimeout(value: number): number {
  if (!Number.isFinite(value) || value < 1 || value > MAX_TIMEOUT_MS) {
    throw new DuffelProviderError({
      code: "invalid_request",
      message: "The flight provider timeout is invalid.",
      status: 500,
    });
  }
  return Math.floor(value);
}

function providerErrorCode(status: number): {
  code: DuffelProviderErrorCode;
  status: number;
  message: string;
  retryable: boolean;
} {
  if (status === 401 || status === 403) {
    return {
      code: "authentication_failed",
      status: 503,
      message: "Flight search authentication is unavailable.",
      retryable: false,
    };
  }
  if (status === 429) {
    return {
      code: "rate_limited",
      status: 503,
      message: "Flight search is temporarily busy. Please try again shortly.",
      retryable: true,
    };
  }
  if (status >= 500) {
    return {
      code: "unavailable",
      status: 502,
      message: "The flight provider is temporarily unavailable.",
      retryable: true,
    };
  }
  return {
    code: "provider_rejected",
    status: 422,
    message: "The flight provider could not complete this request.",
    retryable: false,
  };
}

function providerRequestId(response: Response): string | null {
  const value =
    response.headers.get("x-request-id") ??
    response.headers.get("duffel-request-id");
  return value && value.length <= 200 ? value : null;
}

function apiEnvelope<T>(value: unknown): DuffelApiEnvelope<T> | null {
  if (typeof value !== "object" || value === null || !("data" in value)) {
    return null;
  }
  return value as DuffelApiEnvelope<T>;
}

function providerCodes(value: unknown): string[] {
  if (typeof value !== "object" || value === null) return [];
  const errors = (value as DuffelApiErrorEnvelope).errors;
  if (!Array.isArray(errors)) return [];
  return errors
    .map((error) =>
      error && typeof error.code === "string" ? error.code : null,
    )
    .filter((code): code is string => code !== null)
    .slice(0, 10);
}

export function createDuffelClient(options: DuffelClientOptions = {}) {
  const getConfig = options.getConfig ?? environmentConfig;
  const fetchImpl = options.fetchImpl ?? fetch;
  const defaultTimeoutMs = boundedTimeout(
    options.timeoutMs ?? DEFAULT_TIMEOUT_MS,
  );

  return {
    getMode(): DuffelMode | null {
      return getConfig()?.mode ?? null;
    },

    async request<T>(
      path: string,
      optionsForRequest: DuffelRequestOptions = {},
    ): Promise<DuffelResult<T>> {
      const config = validatedConfig(getConfig);
      const timeoutMs = boundedTimeout(
        optionsForRequest.timeoutMs ?? defaultTimeoutMs,
      );
      const url = requestUrl(path, optionsForRequest.query);
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort("timeout"), timeoutMs);
      const abortFromCaller = () => controller.abort("caller");
      optionsForRequest.signal?.addEventListener("abort", abortFromCaller, {
        once: true,
      });
      if (optionsForRequest.signal?.aborted) abortFromCaller();

      const headers: Record<string, string> = {
        Accept: "application/json",
        Authorization: `Bearer ${config.accessToken}`,
        "Duffel-Version": "v2",
        "User-Agent": "SkyETA/1.0",
      };
      let body: string | undefined;
      if (optionsForRequest.body !== undefined) {
        headers["Content-Type"] = "application/json";
        try {
          body = JSON.stringify(optionsForRequest.body);
        } catch {
          clearTimeout(timeout);
          optionsForRequest.signal?.removeEventListener(
            "abort",
            abortFromCaller,
          );
          throw new DuffelProviderError({
            code: "invalid_request",
            message: "The flight provider request body is invalid.",
            status: 500,
          });
        }
      }
      if (optionsForRequest.idempotencyKey) {
        if (!/^[A-Za-z0-9._:-]{1,255}$/.test(optionsForRequest.idempotencyKey)) {
          clearTimeout(timeout);
          optionsForRequest.signal?.removeEventListener(
            "abort",
            abortFromCaller,
          );
          throw new DuffelProviderError({
            code: "invalid_request",
            message: "The flight provider idempotency key is invalid.",
            status: 500,
          });
        }
        headers["Idempotency-Key"] = optionsForRequest.idempotencyKey;
      }

      let response: Response;
      try {
        response = await fetchImpl(url, {
          method: optionsForRequest.method ?? "GET",
          headers,
          body,
          signal: controller.signal,
          cache: "no-store",
        });
      } catch {
        const timedOut =
          controller.signal.aborted &&
          !optionsForRequest.signal?.aborted;
        throw new DuffelProviderError({
          code: timedOut ? "timeout" : "unavailable",
          message: timedOut
            ? "The flight provider timed out."
            : "The flight provider is unavailable.",
          status: timedOut ? 504 : 502,
          retryable: true,
        });
      } finally {
        clearTimeout(timeout);
        optionsForRequest.signal?.removeEventListener(
          "abort",
          abortFromCaller,
        );
      }

      const requestId = providerRequestId(response);
      let payload: unknown = null;
      try {
        payload = await response.json();
      } catch {
        // A valid Duffel response is always JSON; do not expose raw response text.
      }

      if (!response.ok) {
        const mapped = providerErrorCode(response.status);
        const error = new DuffelProviderError({
          ...mapped,
          providerStatus: response.status,
          requestId,
        });
        // Preserve machine-readable provider codes for server logs without
        // copying provider messages, tokens or passenger data into the error.
        if (providerCodes(payload).length > 0) {
          Object.defineProperty(error, "providerCodes", {
            value: providerCodes(payload),
            enumerable: false,
          });
        }
        throw error;
      }

      const envelope = apiEnvelope<T>(payload);
      if (!envelope) {
        throw new DuffelProviderError({
          code: "invalid_response",
          message: "The flight provider returned an invalid response.",
          status: 502,
          providerStatus: response.status,
          requestId,
          retryable: true,
        });
      }

      return {
        data: envelope.data,
        meta: envelope.meta,
        mode: config.mode,
        providerStatus: response.status,
        requestId,
      };
    },
  };
}
