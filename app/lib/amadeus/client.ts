import type { FlightProviderEnvironment } from "../../types/flight-booking.ts";
import {
  BodyTooLargeError,
  readBoundedJson,
} from "../http/bounded-json.ts";

const DEFAULT_TIMEOUT_MS = 25_000;
const MAX_TIMEOUT_MS = 45_000;
const MAX_RESPONSE_BYTES = 6_000_000;
const AMADEUS_PATH = /^\/v[12]\/[A-Za-z0-9_./-]+$/;

type FetchLike = (
  input: string | URL | Request,
  init?: RequestInit,
) => Promise<Response>;

export type AmadeusMode = FlightProviderEnvironment;

type AmadeusClientConfig = {
  apiKey: string;
  apiSecret: string;
  mode: AmadeusMode;
};

type AmadeusRequestOptions = {
  method?: "GET" | "POST";
  query?: Record<string, string | number | boolean | null | undefined>;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  timeoutMs?: number;
};

type AmadeusClientOptions = {
  getConfig?: () => AmadeusClientConfig | null;
  fetchImpl?: FetchLike;
  now?: () => number;
  timeoutMs?: number;
};

export type AmadeusResult<T> = {
  data: T;
  dictionaries?: unknown;
  included?: unknown;
  meta?: unknown;
  mode: AmadeusMode;
  providerStatus: number;
  requestId: string | null;
};

export type AmadeusProviderErrorCode =
  | "not_configured"
  | "invalid_configuration"
  | "invalid_request"
  | "timeout"
  | "unavailable"
  | "authentication_failed"
  | "rate_limited"
  | "provider_rejected"
  | "invalid_response";

export class AmadeusProviderError extends Error {
  readonly code: AmadeusProviderErrorCode;
  readonly status: number;
  readonly providerStatus: number | null;
  readonly requestId: string | null;
  readonly retryable: boolean;

  constructor(options: {
    code: AmadeusProviderErrorCode;
    message: string;
    status: number;
    providerStatus?: number | null;
    requestId?: string | null;
    retryable?: boolean;
  }) {
    super(options.message);
    this.name = "AmadeusProviderError";
    this.code = options.code;
    this.status = options.status;
    this.providerStatus = options.providerStatus ?? null;
    this.requestId = options.requestId ?? null;
    this.retryable = options.retryable ?? false;
  }
}

function ensureServerRuntime(): void {
  if (typeof window !== "undefined") {
    throw new AmadeusProviderError({
      code: "invalid_configuration",
      message: "The flight provider can only be used on the server.",
      status: 500,
    });
  }
}

function environmentConfig(): AmadeusClientConfig | null {
  ensureServerRuntime();
  const apiKey = process.env.AMADEUS_API_KEY?.trim();
  const apiSecret = process.env.AMADEUS_API_SECRET?.trim();
  const rawMode = process.env.AMADEUS_MODE?.trim().toLowerCase();

  if (!apiKey && !apiSecret && !rawMode) return null;
  if (!apiKey || !apiSecret || (rawMode !== "test" && rawMode !== "live")) {
    throw new AmadeusProviderError({
      code: "invalid_configuration",
      message: "The flight provider configuration is incomplete.",
      status: 503,
    });
  }
  return { apiKey, apiSecret, mode: rawMode };
}

function validatedConfig(
  getConfig: () => AmadeusClientConfig | null,
): AmadeusClientConfig {
  ensureServerRuntime();
  const config = getConfig();
  if (!config) {
    throw new AmadeusProviderError({
      code: "not_configured",
      message: "Live flight search is not configured.",
      status: 503,
    });
  }
  if (
    !config.apiKey.trim() ||
    !config.apiSecret.trim() ||
    (config.mode !== "test" && config.mode !== "live")
  ) {
    throw new AmadeusProviderError({
      code: "invalid_configuration",
      message: "The flight provider configuration is invalid.",
      status: 503,
    });
  }
  return {
    apiKey: config.apiKey.trim(),
    apiSecret: config.apiSecret.trim(),
    mode: config.mode,
  };
}

