"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import styles from "../booking.module.css";

type PaymentState =
  | "confirming_payment"
  | "creating_booking"
  | "confirmed"
  | "manual_review"
  | "failed";

type BookingStatusResponse = {
  ok: true;
  state: PaymentState;
  bookingReference?: string;
  message: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStatusResponse(value: unknown): value is BookingStatusResponse {
  return (
    isRecord(value) &&
    value.ok === true &&
    typeof value.state === "string" &&
    typeof value.message === "string"
  );
}

export default function PaymentReturnExperience({
  reference,
}: {
  reference: string | null;
}) {
  const [result, setResult] = useState<BookingStatusResponse>();
  const [error, setError] = useState(reference ? "" : "The payment reference is missing.");

  useEffect(() => {
    if (!reference) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempts = 0;

    const check = async () => {
      attempts += 1;
      try {
        const response = await fetch(
          `/api/skyeta/bookings/status?reference=${encodeURIComponent(reference)}`,
          { cache: "no-store" },
        );
        const body: unknown = await response.json();
        if (!response.ok || !isStatusResponse(body)) {
          throw new Error("We could not confirm this payment yet.");
        }
        if (cancelled) return;
        setResult(body);
        setError("");
        if (
          (body.state === "confirming_payment" ||
            body.state === "creating_booking") &&
          attempts < 30
        ) {
          timer = setTimeout(check, 2_000);
        }
      } catch (caught) {
        if (cancelled) return;
        setError(caught instanceof Error ? caught.message : "We could not confirm this payment yet.");
        if (attempts < 30) timer = setTimeout(check, 2_000);
      }
    };

    void check();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [reference]);

  const confirmed = result?.state === "confirmed";
  const terminal =
    confirmed || result?.state === "manual_review" || result?.state === "failed";

  return (
    <section className={styles.paymentReturn} aria-live="polite">
      <span className={confirmed ? styles.returnSuccess : styles.returnPulse} aria-hidden="true">
        {confirmed ? "✓" : ""}
      </span>
      <p className={styles.kicker}>SkyETA secure checkout</p>
      <h1>{confirmed ? "Your flight is booked" : terminal ? "We are checking your booking" : "Confirming your payment"}</h1>
      <p>
        {(result?.message ?? error) ||
          "Please keep this page open while SkyETA confirms the airline booking."}
      </p>
      {result?.bookingReference ? (
        <div className={styles.bookingReference}>
          <span>Airline booking reference</span>
          <strong>{result.bookingReference}</strong>
        </div>
      ) : null}
      {error && !result ? <p className={styles.checkoutStatus}>{error}</p> : null}
      <div className={styles.returnActions}>
        <Link className={styles.primaryButton} href="/skyeta">
          Return to SkyETA
        </Link>
        {!terminal && reference ? <small>Confirmation can take up to a minute.</small> : null}
      </div>
    </section>
  );
}
