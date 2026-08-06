import { isAmadeusCacheId } from "../../../../../lib/amadeus/offer-cache";
import { isIgnavCacheId } from "../../../../../lib/ignav/offer-cache";
import { createAmadeusOfferRefreshHandler } from "./amadeus-refresh";
import { createIgnavOfferRefreshHandler } from "./ignav-refresh";
import { createOfferRefreshHandler } from "./refresh";

export const dynamic = "force-dynamic";

const duffelRefresh = createOfferRefreshHandler();
const amadeusRefresh = createAmadeusOfferRefreshHandler();
const ignavRefresh = createIgnavOfferRefreshHandler();

export async function POST(
  request: Request,
  context: { params: Promise<{ offerId: string }> | { offerId: string } },
) {
  const params = await context.params;
  if (isIgnavCacheId(params.offerId)) {
    return ignavRefresh(request, params.offerId);
  }
  return isAmadeusCacheId(params.offerId)
    ? amadeusRefresh(request, params.offerId)
    : duffelRefresh(request, params.offerId);
}
