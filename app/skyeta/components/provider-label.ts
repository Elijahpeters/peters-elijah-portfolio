export function flightProviderLabel(provider: string | null | undefined) {
  if (provider === "ignav") return "iGNav";
  if (provider === "amadeus") return "Amadeus";
  if (provider === "duffel") return "Duffel";
  return "the connected flight provider";
}
