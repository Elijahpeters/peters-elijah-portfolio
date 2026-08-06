"use client";

import type { FlightSegment, Money } from "../../types/flight-booking";
import type { SkyetaFlightOffer } from "./flight-ui-types";
import { isoDurationMinutes } from "../../lib/flight-provider/duration";
import { flightDateParts } from "../../lib/flight-provider/display-time";
import FareConditions from "./FareConditions";
import ProviderModeBadge from "./ProviderModeBadge";
import SkyetaRiskBadge from "./SkyetaRiskBadge";
import styles from "../booking.module.css";

export interface OfferCardProps {
  offer: SkyetaFlightOffer;
  onSelect: (offer: SkyetaFlightOffer) => void | Promise<void>;
  isSelecting?: boolean;
  isSelected?: boolean;
}

function formatMoney(money: Money) {
  const value = Number(money.amount);
  if (!Number.isFinite(value)) return `${money.currency} ${money.amount}`;
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

function durationLabel(duration: string | null, segments: FlightSegment[]) {
  const totalMinutes =
    isoDurationMinutes(duration) ||
    segments.reduce(
      (total, segment) => total + (isoDurationMinutes(segment.duration) ?? 0),
      0,
    );
  if (!totalMinutes) return null;
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return `${hours ? `${hours}h ` : ""}${minutes ? `${minutes}m` : ""}`.trim();
}

export default function OfferCard({
  offer,
  onSelect,
  isSelecting = false,
  isSelected = false,
}: OfferCardProps) {
  const segments = offer.slices.flatMap((slice) => slice.segments);
  const first = segments[0];
  const last = segments.at(-1);

  if (!first || !last) return null;

  const canRecheck = offer.source.isLive && offer.isBookable;
  const carrierNames = Array.from(
    new Set(segments.map((segment) => segment.marketingCarrier.name)),
  ).join(" + ");
  const firstCabin = segments.find((segment) => segment.cabinName)?.cabinName;
  const firstFareBrand = segments.find(
    (segment) => segment.fareBrandName,
  )?.fareBrandName;

  return (
    <article
      className={`${styles.offerCard} ${isSelected ? styles.offerSelected : ""}`}
      aria-label={`${first.origin.iataCode} to ${last.destination.iataCode} with ${carrierNames}`}
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
        <ProviderModeBadge mode={offer.source.environment} compact />
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
                      ? ` / Terminal ${segment.originTerminal}`
                      : ""}
                  </span>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      <div className={styles.offerMeta}>
        <SkyetaRiskBadge risk={offer.skyetaRisk} />
        {offer.source.provider === "amadeus" ? (
          <span className={styles.expiry}>
            Live prices can change quickly; recheck before relying on this fare
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

      <div className={styles.offerAction}>
        <div className={styles.price}>
          <span>
            Total for {offer.passengerCount} passenger
            {offer.passengerCount === 1 ? "" : "s"}
          </span>
          <strong>{formatMoney(offer.total)}</strong>
          <small>Provider fare snapshot; no payment collected</small>
        </div>
        <button
          type="button"
          className={styles.selectButton}
          disabled={!canRecheck || isSelecting}
          onClick={() => onSelect(offer)}
        >
          {isSelecting
            ? "Checking latest fare..."
            : canRecheck
              ? "Recheck fare"
              : offer.source.environment === "test"
                ? "Test fare - comparison only"
                : "Fare unavailable"}
        </button>
      </div>
    </article>
  );
}
