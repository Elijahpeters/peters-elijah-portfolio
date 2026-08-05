import { createGetCheckoutSessionHandler } from "./get-session";

export const dynamic = "force-dynamic";

const handler = createGetCheckoutSessionHandler();

export async function GET(
  request: Request,
  context: { params: Promise<{ sessionId: string }> | { sessionId: string } },
) {
  const params = await context.params;
  return handler(request, params.sessionId);
}
