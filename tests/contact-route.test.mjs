import assert from "node:assert/strict";
import test from "node:test";

import {
  buildResendPayload,
  createContactHandler,
  escapeHtml,
  validateContactSubmission,
} from "../app/api/contact/contact.ts";

const validSubmission = {
  name: "Ada Recruiter",
  email: "ada@example.com",
  company: "Example Engineering",
  reason: "job-opportunity",
  message: "I would like to discuss an electronics engineering role with you.",
  website: "",
};

const providerConfig = {
  apiKey: "server-only-resend-key",
  toEmail: "peters@example.com",
  fromEmail: "Portfolio <contact@example.com>",
};

function contactRequest(body, headers = {}) {
  return new Request("https://portfolio.test/api/contact", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "CF-Connecting-IP": "203.0.113.10",
      ...headers,
    },
    body: JSON.stringify(body),
  });
}

test("contact validation rejects incomplete input and the honeypot", () => {
  const invalid = validateContactSubmission({
    ...validSubmission,
    name: "A",
    email: "not-an-email",
    reason: "sales",
    message: "Too short",
    website: "https://spam.example",
  });

  assert.equal(invalid.ok, false);
  assert.deepEqual(Object.keys(invalid.fields).sort(), [
    "email",
    "form",
    "message",
    "name",
    "reason",
  ]);
});

test("unconfigured contact delivery returns an honest fallback and never fetches", async () => {
  let fetchCount = 0;
  const handler = createContactHandler({
    getProviderConfig: () => null,
    fetchImpl: async () => {
      fetchCount += 1;
      throw new Error("fetch must not run");
    },
  });

  const response = await handler(contactRequest(validSubmission));
  const body = await response.json();

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.deepEqual(body, {
    ok: false,
    configured: false,
    message:
      "Direct form delivery is not configured. Use the prepared email option instead.",
  });
  assert.equal(fetchCount, 0);
});

test("configured delivery sends a minimal escaped Resend request", async () => {
  let requestedUrl;
  let requestedInit;
  const handler = createContactHandler({
    getProviderConfig: () => providerConfig,
    makeIdempotencyKey: () => "fixed-id",
    fetchImpl: async (input, init) => {
      requestedUrl = String(input);
      requestedInit = init;
      return Response.json({ id: "email_123" }, { status: 200 });
    },
  });

  const submission = {
    ...validSubmission,
    name: "Ada <Recruiter>",
    message: "Hello <script>alert('x')</script>\nCan we discuss this role?",
  };
  const response = await handler(contactRequest(submission));
  const body = await response.json();
  const providerBody = JSON.parse(requestedInit.body);

  assert.equal(response.status, 200);
  assert.deepEqual(body, {
    ok: true,
    configured: true,
    accepted: true,
    message:
      "Your message was accepted for delivery. Peters will reply to the email you provided.",
  });
  assert.equal(requestedUrl, "https://api.resend.com/emails");
  assert.equal(requestedInit.method, "POST");
  assert.equal(requestedInit.headers.Authorization, "Bearer server-only-resend-key");
  assert.equal(requestedInit.headers["User-Agent"], "Peters-Elijah-Portfolio/1.0");
  assert.equal(requestedInit.headers["Idempotency-Key"], "portfolio-contact-fixed-id");
  assert.equal(providerBody.reply_to, "ada@example.com");
  assert.deepEqual(providerBody.to, ["peters@example.com"]);
  assert.match(providerBody.html, /Ada &lt;Recruiter&gt;/);
  assert.match(providerBody.html, /&lt;script&gt;alert\(&#39;x&#39;\)&lt;\/script&gt;/);
  assert.doesNotMatch(providerBody.html, /<script>/);
  assert.doesNotMatch(JSON.stringify(body), /server-only-resend-key/);
});

test("provider failures stay generic and never produce delivery success", async () => {
  const handler = createContactHandler({
    getProviderConfig: () => providerConfig,
    fetchImpl: async () =>
      Response.json(
        { message: "secret provider detail", api_key: providerConfig.apiKey },
        { status: 403 },
      ),
  });

  const response = await handler(contactRequest(validSubmission));
  const responseText = await response.text();
  const body = JSON.parse(responseText);

  assert.equal(response.status, 502);
  assert.equal(body.ok, false);
  assert.equal(body.configured, true);
  assert.equal(body.error.code, "provider_error");
  assert.equal(body.accepted, undefined);
  assert.doesNotMatch(responseText, /secret provider detail|server-only-resend-key/);
});

test("best-effort limiter bounds configured delivery attempts per client", async () => {
  let fetchCount = 0;
  const handler = createContactHandler({
    getProviderConfig: () => providerConfig,
    rateLimitMax: 1,
    now: () => 1_000,
    fetchImpl: async () => {
      fetchCount += 1;
      return Response.json({ id: "email_123" });
    },
  });

  assert.equal((await handler(contactRequest(validSubmission))).status, 200);
  const limited = await handler(contactRequest(validSubmission));
  const body = await limited.json();

  assert.equal(limited.status, 429);
  assert.equal(limited.headers.get("retry-after"), "900");
  assert.equal(body.error.code, "rate_limited");
  assert.equal(fetchCount, 1);
});

test("HTML escaping covers every email markup metacharacter", () => {
  assert.equal(escapeHtml(`&<>"'`), "&amp;&lt;&gt;&quot;&#39;");
  const payload = buildResendPayload(validSubmission, providerConfig);
  assert.equal(payload.reply_to, validSubmission.email);
  assert.match(payload.text, /New portfolio enquiry/);
});