function originFor(mode: AmadeusMode): string {
  return mode === "live"
    ? "https://api.amadeus.com"
    : "https://test.api.amadeus.com";
}

function boundedTimeout(value: number): number {
  if (!Number.isFinite(value) || value < 1 || value > MAX_TIMEOUT_MS) {
    throw new AmadeusProviderError({
      code: "invalid_request",
      message: "The flight provider timeout is invalid.",
      status: 500,
    });
  }
  return Math.floor(value);
}

function requestUrl(
  origin: string,
  path: string,
  query: AmadeusRequestOptions["query"],
): URL {
  if (
    !AMADEUS_PATH.test(path) ||
    path.includes("..") ||
    path.includes("//") ||
    path.includes("?") ||
    path.includes("#")
  ) {
    throw new AmadeusProviderError({
      code: "invalid_request",
      message: "The flight provider request path is invalid.",
      status: 500,
    });
  }
  const url = new URL(path, origin);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== null && value !== undefined) {
      url.searchParams.set(key, String(value));
    }
  }
  return url;
}

function requestId(response: Response): string | null {
  const value =
    response.headers.get("ama-request-id") ??
    response.headers.get("x-request-id") ??
    response.headers.get("trace-id");
  return value && value.length <= 200 ? value : null;
}

function providerError(status: number) {
  if (status === 401 || status === 403) {
    return {
      code: "authentication_failed" as const,
      status: 503,
      message: "Flight search authentication is unavailable.",
      retryable: false,
    };
  }
  if (status === 429) {
    return {
      code: "rate_limited" as const,
      status: 503,
      message: "Flight search is temporarily busy. Please try again shortly.",
      retryable: true,
    };
  }
  if (status >= 500) {
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
    throw new AmadeusProviderError({
      code: "invalid_response",
      message: "The flight provider response is too large.",
      status: 502,
      providerStatus: response.status,
      requestId: requestId(response),
      retryable: true,
    });
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function createAmadeusClient(options: AmadeusClientOptions = {}) {
  const getConfig = options.getConfig ?? environmentConfig;
  const fetchImpl = options.fetchImpl ?? fetch;
  const now = options.now ?? Date.now;
  const defaultTimeoutMs = boundedTimeout(
    options.timeoutMs ?? DEFAULT_TIMEOUT_MS,
  );
  let cachedToken: {
    apiKey: string;
    mode: AmadeusMode;
    value: string;
    expiresAt: number;
  } | null = null;
  let tokenRequest: Promise<string> | null = null;

  async function accessToken(config: AmadeusClientConfig): Promise<string> {
    if (
      cachedToken &&
      cachedToken.apiKey === config.apiKey &&
      cachedToken.mode === config.mode &&
      cachedToken.expiresAt > now() + 60_000
    ) {
      return cachedToken.value;
    }
    if (tokenRequest) return tokenRequest;

    tokenRequest = (async () => {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort("timeout"), defaultTimeoutMs);
      let response!: Response;
      let payload: unknown;
      try {
        response = await fetchImpl(
          new URL("/v1/security/oauth2/token", originFor(config.mode)),
          {
            method: "POST",
            headers: {
              Accept: "application/json",
              "Content-Type": "application/x-www-form-urlencoded",
              "User-Agent": "SkyETA/1.0",
            },
            body: new URLSearchParams({
              grant_type: "client_credentials",
              client_id: config.apiKey,
              client_secret: config.apiSecret,
            }).toString(),
            signal: controller.signal,
            cache: "no-store",
            redirect: "error",
          },
        );
        payload = await safeJson(response);
        if (controller.signal.aborted) throw new Error("request_aborted");
      } catch (error) {
        if (error instanceof AmadeusProviderError) throw error;
        throw new AmadeusProviderError({
          code: controller.signal.aborted ? "timeout" : "unavailable",
          message: controller.signal.aborted
            ? "The flight provider timed out."
            : "The flight provider is unavailable.",
          status: controller.signal.aborted ? 504 : 502,
          retryable: true,
        });
      } finally {
        clearTimeout(timeout);
      }

      if (!response.ok) {
        const mapped = providerError(response.status);
        throw new AmadeusProviderError({
          ...mapped,
          providerStatus: response.status,
          requestId: requestId(response),
        });
      }
      if (!isRecord(payload)) {
        throw new AmadeusProviderError({
          code: "invalid_response",
          message: "The flight provider returned an invalid response.",
          status: 502,
          providerStatus: response.status,
          requestId: requestId(response),
          retryable: true,
        });
      }
      const value =
        typeof payload.access_token === "string" ? payload.access_token : "";
      const expiresIn =
        typeof payload.expires_in === "number" ? payload.expires_in : 0;
      if (!value || !Number.isFinite(expiresIn) || expiresIn <= 0) {
        throw new AmadeusProviderError({
          code: "invalid_response",
          message: "The flight provider returned an invalid response.",
          status: 502,
          providerStatus: response.status,
          requestId: requestId(response),
          retryable: true,
        });
      }
      cachedToken = {
        apiKey: config.apiKey,
        mode: config.mode,
        value,
        expiresAt: now() + Math.min(expiresIn, 1_800) * 1_000,
      };
      return value;
    })();

    try {
      return await tokenRequest;
    } finally {
      tokenRequest = null;
    }
  }

  return {
    getMode(): AmadeusMode | null {
      return getConfig()?.mode ?? null;
    },

    async request<T>(
      path: string,
      requestOptions: AmadeusRequestOptions = {},
    ): Promise<AmadeusResult<T>> {
      const config = validatedConfig(getConfig);
      const timeoutMs = boundedTimeout(
        requestOptions.timeoutMs ?? defaultTimeoutMs,
      );
      const url = requestUrl(
        originFor(config.mode),
        path,
        requestOptions.query,
      );
      const token = await accessToken(config);
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort("timeout"), timeoutMs);
      const abortFromCaller = () => controller.abort("caller");
      requestOptions.signal?.addEventListener("abort", abortFromCaller, {
        once: true,
      });
      if (requestOptions.signal?.aborted) abortFromCaller();

      const headers: Record<string, string> = {
        Accept: "application/json",
        Authorization: `Bearer ${token}`,
        "User-Agent": "SkyETA/1.0",
        ...requestOptions.headers,
      };
      let body: string | undefined;
      if (requestOptions.body !== undefined) {
        headers["Content-Type"] = "application/json";
        try {
          body = JSON.stringify(requestOptions.body);
        } catch {
          clearTimeout(timeout);
          throw new AmadeusProviderError({
            code: "invalid_request",
            message: "The flight provider request body is invalid.",
            status: 500,
          });
        }
      }

      let response!: Response;
      let payload: unknown;
      try {
        response = await fetchImpl(url, {
          method: requestOptions.method ?? "GET",
          headers,
          body,
          signal: controller.signal,
          cache: "no-store",
          redirect: "error",
        });
        payload = await safeJson(response);
        if (controller.signal.aborted) throw new Error("request_aborted");
      } catch (error) {
        if (error instanceof AmadeusProviderError) throw error;
        const timedOut =
          controller.signal.aborted && !requestOptions.signal?.aborted;
        throw new AmadeusProviderError({
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
        const mapped = providerError(response.status);
        throw new AmadeusProviderError({
          ...mapped,
          providerStatus: response.status,
          requestId: requestId(response),
        });
      }
      if (!isRecord(payload) || !("data" in payload)) {
        throw new AmadeusProviderError({
          code: "invalid_response",
          message: "The flight provider returned an invalid response.",
          status: 502,
          providerStatus: response.status,
          requestId: requestId(response),
          retryable: true,
        });
      }
      return {
        data: payload.data as T,
        dictionaries: payload.dictionaries,
        included: payload.included,
        meta: payload.meta,
        mode: config.mode,
        providerStatus: response.status,
        requestId: requestId(response),
      };
    },
  };
}
