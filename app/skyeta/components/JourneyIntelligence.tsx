"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type { FlightSegment } from "../../types/flight-booking";
import type { SkyetaRiskAssessment } from "./flight-ui-types";
import styles from "../booking.module.css";

const FLIGHT_IATA = /^[A-Z0-9]{2}[0-9]{1,4}$/;
const AIRLABS_HISTORY_URL = "https://airlabs.co/docs/historical";
const MAX_HISTORY_LOOKUPS = 6;

type SampleConfidence =
  | "insufficient"
  | "limited"
  | "moderate"
  | "strong";

type DelayProbability = {
  observedLate: number;
  laplaceProbabilityPercent: number | null;
  wilson95LowPercent: number | null;
  wilson95HighPercent: number | null;
};

type Evidence = {
  flightIata: string;
  originIata: string;
  destinationIata: string;
  observations: number;
  arrivalDelayKnown: number;
  arrived15PlusLate: number;
  arrived30PlusLate: number;
  arrived60PlusLate: number;
  arrival15Plus: DelayProbability;
  arrival30Plus: DelayProbability;
  arrival60Plus: DelayProbability;
  typicalLateArrivalMinutes: number | null;
  arrivalDataSufficient: boolean;
  arrivalSampleConfidence: SampleConfidence;
  departureDelayKnown: number;
  departed15PlusLate: number;
  earliestObservedDate: string | null;
  latestObservedDate: string | null;
};

type ParsedEvidence = {
  flights: Evidence[];
  partial: boolean;
};

type RecentPerformanceState =
  | { status: "idle"; requestKey: string }
  | { status: "loading"; requestKey: string }
  | {
      status: "ready";
      requestKey: string;
      flights: Evidence[];
      partial: boolean;
    }
  | { status: "error"; requestKey: string; message: string };

