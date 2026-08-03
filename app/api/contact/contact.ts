const RESEND_EMAILS_ENDPOINT = "https://api.resend.com/emails";
const DEFAULT_TIMEOUT_MS = 8_000;
const DEFAULT_RATE_LIMIT_WINDOW_MS = 15 * 60 * 1_000;
const DEFAULT_RATE_LIMIT_MAX = 5;
const MAX_BODY_BYTES = 16_000;
const MAX_RATE_LIMIT_ENTRIES = 1_000;

export const CONTACT_REASONS = [
  "job-opportunity",
  "project-contract",
  "technical-collaboration",
  "other",
] as const;

export type ContactReason = (typeof CONTACT_REASONS)[number];

export type ContactSubmission = {
  name: string;
  email: string;
  company: string;
  reason: ContactReason;
  message: string;
  website: string;
};

export type ContactProviderConfig = {
  apiKey: string;
  toEmail: string;
  fromEmail: string;
};

type FetchLike = (
  input: string | URL | Request,
  init?: RequestInit,
) => Promise<Response>;

type ContactHandlerOptions = {
  getProviderConfig?: () => ContactProviderConfig | null;
  fetchImpl?: FetchLike;
  now?: () => number;
  makeIdempotencyKey?: () => string;
  timeoutMs?: number;
  rateLimitWindowMs?: number;
  rateLimitMax?: number;
};

type ValidationResult =
  | { ok: true; submission: ContactSubmission }
  | { ok: false; fields: Record<string, string> };

type RateLimitEntry = {
  count: number;
  resetAt: number;
};

const REASON_LABELS: Record<ContactReason, string> = {
  "job-opportunity": "Job opportunity",
  "project-contract": "Project or contract",
  "technical-collaboration": "Technical collaboration",
  other: "Other enquiry",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requiredString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function singleLine(value: string): string {
  return value.replace(/[\u0000-\u001f\u007f]+/g, " ").replace(/\s+/g, " ").trim();
}

function messageText(value: string): string {
  return value
    .replace(/\u0000/g, "")
    .replace(/\r\n?/g, "\n")
    .replace(/[\t ]+\n/g, "\n")
    .trim();
}

function isEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value) && value.length <= 254;
}

export function validateContactSubmission(value: unknown): ValidationResult {
  if (!isRecord(value)) {
    return { ok: false, fields: { form: "Enter your contact details and message." } };
  }

  const name = singleLine(requiredString(value.name));
  const email = requiredString(value.email).toLowerCase();
  const company = singleLine(requiredString(value.company));
  const reason = requiredString(value.reason);
  const message = messageText(requiredString(value.message));
  const website = requiredString(value.website);
  const fields: Record<string, string> = {};

  if (name.length < 2 || name.length > 80) {
    fields.name = "Enter a name between 2 and 80 characters.";
  }
  if (!isEmail(email)) {
    fields.email = "Enter a valid email address.";
  }
  if (company.length > 120) {
    fields.company = "Keep the company name under 120 characters.";
  }
  if (!CONTACT_REASONS.includes(reason as ContactReason)) {
    fields.reason = "Choose what you would like to discuss.";
  }
  if (message.length < 20 || message.length > 2_000) {
    fields.message = "Enter a message between 20 and 2,000 characters.";
  }
  if (website.length > 0) {
    fields.form = "This submission could not be accepted.";
  }

  if (Object.keys(fields).length > 0) return { ok: false, fields };

  return {
    ok: true,
    submission: {
      name,
      email,
      company,
      reason: reason as ContactReason,
      message,
      website: "",
    },
  };
}

export function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => {
    const entities: Record<string, string> = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return entities[character];
  });
}

function reasonLabel(reason: ContactReason): string {
  return REASON_LABELS[reason];
}

