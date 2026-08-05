"use client";

import { useCallback, useState } from "react";

import FlightSearchForm from "./FlightSearchForm";
import OfferResults, { type OfferResultsStatus } from "./OfferResults";
import type {
  FlightProviderMode,
  FlightSearchValues,
  SkyetaFlightOffer,
} from "./flight-ui-types";
import styles from "../booking.module.css";

type SearchSuccess = {
  ok: true;
  mode: "test" | "live";
  offers: SkyetaFlightOffer[];
};

type RefreshSuccess = {
  ok: true;
  mode: "test" | "live";
  offer: SkyetaFlightOffer;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function responseMessage(value: unknown, fallback: string): string {
  if (
    isRecord(value) &&
    isRecord(value.error) &&
    typeof value.error.message === "string"
  ) {
    return value.error.message;
  }
  return fallback;
}

function isMode(value: unknown): value is "test" | "live" {
  return value === "test" || value === "live";
}

function isSearchSuccess(value: unknown): value is SearchSuccess {
  return (
    isRecord(value) &&
    value.ok === true &&
    isMode(value.mode) &&
    Array.isArray(value.offers)
  );
}

function isRefreshSuccess(value: unknown): value is RefreshSuccess {
  return (
    isRecord(value) &&
    value.ok === true &&
    isMode(value.mode) &&
    isRecord(value.offer)
  );
}

export default function FlightSearchExperience({
  initialProviderMode,
}: {
  initialProviderMode: FlightProviderMode;
}) {
  const [providerMode, setProviderMode] =
    useState<FlightProviderMode>(initialProviderMode);
  const [offers, setOffers] = useState<SkyetaFlightOffer[]>([]);
  const [status, setStatus] = useState<OfferResultsStatus>("idle");
  const [errorMessage, setErrorMessage] = useState("");
  const [lastSearch, setLastSearch] = useState<FlightSearchValues | null>(null);
  const [selectedOfferId, setSelectedOfferId] = useState<string>();
  const [selectingOfferId, setSelectingOfferId] = useState<string>();
  const [fareMessage, setFareMessage] = useState("");

  const performSearch = useCallback(async (values: FlightSearchValues) => {
    setStatus("loading");
    setErrorMessage("");
    setFareMessage("");
    setLastSearch(values);
    setSelectedOfferId(undefined);

    try {
      const response = await fetch("/api/skyeta/offers/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          origin: values.origin,
          destination: values.destination,
          departureDate: values.departureDate,
          returnDate: values.returnDate ?? null,
          passengers: {
            adults: values.adults,
            children: values.children,
            infantsWithoutSeat: values.infants,
          },
          cabinClass: values.cabin,
        }),
      });
      const body: unknown = await response.json();
      if (!response.ok || !isSearchSuccess(body)) {
        throw new Error(
          responseMessage(body, "Flight search could not be completed."),
        );
      }

      setProviderMode(body.mode);
      setOffers(body.offers);
      setStatus("success");
    } catch (error) {
      setOffers([]);
      setStatus("error");
      setErrorMessage(
        error instanceof Error
          ? error.message
          : "Flight search could not be completed.",
      );
    }
  }, []);

  const recheckOffer = useCallback(async (offer: SkyetaFlightOffer) => {
    setSelectingOfferId(offer.id);
    setFareMessage("");
    try {
      const response = await fetch(
        `/api/skyeta/offers/${encodeURIComponent(offer.id)}/refresh`,
        { method: "POST" },
      );
      const body: unknown = await response.json();
      if (!response.ok || !isRefreshSuccess(body)) {
        throw new Error(
          responseMessage(body, "The latest fare could not be confirmed."),
        );
      }

      setProviderMode(body.mode);
      setSelectedOfferId(body.offer.id);
      setOffers((current) =>
        current.map((entry) => (entry.id === body.offer.id ? body.offer : entry)),
      );
      setFareMessage(
        "Latest provider quote confirmed. SkyETA compares fares and does not collect payment.",
      );
    } catch (error) {
      setFareMessage(
        error instanceof Error
          ? error.message
          : "The latest fare could not be confirmed.",
      );
    } finally {
      setSelectingOfferId(undefined);
    }
  }, []);

  return (
    <section className={styles.bookingExperience} aria-labelledby="flight-search-title">
      <div className={styles.experienceLead}>
        <p className={styles.kicker}>Provider itinerary search</p>
        <h2 id="flight-search-title">Compare fares with SkyETA delay insight.</h2>
        <p>
          Compare provider-backed schedules, total prices, stops, baggage and fare
          conditions. Recheck a fare for the latest provider quote. SkyETA does
          not collect payment or sell tickets.
        </p>
      </div>

      <div className={styles.experienceGrid}>
        <FlightSearchForm
          providerMode={providerMode}
          onSearch={performSearch}
          isSearching={status === "loading"}
        />
        <OfferResults
          providerMode={providerMode}
          offers={offers}
          status={status}
          onSelectOffer={recheckOffer}
          selectedOfferId={selectedOfferId}
          selectingOfferId={selectingOfferId}
          errorMessage={errorMessage}
          onRetry={lastSearch ? () => performSearch(lastSearch) : undefined}
        />
      </div>

      {fareMessage ? (
        <p className={styles.checkoutStatus} role="status">
          {fareMessage}
        </p>
      ) : null}
    </section>
  );
}
