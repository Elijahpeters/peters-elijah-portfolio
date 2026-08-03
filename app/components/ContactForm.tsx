"use client";

import { useMemo, useState, type FormEvent } from "react";

const CONTACT_EMAIL = "peterselijah11@gmail.com";

const REASONS = [
  { value: "job-opportunity", label: "Job opportunity" },
  { value: "project-contract", label: "Project or contract" },
  { value: "technical-collaboration", label: "Technical collaboration" },
  { value: "other", label: "Other enquiry" },
] as const;

type FormValues = {
  name: string;
  email: string;
  company: string;
  reason: string;
  message: string;
  website: string;
};

type FieldErrors = Partial<Record<keyof FormValues | "form", string>>;

type SubmissionState =
  | { kind: "idle" }
  | { kind: "sending" }
  | { kind: "validation"; message: string }
  | { kind: "success"; message: string }
  | { kind: "fallback"; message: string }
  | { kind: "error"; message: string };

type ContactResponse = {
  ok?: boolean;
  configured?: boolean;
  accepted?: boolean;
  message?: string;
  error?: {
    message?: string;
    fields?: FieldErrors;
  };
};

const INITIAL_VALUES: FormValues = {
  name: "",
  email: "",
  company: "",
  reason: "",
  message: "",
  website: "",
};

function validate(values: FormValues): FieldErrors {
  const errors: FieldErrors = {};
  const name = values.name.trim();
  const email = values.email.trim();
  const company = values.company.trim();
  const message = values.message.trim();

  if (name.length < 2 || name.length > 80) {
    errors.name = "Enter a name between 2 and 80 characters.";
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || email.length > 254) {
    errors.email = "Enter a valid email address.";
  }
  if (company.length > 120) {
    errors.company = "Keep the company name under 120 characters.";
  }
  if (!REASONS.some((reason) => reason.value === values.reason)) {
    errors.reason = "Choose what you would like to discuss.";
  }
  if (message.length < 20 || message.length > 2_000) {
    errors.message = "Enter a message between 20 and 2,000 characters.";
  }

  return errors;
}

