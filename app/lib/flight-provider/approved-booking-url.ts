const BUILT_IN_APPROVED_HOSTS = [
  "aa.com",
  "aircanada.com",
  "airfrance.com",
  "alternativeairlines.com",
  "britishairways.com",
  "brusselsairlines.com",
  "cathaypacific.com",
  "delta.com",
  "egyptair.com",
  "emirates.com",
  "ethiopianairlines.com",
  "etihad.com",
  "expedia.com",
  "flyairpeace.com",
  "flysaa.com",
  "iberia.com",
  "kenya-airways.com",
  "kiwi.com",
  "klm.com",
  "lufthansa.com",
  "mytrip.com",
  "qantas.com",
  "qatarairways.com",
  "royalairmaroc.com",
  "rwandair.com",
  "saudia.com",
  "singaporeair.com",
  "tapairportugal.com",
  "travelstart.com",
  "travelstart.com.ng",
  "trip.com",
  "turkishairlines.com",
  "united.com",
  "virginatlantic.com",
  "wakanow.com",
] as const;

const HOSTNAME = /^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])$/;

function canonicalApprovedHost(value: string): string | null {
  const host = value.trim().toLowerCase().replace(/^\.+|\.+$/g, "");
  return HOSTNAME.test(host) ? host : null;
}

export function approvedBookingHosts(
  configuredHosts = process.env.SKYETA_BOOKING_ALLOWED_HOSTS,
): ReadonlySet<string> {
  const hosts = new Set<string>(BUILT_IN_APPROVED_HOSTS);
  for (const value of configuredHosts?.split(",") ?? []) {
    const host = canonicalApprovedHost(value);
    if (host) hosts.add(host);
  }
  return hosts;
}

function matchesApprovedHost(
  hostname: string,
  approvedHosts: ReadonlySet<string>,
): boolean {
  for (const approvedHost of approvedHosts) {
    if (
      hostname === approvedHost ||
      hostname.endsWith(`.${approvedHost}`)
    ) {
      return true;
    }
  }
  return false;
}

export function approvedBookingUrl(
  value: unknown,
  approvedHosts: ReadonlySet<string> = approvedBookingHosts(),
): string | null {
  if (typeof value !== "string" || value.length === 0 || value.length > 2_048) {
    return null;
  }

  try {
    const url = new URL(value);
    const hostname = url.hostname.toLowerCase();
    if (
      url.protocol !== "https:" ||
      url.username ||
      url.password ||
      (url.port && url.port !== "443") ||
      !matchesApprovedHost(hostname, approvedHosts)
    ) {
      return null;
    }

    return url.toString();
  } catch {
    return null;
  }
}
