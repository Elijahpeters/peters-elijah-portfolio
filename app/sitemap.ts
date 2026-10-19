import type { MetadataRoute } from "next";

const PRODUCTION_SITE_URL = "https://peterselijah.name.ng";

export default function sitemap(): MetadataRoute.Sitemap {
  const origin = PRODUCTION_SITE_URL;

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
      url: `${origin}/readme`,
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
      url: `${origin}/projects/skyeta`,
      changeFrequency: "monthly",
      priority: 0.8,
    },
    {
      url: `${origin}/projects/aurapass`,
      changeFrequency: "monthly",
      priority: 0.8,
    },
    {
      url: `${origin}/projects/incubator-carrier`,
      changeFrequency: "monthly",
      priority: 0.8,
    },
    {
      url: `${origin}/projects/circuits`,
      changeFrequency: "monthly",
      priority: 0.8,
    },
  ];
}