type JourneyLeg = {
  label: string;
  originIata: string;
  destinationIata: string;
  identifier: string | null;
  requested: boolean;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function validCount(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function validProbability(value: unknown): value is number | null {
  return (
    value === null ||
    (typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 100)
  );
}

function validDate(value: unknown): value is string | null {
  return (
    value === null ||
    (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value))
  );
}

function validAirportIata(value: unknown): value is string {
  return typeof value === "string" && /^[A-Z]{3}$/.test(value);
}

function isDelayProbability(
  value: unknown,
  sampleSize: number,
): value is DelayProbability {
  if (!isRecord(value) || !validCount(value.observedLate)) return false;
  if (value.observedLate > sampleSize) return false;
  if (
    !validProbability(value.laplaceProbabilityPercent) ||
    !validProbability(value.wilson95LowPercent) ||
    !validProbability(value.wilson95HighPercent)
  ) {
    return false;
  }
  if (sampleSize === 0) {
    return (
      value.laplaceProbabilityPercent === null &&
      value.wilson95LowPercent === null &&
      value.wilson95HighPercent === null
    );
  }
  return (
    value.laplaceProbabilityPercent !== null &&
    value.wilson95LowPercent !== null &&
    value.wilson95HighPercent !== null &&
    value.wilson95LowPercent <= value.wilson95HighPercent
  );
}

function isEvidence(value: unknown): value is Evidence {
  if (
    !isRecord(value) ||
    typeof value.flightIata !== "string" ||
    !FLIGHT_IATA.test(value.flightIata) ||
    !validAirportIata(value.originIata) ||
    !validAirportIata(value.destinationIata) ||
    value.originIata === value.destinationIata ||
    !validCount(value.observations) ||
    !validCount(value.arrivalDelayKnown) ||
    !validCount(value.arrived15PlusLate) ||
    !validCount(value.arrived30PlusLate) ||
    !validCount(value.arrived60PlusLate) ||
    value.arrivalDelayKnown > value.observations ||
    value.arrived60PlusLate > value.arrived30PlusLate ||
    value.arrived30PlusLate > value.arrived15PlusLate ||
    value.arrived15PlusLate > value.arrivalDelayKnown ||
    !isDelayProbability(value.arrival15Plus, value.arrivalDelayKnown) ||
    !isDelayProbability(value.arrival30Plus, value.arrivalDelayKnown) ||
    !isDelayProbability(value.arrival60Plus, value.arrivalDelayKnown) ||
    (value.typicalLateArrivalMinutes !== null &&
      (!validCount(value.typicalLateArrivalMinutes) ||
        value.typicalLateArrivalMinutes < 15)) ||
    typeof value.arrivalDataSufficient !== "boolean" ||
    !["insufficient", "limited", "moderate", "strong"].includes(
      String(value.arrivalSampleConfidence),
    ) ||
    !validCount(value.departureDelayKnown) ||
    !validCount(value.departed15PlusLate) ||
    value.departureDelayKnown > value.observations ||
    value.departed15PlusLate > value.departureDelayKnown ||
    !validDate(value.earliestObservedDate) ||
    !validDate(value.latestObservedDate)
  ) {
    return false;
  }

  return (
    value.arrivalDataSufficient === (value.arrivalDelayKnown >= 5) &&
    (value.arrived15PlusLate === 0
      ? value.typicalLateArrivalMinutes === null
      : value.typicalLateArrivalMinutes !== null) &&
    value.arrival15Plus.observedLate === value.arrived15PlusLate &&
    value.arrival30Plus.observedLate === value.arrived30PlusLate &&
    value.arrival60Plus.observedLate === value.arrived60PlusLate
  );
}

function parseEvidence(value: unknown): ParsedEvidence | null {
  if (
    !isRecord(value) ||
    value.ok !== true ||
    typeof value.partial !== "boolean" ||
    !Array.isArray(value.flights)
  ) {
    return null;
  }
  return value.flights.every(isEvidence)
    ? { flights: value.flights, partial: value.partial }
    : null;
}

function flightRouteIdentifiers(segments: FlightSegment[]) {
  const candidates = segments.map((segment) => {
    const flightIata =
      `${segment.marketingCarrier.iataCode}${segment.marketingFlightNumber ?? ""}`
        .replace(/[^A-Z0-9]/gi, "")
        .toUpperCase();
    const originIata = segment.origin.iataCode.toUpperCase();
    const destinationIata = segment.destination.iataCode.toUpperCase();
    const identifier =
      FLIGHT_IATA.test(flightIata) &&
      validAirportIata(originIata) &&
      validAirportIata(destinationIata) &&
      originIata !== destinationIata
        ? `${flightIata}:${originIata}:${destinationIata}`
        : null;
    return {
      label: FLIGHT_IATA.test(flightIata) ? flightIata : "Flight number unavailable",
      originIata,
      destinationIata,
      identifier,
    };
  });
  const uniqueIdentifiers = [
    ...new Set(
      candidates
        .map((candidate) => candidate.identifier)
        .filter((value): value is string => value !== null),
    ),
  ];
  const identifiers = uniqueIdentifiers.slice(0, MAX_HISTORY_LOOKUPS);
  const requested = new Set(identifiers);
  return {
    identifiers,
    isLimited: uniqueIdentifiers.length > MAX_HISTORY_LOOKUPS,
    legs: candidates.map(
      (candidate): JourneyLeg => ({
        ...candidate,
        requested:
          candidate.identifier !== null && requested.has(candidate.identifier),
      }),
    ),
  };
}

function usModelCopy(risk?: SkyetaRiskAssessment) {
  if (!risk || risk.status === "unavailable") {
    return {
      headline: "Not available for this route",
      detail:
        "The separate SkyETA schedule model currently covers selected U.S. domestic routes only.",
    };
  }
  if (risk.scope === "highest_scored_segment") {
    return {
      headline: `${risk.scoredSegments} of ${risk.totalSegments} segments covered`,
      detail:
        "The U.S. model scored the covered flight segments separately. It does not turn the highest leg score into a whole-journey percentage.",
    };
  }
  const percentage = Math.round(Math.min(100, Math.max(0, risk.percentage)));
  return {
    headline: `${percentage}% chance of arriving 15+ minutes late`,
    detail: `The U.S. schedule model estimates that about ${percentage} in 100 comparable single-flight journeys would arrive at least 15 minutes late.`,
  };
}

function evidenceKey(evidence: Evidence): string {
  return `${evidence.flightIata}:${evidence.originIata}:${evidence.destinationIata}`;
}

function roundedOutlook(probability: DelayProbability): string {
  return probability.laplaceProbabilityPercent === null
    ? "—"
    : `${Math.round(probability.laplaceProbabilityPercent)}%`;
}

function confidenceCopy(confidence: SampleConfidence): string {
  if (confidence === "strong") return "Strong sample confidence";
  if (confidence === "moderate") return "Moderate sample confidence";
  if (confidence === "limited") return "Limited sample confidence";
  return "Insufficient sample";
}

function combinedHistoricalOutlook(
  legs: JourneyLeg[],
  evidenceByKey: Map<string, Evidence>,
  isLimited: boolean,
) {
  if (legs.length === 0 || isLimited) return null;
  const evidence = legs.map((leg) =>
    leg.identifier ? evidenceByKey.get(leg.identifier) : undefined,
  );
  if (
    evidence.some(
      (item) =>
        !item ||
        !item.arrivalDataSufficient ||
        item.arrival15Plus.laplaceProbabilityPercent === null,
    )
  ) {
    return null;
  }
  const completeEvidence = evidence as Evidence[];
  const noLateArrivalProbability = completeEvidence.reduce(
    (product, item) =>
      product * (1 - (item.arrival15Plus.laplaceProbabilityPercent ?? 0) / 100),
    1,
  );
  const confidenceOrder: SampleConfidence[] = [
    "insufficient",
    "limited",
    "moderate",
    "strong",
  ];
  const confidence = completeEvidence.reduce<SampleConfidence>(
    (lowest, item) =>
      confidenceOrder.indexOf(item.arrivalSampleConfidence) <
      confidenceOrder.indexOf(lowest)
        ? item.arrivalSampleConfidence
        : lowest,
    "strong",
  );
  return {
    probabilityPercent: Math.round((1 - noLateArrivalProbability) * 100),
    confidence,
  };
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
  const usModelSummary = usModelCopy(risk);
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
      const parsed = parseEvidence(body);
      if (!response.ok || !parsed) {
        throw new Error("recent_performance_unavailable");
      }
      if (
        nextController.signal.aborted ||
        controller.current !== nextController
      ) {
        return;
      }
      setState({
        status: "ready",
        requestKey: pendingRequestKey,
        flights: parsed.flights,
        partial: parsed.partial,
      });
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
          "Worldwide historical records are unavailable right now. Your fare result is unaffected.",
      });
    } finally {
      if (controller.current === nextController) {
        controller.current = null;
      }
    }
  }

  const readyEvidence =
    visibleState.status === "ready" ? visibleState.flights : [];
  const evidenceByKey = new Map(
    readyEvidence.map((evidence) => [evidenceKey(evidence), evidence]),
  );
  const combined =
    visibleState.status === "ready"
      ? combinedHistoricalOutlook(
          lookupPlan.legs,
          evidenceByKey,
          lookupPlan.isLimited,
        )
      : null;

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
      <summary>Check 15+, 30+ and 60+ minute delay history</summary>
      <div className={styles.intelligencePanel}>
        <div className={styles.intelligenceHeading}>
          <span>Worldwide historical outlook</span>
          <strong>How each flight has performed before</strong>
          <p>
            This comparison uses route-matched completed-flight records. It is
            separate from SkyETA&apos;s selected-U.S.-route model and does not
            claim that every flight has coverage.
          </p>
        </div>

        <div className={styles.intelligenceGrid}>
          <article>
            <span>Current itinerary</span>
            <strong>
              {segments.length} flight leg{segments.length === 1 ? "" : "s"}
            </strong>
            <p>
              Schedule and fare information supplied by the connected flight
              provider.
            </p>
          </article>
          <article>
            <span>U.S. schedule model · selected routes only</span>
            <strong>{usModelSummary.headline}</strong>
            <p>{usModelSummary.detail}</p>
          </article>
          <article>
            <span>Worldwide AirLabs history</span>
            <strong>
              {combined
                ? `${combined.probabilityPercent}% journey outlook`
                : "Checked flight by flight"}
            </strong>
            <p>
              {combined
                ? `Historical chance that at least one leg arrives 15+ minutes late · ${confidenceCopy(combined.confidence)}.`
                : "A journey-wide percentage appears only when every leg has enough usable arrival records."}
            </p>
          </article>
        </div>

        <div className={styles.intelligenceGrid}>
          <article>
            <span>Flight-by-flight evidence</span>
          {lookupPlan.isLimited ? (
            <p>
              Every leg is listed, but only the first {MAX_HISTORY_LOOKUPS} distinct
              flights are checked in one request. No journey total is shown.
            </p>
          ) : null}
          {lookupPlan.identifiers.length === 0 ? (
            <p>
              The provider did not supply usable flight numbers for historical
              matching.
            </p>
          ) : visibleState.status === "idle" ? (
            <p role="status">
              Open this panel to check route-matched completed-flight records.
            </p>
          ) : visibleState.status === "loading" ? (
            <p role="status">Checking route-matched completed-flight records…</p>
          ) : visibleState.status === "error" ? (
            <div className={styles.intelligenceError} role="status">
              <p>{visibleState.message}</p>
              <button type="button" onClick={() => void loadRecentPerformance()}>
                Try again
              </button>
            </div>
          ) : (
            <div className={styles.observedList}>
              {lookupPlan.legs.map((leg, index) => {
                const evidence = leg.identifier
                  ? evidenceByKey.get(leg.identifier)
                  : undefined;
                return (
                  <div
                    key={`${leg.identifier ?? `${leg.originIata}:${leg.destinationIata}`}:${index}`}
                  >
                    <strong>
                      {leg.label} · {leg.originIata} → {leg.destinationIata}
                    </strong>
                    {!leg.identifier ? (
                      <p>
                        No flight number was supplied, so this leg cannot be
                        matched to route-specific history.
                      </p>
                    ) : !leg.requested ? (
                      <p>
                        Listed but not checked because this itinerary exceeds
                        the six-flight lookup limit.
                      </p>
                    ) : !evidence ? (
                      <p>
                        No usable completed-flight history was returned for this
                        exact flight and route.
                      </p>
                    ) : !evidence.arrivalDataSufficient ? (
                      <p>
                        {evidence.arrivalDelayKnown} usable arrival record
                        {evidence.arrivalDelayKnown === 1 ? "" : "s"} found. At
                        least 5 are required before SkyETA displays percentages.
                      </p>
                    ) : (
                      <>
                        <p>
                          15+ min: {roundedOutlook(evidence.arrival15Plus)} ·
                          {" "}30+ min: {roundedOutlook(evidence.arrival30Plus)} ·
                          {" "}60+ min: {roundedOutlook(evidence.arrival60Plus)}
                        </p>
                        <p>
                          {evidence.arrived15PlusLate} of {evidence.arrivalDelayKnown}
                          {" "}recorded arrivals were 15+ minutes late. Typical
                          delay when that happened:{" "}
                          {evidence.typicalLateArrivalMinutes === null
                            ? "none in this sample"
                            : `${evidence.typicalLateArrivalMinutes} minutes`}.
                        </p>
                        <p>
                          {confidenceCopy(evidence.arrivalSampleConfidence)}
                          {evidence.arrival15Plus.wilson95LowPercent !== null &&
                          evidence.arrival15Plus.wilson95HighPercent !== null
                            ? ` · 15-minute uncertainty range ${Math.round(evidence.arrival15Plus.wilson95LowPercent)}–${Math.round(evidence.arrival15Plus.wilson95HighPercent)}%`
                            : ""}
                        </p>
                      </>
                    )}
                    {evidence ? (
                      <small>
                        {evidence.arrivalDelayKnown} arrivals with usable delay
                        data from {evidence.observations} completed records
                        {evidence.earliestObservedDate && evidence.latestObservedDate
                          ? ` · ${evidence.earliestObservedDate} to ${evidence.latestObservedDate}`
                          : ""}
                      </small>
                    ) : null}
                  </div>
                );
              })}
              {visibleState.partial ? (
                <p>
                  Some provider lookups were unavailable, so no complete journey
                  outlook is shown.
                </p>
              ) : null}
            </div>
          )}
          </article>
        </div>

        <p className={styles.intelligenceNote}>
          How to read this: SkyETA softens small samples so a few records never
          appear as an absolute 0% or 100%. The uncertainty range shows how much
          the estimate may move as more records become available. A journey total
          appears only when every leg has at least 5 usable arrivals and treats the
          legs as independent. This is completed-flight history from{" "}
          <a href={AIRLABS_HISTORY_URL} target="_blank" rel="noopener noreferrer">
            AirLabs
          </a>
          , not live flight status or a promise about a future trip. Coverage varies
          by flight.
        </p>
      </div>
    </details>
  );
}