function preparedEmailHref(values: FormValues): string {
  const selectedReason = REASONS.find(
    (reason) => reason.value === values.reason,
  );
  const subject = selectedReason
    ? `Portfolio enquiry — ${selectedReason.label}`
    : "Portfolio enquiry";
  const body = [
    values.name.trim() ? `Name: ${values.name.trim()}` : "",
    values.email.trim() ? `Email: ${values.email.trim()}` : "",
    values.company.trim() ? `Company: ${values.company.trim()}` : "",
    "",
    values.message.trim(),
  ]
    .filter((line, index, lines) => line || (index > 0 && index < lines.length - 1))
    .join("\n");

  return `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

export default function ContactForm() {
  const [values, setValues] = useState<FormValues>(INITIAL_VALUES);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [submission, setSubmission] = useState<SubmissionState>({ kind: "idle" });
  const mailtoHref = useMemo(() => preparedEmailHref(values), [values]);
  const isSending = submission.kind === "sending";
  const showFallback = submission.kind === "fallback" || submission.kind === "error";

  function updateField(field: keyof FormValues, value: string) {
    setValues((current) => ({ ...current, [field]: value }));
    setErrors((current) => {
      if (!current[field] && !current.form) return current;
      const next = { ...current };
      delete next[field];
      delete next.form;
      return next;
    });
    if (submission.kind !== "idle") setSubmission({ kind: "idle" });
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const clientErrors = validate(values);
    if (Object.keys(clientErrors).length > 0) {
      setErrors(clientErrors);
      setSubmission({
        kind: "validation",
        message: "Check the highlighted fields and try again.",
      });
      return;
    }

    setErrors({});
    setSubmission({ kind: "sending" });

    try {
      const response = await fetch("/api/contact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      const result = (await response.json()) as ContactResponse;

      if (response.ok && result.ok && result.accepted) {
        setSubmission({
          kind: "success",
          message: result.message || "Your message was accepted for delivery.",
        });
        setValues(INITIAL_VALUES);
        return;
      }

      if (result.error?.fields) {
        setErrors(result.error.fields);
        setSubmission({
          kind: "validation",
          message:
            result.error.message || "Check the highlighted fields and try again.",
        });
        return;
      }
      const message =
        result.message ||
        result.error?.message ||
        "Message delivery could not be confirmed. Please use the prepared email option.";
      setSubmission({
        kind: result.configured === false ? "fallback" : "error",
        message,
      });
    } catch {
      setSubmission({
        kind: "error",
        message:
          "The form could not connect. You can still send the same details with the prepared email option.",
      });
    }
  }

  return (
    <div className="contact-form-shell">
      <form
        className="contact-form"
        onSubmit={handleSubmit}
        noValidate
        aria-busy={isSending}
      >
        <div className="contact-form__grid">
          <div className="contact-form__field">
            <label htmlFor="contact-name">Name</label>
            <input
              id="contact-name"
              name="name"
              type="text"
              autoComplete="name"
              value={values.name}
              onChange={(event) => updateField("name", event.target.value)}
              aria-invalid={Boolean(errors.name)}
              aria-describedby={errors.name ? "contact-name-error" : undefined}
              maxLength={80}
              required
            />
            {errors.name ? (
              <span className="contact-form__error" id="contact-name-error">
                {errors.name}
              </span>
            ) : null}
          </div>

          <div className="contact-form__field">
            <label htmlFor="contact-email">Email</label>
            <input
              id="contact-email"
              name="email"
              type="email"
              inputMode="email"
              autoComplete="email"
              value={values.email}
              onChange={(event) => updateField("email", event.target.value)}
              aria-invalid={Boolean(errors.email)}
              aria-describedby={errors.email ? "contact-email-error" : undefined}
              maxLength={254}
              required
            />
            {errors.email ? (
              <span className="contact-form__error" id="contact-email-error">
                {errors.email}
              </span>
            ) : null}
          </div>

          <div className="contact-form__field">
            <label htmlFor="contact-company">
              Company <span className="contact-form__optional">Optional</span>
            </label>
            <input
              id="contact-company"
              name="company"
              type="text"
              autoComplete="organization"
              value={values.company}
              onChange={(event) => updateField("company", event.target.value)}
              aria-invalid={Boolean(errors.company)}
              aria-describedby={errors.company ? "contact-company-error" : undefined}
              maxLength={120}
            />
            {errors.company ? (
              <span className="contact-form__error" id="contact-company-error">
                {errors.company}
              </span>
            ) : null}
          </div>

          <div className="contact-form__field">
            <label htmlFor="contact-reason">Reason for reaching out</label>
            <select
              id="contact-reason"
              name="reason"
              value={values.reason}
              onChange={(event) => updateField("reason", event.target.value)}
              aria-invalid={Boolean(errors.reason)}
              aria-describedby={errors.reason ? "contact-reason-error" : undefined}
              required
            >
              <option value="">Select one</option>
              {REASONS.map((reason) => (
                <option key={reason.value} value={reason.value}>
                  {reason.label}
                </option>
              ))}
            </select>
            {errors.reason ? (
              <span className="contact-form__error" id="contact-reason-error">
                {errors.reason}
              </span>
            ) : null}
          </div>

          <div className="contact-form__field contact-form__field--message">
            <label htmlFor="contact-message">Message</label>
            <textarea
              id="contact-message"
              name="message"
              rows={6}
              value={values.message}
              onChange={(event) => updateField("message", event.target.value)}
              aria-invalid={Boolean(errors.message)}
              aria-describedby={
                errors.message
                  ? "contact-message-hint contact-message-error"
                  : "contact-message-hint"
              }
              minLength={20}
              maxLength={2_000}
              required
            />
            <span className="contact-form__hint" id="contact-message-hint">
              Include the role, project or problem you would like to discuss.
            </span>
            {errors.message ? (
              <span className="contact-form__error" id="contact-message-error">
                {errors.message}
              </span>
            ) : null}
          </div>
        </div>

        <div
          className="contact-form__honeypot"
          aria-hidden="true"
          style={{ position: "absolute", left: "-10000px", width: "1px", height: "1px", overflow: "hidden" }}
        >
          <label htmlFor="contact-website">Website</label>
          <input
            id="contact-website"
            name="website"
            type="text"
            autoComplete="off"
            tabIndex={-1}
            value={values.website}
            onChange={(event) => updateField("website", event.target.value)}
          />
        </div>

        <div className="contact-form__footer">
          <button type="submit" disabled={isSending}>
            {isSending ? "Sending…" : "Send enquiry"}
          </button>
          <p className="contact-form__privacy">
            Your details are used only to reply to this enquiry.
          </p>
        </div>

        {errors.form ? (
          <p className="contact-form__status contact-form__status--error" role="alert">
            {errors.form}
          </p>
        ) : null}

        {submission.kind !== "idle" && submission.kind !== "sending" ? (
          <div
            className={`contact-form__status contact-form__status--${submission.kind}`}
            role={submission.kind === "success" ? "status" : "alert"}
            aria-live="polite"
          >
            <p>{submission.message}</p>
            {showFallback ? (
              <a href={mailtoHref}>Open prepared email ↗</a>
            ) : null}
          </div>
        ) : null}
      </form>

      <p className="contact-form__direct">
        Prefer email? <a href={mailtoHref}>{CONTACT_EMAIL}</a>
      </p>
    </div>
  );
}
