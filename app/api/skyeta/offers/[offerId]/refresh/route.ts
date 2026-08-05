import { createOfferRefreshHandler } from "./refresh";

export const dynamic = "force-dynamic";

const handler = createOfferRefreshHandler();

export async function POST(
  request: Request,
  context: { params: Promise<{ offerId: string }> | { offerId: string } },
) {
  const params = await context.params;
  return handler(request, params.offerId);
}
