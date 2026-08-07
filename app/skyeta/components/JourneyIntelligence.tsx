"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type { FlightSegment } from "../../types/flight-booking";
import type { SkyetaRiskAssessment } from "./flight-ui-types";
import styles from "../booking.module.css";

const FLIGHT_IATA = /^[A-Z0-9]{2}[0-9]{1,4}$/;
const AIRLABS_HISTORY_URL = "https://airlabs.co/docs/historical";

type Evidence = {
  flightIata: string;
  originIata: string;
  destinationIata: string;
  observations: number;
  arrivalDelayKnown: number;
  arrived15PlusLate: number;
  departureDelayKnown: number;
  departed15PlusLate: number;
  earliestObservedDate: string | null;
  latestObservedDate: string | null;
};

type RecentPerformanceState =
  | { status: "idle"; requestKey: string }
  | { status: "loading"; requestKey: string }
  | { status: "ready"; requestKey: string; flights: Evidence[] }
  | { status: "error"; requestKey: string; message: string };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function validCount(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function validDate(value: unknown): value is string | null {
  return value === null || (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value));
}

function validAirportIata(value: unknown): value is string {
  return typeof value === "string" && /^[A-Z]{3}$/.test(value);
}

function isEvidence(value: unknown): value is Evidence {
  return (
    isRecord(value) &&
    typeof value.flightIata === "string" &&
    FLIGHT_IATA.test(value.flightIata) &&
    validAirportIata(value.originIata) &&
    validAirportIata(value.destinationIata) &&
    value.originIata !== value.destinationIata &&
    validCount(value.observations) &&
    validCount(value.arrivalDelayKnown) &&
    validCount(value.arrived15PlusLate) &&
    value.arrived15PlusLate <= value.arrivalDelayKnown &&
    validCount(value.departureDelayKnown) &&
    validCount(value.departed15PlusLate) &&
    value.departed15PlusLate <= value.departureDelayKnown &&
    validDate(value.earliestObservedDate) &&
    validDate(value.latestObservedDate)
  );
}

function parseEvidence(value: unknown): Evidence[] | null {
  if (!isRecord(value) || value.ok !== true || !Array.isArray(value.flights)) {
    return null;
  }
  return value.flights.every(isEvidence) ? value.flights : null;
}

function flightRouteIdentifiers(segments: FlightSegment[]) {
  const identifiers = segments
    .map((segment) => {
      const flightIata =
        `${segment.marketingCarrier.iataCode}${segment.marketingFlightNumber ?? ""}`
          .replace(/[^A-Z0-9]/gi, "")
          .toUpperCase();
      const originIata = segment.origin.iataCode.toUpperCase();
      const destinationIata = segment.destination.iataCode.toUpperCase();
      if (
        !FLIGHT_IATA.test(flightIata) ||
        !validAirportIata(originIata) ||
        !validAirportIata(destinationIata) ||
        originIata === destinationIata
      ) {
        return null;
      }
      return `${flightIata}:${originIata}:${destinationIata}`;
    })
    .filter((value): value is string => value !== null);
  const uniqueIdentifiers = [...new Set(identifiers)];
  return {
    identifiers: uniqueIdentifiers.slice(0, 3),
    isLimited: uniqueIdentifiers.length > 3,
  };
}

function riskCopy(risk?: SkyetaRiskAssessment) {
  if (!risk || risk.status === "unavailable") {
    return {
      headline: "Delay outlook not yet verified",
      detail:
        "SkyETA will not invent a percentage when dependable route evidence is unavailable.",
    };
  }
  if (risk.coverage === "partial") {
    return {
      headline: `${risk.scoredSegments} of ${risk.totalSegments} flight segments analysed`,
      detail:
        "A whole-journey percentage is not shown because every segment needs verified coverage.",
    };
  }
  const percentage = Math.round(Math.min(100, Math.max(0, risk.percentage)));
  return {
    headline: `${percentage}% chance of arriving 15+ minutes late`,
    detail: `SkyETA estimates that about ${percentage} in 100 comparable flights would arrive at least 15 minutes late.`,
  };
}

function observedCopy(evidence: Evidence) {
  if (evidence.arrivalDelayKnown >= 3) {
    return `${evidence.arrived15PlusLate} of ${evidence.arrivalDelayKnown} recent recorded arrivals were at least 15 minutes late.`;
  }
  if (evidence.departureDelayKnown >= 3) {
    return `${evidence.departed15PlusLate} of ${evidence.departureDelayKnown} recent recorded departures left at least 15 minutes late.`;
  }
  return "Not enough verified recent delay records are available for a dependable comparison.";
}

