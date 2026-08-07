"use client";

import { useMemo, useState } from "react";

import type { ExternalBookingLink } from "../../types/flight-booking";
import { isoDurationMinutes } from "../../lib/flight-provider/duration";
import type {
  DisplayCurrency,
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
  onCancel?: () => void;
  displayCurrency: DisplayCurrency;
}

type SortMode = "best" | "cheapest" | "fastest";
type StopsFilter = "any" | "direct" | "one-or-fewer";
type DepartureFilter = "any" | "morning" | "afternoon" | "evening";

function durationMinutes(offer: SkyetaFlightOffer) {
  const minutes = offer.slices.reduce((total, slice) => {
    const supplied = isoDurationMinutes(slice.duration);
    if (supplied) return total + supplied;
    return (
      total +
      slice.segments.reduce(
        (segmentTotal, segment) =>
          segmentTotal + (isoDurationMinutes(segment.duration) ?? 0),
        0,
      )
    );
  }, 0);
  return minutes > 0 ? minutes : null;
}

function numericPrice(offer: SkyetaFlightOffer) {
  const value = Number(offer.total.amount);
  return Number.isFinite(value) ? value : Number.POSITIVE_INFINITY;
}

function firstDepartureHour(offer: SkyetaFlightOffer) {
  const value = offer.slices[0]?.segments[0]?.departingAt;
  const match = value?.match(/T(\d{2}):/);
  return match ? Number(match[1]) : null;
}

function matchesDeparture(offer: SkyetaFlightOffer, filter: DepartureFilter) {
  if (filter === "any") return true;
  const hour = firstDepartureHour(offer);
  if (hour === null) return false;
  if (filter === "morning") return hour >= 5 && hour < 12;
  if (filter === "afternoon") return hour >= 12 && hour < 18;
  return hour >= 18 || hour < 5;
}

function hasBaggage(offer: SkyetaFlightOffer) {
  const baggage = [
    ...offer.baggage,
    ...offer.slices.flatMap((slice) =>
      slice.segments.flatMap((segment) => segment.baggage),
    ),
  ];
  return baggage.some(
    (item) =>
      (item.quantity !== null && item.quantity > 0) ||
      (item.weightKilograms !== null && item.weightKilograms > 0),
  );
}

function airlineNames(offer: SkyetaFlightOffer) {
  return Array.from(
    new Set(
      offer.slices
        .flatMap((slice) => slice.segments)
        .map((segment) => segment.marketingCarrier.name)
        .filter(Boolean),
    ),
  );
}

function bestScore(
  offer: SkyetaFlightOffer,
  bounds: {
    minimumPrice: number;
    maximumPrice: number;
    minimumDuration: number;
    maximumDuration: number;
    comparablePrices: boolean;
  },
) {
  const normalize = (value: number, minimum: number, maximum: number) =>
    maximum > minimum ? (value - minimum) / (maximum - minimum) : 0;
  const offerPrice = numericPrice(offer);
  const priceScore = bounds.comparablePrices
    ? Number.isFinite(offerPrice)
      ? normalize(offerPrice, bounds.minimumPrice, bounds.maximumPrice)
      : 1
    : 0.5;
  const offerDuration = durationMinutes(offer);
  const durationScore =
    offerDuration === null
      ? 1
      : normalize(
          offerDuration,
          bounds.minimumDuration,
          bounds.maximumDuration,
        );
  const stopScore = Math.min(offer.connectionCount, 2) / 2;

  return priceScore * 0.5 + durationScore * 0.35 + stopScore * 0.15;
}

