"use client";

import { MouseEvent, useEffect, useId, useRef } from "react";

import type { Money } from "../../types/flight-booking";
import type { FlightProviderMode } from "./flight-ui-types";
import ProviderModeBadge from "./ProviderModeBadge";
import styles from "../booking.module.css";

export interface PriceChangeDialogProps {
  open: boolean;
  providerMode: FlightProviderMode;
  previousTotal: Money;
  currentTotal: Money;
  onAccept: () => void | Promise<void>;
  onCancel: () => void;
  isAccepting?: boolean;
}

function numericAmount(money: Money) {
  const amount = Number(money.amount);
  return Number.isFinite(amount) ? amount : null;
}

function formatMoney(money: Money) {
  const value = numericAmount(money);
  if (value === null) return `${money.currency} ${money.amount}`;
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: money.currency,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${money.currency} ${money.amount}`;
  }
}

export default function PriceChangeDialog({
  open,
  providerMode,
  previousTotal,
  currentTotal,
  onAccept,
  onCancel,
  isAccepting = false,
}: PriceChangeDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  const previous = numericAmount(previousTotal);
  const current = numericAmount(currentTotal);
  const sameCurrency = previousTotal.currency === currentTotal.currency;
  const direction =
    previous !== null && current !== null && sameCurrency
      ? current > previous
        ? "higher"
        : current < previous
          ? "lower"
          : "same"
      : "changed";
  const heading =
    direction === "higher"
      ? "The fare has increased"
      : direction === "lower"
        ? "Good news — the fare dropped"
        : direction === "same"
          ? "The fare is confirmed"
          : "The fare has changed";
  const canAccept = providerMode === "live" && !isAccepting;

  const handleBackdrop = (event: MouseEvent<HTMLDialogElement>) => {
    if (event.target === dialogRef.current) onCancel();
  };

  return (
    <dialog
      ref={dialogRef}
      className={styles.priceDialog}
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      onCancel={(event) => {
        event.preventDefault();
        onCancel();
      }}
      onClick={handleBackdrop}
    >
      <div className={styles.dialogCard}>
        <div className={styles.dialogHeading}>
          <div>
            <p className={styles.kicker}>Final price check</p>
            <h2 id={titleId}>{heading}</h2>
          </div>
          <ProviderModeBadge mode={providerMode} compact />
        </div>

        <p id={descriptionId} className={styles.dialogCopy}>
          Airlines can update a fare after search. Review the provider’s latest
          total before continuing.
        </p>

        <dl className={styles.priceComparison}>
          <div>
            <dt>Search price</dt>
            <dd>{formatMoney(previousTotal)}</dd>
          </div>
          <div className={styles.confirmedPrice}>
            <dt>Current confirmed price</dt>
            <dd>{formatMoney(currentTotal)}</dd>
          </div>
        </dl>

        {providerMode !== "live" ? (
          <p className={styles.modeNotice} role="status">
            This price is not from a live ticketing environment, so checkout is
            disabled.
          </p>
        ) : null}

        <div className={styles.dialogActions}>
          <button
            type="button"
            className={styles.secondaryButton}
            onClick={onCancel}
          >
            Go back
          </button>
          <button
            type="button"
            className={styles.primaryButton}
            disabled={!canAccept}
            onClick={onAccept}
          >
            {isAccepting ? "Securing fare…" : "Accept current fare"}
          </button>
        </div>
      </div>
    </dialog>
  );
}
