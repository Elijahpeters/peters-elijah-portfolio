"use client";

import { useCallback, useRef, useState } from "react";

import type { ExternalBookingLink } from "../../types/flight-booking";
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
  bookingLinks?: ExternalBookingLink[];
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

function isBookingLink(value: unknown): value is ExternalBookingLink {
  return (
    isRecord(value) &&
    typeof value.providerName === "string" &&
    (value.providerType === "airline" || value.providerType === "third_party") &&
    typeof value.url === "string"
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
  const [selectedBookingLinks, setSelectedBookingLinks] = useState<
    ExternalBookingLink[]
  >([]);
  const refreshSequence = useRef(0);

  const performSearch = useCallback(async (values: FlightSearchValues) => {
    refreshSequence.current += 1;
    setStatus("loading");
    setErrorMessage("");
    setFareMessage("");
    setLastSearch(values);
    setSelectedOfferId(undefined);
    setSelectedBookingLinks([]);
    setSelectingOfferId(undefined);

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
    const sequence = refreshSequence.current + 1;
    refreshSequence.current = sequence;
    setSelectingOfferId(offer.id);
    setFareMessage("");
    setSelectedOfferId(undefined);
    setSelectedBookingLinks([]);
    try {
      const response = await fetch(
        `/api/skyeta/offers/${encodeURIComponent(offer.id)}/refresh`,
        { method: "POST" },
      );
      const body: unknown = await response.json();
      if (sequence !== refreshSequence.current) return;
      if (!response.ok || !isRefreshSuccess(body)) {
        throw new Error(
          responseMessage(body, "The latest fare could not be confirmed."),
        );
      }

      setProviderMode(body.mode);
      setSelectedOfferId(body.offer.id);
      const links = Array.isArray(body.bookingLinks)
        ? body.bookingLinks.filter(isBookingLink)
        : [];
      setSelectedBookingLinks(links);
      setOffers((current) =>
        current.map((entry) => (entry.id === body.offer.id ? body.offer : entry)),
      );
      setFareMessage(
        links.length
          ? "Latest fare checked. Continue with an airline or booking partner below; payment happens on their site."
          : "Latest fare checked, but no direct booking link is available for this option right now.",
      );
    } catch (error) {
      if (sequence !== refreshSequence.current) return;
      setSelectedOfferId(undefined);
      setSelectedBookingLinks([]);
      setFareMessage(
        error instanceof Error
          ? error.message
          : "The latest fare could not be confirmed.",
      );
    } finally {
      if (sequence === refreshSequence.current) {
        setSelectingOfferId(undefined);
      }
    }
  }, []);

  return (
    <section className={styles.bookingExperience} aria-labelledby="flight-search-title">
      <div className={styles.experienceLead}>
        <p className={styles.kicker}>Search domestic and international flights</p>
        <h2 id="flight-search-title">Where do you want to fly?</h2>
        <p>
          Search by city, airport name or code—Lagos, Abuja, London, LOS or LHR.
          Compare current provider fares and schedules; SkyETA will clearly show
          which additional insights are available for each itinerary.
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
          selectedBookingLinks={selectedBookingLinks}
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
