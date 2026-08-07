"use client";

import type {
  ExternalBookingLink,
  FlightSegment,
  Money,
} from "../../types/flight-booking";
import { isoDurationMinutes } from "../../lib/flight-provider/duration";
import { flightDateParts } from "../../lib/flight-provider/display-time";
import type {
  DisplayCurrency,
  SkyetaFlightOffer,
} from "./flight-ui-types";
import { flightProviderLabel } from "./provider-label";
import CurrencyEquivalents from "./CurrencyEquivalents";
import FareConditions from "./FareConditions";
import JourneyIntelligence from "./JourneyIntelligence";
import ProviderModeBadge from "./ProviderModeBadge";
import SkyetaRiskBadge from "./SkyetaRiskBadge";
import styles from "../booking.module.css";

export interface OfferCardProps {
  offer: SkyetaFlightOffer;
  onSelect: (offer: SkyetaFlightOffer) => void | Promise<void>;
  displayCurrency: DisplayCurrency;
  isSelecting?: boolean;
  isSelectionLocked?: boolean;
  isSelected?: boolean;
  bookingLinks?: ExternalBookingLink[];
}

function formatMoney(money: Money) {
  const value = Number(money.amount);
  if (!Number.isFinite(value)) return `${money.currency} ${money.amount}`;
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: money.currency,
      currencyDisplay: "code",
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${money.currency} ${money.amount}`;
  }
}

function averageMoney(money: Money, passengerCount: number): Money | null {
  const value = Number(money.amount);
  if (!Number.isFinite(value) || passengerCount < 1) return null;
  return {
    amount: (value / passengerCount).toFixed(2),
    currency: money.currency,
  };
}

function minutesLabel(totalMinutes: number | null) {
  if (!totalMinutes || totalMinutes < 1) return null;
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return `${hours ? `${hours}h ` : ""}${minutes ? `${minutes}m` : ""}`.trim();
}

function durationLabel(duration: string | null, segments: FlightSegment[]) {
  const totalMinutes =
    isoDurationMinutes(duration) ||
    segments.reduce(
      (total, segment) => total + (isoDurationMinutes(segment.duration) ?? 0),
      0,
    );
  return minutesLabel(totalMinutes);
}

function elapsedMinutes(start: string | null, end: string | null) {
  if (!start || !end) return null;
  const startTime = Date.parse(start);
  const endTime = Date.parse(end);
  if (!Number.isFinite(startTime) || !Number.isFinite(endTime)) return null;
  const minutes = Math.round((endTime - startTime) / 60_000);
  return minutes > 0 ? minutes : null;
}

function connectionLayovers(segments: FlightSegment[]) {
  return segments.slice(0, -1).map((segment, index) => {
    const next = segments[index + 1];
    return {
      key: `${segment.id}:${next.id}`,
      airportCode:
        segment.destination.iataCode || next.origin.iataCode || "Connecting airport",
      duration: minutesLabel(
        elapsedMinutes(segment.arrivingAt, next.departingAt),
      ),
    };
  });
}

function checkedAtLabel(offer: SkyetaFlightOffer) {
  const value = offer.updatedAt || offer.createdAt;
  if (!value) return "Last-checked time not supplied by provider";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Last-checked time not supplied by provider";
  }
  return `Last checked ${new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date)}`;
}

function taxItemizationLabel(offer: SkyetaFlightOffer) {
  if (offer.tax) {
    return `Provider-reported tax component: ${formatMoney(offer.tax)}. Confirm the final breakdown before booking.`;
  }
  return "Taxes and fees were not itemized separately by the provider.";
}

export default function OfferCard({
  offer,
  onSelect,
  displayCurrency,
  isSelecting = false,
  isSelectionLocked = false,
  isSelected = false,
  bookingLinks,
}: OfferCardProps) {
  const segments = offer.slices.flatMap((slice) => slice.segments);
  const first = segments[0];
  const last = segments.at(-1);

  if (!first || !last) return null;

  const canRecheck = offer.source.isLive && offer.isBookable;
  const carrierNames =
    Array.from(
      new Set(
        segments
          .map((segment) => segment.marketingCarrier.name)
          .filter(Boolean),
      ),
    ).join(" + ") || offer.owner.name || "Airline not supplied";
  const providerName = flightProviderLabel(offer.source.provider);
  const perTraveler = averageMoney(offer.total, offer.passengerCount);
  const firstCabin = segments.find((segment) => segment.cabinName)?.cabinName;
  const firstFareBrand = segments.find(
    (segment) => segment.fareBrandName,
  )?.fareBrandName;
  const journeyIntelligenceKey = segments
    .map((segment) =>
      [
        segment.id,
        segment.marketingCarrier.iataCode,
        segment.marketingFlightNumber ?? "",
        segment.origin.iataCode,
        segment.destination.iataCode,
        segment.departingAt,
      ].join(":"),
    )
    .join("|");
  const journeyRouteLabel = offer.slices
    .map((slice, index) => {
      const sliceFirst = slice.segments[0];
      const sliceLast = slice.segments.at(-1);
      if (!sliceFirst || !sliceLast) return null;
      const route = `${sliceFirst.origin.iataCode} to ${sliceLast.destination.iataCode}`;
      return index === 0 ? route : `leg ${index + 1} ${route}`;
    })
    .filter((route): route is string => Boolean(route))
    .join(", ");

  return (
    <article
      className={`${styles.offerCard} ${isSelected ? styles.offerSelected : ""}`}
      aria-label={`${journeyRouteLabel || `${first.origin.iataCode} to ${last.destination.iataCode}`} with ${carrierNames}`}
    >
      <div className={styles.offerTopline}>
        <div className={styles.carrier}>
          <span className={styles.carrierMark} aria-hidden="true">
            {(first.marketingCarrier.iataCode || carrierNames)
              .slice(0, 2)
              .toUpperCase()}
          </span>
          <div>
            <strong>{carrierNames}</strong>
            <span>
              {segments
                .map((segment) =>
                  [
                    segment.marketingCarrier.iataCode,
                    segment.marketingFlightNumber,
                  ]
                    .filter(Boolean)
                    .join(""),
                )
                .filter(Boolean)
                .join(" / ") || "Flight number not supplied by provider"}
            </span>
          </div>
        </div>
        <div className={styles.providerIdentity}>
          <span>Price source</span>
          <strong>{providerName}</strong>
          <ProviderModeBadge mode={offer.source.environment} compact />
        </div>
      </div>

      <div className={styles.sliceList}>
        {offer.slices.map((slice, sliceIndex) => {
          const sliceFirst = slice.segments[0];
          const sliceLast = slice.segments.at(-1);
          if (!sliceFirst || !sliceLast) return null;

          const departure = flightDateParts(
            sliceFirst.departingAt,
            sliceFirst.origin.timeZone,
          );
          const arrival = flightDateParts(
            sliceLast.arrivingAt,
            sliceLast.destination.timeZone,
          );
          const duration = durationLabel(slice.duration, slice.segments);
          const layovers = connectionLayovers(slice.segments);
          const technicalStops = slice.segments.flatMap((segment) =>
            segment.stops.map((stop, stopIndex) => ({
              key: `${segment.id}:stop:${stop.id ?? stopIndex}`,
              airportCode: stop.airport.iataCode || "Technical stop",
              duration: minutesLabel(isoDurationMinutes(stop.duration)),
            })),
          );
          const legLabel =
            offer.slices.length === 1
              ? "Flight"
              : sliceIndex === 0
                ? "Outbound"
                : sliceIndex === 1
                  ? "Return"
                  : `Leg ${sliceIndex + 1}`;

          return (
            <div className={styles.slice} key={slice.id}>
              <p className={styles.sliceLabel}>{legLabel}</p>
              <div className={styles.itinerary}>
                <div className={styles.endpoint}>
                  <strong>{departure.time}</strong>
                  <span>{sliceFirst.origin.iataCode}</span>
                  <small>{departure.date}</small>
                </div>

                <div className={styles.journeyLine}>
                  <span>{duration || "Duration not supplied by provider"}</span>
                  <i aria-hidden="true" />
                  <strong>
                    {slice.connectionCount === 0
                      ? "Direct"
                      : `${slice.connectionCount} stop${
                          slice.connectionCount > 1 ? "s" : ""
                        }`}
                  </strong>
                </div>

                <div className={`${styles.endpoint} ${styles.endpointArrival}`}>
                  <strong>{arrival.time}</strong>
                  <span>{sliceLast.destination.iataCode}</span>
                  <small>{arrival.date}</small>
                </div>
              </div>

              <div className={styles.segmentDetails}>
                {slice.segments.map((segment) => (
                  <span key={segment.id}>
                    {segment.origin.iataCode} &rarr; {segment.destination.iataCode}
                    {segment.originTerminal
                      ? ` · Terminal ${segment.originTerminal}`
                      : ""}
                  </span>
                ))}
              </div>

              {layovers.length || technicalStops.length ? (
                <div className={styles.layoverList} aria-label={`${legLabel} stops`}>
                  {layovers.map((layover) => (
                    <span key={layover.key}>
                      Layover at <strong>{layover.airportCode}</strong> ·{" "}
                      {layover.duration || "duration not supplied"}
                    </span>
                  ))}
                  {technicalStops.map((stop) => (
                    <span key={stop.key}>
                      Technical stop at <strong>{stop.airportCode}</strong> ·{" "}
                      {stop.duration || "duration not supplied"}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>

      <div className={styles.offerMeta}>
        <SkyetaRiskBadge risk={offer.skyetaRisk} />
        {offer.source.isLive ? (
          <span className={styles.expiry}>
            Prices can change; confirm the latest total before continuing
          </span>
        ) : offer.expiresAt ? (
          <span className={styles.expiry}>
            Provider quote expires at {flightDateParts(offer.expiresAt).time}
          </span>
        ) : null}
      </div>

      <FareConditions
        conditions={offer.fareConditions}
        baggage={offer.baggage}
        cabinName={firstCabin}
        fareBrandName={firstFareBrand}
      />

      <JourneyIntelligence
        key={journeyIntelligenceKey}
        segments={segments}
        risk={offer.skyetaRisk}
      />

      <div className={styles.offerAction}>
        <div className={styles.price}>
          <span>
            Total for {offer.passengerCount} passenger
            {offer.passengerCount === 1 ? "" : "s"}
          </span>
          <strong>{formatMoney(offer.total)}</strong>
          {perTraveler ? (
            <small>
              {formatMoney(perTraveler)} average per traveler; actual traveler fares
              may differ
            </small>
          ) : null}
          <small>{taxItemizationLabel(offer)}</small>
          <small>{checkedAtLabel(offer)}</small>
          <CurrencyEquivalents
            money={offer.total}
            preferredCurrency={displayCurrency}
          />
        </div>
        <button
          type="button"
          className={styles.selectButton}
          disabled={!canRecheck || isSelectionLocked}
          onClick={() => onSelect(offer)}
        >
          {isSelecting
            ? "Checking latest price…"
            : canRecheck
              ? "Check latest price & booking sites"
              : offer.source.environment === "test"
                ? "Test fare · comparison only"
                : "Fare unavailable"}
        </button>
      </div>

      {isSelected && bookingLinks?.length ? (
        <div className={styles.bookingLinksPanel} aria-label="Booking providers">
          <div className={styles.bookingLinksHeading}>
            <div>
              <span>Continue on another site</span>
              <strong>Choose where to complete your booking</strong>
            </div>
            <small>SkyETA never receives your card details.</small>
          </div>
          <p className={styles.bookingResponsibility}>
            You will leave SkyETA. The airline or booking partner you choose handles
            payment, ticketing, changes, refunds and support. No affiliate payment is
            currently configured for this handoff.
          </p>
          <div className={styles.bookingLinksList}>
            {bookingLinks.map((link) => (
              <a
                key={link.url}
                className={styles.bookingLink}
                href={link.url}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={`Continue to ${link.providerName} in a new tab`}
              >
                <span>
                  <strong>{link.providerName}</strong>
                  <small>
                    {link.providerType === "airline"
                      ? "Airline website"
                      : "Booking partner"}
                    {link.fareName ? ` · ${link.fareName}` : ""}
                  </small>
                </span>
                <span className={styles.bookingLinkPrice}>
                  {link.price ? formatMoney(link.price) : "View current price"}
                  <b aria-hidden="true">↗</b>
                </span>
              </a>
            ))}
          </div>
        </div>
      ) : null}
    </article>
  );
}
