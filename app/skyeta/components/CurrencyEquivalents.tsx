"use client";

import { useCallback, useEffect, useState } from "react";

import type { Money } from "../../types/flight-booking";
import type { DisplayCurrency } from "./flight-ui-types";
import styles from "../booking.module.css";

const TARGET_CURRENCIES = ["USD", "GBP", "EUR"] as const;
type TargetCurrency = (typeof TARGET_CURRENCIES)[number];

type RatesPayload = {
  ok: true;
  base: "NGN";
  rates: Record<TargetCurrency, number>;
  asOf: string;
  stale: boolean;
  source: {
    name: string;
    url: string;
  };
};

type LoadState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; data: RatesPayload }
  | { status: "error" };

let sharedRatesRequest: Promise<RatesPayload> | null = null;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isRatesPayload(value: unknown): value is RatesPayload {
  if (
    !isRecord(value) ||
    value.ok !== true ||
    value.base !== "NGN" ||
    !isRecord(value.rates) ||
    typeof value.asOf !== "string" ||
    typeof value.stale !== "boolean" ||
    !isRecord(value.source) ||
    value.source.name !== "Central Bank of Nigeria via Frankfurter" ||
    value.source.url !== "https://frankfurter.dev/providers/cbn/"
  ) {
    return false;
  }
  const rates = value.rates;
  return TARGET_CURRENCIES.every(
    (currency) =>
      typeof rates[currency] === "number" &&
      Number.isFinite(rates[currency]) &&
      rates[currency] > 0,
  );
}

function requestRates(): Promise<RatesPayload> {
  sharedRatesRequest ??= fetch("/api/skyeta/currency-rates", {
    headers: { Accept: "application/json" },
  })
    .then(async (response) => {
      const body: unknown = await response.json();
      if (!response.ok || !isRatesPayload(body)) {
        throw new Error("Currency equivalents are unavailable.");
      }
      return body;
    })
    .catch((error) => {
      sharedRatesRequest = null;
      throw error;
    });
  return sharedRatesRequest;
}

function formatEquivalent(
  amount: string,
  rate: number,
  currency: TargetCurrency,
) {
  const converted = Number(amount) * rate;
  if (!Number.isFinite(converted)) return null;
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    currencyDisplay: "code",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(converted);
}

function formatRateDate(value: string) {
  const date = new Date(`${value}T00:00:00.000Z`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeZone: "UTC",
  }).format(date);
}

export default function CurrencyEquivalents({
  money,
  preferredCurrency,
}: {
  money: Money;
  preferredCurrency: DisplayCurrency;
}) {
  const [state, setState] = useState<LoadState>({ status: "idle" });
  const canConvert =
    money.currency === "NGN" && Number.isFinite(Number(money.amount));
  const preferredTarget: TargetCurrency | null =
    preferredCurrency === "NGN" ? null : preferredCurrency;

  const loadRates = useCallback(() => {
    setState({ status: "loading" });
    void requestRates().then(
      (data) => setState({ status: "ready", data }),
      () => setState({ status: "error" }),
    );
  }, []);

  useEffect(() => {
    if (!canConvert || !preferredTarget) return;

    let cancelled = false;
    void requestRates().then(
      (data) => {
        if (!cancelled) setState({ status: "ready", data });
      },
      () => {
        if (!cancelled) setState({ status: "error" });
      },
    );

    return () => {
      cancelled = true;
    };
  }, [canConvert, preferredTarget]);

  if (!canConvert) return null;

  const preferredEquivalent =
    preferredTarget && state.status === "ready"
      ? formatEquivalent(
          money.amount,
          state.data.rates[preferredTarget],
          preferredTarget,
        )
      : null;

  return (
    <div className={styles.currencyConversion}>
      {preferredTarget ? (
        <div className={styles.preferredCurrency} aria-live="polite">
          <span>Approximate total in {preferredTarget}</span>
          {preferredEquivalent ? (
            <strong>≈ {preferredEquivalent}</strong>
          ) : state.status === "error" ? (
            <small>Conversion unavailable; the NGN provider price is unchanged.</small>
          ) : (
            <small>Loading reference rate…</small>
          )}
        </div>
      ) : null}

      <details
        className={styles.currencyDisclosure}
        onToggle={(event) => {
          if (event.currentTarget.open && state.status === "idle") loadRates();
        }}
      >
        <summary>
          {preferredTarget ? "View all currency equivalents" : "View other currencies"}
        </summary>
        <div className={styles.currencyPanel} aria-live="polite">
          {state.status === "idle" || state.status === "loading" ? (
            <p className={styles.currencyStatus}>Loading reference rates…</p>
          ) : state.status === "error" ? (
            <div className={styles.currencyStatus}>
              <p>
                Currency equivalents are unavailable. The NGN fare above is
                unchanged.
              </p>
              <button type="button" onClick={loadRates}>
                Try again
              </button>
            </div>
          ) : (
            <>
              <dl className={styles.currencyGrid}>
                {TARGET_CURRENCIES.map((currency) => (
                  <div key={currency}>
                    <dt>{currency}</dt>
                    <dd>
                      ≈{" "}
                      {formatEquivalent(
                        money.amount,
                        state.data.rates[currency],
                        currency,
                      )}
                    </dd>
                  </div>
                ))}
              </dl>
              <p className={styles.currencyNote}>
                Indicative CBN reference rates via{" "}
                <a
                  href={state.data.source.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Frankfurter
                </a>
                , {formatRateDate(state.data.asOf)}
                {state.data.stale ? " (cached)" : ""}. For comparison only—the
                airline, booking partner or card provider sets the final amount
                charged.
              </p>
            </>
          )}
        </div>
      </details>
    </div>
  );
}
