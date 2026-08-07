"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { ExternalBookingLink } from "../../types/flight-booking";
import FlightSearchForm from "./FlightSearchForm";
import OfferResults, { type OfferResultsStatus } from "./OfferResults";
import type {
  FlightProviderMode,
  FlightSearchValues,
  SkyetaFlightOffer,
} from "./flight-ui-types";
import { flightProviderLabel } from "./provider-label";
import styles from "../booking.module.css";

type SearchSuccess = {
  ok: true;
  mode: "test" | "live";
  provider: "duffel" | "amadeus" | "ignav";
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
    (value.provider === "duffel" ||
      value.provider === "amadeus" ||
      value.provider === "ignav") &&
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
  initialProviderName,
}: {
  initialProviderMode: FlightProviderMode;
  initialProviderName: "duffel" | "amadeus" | "ignav";
}) {
  const [providerMode, setProviderMode] =
    useState<FlightProviderMode>(initialProviderMode);
  const [providerName, setProviderName] = useState(initialProviderName);
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
  const searchSequence = useRef(0);
  const searchController = useRef<AbortController | null>(null);
  const refreshController = useRef<AbortController | null>(null);

  useEffect(
    () => () => {
      searchController.current?.abort("unmounted");
      refreshController.current?.abort("unmounted");
    },
    [],
  );

  const performSearch = useCallback(async (values: FlightSearchValues) => {
    const sequence = searchSequence.current + 1;
    searchSequence.current = sequence;
    refreshSequence.current += 1;
    searchController.current?.abort("replaced");
    refreshController.current?.abort("replaced");
    const controller = new AbortController();
    searchController.current = controller;
    const timeout = window.setTimeout(
      () => controller.abort("timeout"),
      40_000,
    );
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
        signal: controller.signal,
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
      if (sequence !== searchSequence.current) return;
      if (!response.ok || !isSearchSuccess(body)) {
        throw new Error(
          responseMessage(body, "Flight search could not be completed."),
        );
      }

      setProviderMode(body.mode);
      setProviderName(body.provider);
      setOffers(body.offers);
      setStatus("success");
    } catch (error) {
      if (sequence !== searchSequence.current) return;
      setOffers([]);
      setStatus("error");
      const abortReason = controller.signal.reason;
      setErrorMessage(
        abortReason === "timeout"
          ? "The flight provider took too long to respond. Check your connection and try again."
          : abortReason === "cancelled"
            ? "Search cancelled. Your journey details are still here when you are ready."
            : error instanceof Error
          ? error.message
          : "Flight search could not be completed.",
      );
    } finally {
      window.clearTimeout(timeout);
      if (searchController.current === controller) {
        searchController.current = null;
      }
    }
  }, []);

  const cancelSearch = useCallback(() => {
    searchController.current?.abort("cancelled");
  }, []);

  const recheckOffer = useCallback(async (offer: SkyetaFlightOffer) => {
    const sequence = refreshSequence.current + 1;
    refreshSequence.current = sequence;
    refreshController.current?.abort("replaced");
    const controller = new AbortController();
    refreshController.current = controller;
    const timeout = window.setTimeout(
      () => controller.abort("timeout"),
      40_000,
    );
    setSelectingOfferId(offer.id);
    setFareMessage("");
    setSelectedOfferId(undefined);
    setSelectedBookingLinks([]);
    try {
      const response = await fetch(
        `/api/skyeta/offers/${encodeURIComponent(offer.id)}/refresh`,
        { method: "POST", signal: controller.signal },
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
        controller.signal.reason === "timeout"
          ? "The latest fare check took too long. Please try this option again."
          : error instanceof Error
          ? error.message
          : "The latest fare could not be confirmed.",
      );
    } finally {
      window.clearTimeout(timeout);
      if (refreshController.current === controller) {
        refreshController.current = null;
      }
      if (sequence === refreshSequence.current) {
        setSelectingOfferId(undefined);
      }
    }
  }, []);

  return (
    <section className={styles.bookingExperience} aria-label="Find flights worldwide">
      <div className={styles.experienceGrid}>
        <FlightSearchForm
          providerMode={providerMode}
          providerName={flightProviderLabel(providerName)}
          onSearch={performSearch}
          onCancelSearch={cancelSearch}
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
          onCancel={status === "loading" ? cancelSearch : undefined}
          displayCurrency={lastSearch?.displayCurrency ?? "NGN"}
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