export function buildResendPayload(
  submission: ContactSubmission,
  config: ContactProviderConfig,
) {
  const companyLine = submission.company || "Not provided";
  const topic = reasonLabel(submission.reason);
  const text = [
    "New portfolio enquiry",
    "",
    `Name: ${submission.name}`,
    `Email: ${submission.email}`,
    `Company: ${companyLine}`,
    `Reason: ${topic}`,
    "",
    "Message:",
    submission.message,
  ].join("\n");

  const htmlMessage = escapeHtml(submission.message).replace(/\n/g, "<br>");
  const html = [
    "<h1>New portfolio enquiry</h1>",
    `<p><strong>Name:</strong> ${escapeHtml(submission.name)}</p>`,
    `<p><strong>Email:</strong> ${escapeHtml(submission.email)}</p>`,
    `<p><strong>Company:</strong> ${escapeHtml(companyLine)}</p>`,
    `<p><strong>Reason:</strong> ${escapeHtml(topic)}</p>`,
    `<p><strong>Message:</strong><br>${htmlMessage}</p>`,
  ].join("");

  return {
    from: config.fromEmail,
    to: [config.toEmail],
    reply_to: submission.email,
    subject: `[Portfolio] ${topic} — ${submission.name}`,
    text,
    html,
  };
}

function environmentProviderConfig(): ContactProviderConfig | null {
  const apiKey = process.env.RESEND_API_KEY?.trim();
  const toEmail = process.env.CONTACT_TO_EMAIL?.trim();
  const fromEmail = process.env.CONTACT_FROM_EMAIL?.trim();
  const bracketedFrom = fromEmail?.match(/<([^<>]+)>$/)?.[1] ?? fromEmail;
  if (
    !apiKey ||
    !toEmail ||
    !fromEmail ||
    !isEmail(toEmail) ||
    !bracketedFrom ||
    !isEmail(bracketedFrom)
  ) {
    return null;
  }
  return { apiKey, toEmail, fromEmail };
}

function clientIdentifier(request: Request): string {
  const cloudflareIp = request.headers.get("cf-connecting-ip")?.trim();
  if (cloudflareIp) return cloudflareIp;

  const forwardedIp = request.headers
    .get("x-forwarded-for")
    ?.split(",")[0]
    ?.trim();
  if (forwardedIp) return forwardedIp;

  return request.headers.get("x-real-ip")?.trim() || "unknown";
}

function json(
  body: unknown,
  status: number,
  headers: Record<string, string> = {},
): Response {
  return Response.json(body, {
    status,
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "application/json; charset=utf-8",
      ...headers,
    },
  });
}

