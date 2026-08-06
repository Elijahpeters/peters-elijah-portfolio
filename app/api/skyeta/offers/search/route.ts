import { selectedFlightProvider } from "../../../../lib/flight-provider/config";
import { createAmadeusOfferSearchHandler } from "./amadeus-search";
import { createOfferSearchHandler } from "./search";

export const dynamic = "force-dynamic";

const duffelSearch = createOfferSearchHandler();
const amadeusSearch = createAmadeusOfferSearchHandler();

export async function POST(request: Request): Promise<Response> {
  return selectedFlightProvider() === "amadeus"
    ? amadeusSearch(request)
    : duffelSearch(request);
}