function maximumStopsOnOneLeg(offer: SkyetaFlightOffer): number {
  return Math.max(0, ...offer.slices.map((slice) => slice.connectionCount));
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
  onCancel,
  displayCurrency,
}: OfferResultsProps) {
  const [expandedResultKey, setExpandedResultKey] = useState<string>();
  const [sortMode, setSortMode] = useState<SortMode>("best");
  const [stopsFilter, setStopsFilter] = useState<StopsFilter>("any");
  const [airlineFilter, setAirlineFilter] = useState("any");
  const [departureFilter, setDepartureFilter] =
    useState<DepartureFilter>("any");
  const [baggageOnly, setBaggageOnly] = useState(false);
  const [maximumDuration, setMaximumDuration] = useState("any");

  const availableAirlines = useMemo(
    () =>
      Array.from(new Set(offers.flatMap(airlineNames))).sort((a, b) =>
        a.localeCompare(b),
      ),
    [offers],
  );
  const comparablePrices =
    new Set(offers.map((offer) => offer.total.currency)).size <= 1;
  const effectiveAirlineFilter = availableAirlines.includes(airlineFilter)
    ? airlineFilter
    : "any";

  const filteredOffers = useMemo(() => {
    const maximumMinutes =
      maximumDuration === "any" ? null : Number(maximumDuration) * 60;
    const filtered = offers.filter((offer) => {
      const maximumStops = maximumStopsOnOneLeg(offer);
      if (stopsFilter === "direct" && maximumStops !== 0) return false;
      if (stopsFilter === "one-or-fewer" && maximumStops > 1) {
        return false;
      }
      if (
        effectiveAirlineFilter !== "any" &&
        !airlineNames(offer).includes(effectiveAirlineFilter)
      ) {
        return false;
      }
      if (baggageOnly && !hasBaggage(offer)) return false;
      if (!matchesDeparture(offer, departureFilter)) return false;
      if (maximumMinutes !== null) {
        const duration = durationMinutes(offer);
        if (duration === null || duration > maximumMinutes) return false;
      }
      return true;
    });

    if (sortMode === "cheapest" && comparablePrices) {
      return [...filtered].sort((a, b) => numericPrice(a) - numericPrice(b));
    }
    if (sortMode === "fastest") {
      return [...filtered].sort(
        (a, b) =>
          (durationMinutes(a) ?? Number.POSITIVE_INFINITY) -
          (durationMinutes(b) ?? Number.POSITIVE_INFINITY),
      );
    }

    const finitePrices = filtered.map(numericPrice).filter(Number.isFinite);
    const durations = filtered
      .map(durationMinutes)
      .filter((value): value is number => value !== null);
    const bounds = {
      minimumPrice: finitePrices.length ? Math.min(...finitePrices) : 0,
      maximumPrice: finitePrices.length ? Math.max(...finitePrices) : 0,
      minimumDuration: durations.length ? Math.min(...durations) : 0,
      maximumDuration: durations.length ? Math.max(...durations) : 0,
      comparablePrices,
    };

    return [...filtered].sort(
      (a, b) => bestScore(a, bounds) - bestScore(b, bounds),
    );
  }, [
    baggageOnly,
    comparablePrices,
    departureFilter,
    effectiveAirlineFilter,
    maximumDuration,
    offers,
    sortMode,
    stopsFilter,
  ]);

  const resetFilters = () => {
    setStopsFilter("any");
    setAirlineFilter("any");
    setDepartureFilter("any");
    setBaggageOnly(false);
    setMaximumDuration("any");
  };

  if (providerMode === "unconfigured") {
    return (
      <section className={styles.resultsState} aria-labelledby="offers-heading">
        <ProviderModeBadge mode="unconfigured" />
        <h2 id="offers-heading">Flight search is being connected</h2>
        <p>
          Results remain unavailable until a flight provider is verified. Sample
          fares are never presented as current inventory.
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
        {onCancel ? (
          <button
            type="button"
            className={styles.secondaryButton}
            onClick={onCancel}
          >
            Cancel search
          </button>
        ) : null}
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
          <button
            type="button"
            className={styles.secondaryButton}
            onClick={onRetry}
          >
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
        <p>Enter a route, date and passengers to search current flights and prices.</p>
      </section>
    );
  }

  if (offers.length === 0) {
    return (
      <section className={styles.resultsState} aria-labelledby="offers-heading">
        <h2 id="offers-heading">No current fares matched this search</h2>
        <p>Try a nearby date or another airport.</p>
      </section>
    );
  }

  const resultKey = `${filteredOffers.length}:${filteredOffers[0]?.id ?? ""}:${filteredOffers.at(-1)?.id ?? ""}`;
  const isExpanded = expandedResultKey === resultKey;
  const visibleOffers = isExpanded ? filteredOffers : filteredOffers.slice(0, 8);

  return (
    <section className={styles.results} aria-labelledby="offers-heading">
      <div className={styles.resultsHeading}>
        <div>
          <p className={styles.kicker}>Available itineraries</p>
          <h2 id="offers-heading">
            {filteredOffers.length} of {offers.length} flight option
            {offers.length === 1 ? "" : "s"}
          </h2>
        </div>
        <ProviderModeBadge mode={providerMode} />
      </div>

      {providerMode === "test" ? (
        <p className={styles.modeNotice} role="status">
          These are clearly labelled provider test results, not current flights or
          prices.
        </p>
      ) : null}

      <div className={styles.resultsControls} aria-label="Sort and filter flights">
        <div className={styles.sortControls}>
          <span>Sort by</span>
          <div className={styles.sortButtons}>
            <button
              type="button"
              aria-pressed={sortMode === "best"}
              onClick={() => setSortMode("best")}
            >
              Best
            </button>
            <button
              type="button"
              aria-pressed={sortMode === "cheapest"}
              disabled={!comparablePrices}
              title={
                comparablePrices
                  ? undefined
                  : "Cheapest is unavailable when results use different currencies."
              }
              onClick={() => setSortMode("cheapest")}
            >
              Cheapest
            </button>
            <button
              type="button"
              aria-pressed={sortMode === "fastest"}
              onClick={() => setSortMode("fastest")}
            >
              Fastest
            </button>
          </div>
          <small>
            {sortMode === "best"
              ? "Best balances price, journey time and stops."
              : sortMode === "cheapest"
                ? "Lowest total provider price first."
                : "Shortest total journey first."}
          </small>
        </div>

        <div className={styles.filterGrid}>
          <label>
            <span>Stops</span>
            <select
              value={stopsFilter}
              onChange={(event) =>
                setStopsFilter(event.target.value as StopsFilter)
              }
            >
              <option value="any">Any stops</option>
              <option value="direct">Direct only</option>
              <option value="one-or-fewer">Up to 1 stop</option>
            </select>
          </label>

          <label>
            <span>Airline</span>
            <select
              value={effectiveAirlineFilter}
              onChange={(event) => setAirlineFilter(event.target.value)}
            >
              <option value="any">Any airline</option>
              {availableAirlines.map((airline) => (
                <option key={airline} value={airline}>
                  {airline}
                </option>
              ))}
            </select>
          </label>

          <label>
            <span>Departure</span>
            <select
              value={departureFilter}
              onChange={(event) =>
                setDepartureFilter(event.target.value as DepartureFilter)
              }
            >
              <option value="any">Any time</option>
              <option value="morning">Morning · 5 AM–12 PM</option>
              <option value="afternoon">Afternoon · 12–6 PM</option>
              <option value="evening">Evening · after 6 PM</option>
            </select>
          </label>

          <label>
            <span>Journey duration</span>
            <select
              value={maximumDuration}
              onChange={(event) => setMaximumDuration(event.target.value)}
            >
              <option value="any">Any duration</option>
              <option value="6">Up to 6 hours</option>
              <option value="12">Up to 12 hours</option>
              <option value="18">Up to 18 hours</option>
              <option value="24">Up to 24 hours</option>
            </select>
          </label>

          <label className={styles.checkboxFilter}>
            <input
              type="checkbox"
              checked={baggageOnly}
              onChange={(event) => setBaggageOnly(event.target.checked)}
            />
            <span>Fares with stated baggage</span>
          </label>

          <button
            type="button"
            className={styles.resetFilters}
            onClick={resetFilters}
          >
            Reset filters
          </button>
        </div>
      </div>

      {filteredOffers.length === 0 ? (
        <div className={styles.filteredEmpty} role="status">
          <strong>No flights match every selected filter.</strong>
          <span>Reset the filters or broaden one selection.</span>
          <button type="button" onClick={resetFilters}>
            Reset filters
          </button>
        </div>
      ) : (
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
              displayCurrency={displayCurrency}
            />
          ))}
        </div>
      )}

      {visibleOffers.length < filteredOffers.length ? (
        <button
          type="button"
          className={styles.secondaryButton}
          onClick={() => setExpandedResultKey(resultKey)}
        >
          Show {filteredOffers.length - visibleOffers.length} more options
        </button>
      ) : null}
    </section>
  );
}
