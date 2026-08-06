import { selectedFlightProvider } from "../../../../lib/flight-provider/config";
import { createAmadeusOfferSearchHandler } from "./amadeus-search";
import { createIgnavOfferSearchHandler } from "./ignav-search";
import { createOfferSearchHandler } from "./search";

export const dynamic = "force-dynamic";

const duffelSearch = createOfferSearchHandler();
const amadeusSearch = createAmadeusOfferSearchHandler();
const ignavSearch = createIgnavOfferSearchHandler();

export async function POST(request: Request): Promise<Response> {
  const provider = selectedFlightProvider();
  if (provider === "ignav") return ignavSearch(request);
  if (provider === "amadeus") return amadeusSearch(request);
  return duffelSearch(request);
}
