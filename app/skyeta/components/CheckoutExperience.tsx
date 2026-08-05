"use client";

import { useEffect, useState } from "react";

import PassengerDetailsForm, {
  type PassengerDetails,
} from "./PassengerDetailsForm";
import styles from "../booking.module.css";

type CheckoutData = {
  checkoutSessionId: string;
  total: { amount: string; currency: string };
  expiresAt: string | null;
  itinerary: {
    journeys: Array<{
      origin: string;
      destination: string;
      departureAt: string;
      arrivalAt: string;
      segmentCount: number;
      marketingCarriers: string[];
    }>;
    totalSegments: number;
    totalStops: number;
  };
  fare: {
    passengerTypes: PassengerDetails["type"][];
    identityDocumentsRequired: boolean;
    cabinClass: string | null;
    fareBrand: string | null;
  };
  risk: {
    coverage: "full" | "partial" | "unavailable";
    delayRiskPercent: number | null;
  };
  paymentConfigured: boolean;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function errorMessage(value: unknown, fallback: string): string {
  return isRecord(value) &&
    isRecord(value.error) &&
    typeof value.error.message === "string"
    ? value.error.message
    : fallback;
}

function formatMoney(total: CheckoutData["total"]) {
  const amount = Number(total.amount);
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: total.currency,
    }).format(amount);
  } catch {
    return `${total.currency} ${total.amount}`;
  }
}

export default function CheckoutExperience({ sessionId }: { sessionId: string }) {
  const [data, setData] = useState<CheckoutData>();
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const response = await fetch(
          `/api/skyeta/checkout/sessions/${encodeURIComponent(sessionId)}`,
          { cache: "no-store" },
        );
        const body: unknown = await response.json();
        if (!response.ok || !isRecord(body) || body.ok !== true) {
          throw new Error(errorMessage(body, "Checkout could not be loaded."));
        }
        if (!cancelled) setData(body as unknown as CheckoutData);
      } catch (error) {
        if (!cancelled) {
          setMessage(
            error instanceof Error ? error.message : "Checkout could not be loaded.",
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const beginPayment = async (passengers: PassengerDetails[]) => {
    setSubmitting(true);
    setMessage("");
    try {
      const response = await fetch("/api/skyeta/payments/checkout", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": `checkout-${crypto.randomUUID()}`,
        },
        body: JSON.stringify({ checkoutSessionId: sessionId, passengers }),
      });
      const body: unknown = await response.json();
      if (
        !response.ok ||
        !isRecord(body) ||
        body.ok !== true ||
        typeof body.checkoutUrl !== "string"
      ) {
        throw new Error(errorMessage(body, "Secure payment could not be started."));
      }
      const checkoutUrl = new URL(body.checkoutUrl);
      if (checkoutUrl.protocol !== "https:") {
        throw new Error("The secure payment link is invalid.");
      }
      window.location.assign(checkoutUrl.toString());
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Secure payment could not be started.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return <p className={styles.checkoutLoading}>Checking the latest fare…</p>;
  }
  if (!data) {
    return <p className={styles.checkoutStatus}>{message}</p>;
  }

  return (
    <div className={styles.checkoutLayout}>
      <aside className={styles.checkoutSummary}>
        <p className={styles.kicker}>Your itinerary</p>
        <h1>Review before payment</h1>
        <div className={styles.journeySummary}>
          {data.itinerary.journeys.map((journey, index) => (
            <div key={`${journey.origin}-${journey.destination}-${index}`}>
              <strong>
                {journey.origin} → {journey.destination}
              </strong>
              <span>{new Date(journey.departureAt).toLocaleString()}</span>
              <small>
                {journey.segmentCount === 1
                  ? "Direct"
                  : `${journey.segmentCount - 1} stop${journey.segmentCount > 2 ? "s" : ""}`}
              </small>
            </div>
          ))}
        </div>
        <dl className={styles.checkoutFacts}>
          <div>
            <dt>Confirmed total</dt>
            <dd>{formatMoney(data.total)}</dd>
          </div>
          <div>
            <dt>SkyETA</dt>
            <dd>
              {data.risk.delayRiskPercent === null
                ? "Not available for this route"
                : `${data.risk.delayRiskPercent}% delay risk`}
            </dd>
          </div>
          <div>
            <dt>Fare</dt>
            <dd>{[data.fare.cabinClass, data.fare.fareBrand].filter(Boolean).join(" · ") || "Standard"}</dd>
          </div>
        </dl>
        {data.expiresAt ? (
          <p className={styles.expiryNote}>
            This price is held until {new Date(data.expiresAt).toLocaleString()}.
          </p>
        ) : null}
      </aside>

      <div>
        {!data.paymentConfigured ? (
          <p className={styles.modeNotice} role="status">
            Secure payment and ticketing are not enabled yet. No passenger data
            will be submitted until the production payment account is verified.
          </p>
        ) : null}
        {message ? (
          <p className={styles.checkoutStatus} role="alert">
            {message}
          </p>
        ) : null}
        <PassengerDetailsForm
          passengerTypes={data.fare.passengerTypes}
          identityDocumentsRequired={data.fare.identityDocumentsRequired}
          onSubmit={beginPayment}
          disabled={!data.paymentConfigured}
          isSubmitting={submitting}
        />
      </div>
    </div>
  );
}
