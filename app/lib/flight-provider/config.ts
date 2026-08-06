import type { FlightProviderEnvironment } from "../../types/flight-booking.ts";

export type FlightProviderName = "duffel" | "amadeus" | "ignav";

type EnvironmentLike = Record<string, string | undefined>;

function requestedProvider(environment: EnvironmentLike): FlightProviderName | null {
  const value = environment.SKYETA_FLIGHT_PROVIDER?.trim().toLowerCase();
  return value === "duffel" || value === "amadeus" || value === "ignav"
    ? value
    : null;
}

function hasAnyIgnavSetting(environment: EnvironmentLike): boolean {
  return Boolean(environment.IGNAV_API_KEY?.trim());
}

function hasAnyAmadeusSetting(environment: EnvironmentLike): boolean {
  return Boolean(
    environment.AMADEUS_API_KEY?.trim() ||
      environment.AMADEUS_API_SECRET?.trim() ||
      environment.AMADEUS_MODE?.trim(),
  );
}

export function selectedFlightProvider(
  environment: EnvironmentLike = process.env,
): FlightProviderName {
  const requested = requestedProvider(environment);
  if (requested) return requested;
  if (hasAnyIgnavSetting(environment)) return "ignav";
  return hasAnyAmadeusSetting(environment) ? "amadeus" : "duffel";
}

export function configuredFlightProviderEnvironment(
  environment: EnvironmentLike = process.env,
): FlightProviderEnvironment | null {
  const provider = selectedFlightProvider(environment);
  if (provider === "ignav") {
    return environment.IGNAV_API_KEY?.trim() ? "live" : null;
  }
  if (provider === "amadeus") {
    const mode = environment.AMADEUS_MODE?.trim().toLowerCase();
    return environment.AMADEUS_API_KEY?.trim() &&
      environment.AMADEUS_API_SECRET?.trim() &&
      (mode === "test" || mode === "live")
      ? mode
      : null;
  }

  const mode = environment.DUFFEL_MODE?.trim().toLowerCase();
  return environment.DUFFEL_ACCESS_TOKEN?.trim() &&
    (mode === "test" || mode === "live")
    ? mode
    : null;
}