export function createContactHandler(options: ContactHandlerOptions = {}) {
  const getProviderConfig =
    options.getProviderConfig ?? environmentProviderConfig;
  const fetchImpl = options.fetchImpl ?? fetch;
  const now = options.now ?? Date.now;
  const makeIdempotencyKey =
    options.makeIdempotencyKey ?? (() => crypto.randomUUID());
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const rateLimitWindowMs =
    options.rateLimitWindowMs ?? DEFAULT_RATE_LIMIT_WINDOW_MS;
  const rateLimitMax = options.rateLimitMax ?? DEFAULT_RATE_LIMIT_MAX;
  const rateLimits = new Map<string, RateLimitEntry>();

  return async function POST(request: Request): Promise<Response> {
    const contentType = request.headers.get("content-type") ?? "";
    if (!contentType.toLowerCase().startsWith("application/json")) {
      return json(
        {
          ok: false,
          configured: Boolean(getProviderConfig()),
          error: {
            code: "unsupported_media_type",
            message: "Submit the contact form as JSON.",
          },
        },
        415,
      );
    }

    const contentLength = Number(request.headers.get("content-length") ?? 0);
    if (Number.isFinite(contentLength) && contentLength > MAX_BODY_BYTES) {
      return json(
        {
          ok: false,
          configured: Boolean(getProviderConfig()),
          error: {
            code: "payload_too_large",
            message: "The contact form is too large.",
          },
        },
        413,
      );
    }

    let value: unknown;
    try {
      value = await request.json();
    } catch {
      return json(
        {
          ok: false,
          configured: Boolean(getProviderConfig()),
          error: { code: "invalid_json", message: "The form data is invalid." },
        },
        400,
      );
    }

    const validation = validateContactSubmission(value);
    if (!validation.ok) {
      return json(
        {
          ok: false,
          configured: Boolean(getProviderConfig()),
          error: {
            code: "validation_error",
            message: "Check the highlighted fields and try again.",
            fields: validation.fields,
          },
        },
        400,
      );
    }

    const config = getProviderConfig();
    if (!config) {
      return json(
        {
          ok: false,
          configured: false,
          message:
            "Direct form delivery is not configured. Use the prepared email option instead.",
        },
        200,
      );
    }

    const currentTime = now();
    const identifier = clientIdentifier(request);
    let rateLimit = rateLimits.get(identifier);
    if (!rateLimit || rateLimit.resetAt <= currentTime) {
      if (rateLimits.size >= MAX_RATE_LIMIT_ENTRIES) {
        for (const [key, entry] of rateLimits) {
          if (entry.resetAt <= currentTime) rateLimits.delete(key);
        }
        if (rateLimits.size >= MAX_RATE_LIMIT_ENTRIES) {
          const oldestKey = rateLimits.keys().next().value;
          if (oldestKey !== undefined) rateLimits.delete(oldestKey);
        }
      }
      rateLimit = { count: 0, resetAt: currentTime + rateLimitWindowMs };
      rateLimits.set(identifier, rateLimit);
    }
    if (rateLimit.count >= rateLimitMax) {
      const retryAfterSeconds = Math.max(
        1,
        Math.ceil((rateLimit.resetAt - currentTime) / 1_000),
      );
      return json(
        {
          ok: false,
          configured: true,
          error: {
            code: "rate_limited",
            message: "Too many messages were submitted. Please try again later.",
          },
        },
        429,
        { "Retry-After": String(retryAfterSeconds) },
      );
    }
    rateLimit.count += 1;

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    let providerResponse: Response;
    try {
      providerResponse = await fetchImpl(RESEND_EMAILS_ENDPOINT, {
        method: "POST",
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${config.apiKey}`,
          "Content-Type": "application/json",
          "Idempotency-Key": `portfolio-contact-${makeIdempotencyKey()}`,
          "User-Agent": "Peters-Elijah-Portfolio/1.0",
        },
        body: JSON.stringify(buildResendPayload(validation.submission, config)),
        signal: controller.signal,
        cache: "no-store",
      });
    } catch {
      const timedOut = controller.signal.aborted;
      return json(
        {
          ok: false,
          configured: true,
          error: {
            code: timedOut ? "provider_timeout" : "provider_unavailable",
            message: timedOut
              ? "Message delivery timed out. Please use the prepared email option."
              : "Message delivery is unavailable. Please use the prepared email option.",
          },
        },
        timedOut ? 504 : 502,
      );
    } finally {
      clearTimeout(timeout);
    }

    let providerResult: unknown = null;
    try {
      providerResult = await providerResponse.json();
    } catch {
      // A successful Resend response must still contain its accepted email ID.
    }

    if (
      !providerResponse.ok ||
      !isRecord(providerResult) ||
      typeof providerResult.id !== "string" ||
      providerResult.id.length === 0
    ) {
      return json(
        {
          ok: false,
          configured: true,
          error: {
            code: "provider_error",
            message:
              "Message delivery could not be confirmed. Please use the prepared email option.",
          },
        },
        502,
      );
    }

    return json(
      {
        ok: true,
        configured: true,
        accepted: true,
        message:
          "Your message was accepted for delivery. Peters will reply to the email you provided.",
      },
      200,
    );
  };
}
