import type { FlightOffer } from "../../types/flight-booking";
import { isoDurationMinutes } from "../flight-provider/duration.ts";
import {
  scoreSkyetaItinerary,
  type ScorableFlightSegment,
  type SkyetaItineraryRisk,
} from "./server-risk.ts";

export type FlightOfferWithSkyetaRisk = FlightOffer & {
  skyetaRisk: SkyetaItineraryRisk;
};

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
      durationMinutes: isoDurationMinutes(segment.duration),
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
