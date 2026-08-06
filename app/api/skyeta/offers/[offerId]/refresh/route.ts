import { isAmadeusCacheId } from "../../../../../lib/amadeus/offer-cache";
import { createAmadeusOfferRefreshHandler } from "./amadeus-refresh";
import { createOfferRefreshHandler } from "./refresh";

export const dynamic = "force-dynamic";

const duffelRefresh = createOfferRefreshHandler();
const amadeusRefresh = createAmadeusOfferRefreshHandler();

export async function POST(
  request: Request,
  context: { params: Promise<{ offerId: string }> | { offerId: string } },
) {
  const params = await context.params;
  return isAmadeusCacheId(params.offerId)
    ? amadeusRefresh(request, params.offerId)
    : duffelRefresh(request, params.offerId);
}
