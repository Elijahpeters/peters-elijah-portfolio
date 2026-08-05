import type { FlightOffer } from "../../types/flight-booking";
import {
  scoreSkyetaItinerary,
  type ScorableFlightSegment,
  type SkyetaItineraryRisk,
} from "./server-risk.ts";

export type FlightOfferWithSkyetaRisk = FlightOffer & {
  skyetaRisk: SkyetaItineraryRisk;
};

function durationMinutes(value: string | null): number | null {
  if (!value) return null;
  const match = value.match(
    /^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:\d+(?:\.\d+)?S)?)?$/,
  );
  if (!match) return null;
  const minutes =
    Number(match[1] ?? 0) * 1_440 +
    Number(match[2] ?? 0) * 60 +
    Number(match[3] ?? 0);
  return minutes > 0 ? minutes : null;
}

function riskSegments(offer: FlightOffer): ScorableFlightSegment[] {
  return offer.slices.flatMap((slice) =>
    slice.segments.map((segment) => ({
      origin: segment.origin.iataCode,
      destination: segment.destination.iataCode,
      carrierIata:
        segment.operatingCarrier.iataCode ??
        segment.marketingCarrier.iataCode ??
        "",
      departureLocal: segment.departingAt,
      durationMinutes: durationMinutes(segment.duration),
      distanceMiles:
        segment.distanceKilometres === null
          ? null
          : segment.distanceKilometres * 0.621371,
    })),
  );
}

export function addSkyetaRisk(
  offer: FlightOffer,
): FlightOfferWithSkyetaRisk {
  return {
    ...offer,
    skyetaRisk: scoreSkyetaItinerary(riskSegments(offer)),
  };
}
