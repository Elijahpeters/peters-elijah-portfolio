import type { MetadataRoute } from "next";

const PRODUCTION_SITE_URL = "https://peterselijah.name.ng";

function siteOrigin(): string {
  const configuredUrl = process.env.NEXT_PUBLIC_SITE_URL?.trim();
  if (!configuredUrl) return PRODUCTION_SITE_URL;

  try {
    const url = new URL(configuredUrl);
    if (url.protocol === "https:" || url.hostname === "localhost") {
      return url.origin;
    }
  } catch {
    // Fall back to the public domain when deployment configuration is malformed.
  }

  return PRODUCTION_SITE_URL;
}

export default function sitemap(): MetadataRoute.Sitemap {
  const origin = siteOrigin();

  return [
    {
      url: `${origin}/`,
      changeFrequency: "monthly",
      priority: 1,
    },
    {
      url: `${origin}/skyeta`,
      changeFrequency: "monthly",
      priority: 0.8,
    },
    {
      url: `${origin}/skyeta/help`,
      changeFrequency: "monthly",
      priority: 0.5,
    },
    {
      url: `${origin}/skyeta/privacy`,
      changeFrequency: "yearly",
      priority: 0.4,
    },
    {
      url: `${origin}/skyeta/terms`,
      changeFrequency: "yearly",
      priority: 0.4,
    },
    {
      url: `${origin}/projects/aurapass`,
      changeFrequency: "monthly",
      priority: 0.8,
    },
  ];
}
