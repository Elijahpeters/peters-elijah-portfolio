"use client";

import { useState } from "react";

import type { ExternalBookingLink } from "../../types/flight-booking";
import type {
  FlightProviderMode,
  SkyetaFlightOffer,
} from "./flight-ui-types";
import OfferCard from "./OfferCard";
import ProviderModeBadge from "./ProviderModeBadge";
import styles from "../booking.module.css";

export type OfferResultsStatus = "idle" | "loading" | "success" | "error";

export interface OfferResultsProps {
  providerMode: FlightProviderMode;
  offers: SkyetaFlightOffer[];
  status: OfferResultsStatus;
  onSelectOffer: (offer: SkyetaFlightOffer) => void | Promise<void>;
  selectedOfferId?: string;
  selectingOfferId?: string;
  selectedBookingLinks?: ExternalBookingLink[];
  errorMessage?: string;
  onRetry?: () => void;
}

export default function OfferResults({
  providerMode,
  offers,
  status,
  onSelectOffer,
  selectedOfferId,
  selectingOfferId,
  selectedBookingLinks = [],
  errorMessage,
  onRetry,
}: OfferResultsProps) {
  const [expandedResultKey, setExpandedResultKey] = useState<string>();

  if (providerMode === "unconfigured") {
    return (
      <section className={styles.resultsState} aria-labelledby="offers-heading">
        <ProviderModeBadge mode="unconfigured" />
        <h2 id="offers-heading">Provider fare search is being connected</h2>
        <p>
          Results remain unavailable until a production flight provider is
          verified. No sample fares are shown as real inventory.
        </p>
      </section>
    );
  }

  if (status === "loading") {
    return (
      <section
        className={styles.resultsState}
        aria-labelledby="offers-heading"
        aria-live="polite"
        aria-busy="true"
      >
        <span className={styles.loadingMark} aria-hidden="true" />
        <h2 id="offers-heading">Checking current flight inventory</h2>
        <p>Comparing current schedules, prices, stops and baggage…</p>
      </section>
    );
  }

  if (status === "error") {
    return (
      <section
        className={`${styles.resultsState} ${styles.resultsError}`}
        aria-labelledby="offers-heading"
        role="alert"
      >
        <h2 id="offers-heading">Flight search could not be completed</h2>
        <p>{errorMessage || "The provider did not return a usable response."}</p>
        {onRetry ? (
          <button type="button" className={styles.secondaryButton} onClick={onRetry}>
            Try again
          </button>
        ) : null}
      </section>
    );
  }

  if (status === "idle") {
    return (
      <section className={styles.resultsState} aria-labelledby="offers-heading">
        <h2 id="offers-heading">Your available flights will appear here</h2>
        <p>Enter a route, date and passengers to start a provider-backed search.</p>
      </section>
    );
  }

  if (offers.length === 0) {
    return (
      <section className={styles.resultsState} aria-labelledby="offers-heading">
        <h2 id="offers-heading">No verified fares matched this search</h2>
        <p>Try a nearby date or airport. Unconfirmed or invented prices are not shown.</p>
      </section>
    );
  }

  const resultKey = `${offers.length}:${offers[0]?.id ?? ""}:${offers.at(-1)?.id ?? ""}`;
  const isExpanded = expandedResultKey === resultKey;
  const visibleOffers = isExpanded ? offers : offers.slice(0, 8);

  return (
    <section className={styles.results} aria-labelledby="offers-heading">
      <div className={styles.resultsHeading}>
        <div>
          <p className={styles.kicker}>Available itineraries</p>
          <h2 id="offers-heading">
            {offers.length} flight option{offers.length === 1 ? "" : "s"}
          </h2>
        </div>
        <ProviderModeBadge mode={providerMode} />
      </div>

      {providerMode === "test" ? (
        <p className={styles.modeNotice} role="status">
          These are clearly labelled provider test results, not real flights or
          prices.
        </p>
      ) : null}

      <div className={styles.offerList}>
        {visibleOffers.map((offer) => (
          <OfferCard
            key={offer.id}
            offer={offer}
            onSelect={onSelectOffer}
            isSelected={selectedOfferId === offer.id}
            isSelecting={selectingOfferId === offer.id}
            isSelectionLocked={Boolean(selectingOfferId)}
            bookingLinks={
              selectedOfferId === offer.id ? selectedBookingLinks : undefined
            }
          />
        ))}
      </div>

      {visibleOffers.length < offers.length ? (
        <button
          type="button"
          className={styles.secondaryButton}
          onClick={() => setExpandedResultKey(resultKey)}
        >
          Show {offers.length - visibleOffers.length} more options
        </button>
      ) : null}
    </section>
  );
}
