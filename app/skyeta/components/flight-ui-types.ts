import type {
  FlightOffer as ProviderFlightOffer,
  FlightProviderEnvironment,
} from "../../types/flight-booking";
import type { SkyetaItineraryRisk } from "../../lib/skyeta/server-risk";

export type FlightProviderMode =
  | FlightProviderEnvironment
  | "unconfigured";

export type CabinClass =
  | "economy"
  | "premium_economy"
  | "business"
  | "first";

export interface FlightSearchValues {
  origin: string;
  destination: string;
  departureDate: string;
  returnDate?: string;
  adults: number;
  children: number;
  infants: number;
  cabin: CabinClass;
}

export type SkyetaRiskAssessment = SkyetaItineraryRisk;

export type SkyetaFlightOffer = ProviderFlightOffer & {
  skyetaRisk?: SkyetaRiskAssessment;
};