export default function JourneyIntelligence({
  segments,
  risk,
}: {
  segments: FlightSegment[];
  risk?: SkyetaRiskAssessment;
}) {
  const lookupPlan = useMemo(() => flightRouteIdentifiers(segments), [segments]);
  const requestKey = lookupPlan.identifiers.join(",");
  const riskSummary = riskCopy(risk);
  const controller = useRef<AbortController | null>(null);
  const [state, setState] = useState<RecentPerformanceState>({
    status: "idle",
    requestKey,
  });
  const visibleState: RecentPerformanceState =
    state.requestKey === requestKey
      ? state
      : { status: "idle", requestKey };

  useEffect(() => {
    controller.current?.abort();
    controller.current = null;

    return () => {
      controller.current?.abort();
      controller.current = null;
    };
  }, [requestKey]);

  async function loadRecentPerformance() {
    if (
      lookupPlan.identifiers.length === 0 ||
      visibleState.status === "loading" ||
      visibleState.status === "ready"
    ) {
      return;
    }
    const pendingRequestKey = requestKey;
    controller.current?.abort();
    const nextController = new AbortController();
    controller.current = nextController;
    setState({ status: "loading", requestKey: pendingRequestKey });
    try {
      const response = await fetch(
        `/api/skyeta/recent-performance?flights=${encodeURIComponent(requestKey)}`,
        { signal: nextController.signal },
      );
      const body: unknown = await response.json();
      const flights = parseEvidence(body);
      if (!response.ok || !flights) throw new Error("recent_performance_unavailable");
      if (
        nextController.signal.aborted ||
        controller.current !== nextController
      ) {
        return;
      }
      setState({ status: "ready", requestKey: pendingRequestKey, flights });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      if (
        nextController.signal.aborted ||
        controller.current !== nextController
      ) {
        return;
      }
      setState({
        status: "error",
        requestKey: pendingRequestKey,
        message:
          "Recent observed performance is unavailable right now. Your fare result is unaffected.",
      });
    } finally {
      if (controller.current === nextController) {
        controller.current = null;
      }
    }
  }

  return (
    <details
      key={requestKey}
      className={styles.intelligenceDisclosure}
      onToggle={(event) => {
        if (event.currentTarget.open && visibleState.status === "idle") {
          void loadRecentPerformance();
        }
      }}
    >
      <summary>View SkyETA journey intelligence</summary>
      <div className={styles.intelligencePanel}>
        <div className={styles.intelligenceHeading}>
          <span>Evidence, not guesswork</span>
          <strong>What SkyETA knows about this journey</strong>
          <p>
            Fare, schedule, historical and operational sources stay clearly
            labelled instead of being mixed into one unexplained score.
          </p>
        </div>

        <div className={styles.intelligenceGrid}>
          <article>
            <span>Provider itinerary</span>
            <strong>
              {segments.length} flight segment{segments.length === 1 ? "" : "s"}
            </strong>
            <p>
              Current schedule and fare information supplied by the connected
              flight provider.
            </p>
          </article>
          <article>
            <span>Verified delay outlook</span>
            <strong>{riskSummary.headline}</strong>
            <p>{riskSummary.detail}</p>
          </article>
          <article>
            <span>Recent observed performance</span>
            {lookupPlan.isLimited ? (
              <p>
                Only the first 3 distinct flight segments are checked for recent
                performance.
              </p>
            ) : null}
            {lookupPlan.identifiers.length === 0 ? (
              <p>The provider did not supply a flight number for historical lookup.</p>
            ) : visibleState.status === "idle" ? (
              <p role="status">Open this panel to check recent completed-flight records.</p>
            ) : visibleState.status === "loading" ? (
              <p role="status">Checking recent completed-flight records…</p>
            ) : visibleState.status === "error" ? (
              <div className={styles.intelligenceError} role="status">
                <p>{visibleState.message}</p>
                <button type="button" onClick={() => void loadRecentPerformance()}>
                  Try again
                </button>
              </div>
            ) : (
              <div className={styles.observedList}>
                {visibleState.flights.map((evidence) => (
                  <div
                    key={`${evidence.flightIata}:${evidence.originIata}:${evidence.destinationIata}`}
                  >
                    <strong>
                      {evidence.flightIata} · {evidence.originIata} →{" "}
                      {evidence.destinationIata}
                    </strong>
                    <p>{observedCopy(evidence)}</p>
                    {evidence.earliestObservedDate && evidence.latestObservedDate ? (
                      <small>
                        Records {evidence.earliestObservedDate} to {evidence.latestObservedDate}
                      </small>
                    ) : null}
                  </div>
                ))}
              </div>
            )}
          </article>
        </div>

        <p className={styles.intelligenceNote}>
          Recent performance is observed history from{" "}
          <a href={AIRLABS_HISTORY_URL} target="_blank" rel="noopener noreferrer">
            AirLabs
          </a>
          , not a prediction of this future flight. Coverage varies by flight.
        </p>
      </div>
    </details>
  );
}
