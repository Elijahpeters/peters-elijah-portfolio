import type { Metadata } from "next";

const publicOrigin = process.env.NEXT_PUBLIC_SITE_URL || "https://peterselijah.name.ng";
const skyetaTitle = "SkyETA | Flight Search & Reliability by Elijah Peters";
const skyetaDescription =
  "Compare flights worldwide with SkyETA by Elijah Peters. Explore historical reliability where records exist and delay predictions for selected U.S. domestic routes.";
const socialImage = "/skyeta/opengraph-image";

export const metadata: Metadata = {
  metadataBase: new URL(publicOrigin),
  alternates: {
    canonical: "/skyeta",
  },
  openGraph: {
    type: "website",
    url: "/skyeta",
    siteName: "SkyETA",
    title: skyetaTitle,
    description: skyetaDescription,
    images: [
      {
        url: socialImage,
        secureUrl: socialImage,
        type: "image/png",
        width: 1200,
        height: 630,
        alt: "SkyETA by Elijah Peters (Peters Elijah Temidayo)",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: skyetaTitle,
    description: skyetaDescription,
    images: [{ url: socialImage, alt: "SkyETA by Elijah Peters (Peters Elijah Temidayo)" }],
  },
};

export default function SkyetaLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return children;
}
